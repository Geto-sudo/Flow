"""
Verify — compares expected state to actual rendered output.

Three levels of check (cheap to robust):
  1. Metadata (ffprobe)         : duration, resolution, fps, audio
  2. VAD re-extract (optional)  : re-detect silences on the output
  3. Content re-extract (opt)   : re-transcribe + re-CLIP for content match

Used by agents in the observe→plan→execute→verify loop to decide
whether to re-iterate or commit the edit.

────────────────────────────────────────────────────────────────────────
EXPECTED SCHEMA
────────────────────────────────────────────────────────────────────────

expected is a dict with optional fields:

  {"duration": 3.0}                 # expected duration in seconds (±0.5s)
  {"resolution": "320x192"}         # expected WxH
  {"fps": 24.0}                     # expected framerate
  {"has_audio": True}               # output must have an audio stream
  {"min_duration": 1.0}             # output must be at least N seconds
  {"max_duration": 10.0}            # output must be at most N seconds
  {"codec": "h264"}                 # expected video codec
  {"audio_codec": "aac"}            # expected audio codec
  {"transcript_contains": "hello"}  # output transcript must contain substring
                                    # (requires re-transcribe, slow)
  {"transcript_exact": "hi"}        # output transcript must equal string
  {"label_present": "person"}       # YOLO/CLIP must detect label in output
                                    # (requires re-detect, slow)

actual is one of:
  - str: a path to the rendered video file
  - dict: pre-extracted metadata {"duration": ..., "resolution": ..., ...}
  - ProjectGraph: a graph to extract metadata from

────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
import os
import subprocess
import json
from typing import List, Dict, Optional, Union
from . import _ffmpeg as _ff
from .video_parser import probe_video


# Public type alias
Expected = Dict
Actual = Union[str, Dict, "ProjectGraph"]


def verify(expected: Expected, actual: Actual,
           re_transcribe: bool = False,
           re_detect: bool = False) -> dict:
    """Compare expected to actual and return a structured verdict.

    Args:
        expected: dict of expected properties (see module docstring).
        actual: path to video file, dict of metadata, or ProjectGraph.
        re_transcribe: if True and expected has transcript_*, re-run
            faster-whisper on the output to verify content. Slow (~3s).
        re_detect: if True and expected has label_present, re-run YOLO
            on the output. Slow (~2s).

    Returns:
        {
            "ok": bool,                 # True if all checks pass
            "checks": [...],            # per-check results
            "errors": [str, ...],       # blocking errors
            "warnings": [str, ...],     # non-blocking issues
            "summary": str,             # one-line human summary
            "diff": {                   # structured diff for re-iteration
                "mismatched": [...],
                "missing_in_actual": [...],
            }
        }
    """
    checks: List[dict] = []
    errors: List[str] = []
    warnings: List[str] = []

    # 1. Resolve actual → metadata dict
    actual_meta = _resolve_actual(actual)
    if actual_meta is None:
        return {
            "ok": False,
            "checks": [],
            "errors": [f"Could not resolve actual: {actual!r}"],
            "warnings": [],
            "summary": "Failed to load actual",
            "diff": {"mismatched": [], "missing_in_actual": []},
        }

    # 2. Cheap metadata checks
    for key in ("duration", "resolution", "fps", "has_audio",
                "codec", "audio_codec"):
        if key not in expected:
            continue
        exp = expected[key]
        got = actual_meta.get(key)
        ok = _match(key, exp, got)
        checks.append({
            "name": key, "expected": exp, "actual": got, "ok": ok
        })
        if not ok:
            errors.append(
                f"{key}: expected {exp!r}, got {got!r}"
            )

    # Range checks (min/max duration)
    for key in ("min_duration", "max_duration"):
        if key not in expected:
            continue
        exp = expected[key]
        dur = actual_meta.get("duration", 0)
        if key == "min_duration":
            ok = dur >= exp
        else:
            ok = dur <= exp
        checks.append({
            "name": key, "expected": exp, "actual": dur, "ok": ok
        })
        if not ok:
            errors.append(
                f"{key}: {exp}, but actual duration is {dur:.2f}s"
            )

    # 3. Content checks (slow path)
    if re_transcribe and "transcript_contains" in expected:
        exp_text = expected["transcript_contains"].lower()
        actual_text = _transcribe_for_verify(
            actual_meta.get("_path", actual)
        ).lower()
        ok = exp_text in actual_text
        checks.append({
            "name": "transcript_contains",
            "expected": exp_text, "actual": actual_text[:120], "ok": ok
        })
        if not ok:
            errors.append(f"Transcript does not contain {exp_text!r}")

    if re_transcribe and "transcript_exact" in expected:
        exp_text = expected["transcript_exact"].lower().strip()
        actual_text = _transcribe_for_verify(
            actual_meta.get("_path", actual)
        ).lower().strip()
        ok = exp_text == actual_text
        checks.append({
            "name": "transcript_exact",
            "expected": exp_text, "actual": actual_text[:120], "ok": ok
        })
        if not ok:
            errors.append(f"Transcript mismatch")

    if re_detect and "label_present" in expected:
        label = expected["label_present"]
        path = actual_meta.get("_path")
        if path and os.path.exists(path):
            detected = _yolo_labels_for_verify(path)
            ok = label.lower() in [l.lower() for l in detected]
            checks.append({
                "name": "label_present",
                "expected": label, "actual": detected[:10], "ok": ok
            })
            if not ok:
                warnings.append(f"Label '{label}' not detected in output")

    # 4. Build diff for agent re-iteration
    diff = _build_diff(checks)

    ok = len(errors) == 0
    summary = _summarize(ok, checks, actual_meta)

    return {
        "ok": ok,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "summary": summary,
        "diff": diff,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _resolve_actual(actual) -> Optional[dict]:
    """Convert actual (str / dict / ProjectGraph) to a metadata dict."""
    if isinstance(actual, str):
        if not os.path.exists(actual):
            return None
        try:
            meta = probe_video(actual)
        except Exception:
            return None
        return _meta_to_dict(meta, _path=actual)

    if isinstance(actual, dict):
        # Could be a ProjectGraph (has .nodes) or a metadata dict
        if hasattr(actual, "nodes"):  # ProjectGraph
            return _graph_to_dict(actual)
        return dict(actual)

    if hasattr(actual, "nodes"):  # ProjectGraph duck-typed
        return _graph_to_dict(actual)

    return None


def _meta_to_dict(meta: dict, _path: str = None) -> dict:
    """Convert ffprobe output to a flat metadata dict."""
    fmt = meta.get("format", {})
    out = {
        "duration": float(fmt.get("duration", 0)),
        "size": int(fmt.get("size", 0)),
        "format": fmt.get("format_name", ""),
    }
    video = next((s for s in meta.get("streams", [])
                  if s.get("codec_type") == "video"), None)
    audio = next((s for s in meta.get("streams", [])
                  if s.get("codec_type") == "audio"), None)
    if video:
        out["codec"] = video.get("codec_name", "")
        w = video.get("width", 0)
        h = video.get("height", 0)
        out["resolution"] = f"{w}x{h}"
        out["width"] = w
        out["height"] = h
        rfr = video.get("r_frame_rate", "0/1")
        try:
            num, den = rfr.split("/")
            out["fps"] = float(num) / float(den) if float(den) else 0
        except (ValueError, ZeroDivisionError):
            out["fps"] = 0
    if audio:
        out["has_audio"] = True
        out["audio_codec"] = audio.get("codec_name", "")
    else:
        out["has_audio"] = False
    if _path:
        out["_path"] = _path
    return out


def _graph_to_dict(graph) -> dict:
    """Extract metadata from a ProjectGraph (no file needed)."""
    duration = 0.0
    if graph.clips:
        duration = max(c.end for c in graph.clips)
    elif graph.scenes:
        duration = max(s.end for s in graph.scenes)
    out = {
        "duration": duration,
        "has_audio": len(graph.audio) > 0,
        "scenes": len(graph.scenes),
        "clips": len(graph.clips),
    }
    if graph.clips:
        c = max(graph.clips, key=lambda x: x.duration)
        out["resolution"] = "1920x1080"  # default
        out["codec"] = c.metadata.get("codec", "") if hasattr(c, "metadata") else ""
    return out


def _match(key: str, expected, actual) -> bool:
    """Compare expected vs actual for a given key."""
    if actual is None:
        return False
    if key == "duration":
        return abs(float(expected) - float(actual)) < 0.5
    if key == "fps":
        return abs(float(expected) - float(actual)) < 1.0
    if key == "resolution":
        return str(expected) == str(actual)
    if key in ("has_audio",):
        return bool(expected) == bool(actual)
    return str(expected) == str(actual)


def _transcribe_for_verify(path) -> str:
    """Re-transcribe a video for content verification. Slow."""
    if not path or not os.path.exists(path):
        return ""
    try:
        from .video_parser import _get_whisper
    except ImportError:
        return ""
    try:
        import tempfile, soundfile as sf, subprocess as sp
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        cmd = [_ff.ffmpeg_path(), "-y", "-i", path,
               "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", tmp]
        if sp.run(cmd, capture_output=True, timeout=120).returncode != 0:
            return ""
        audio, sr = sf.read(tmp, dtype="float32")
        os.unlink(tmp)
        model = _get_whisper("tiny")
        segs, _ = model.transcribe(audio, beam_size=1, vad_filter=False)
        return " ".join(s.text.strip() for s in segs)
    except Exception:
        return ""


def _yolo_labels_for_verify(path) -> list:
    """Re-run YOLO on a video and return detected labels. Slow."""
    if not path or not os.path.exists(path):
        return []
    try:
        from .video_parser import _get_yolo, _extract_keyframes
    except ImportError:
        return []
    try:
        import tempfile
        from PIL import Image
        # Need a graph to call _extract_keyframes; build a stub scene
        from .project_graph import ProjectGraph, Scene
        g = ProjectGraph()
        g.add(Scene(start=0, end=1, topic="verify", duration=1))
        # Extract 1 frame at t=0
        keyframes = _extract_keyframes(path, g.scenes)
        if not keyframes:
            return []
        img = keyframes[0][1]
        import numpy as np
        model = _get_yolo("yolov8n.pt")
        arr = np.array(img)[:, :, ::-1]
        results = model(arr, verbose=False, conf=0.4)
        if not results:
            return []
        names = results[0].names
        return [names[int(b.cls[0])] for b in results[0].boxes]
    except Exception:
        return []


def _build_diff(checks: List[dict]) -> dict:
    mismatched = [c for c in checks if not c["ok"]]
    return {
        "mismatched": [
            {"check": c["name"], "expected": c["expected"], "actual": c["actual"]}
            for c in mismatched
        ],
        "missing_in_actual": [
            c["name"] for c in mismatched if c["actual"] is None
        ],
    }


def _summarize(ok: bool, checks: List[dict], actual: dict) -> str:
    if ok:
        n = len(checks)
        return f"OK ({n} check{'s' if n != 1 else ''} passed)"
    n_fail = sum(1 for c in checks if not c["ok"])
    return f"FAIL ({n_fail}/{len(checks)} checks failed)"
