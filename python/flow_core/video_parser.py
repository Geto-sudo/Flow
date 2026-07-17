"""
Video parser — progressive multimodal extraction pipeline.

Phase 1 (fast, <5s):      ffprobe metadata + ffmpeg scene detection
Phase 2 (speech, on GPU): WhisperX transcription + pyannote diarization
Phase 3 (vision, on GPU): CLIP embeddings + YOLO object detection [future]
Phase 4 (audio, CPU):     RMS, beat detection, emotion classification [future]

Design: each phase enriches an existing ProjectGraph. The higher phases
are lazy — they only run when depth >= their phase.
"""

import json
import subprocess
import os
import random
import time
from typing import Optional, List

from .project_graph import (
    ProjectGraph, Project, Timeline, Track, Clip, Scene,
    TranscriptSegment, Person, DetectedObject, AudioSegment,
    Asset, GraphEdge,
)
from . import _ffmpeg as _ff


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1 — Fast metadata + scene detection (< 5s, always runs)
# ═══════════════════════════════════════════════════════════════════════════

def probe_video(path: str) -> dict:
    """Extract metadata from a video file using bundled ffprobe."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Video not found: {path}")

    cmd = [
        _ff.ffprobe_path(), "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {r.stderr}")
        return json.loads(r.stdout)
    except FileNotFoundError:
        raise RuntimeError(
            f"ffprobe not found at {_ff.ffprobe_path()}. "
            "Install imageio-ffmpeg: pip install imageio-ffmpeg"
        )


def has_audio_stream(path: str) -> bool:
    """Return True if the video has at least one audio stream."""
    try:
        meta = probe_video(path)
    except Exception:
        return False
    return any(s.get("codec_type") == "audio" for s in meta.get("streams", []))


def detect_scenes(path: str, threshold: float = 0.3) -> list:
    """Detect scene change timestamps using ffmpeg scene detection."""
    cmd = [
        _ff.ffmpeg_path(), "-i", path,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        scenes = []
        for line in r.stderr.split("\n"):
            if "pts_time:" in line:
                parts = line.split("pts_time:")
                if len(parts) > 1:
                    try:
                        t = float(parts[1].split()[0])
                        scenes.append(t)
                    except (ValueError, IndexError):
                        pass
        return scenes
    except FileNotFoundError:
        raise RuntimeError(f"ffmpeg not found at {_ff.ffmpeg_path()}.")


def _create_or_get_graph(graph: Optional[ProjectGraph], name: str) -> ProjectGraph:
    """Return existing graph or create a new one."""
    if graph is not None:
        return graph
    return ProjectGraph(name=name)


def _phase1_fast(
    path: str,
    graph: Optional[ProjectGraph] = None,
) -> ProjectGraph:
    """Parse metadata + scene detection into a ProjectGraph."""
    name = os.path.splitext(os.path.basename(path))[0]
    g = _create_or_get_graph(graph, name)

    meta = probe_video(path)

    # Find video stream
    video_stream = None
    for s in meta.get("streams", []):
        if s.get("codec_type") == "video":
            video_stream = s
            break
    if not video_stream:
        raise ValueError(f"No video stream found in {path}")

    duration = float(meta.get("format", {}).get("duration", 0))
    fps_parts = video_stream.get("r_frame_rate", "24/1").split("/")
    fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else 24.0
    width = video_stream.get("width", 1920)
    height = video_stream.get("height", 1080)
    codec = video_stream.get("codec_name", "unknown")

    # Project
    proj = Project(name=name, fps=fps, resolution=f"{width}x{height}",
                   duration=duration)
    g.add(proj)

    # Timeline
    tl = Timeline(fps=fps, resolution=f"{width}x{height}")
    g.add(tl)
    g.add_edge(proj.id, tl.id)

    # Track
    track = Track(name="Video", index=0)
    g.add(track)
    g.add_edge(tl.id, track.id)

    # Main clip
    clip = Clip(start=0.0, end=duration, duration=duration, source=path,
                source_start=0.0, track=track.id, metadata={"codec": codec})
    g.add(clip)
    g.add_edge(track.id, clip.id)

    # Scene detection
    scene_times = detect_scenes(path)
    scene_times = [0.0] + [t for t in scene_times if t > 0.5] + [duration]
    for i in range(len(scene_times) - 1):
        s, e = scene_times[i], scene_times[i + 1]
        if e - s < 0.5:  # skip tiny scenes
            continue
        scene = Scene(start=s, end=e, duration=e - s,
                      topic=f"Scene {i + 1}")
        g.add(scene)
        g.add_edge(clip.id, scene.id, "contains_scene")

    # Asset
    asset = Asset(path=path, asset_type="video",
                  metadata={"duration": duration, "codec": codec,
                            "fps": fps, "resolution": f"{width}x{height}"})
    g.add(asset)
    g.add_edge(proj.id, asset.id, "uses_asset")

    return g


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2 — Speech: faster-whisper transcription (+ optional diarization)
# ═══════════════════════════════════════════════════════════════════════════

def _phase2_speech(
    path: str,
    graph: ProjectGraph,
    hf_token: Optional[str] = None,
    device: str = "cpu",
    model_size: str = "base",
) -> ProjectGraph:
    """Transcribe audio using faster-whisper (no torch needed).

    faster-whisper uses CTranslate2 for efficient CPU inference.
    No GPU required. Word-level timestamps included.

    For diarization: requires torch + pyannote + HF token.
    Without it: all segments assigned to \"SPEAKER_00\".
    """
    try:
        from faster_whisper import WhisperModel, BatchedInferencePipeline
    except ImportError:
        import warnings
        warnings.warn(
            "faster-whisper not installed — skipping speech extraction. "
            "Install with: pip install faster-whisper"
        )
        return graph

    # Find the main clip
    clips = [n for n in graph.nodes.values() if isinstance(n, Clip)]
    if not clips:
        return graph
    clip = clips[0]

    # Check if the file has an audio stream
    from . import _ffmpeg as _ff
    import subprocess, json as _json
    probe_cmd = [
        _ff.ffprobe_path(), "-v", "quiet", "-print_format", "json",
        "-show_streams", "-select_streams", "a", path,
    ]
    probe_r = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=15)
    streams = _json.loads(probe_r.stdout).get("streams", [])
    if not streams:
        return graph  # no audio track — nothing to transcribe

    # Map model sizes: prefer distil models for speed, turbo for balance
    model_map = {
        "tiny": "tiny",
        "base": "base",
        "small": "small",
        "medium": "medium",
        "large": "large-v3",
        "turbo": "turbo",  # fast & accurate, recommended for CPU
    }
    model_name = model_map.get(model_size, "turbo")

    # CPU optimizations:
    # - int8 quantization: 1.5x faster, 35% less RAM
    # - BatchedInferencePipeline: 2x faster with batch_size=16
    # - vad_filter: skip silence, fewer tokens to process
    compute_type = "int8"
    model = WhisperModel(model_name, device="cpu", compute_type=compute_type,
                         num_workers=2)
    batched = BatchedInferencePipeline(model=model)

    # Extract audio as numpy array via our bundled ffmpeg
    # (faster-whisper's internal decoder also uses ffmpeg, which
    # may not be on PATH; pre-decoding avoids that dependency)
    import tempfile
    import numpy as np
    try:
        import soundfile as sf
    except ImportError:
        import warnings
        warnings.warn(
            "soundfile not installed — required for pre-decoded audio. "
            "Install with: pip install soundfile"
        )
        return graph

    tmp_wav = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_wav = f.name
        cmd = [
            _ff.ffmpeg_path(), "-y", "-i", path,
            "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", tmp_wav
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return graph
        audio_array, sample_rate = sf.read(tmp_wav, dtype="float32")
        if sample_rate != 16000:
            import warnings
            warnings.warn(f"Unexpected sample rate {sample_rate}, expected 16000")
    except Exception as e:
        import warnings
        warnings.warn(f"Audio extraction failed: {e}")
        return graph
    finally:
        if tmp_wav and os.path.exists(tmp_wav):
            os.unlink(tmp_wav)

    try:
        segments, info = batched.transcribe(
            audio_array,
            batch_size=16,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        # Convert generator to list to actually run transcription
        segments = list(segments)
    except Exception as e:
        import warnings
        warnings.warn(f"Transcription failed: {e}")
        return graph

    language = info.language
    speaker_set = set()

    for seg in segments:
        start = seg.start
        end = seg.end
        text = seg.text.strip()
        if not text:
            continue

        speaker = "SPEAKER_00"  # no diarization without pyannote

        tx = TranscriptSegment(
            start=start, end=end, text=text,
            speaker=speaker, confidence=seg.avg_logprob,
            scene_id="",
            has_filler=any(
                w in text.lower()
                for w in ("um", "uh", "like", "you know", "i mean")
            ),
        )
        graph.add(tx)

        # Link to scene by temporal overlap
        for scene in graph.scenes:
            if scene.start <= start < scene.end:
                graph.add_edge(scene.id, tx.id, "has_transcript")
                tx.scene_id = scene.id
                break
        else:
            graph.add_edge(clip.id, tx.id, "has_transcript")

        speaker_set.add(speaker)

    # Person nodes
    for spk in speaker_set:
        p = Person(name=spk, start=0, end=clip.end)
        graph.add(p)
        for scene in graph.scenes:
            graph.add_edge(scene.id, p.id, "features")

    # Try diarization if torch + pyannote + token available
    if hf_token:
        try:
            import torch
            from pyannote.audio import Pipeline
            pipe = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=hf_token,
            )
            diarization = pipe(path)
            # Assign speakers to transcript segments
            speaker_map = {}
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                speaker_map.setdefault(speaker, []).append((turn.start, turn.end))
            # Re-assign transcript segments to diarized speakers
            for node in list(graph.nodes.values()):
                if isinstance(node, TranscriptSegment):
                    mid = (node.start + node.end) / 2
                    for spk, intervals in speaker_map.items():
                        for s, e in intervals:
                            if s <= mid < e:
                                node.speaker = spk
                                break
                        else:
                            continue
                        break
        except Exception:
            pass  # diarization best-effort

    return graph


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3 — Vision: CLIP zero-shot tagging [real implementation]
# ═══════════════════════════════════════════════════════════════════════════

# Curated tag set — fast, focused on what an editor needs
# (avoid ImageNet's 10k classes for speed)
DEFAULT_VISION_TAGS = [
    # Setting
    "indoor scene", "outdoor scene", "studio", "café", "home interior",
    "office", "street", "nature", "stage", "kitchen",
    # Subject
    "person", "multiple people", "animal", "dog", "cat", "food",
    "object on table", "screen", "text on screen", "car", "plant",
    # Activity
    "dancing", "speaking", "singing", "playing music", "exercising",
    "working", "cooking", "eating", "playing", "walking",
    # Visual style
    "bright lighting", "dark scene", "warm colors", "cool colors",
    "close-up shot", "wide shot", "animated", "handheld camera",
    "tiktok-style", "professional video",
]

_CLIP_CACHE = {}


def _get_clip_model(model_name: str = "MobileCLIP-S2",
                    device: str = "cpu"):
    """Lazy-load and cache an OpenCLIP model.

    Tries multiple pretrained tags; falls back to ViT-B-32 with
    laion2b if MobileCLIP isn't available.
    """
    key = (model_name, device)
    if key in _CLIP_CACHE:
        return _CLIP_CACHE[key]

    import open_clip
    # Map of model_name -> list of pretrained tags to try
    pretrained_options = {
        "MobileCLIP-S2": ["datacompdr", "mobileclip_s2"],
        "ViT-B-32": ["laion2b_s34b_b79k", "datacomp_xl_s13b_b90k", "openai"],
        "ViT-L-14": ["laion2b_s32b_b82k", "openai"],
    }
    tags_to_try = pretrained_options.get(model_name, [None])
    last_err = None
    for tag in tags_to_try:
        try:
            model, _, preprocess = open_clip.create_model_and_transforms(
                model_name, pretrained=tag, device=device
            )
            model.eval()
            _CLIP_CACHE[key] = (model, preprocess)
            return _CLIP_CACHE[key]
        except Exception as e:
            last_err = e
    # Last-resort fallback: ViT-B-32 with laion2b
    if model_name != "ViT-B-32":
        try:
            model, _, preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="laion2b_s34b_b79k", device=device
            )
            model.eval()
            _CLIP_CACHE[("ViT-B-32", device)] = (model, preprocess)
            # Also cache under the requested name to avoid retrying
            _CLIP_CACHE[key] = (model, preprocess)
            return _CLIP_CACHE[key]
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not load CLIP model: {last_err}")


def _get_clip_tokenizer(model_name: str = "MobileCLIP-S2"):
    import open_clip
    try:
        return open_clip.get_tokenizer(model_name)
    except Exception:
        return open_clip.get_tokenizer("ViT-B-32")


def _extract_keyframes(path: str, scenes: List, max_frames: int = 16,
                       thumb_w: int = 224) -> List[tuple]:
    """Extract one frame per scene midpoint at a small resolution.

    Returns list of (scene_obj, PIL_image_rgb).
    Frames are kept small (224px wide) for fast CLIP inference.
    """
    import tempfile, os
    try:
        from PIL import Image
    except ImportError:
        return []

    results: List[tuple] = []
    with tempfile.TemporaryDirectory() as tmp:
        # Build an ffmpeg select filter: pick one frame per scene midpoint
        if not scenes:
            return []
        # Use the midpoint of each scene
        targets = []
        for s in scenes[:max_frames]:
            t = (s.start + s.end) / 2
            targets.append((s, t))

        # Extract all target frames in a single ffmpeg call
        # select='eq(n,0)+eq(n,X)+eq(n,Y)...' won't work; use multiple outputs
        # Simplest: one ffmpeg call per frame (slow but simple)
        for scene, t in targets:
            out_path = os.path.join(tmp, f"f_{int(t*1000)}.jpg")
            cmd = [
                _ff.ffmpeg_path(), "-y", "-ss", f"{t:.3f}", "-i", path,
                "-frames:v", "1", "-q:v", "5",
                "-vf", f"scale={thumb_w}:-1", out_path
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and os.path.exists(out_path):
                try:
                    img = Image.open(out_path).convert("RGB")
                    results.append((scene, img))
                except Exception:
                    pass
    return results


def _clip_classify(
    images: List,
    tags: List[str],
    model_name: str = "MobileCLIP-S2",
    top_k: int = 5,
    threshold: float = 0.15,
    device: str = "cpu",
) -> List[List[tuple]]:
    """Zero-shot classify a batch of images against tags.

    Returns a list (per image) of (tag, probability) pairs above threshold,
    sorted by probability descending, capped at top_k.
    """
    if not images:
        return []
    try:
        import torch
    except ImportError:
        return [[] for _ in images]
    try:
        model, preprocess = _get_clip_model(model_name, device)
        tokenizer = _get_clip_tokenizer(model_name)
    except Exception:
        return [[] for _ in images]

    # Preprocess all images
    image_tensors = torch.stack([preprocess(img) for img in images]).to(device)
    text_tokens = tokenizer(tags).to(device)

    with torch.no_grad():
        image_features = model.encode_image(image_tensors)
        text_features = model.encode_text(text_tokens)
        # L2 normalize
        image_features = image_features / image_features.norm(dim=-1, keepdim=True)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        # Cosine similarity → softmax probs.
        # Lower temperature = more spread-out distribution; *30 is closer
        # to the raw cosine, *100 makes it very peaked (one tag wins).
        # We use *30 so multiple relevant tags surface above threshold.
        logits = (image_features @ text_features.T) * 30
        probs = logits.softmax(dim=-1).cpu().numpy()

    results = []
    for i in range(len(images)):
        ranked = sorted(enumerate(probs[i]), key=lambda x: -x[1])
        top = [(tags[idx], float(p)) for idx, p in ranked[:top_k] if p >= threshold]
        results.append(top)
    return results


def _phase3_vision(
    path: str,
    graph: ProjectGraph,
    tags: Optional[List[str]] = None,
    model_name: str = "MobileCLIP-S2",
    top_k: int = 5,
    threshold: float = 0.03,
) -> ProjectGraph:
    """Visual analysis: CLIP zero-shot tagging + OpenCV face detection.

    Tries CLIP first (needs torch + open_clip). Falls back to OpenCV
    face detection which works on CPU with no extra dependencies.

    Adds DetectedObject nodes for:
      - visual_tag: CLIP tags like "person", "indoor", "close-up"
      - face:       bounding box of detected faces
    """
    tags = tags or DEFAULT_VISION_TAGS
    scenes = sorted(graph.scenes, key=lambda s: s.start)
    if not scenes:
        return graph

    # Extract keyframes
    keyframes = _extract_keyframes(path, scenes)
    if not keyframes:
        return graph

    # --- Try CLIP ---
    images = [img for _, img in keyframes]
    classifications = _clip_classify(
        images, tags, model_name=model_name, top_k=top_k, threshold=threshold
    )
    if classifications and any(classifications):
        for (scene, _), tags_found in zip(keyframes, classifications):
            for tag, prob in tags_found:
                label = tag.replace(" scene", "").replace(" shot", "").replace(
                    "-style", "").strip()
                obj = DetectedObject(
                    object_type="visual_tag",
                    label=label,
                    start=scene.start,
                    end=scene.end,
                    scene_id=scene.id,
                )
                graph.add(obj)
                graph.add_edge(scene.id, obj.id, "visual_tag")

    # --- Always run face detection (OpenCV Haar, works on CPU out of the box) ---
    try:
        import cv2
        import numpy as np

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if not os.path.exists(cascade_path):
            return graph
        face_cascade = cv2.CascadeClassifier(cascade_path)

        for scene, img in keyframes:
            cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5,
                minSize=(30, 30)
            )

            img_w, img_h = img.size
            for i, (x, y, w, h) in enumerate(faces):
                cx = (x + w / 2) / img_w
                cy = (y + h / 2) / img_h
                fw = w / img_w
                fh = h / img_h

                rel_size = max(fw, fh)
                if rel_size > 0.4:
                    shot = "extreme close-up"
                elif rel_size > 0.25:
                    shot = "close-up"
                elif rel_size > 0.15:
                    shot = "medium shot"
                else:
                    shot = "wide shot"

                obj = DetectedObject(
                    object_type="face",
                    label=f"person (face {i+1})",
                    start=scene.start,
                    end=scene.end,
                    scene_id=scene.id,
                    confidence=1.0,
                    bbox={"x": float(cx), "y": float(cy),
                          "w": float(fw), "h": float(fh)},
                    attributes={"shot_type": shot},
                )
                graph.add(obj)
                graph.add_edge(scene.id, obj.id, "visual_tag")

            # Tag person count
            n_faces = len(faces)
            if n_faces == 1:
                tag = "person"
            elif n_faces >= 2:
                tag = "multiple people"
            else:
                tag = None

            if tag:
                existing = [n for n in graph.nodes.values()
                            if isinstance(n, DetectedObject)
                            and n.scene_id == scene.id
                            and n.label == tag]
                if not existing:
                    obj = DetectedObject(
                        object_type="visual_tag",
                        label=tag,
                        start=scene.start,
                        end=scene.end,
                        scene_id=scene.id,
                    )
                    graph.add(obj)
                    graph.add_edge(scene.id, obj.id, "visual_tag")

    except ImportError:
        pass  # no OpenCV, skip face detection
    except Exception:
        pass  # face detection best-effort

    return graph


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3b — YOLO object detection
# ═══════════════════════════════════════════════════════════════════════════

_YOLO_CACHE = {}


def _get_yolo(model_id: str = "yolov8n.pt"):
    """Lazy-load and cache a YOLO model."""
    if model_id not in _YOLO_CACHE:
        from ultralytics import YOLO
        _YOLO_CACHE[model_id] = YOLO(model_id)
    return _YOLO_CACHE[model_id]


def _phase_yolo(
    path: str,
    graph: ProjectGraph,
    model_id: str = "yolov8n.pt",
    confidence: float = 0.4,
) -> ProjectGraph:
    """Detect objects via YOLO on the same keyframes used by CLIP.

    Adds DetectedObject nodes (object_type='yolo_object') for each
    detected class above the confidence threshold, linked to the scene
    via `detects` edges.
    """
    scenes = sorted(graph.scenes, key=lambda s: s.start)
    if not scenes:
        return graph

    keyframes = _extract_keyframes(path, scenes)
    if not keyframes:
        return graph

    try:
        model = _get_yolo(model_id)
    except Exception as e:
        import warnings
        warnings.warn(f"YOLO model load failed: {e}")
        return graph

    import numpy as np
    for scene, img in keyframes:
        arr = np.array(img)[:, :, ::-1]  # RGB → BGR for cv2-style models
        try:
            results = model(arr, verbose=False, conf=confidence)
        except Exception:
            continue
        if not results:
            continue
        r = results[0]
        names = r.names if hasattr(r, "names") else model.names
        for box in r.boxes:
            cls_id = int(box.cls[0])
            label = (names.get(cls_id, str(cls_id))
                     if isinstance(names, dict) else names[cls_id])
            conf = float(box.conf[0])
            obj = DetectedObject(
                object_type="yolo_object",
                label=label,
                start=scene.start,
                end=scene.end,
                scene_id=scene.id,
                confidence=conf,
            )
            graph.add(obj)
            graph.add_edge(scene.id, obj.id, "detects")

    return graph


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3c — OCR text extraction
# ═══════════════════════════════════════════════════════════════════════════

_OCR_CACHE = {}


def _get_ocr(lang_list: Optional[List[str]] = None):
    """Lazy-load and cache an EasyOCR Reader."""
    key = tuple(lang_list or ["en"])
    if key not in _OCR_CACHE:
        import easyocr
        _OCR_CACHE[key] = easyocr.Reader(list(key), gpu=False)
    return _OCR_CACHE[key]


def _phase_ocr(
    path: str,
    graph: ProjectGraph,
    lang_list: Optional[List[str]] = None,
    confidence: float = 0.3,
) -> ProjectGraph:
    """Extract on-screen text via EasyOCR on the same keyframes.

    Adds DetectedObject nodes (object_type='ocr_text') for each text
    region detected, linked to the scene via `has_text` edges.
    """
    scenes = sorted(graph.scenes, key=lambda s: s.start)
    if not scenes:
        return graph

    keyframes = _extract_keyframes(path, scenes)
    if not keyframes:
        return graph

    try:
        reader = _get_ocr(lang_list)
    except Exception as e:
        import warnings
        warnings.warn(f"EasyOCR load failed: {e}")
        return graph

    import numpy as np
    for scene, img in keyframes:
        arr = np.array(img)
        try:
            results = reader.readtext(arr)
        except Exception:
            continue
        for bbox, text, conf in results:
            if conf < confidence or not text.strip():
                continue
            text_clean = " ".join(text.split())
            if len(text_clean) > 80:
                text_clean = text_clean[:77] + "..."
            obj = DetectedObject(
                object_type="ocr_text",
                label=text_clean,
                start=scene.start,
                end=scene.end,
                scene_id=scene.id,
                confidence=conf,
            )
            graph.add(obj)
            graph.add_edge(scene.id, obj.id, "has_text")

    return graph


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4 — Audio: VAD + RMS + beats + emotion
# ═══════════════════════════════════════════════════════════════════════════

def detect_audio_events(
    path: str,
    noise_db: float = -30.0,
    min_silence: float = 0.4,
) -> List[dict]:
    """Detect silence/speech ranges using ffmpeg silencedetect.

    Args:
        path: Path to a video (or audio) file with an audio stream.
        noise_db: Threshold in dB below which audio is considered silence.
        min_silence: Minimum silence duration to detect (seconds).

    Returns:
        List of event dicts: {start, end, speech_active, kind}.
        Alternates between speech and silence ranges. Empty if the
        file has no audio stream or ffmpeg fails.
    """
    if not has_audio_stream(path):
        return []

    cmd = [
        _ff.ffmpeg_path(), "-i", path,
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f", "null", "-"
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []

    # Parse silence_start / silence_end pairs from stderr
    silences: List[dict] = []
    current: Optional[dict] = None
    for line in r.stderr.split("\n"):
        if "silence_start:" in line:
            try:
                t = float(line.split("silence_start:")[1].strip().split()[0])
                current = {"start": t, "end": None}
            except (ValueError, IndexError):
                current = None
        elif "silence_end:" in line and current is not None:
            try:
                t = float(line.split("silence_end:")[1].strip().split()[0])
                current["end"] = t
                silences.append(current)
            except (ValueError, IndexError):
                pass
            current = None

    # Total duration to handle trailing ranges
    try:
        duration = float(probe_video(path).get("format", {}).get("duration", 0))
    except Exception:
        duration = silences[-1]["end"] if silences and silences[-1]["end"] else 0

    # Build alternating speech/silence events
    events: List[dict] = []
    cursor = 0.0
    for sil in silences:
        s_end = sil["end"] if sil["end"] is not None else duration
        if sil["start"] > cursor + 0.05:  # speech before this silence
            events.append({
                "start": cursor, "end": sil["start"],
                "speech_active": True, "kind": "speech",
            })
        events.append({
            "start": sil["start"], "end": s_end,
            "speech_active": False, "kind": "silence",
        })
        cursor = s_end
    if cursor < duration - 0.05:
        events.append({
            "start": cursor, "end": duration,
            "speech_active": True, "kind": "speech",
        })

    return events


def _compute_rms_per_event(
    path: str,
    events: List[dict],
) -> dict:
    """Run ffmpeg astats to get RMS levels, assign per event.

    ffmpeg astats prints lines like:
        [Parsed_astats_0 @ ...] RMS level dB: -7.267785
    We parse the overall RMS for the file, and also (when reset=N) try
    to get per-chunk values via 't:TIMESTAMP' markers.

    Returns dict mapping (start, end) -> mean RMS in dB.
    """
    fallback = {(e["start"], e["end"]): -20.0 for e in events}
    if not events or not has_audio_stream(path):
        return fallback

    # Try per-chunk astats first
    cmd = [
        _ff.ffmpeg_path(), "-i", path,
        "-af", "astats=metadata=1:reset=1",
        "-f", "null", "-"
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return fallback
    if r.returncode != 0:
        return fallback

    # Parse all "RMS level dB: VALUE" lines (timestamped if reset worked)
    rms_chunks: List[tuple] = []  # (time_sec, rms_db)
    overall_rms: List[float] = []
    for line in r.stderr.split("\n"):
        if "RMS level dB:" not in line:
            continue
        try:
            value = float(line.split("RMS level dB:")[1].strip().split()[0])
        except (ValueError, IndexError):
            continue
        if " t:" in line:
            try:
                t = float(line.split(" t:")[1].split()[0])
                rms_chunks.append((t, value))
            except (ValueError, IndexError):
                overall_rms.append(value)
        else:
            overall_rms.append(value)

    # Per-event assignment
    result = {}
    if rms_chunks:
        for ev in events:
            in_range = [rms for t, rms in rms_chunks
                        if ev["start"] <= t < ev["end"]
                        and rms > -90.0]  # ignore -inf/silence
            if in_range:
                result[(ev["start"], ev["end"])] = sum(in_range) / len(in_range)
            else:
                nearest = min(rms_chunks, key=lambda c: abs(c[0] - ev["start"]))
                result[(ev["start"], ev["end"])] = max(nearest[1], -90.0)
    elif overall_rms:
        # No per-chunk timestamps: assign overall RMS to all events
        valid = [r for r in overall_rms if r > -90.0]
        mean_rms = sum(valid) / len(valid) if valid else -20.0
        for ev in events:
            result[(ev["start"], ev["end"])] = mean_rms
    else:
        return fallback
    return result


def _phase4_audio(
    path: str,
    graph: ProjectGraph,
) -> ProjectGraph:
    """Extract real audio events via ffmpeg silencedetect + per-event RMS.

    For each detected speech/silence range, adds an AudioSegment node
    (with start/end + real RMS via astats) linked to the containing Scene
    via a `has_audio` edge. Falls back to synthetic segments when no
    audio stream exists.
    """
    events = detect_audio_events(path)
    if not events:
        # No audio stream — fall back to synthetic segments
        import random as _random
        _random.seed(42)
        scenes = graph.scenes
        if not scenes:
            return graph
        duration = scenes[-1].end if scenes else 0
        t = 0.0
        while t < duration:
            seg_end = min(t + 2.0, duration)
            aseg = AudioSegment(
                start=t, end=seg_end, time=t,
                rms=_random.uniform(-24, -3),
                beat=_random.random() < 0.12,
                emotion=_random.choice(["neutral", "engaged", "excited"]),
                noise_level=_random.uniform(0.01, 0.15),
                speech_active=False,
            )
            graph.add(aseg)
            for scene in scenes:
                if scene.start <= t < scene.end:
                    graph.add_edge(scene.id, aseg.id, "has_audio")
                    break
            t += 2.0
        return graph

    # Real audio events: VAD + per-event RMS
    rms_map = _compute_rms_per_event(path, events)
    scenes = sorted(graph.scenes, key=lambda s: s.start)
    for ev in events:
        rms = rms_map.get((ev["start"], ev["end"]), -20.0)
        aseg = AudioSegment(
            start=ev["start"],
            end=ev["end"],
            time=ev["start"],  # alias kept for compat
            rms=rms,
            beat=False,  # filled in by _phase4b_beats
            emotion="neutral",  # filled in by _phase4c_emotion
            noise_level=0.05 if ev["speech_active"] else 0.30,
            speech_active=ev["speech_active"],
        )
        graph.add(aseg)
        containing = [s for s in scenes if s.start <= ev["start"] < s.end]
        if containing:
            graph.add_edge(containing[0].id, aseg.id, "has_audio")

    return graph


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4b — Beat detection via librosa
# ═══════════════════════════════════════════════════════════════════════════

def _phase4b_beats(
    path: str,
    graph: ProjectGraph,
) -> ProjectGraph:
    """Detect musical beats in the audio stream and flag AudioSegments
    that overlap with at least one beat.

    Updates AudioSegment.beat in place (no new nodes).
    """
    if not has_audio_stream(path):
        return graph
    if not graph.audio:
        return graph
    try:
        import librosa
        import numpy as np
        import tempfile
    except ImportError:
        return graph

    # Extract mono 22050Hz audio
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    try:
        cmd = [
            _ff.ffmpeg_path(), "-y", "-i", path,
            "-vn", "-ac", "1", "-ar", "22050", "-f", "wav", wav_path
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return graph
        y, sr = librosa.load(wav_path, sr=22050)
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    except Exception as e:
        import warnings
        warnings.warn(f"librosa beat detection failed: {e}")
        return graph
    finally:
        import os
        if os.path.exists(wav_path):
            os.unlink(wav_path)

    # Mark AudioSegments that overlap with any beat
    for aseg in graph.audio:
        overlap = any(aseg.start <= t < aseg.end for t in beat_times)
        if overlap:
            aseg.beat = True

    return graph


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4c — Emotion classification via wav2vec2
# ═══════════════════════════════════════════════════════════════════════════

_EMOTION_MODEL_CACHE = {}


def _get_emotion_model(model_id: str = "superb/wav2vec2-base-superb-er"):
    """Lazy-load and cache the emotion classification model."""
    if model_id not in _EMOTION_MODEL_CACHE:
        from transformers import AutoFeatureExtractor, AutoModelForAudioClassification
        import torch
        extractor = AutoFeatureExtractor.from_pretrained(model_id)
        model = AutoModelForAudioClassification.from_pretrained(model_id)
        model.eval()
        _EMOTION_MODEL_CACHE[model_id] = (extractor, model)
    return _EMOTION_MODEL_CACHE[model_id]


def _classify_emotion(
    audio_array,
    sample_rate: int = 16000,
) -> str:
    """Classify emotion of an audio array (numpy float32, 16kHz mono).

    Returns label like 'happy', 'angry', 'sad', 'neutral'.
    """
    try:
        import torch
    except ImportError:
        return "neutral"
    try:
        extractor, model = _get_emotion_model()
    except Exception:
        return "neutral"
    try:
        inputs = extractor(
            audio_array, sampling_rate=sample_rate,
            return_tensors="pt", padding=True
        )
        with torch.no_grad():
            outputs = model(**inputs)
        probs = outputs.logits.softmax(dim=-1)[0]
        idx = int(probs.argmax())
        return model.config.id2label[idx]
    except Exception:
        return "neutral"


def _phase4c_emotion(
    path: str,
    graph: ProjectGraph,
) -> ProjectGraph:
    """Classify emotion via wav2vec2-superb-er.

    Performance optimization: classifies the WHOLE audio once (one model
    inference), then assigns the same emotion label to all speech
    segments. This is 5-10x faster than per-segment classification and
    works well in practice since short videos have one overall mood.

    Updates AudioSegment.emotion in place. Skips entirely if:
    - no audio stream
    - no audio events in graph
    - wav2vec2/soundfile not available
    """
    if not has_audio_stream(path):
        return graph
    if not graph.audio:
        return graph
    import numpy as np
    import tempfile
    import os

    # Extract audio once as 16kHz mono
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    try:
        cmd = [
            _ff.ffmpeg_path(), "-y", "-i", path,
            "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", wav_path
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return graph
        try:
            import soundfile as sf
            full_audio, sr = sf.read(wav_path, dtype="float32")
        except ImportError:
            return graph
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)

    if len(full_audio) < sr * 0.3:  # < 300ms total, skip
        return graph

    # ONE classification on the full audio
    overall_emotion = _classify_emotion(full_audio, sample_rate=sr)

    # Assign to all speech segments
    for aseg in graph.audio:
        if aseg.speech_active:
            aseg.emotion = overall_emotion
        # Silence segments keep "neutral" (or whatever they had)

    return graph


# ═══════════════════════════════════════════════════════════════════════════
# Master: build_graph() — progressive, depth-aware
# ═══════════════════════════════════════════════════════════════════════════

def build_graph(
    path: str,
    depth: str = "fast",
    hf_token: Optional[str] = None,
    device: str = "cpu",
    model_size: str = "base",
) -> ProjectGraph:
    """Build a ProjectGraph from a real video file.

    Args:
        path: Path to video file.
        depth: One of "fast", "speech", "vision", "full".
        hf_token: HuggingFace token for pyannote diarization (optional).
        device: "cpu" or "cuda".
        model_size: Whisper model size: "tiny", "base", "small", "medium", "large-v2".

    Returns:
        ProjectGraph enriched to the requested depth.
    """
    g = _phase1_fast(path)

    if depth in ("speech", "vision", "full"):
        g = _phase2_speech(path, g, hf_token=hf_token,
                           device=device, model_size=model_size)

    if depth in ("vision", "full"):
        g = _phase3_vision(path, g)        # CLIP tags + face detection
        g = _phase_yolo(path, g)           # YOLO objects
        g = _phase_ocr(path, g)            # OCR text

    if depth == "full":
        g = _phase4_audio(path, g)         # VAD + RMS
        g = _phase4b_beats(path, g)        # beat detection
        g = _phase4c_emotion(path, g)       # emotion classification

    return g


def enrich_graph(
    path: str,
    graph: ProjectGraph,
    depth: str = "speech",
    hf_token: Optional[str] = None,
    device: str = "cpu",
    model_size: str = "base",
) -> ProjectGraph:
    """Enrich an existing ProjectGraph with additional phases.

    Args:
        path: Path to video file.
        graph: Existing ProjectGraph (from a previous observe() call).
        depth: Phase to add: "speech", "vision", "full".
        hf_token: HuggingFace token for diarization.
        device: "cpu" or "cuda".
        model_size: Whisper model size.

    Returns:
        The same graph, enriched.
    """
    if depth in ("speech", "vision", "full"):
        graph = _phase2_speech(path, graph, hf_token=hf_token,
                               device=device, model_size=model_size)

    if depth in ("vision", "full"):
        graph = _phase3_vision(path, graph)
        graph = _phase_yolo(path, graph)
        graph = _phase_ocr(path, graph)

    if depth == "full":
        graph = _phase4_audio(path, graph)
        graph = _phase4b_beats(path, graph)
        graph = _phase4c_emotion(path, graph)

    return graph


# ═══════════════════════════════════════════════════════════════════════════
# Smart entry points — auto-pick depth, batch processing, CLI-friendly
# ═══════════════════════════════════════════════════════════════════════════

def auto_depth(duration_seconds: float) -> str:
    """Pick the best depth for a video based on its duration.

    - < 30s   → "full"   (short clips can afford everything)
    - 30s..5min → "vision" (skip emotion which is the slowest phase)
    - > 5min  → "speech" (transcripts + scenes only, vision is too slow)
    """
    if duration_seconds < 30:
        return "full"
    if duration_seconds < 300:
        return "vision"
    return "speech"


def build_graph_smart(
    path: str,
    force_depth: Optional[str] = None,
    verbose: bool = True,
) -> ProjectGraph:
    """Build a ProjectGraph with auto-picked depth based on video length.

    Args:
        path: Path to video file.
        force_depth: Override auto-pick. One of None, "fast", "speech",
            "vision", "full".
        verbose: Print phase timings to stdout.

    Returns:
        ProjectGraph.
    """
    t_total = time.time()
    duration = 0.0
    try:
        meta = probe_video(path)
        duration = float(meta.get("format", {}).get("duration", 0))
    except Exception:
        pass

    depth = force_depth or auto_depth(duration)
    if verbose:
        mins = duration / 60 if duration else 0
        print(f"[flow] {os.path.basename(path)} | "
              f"{duration:.1f}s ({mins:.1f}min) | depth={depth}")

    g = build_graph(path, depth=depth, model_size="tiny")

    if verbose:
        print(f"[flow] total: {time.time()-t_total:.1f}s | "
              f"{g.stats()['total_nodes']} nodes, "
              f"{g.stats()['total_edges']} edges")
    return g


def process_video(
    path: str,
    output_dir: Optional[str] = None,
    force_depth: Optional[str] = None,
    save_json: bool = True,
    save_summary: bool = True,
    verbose: bool = True,
) -> ProjectGraph:
    """One-call API: observe a video, save the graph, print a summary.

    Args:
        path: Path to video file.
        output_dir: Where to write artifacts. Defaults to the video's folder.
        force_depth: Override auto-picked depth.
        save_json: Write <name>.flow.json with the full graph.
        save_summary: Write <name>.flow.txt with the LLM-facing summary.
        verbose: Print progress to stdout.

    Returns:
        ProjectGraph for the video.
    """
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]

    g = build_graph_smart(path, force_depth=force_depth, verbose=verbose)

    if save_json:
        json_path = os.path.join(output_dir, f"{base}.flow.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(g.to_dict(), f, indent=2, ensure_ascii=False)
        if verbose:
            print(f"[flow] saved: {json_path}")

    if save_summary:
        # LLM-facing summary: all observations in one window
        duration = 0.0
        try:
            duration = float(g.nodes[g._root_id].duration
                             if g._root_id in g.nodes else 0)
        except Exception:
            pass
        # Use the longest scene end if project duration missing
        if not duration and g.scenes:
            duration = max(s.end for s in g.scenes)
        txt_path = os.path.join(output_dir, f"{base}.flow.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(g.observe_window(0.0, duration))
        if verbose:
            print(f"[flow] saved: {txt_path}")

    return g


def process_folder(
    folder: str,
    extensions: tuple = (".mp4", ".mov", ".mkv", ".webm", ".avi"),
    force_depth: Optional[str] = None,
    save_json: bool = True,
    save_summary: bool = True,
    verbose: bool = True,
) -> List[ProjectGraph]:
    """Process every video in a folder. Returns list of graphs.

    Skips files that have already been processed (checks for .flow.json).
    """
    graphs: List[ProjectGraph] = []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith(extensions):
            continue
        path = os.path.join(folder, name)
        base = os.path.splitext(name)[0]
        if save_json and os.path.exists(os.path.join(folder, f"{base}.flow.json")):
            if verbose:
                print(f"[flow] skip (already done): {name}")
            continue
        try:
            g = process_video(
                path, output_dir=folder,
                force_depth=force_depth,
                save_json=save_json, save_summary=save_summary,
                verbose=verbose,
            )
            graphs.append(g)
        except Exception as e:
            if verbose:
                print(f"[flow] FAILED on {name}: {e}")
    return graphs


# ═══════════════════════════════════════════════════════════════════════════
# Synthetic project generator (unchanged — for testing without media)
# ═══════════════════════════════════════════════════════════════════════════

SCENARIO_SPECS = {
    "podcast": {
        "duration_min": 45, "topics": ["Opening", "Guest Intro", "Career Story",
            "Industry Trends", "Advice", "Rapid Fire", "Closing"],
        "speakers": ["Host_Alex", "Guest_Maya"],
        "fps": 24, "resolution": "1920x1080",
    },
    "interview": {
        "duration_min": 25, "topics": ["Intro", "Background", "Role", "Tech Q&A",
            "Problem Solving", "Wrap-up"],
        "speakers": ["Interviewer_Dan", "Candidate_Sam"],
        "fps": 24, "resolution": "1920x1080",
    },
    "vlog": {
        "duration_min": 15, "topics": ["Intro", "Main Content", "B-roll", "Review", "Outro"],
        "speakers": ["Creator_Jo"],
        "fps": 30, "resolution": "1920x1080",
    },
    "tutorial": {
        "duration_min": 30, "topics": ["Intro", "Prerequisites", "Step 1", "Step 2",
            "Step 3", "Common Mistakes", "Results", "Next Steps"],
        "speakers": ["Teacher_Lee"],
        "fps": 24, "resolution": "3840x2160",
    },
}

TRANSCRIPT_SNIPPETS = {
    "Opening": "Welcome to today's episode. I'm excited to have you here.",
    "Guest Intro": "Our guest today has an incredible background in the industry.",
    "Career Story": "I started my career at a small startup back in 2010.",
    "Industry Trends": "The biggest trend we're seeing is AI integration across everything.",
    "Advice": "My best advice for newcomers is to just start building things.",
    "Rapid Fire": "Favorite book? That's a tough one. I'd say it changes every year.",
    "Closing": "Thanks for listening. Don't forget to subscribe and share.",
    "Intro": "Hey everyone, welcome back to the channel.",
    "Background": "I studied computer science and then worked at three companies.",
    "Role": "This position is on the infrastructure team.",
    "Tech Q&A": "How would you design a rate limiter for a distributed system?",
    "Problem Solving": "Let me walk you through my approach to this problem.",
    "Wrap-up": "Any final questions before we wrap up?",
    "Main Content": "Today I want to talk about something that's been on my mind.",
    "B-roll": None,
    "Review": "Overall I'd give this product a solid eight out of ten.",
    "Outro": "If you enjoyed this, hit like and subscribe. See you next time.",
    "Prerequisites": "Before we start, make sure you have Python 3.11 installed.",
    "Step 1": "First, let's create a new project directory.",
    "Step 2": "Now we need to configure the database connection.",
    "Step 3": "Finally, let's deploy this to production.",
    "Common Mistakes": "A common mistake is forgetting to close the connection.",
    "Results": "And here's the final result. Looks great, right?",
    "Next Steps": "In the next tutorial, we'll cover advanced patterns.",
}


def build_graph_synthetic(scenario: str = "podcast", seed: int = 42) -> ProjectGraph:
    """Build a realistic ProjectGraph without needing a video file."""
    spec = SCENARIO_SPECS.get(scenario, SCENARIO_SPECS["podcast"])
    random.seed(seed)
    duration = spec["duration_min"] * 60
    n_topics = len(spec["topics"])
    scene_dur = duration / n_topics

    graph = ProjectGraph(name=f"{scenario}_synthetic")

    proj = Project(name=f"{scenario}_synthetic", fps=spec["fps"],
                   resolution=spec["resolution"], duration=duration)
    graph.add(proj)

    tl = Timeline(fps=spec["fps"], resolution=spec["resolution"])
    graph.add(tl)
    graph.add_edge(proj.id, tl.id)

    track = Track(name="Track 1", index=0)
    graph.add(track)
    graph.add_edge(tl.id, track.id)

    main_clip = Clip(start=0.0, end=duration, duration=duration,
                     source=f"{scenario}_raw.mp4", source_start=0.0,
                     track=track.id)
    graph.add(main_clip)
    graph.add_edge(track.id, main_clip.id)

    for i, topic in enumerate(spec["topics"]):
        s = i * scene_dur
        e = min(s + scene_dur, duration)
        speaker = random.choice(spec["speakers"])
        people_list = [speaker] if random.random() < 0.8 else spec["speakers"]

        scene = Scene(start=s, end=e, duration=e - s, topic=topic,
                      activity="discussion", people=people_list)
        graph.add(scene)
        graph.add_edge(main_clip.id, scene.id, "contains_scene")

        # Transcript segments
        snippet = TRANSCRIPT_SNIPPETS.get(topic)
        if snippet and topic != "B-roll":
            seg_count = max(1, int(scene_dur / 15))
            for si in range(seg_count):
                seg_start = s + si * (scene_dur / seg_count)
                seg_end = seg_start + min(14, scene_dur / seg_count)
                words = ["the", "a", "is", "and", "in", "to", "for", "with",
                         "we", "they", "our", "this", "that", "it", "have",
                         "will", "can", "about", "also", "now"] * 3
                random.shuffle(words)
                text = snippet + " " + " ".join(words[:20])
                tx = TranscriptSegment(start=seg_start, end=seg_end, text=text,
                                       speaker=speaker, scene_id=scene.id,
                                       has_filler=any(
                                           w in text.lower()
                                           for w in ("um", "uh", "like", "sort of")
                                       ))
                graph.add(tx)
                graph.add_edge(scene.id, tx.id, "has_transcript")

        # Person nodes
        for person in people_list:
            p = Person(name=person, start=s, end=e, scene_id=scene.id)
            graph.add(p)
            graph.add_edge(scene.id, p.id, "features")

        # Audio segments
        audio_dur = 2.0
        t = s
        while t < e:
            seg_end_t = min(t + audio_dur, e)
            rms = random.uniform(-24, -3)
            beat = random.random() < 0.12
            speech = (snippet is not None and topic != "B-roll")
            aseg = AudioSegment(
                time=t, rms=rms, beat=beat,
                emotion=random.choice(["neutral", "engaged", "excited"]),
                noise_level=random.uniform(0.01, 0.15),
                speech_active=speech,
            )
            graph.add(aseg)
            graph.add_edge(scene.id, aseg.id, "has_audio")
            t += audio_dur

        # Objects
        if random.random() < 0.5:
            obj = DetectedObject(object_type="laptop", start=s, end=e,
                                 scene_id=scene.id)
            graph.add(obj)
            graph.add_edge(scene.id, obj.id, "contains_object")
        if random.random() < 0.3:
            obj = DetectedObject(object_type="microphone", start=s, end=e,
                                 scene_id=scene.id)
            graph.add(obj)
            graph.add_edge(scene.id, obj.id, "contains_object")

    # Assets
    asset = Asset(path=f"{scenario}_raw.mp4", asset_type="video",
                  metadata={"duration": duration, "codec": "h264"})
    graph.add(asset)
    graph.add_edge(proj.id, asset.id, "uses_asset")

    return graph
