# Flow Core

**Open runtime for AI video editing.** Observe, reason, edit, verify.

```bash
# Observe a video
py -m flow_core path/to/video.mp4

# Observe a folder of videos
py -m flow_core path/to/folder/

# Pick depth manually
py -m flow_core video.mp4 -d full    # full multimodal
py -m flow_core video.mp4 -d vision  # skip audio deep analysis
py -m flow_core video.mp4 -d speech  # transcripts + scenes only
py -m flow_core video.mp4 -d fast    # metadata + scene detection
```

## What is Flow?

Flow is a multimodal representation engine for video. The LLM never sees the pixels — it sees a typed graph.

```
video.mp4
   ↓ observe() (4 phases)
   ├── ffprobe metadata
   ├── ffmpeg scene detection
   ├── faster-whisper transcripts
   ├── MobileCLIP-S2 visual tags
   ├── YOLOv8 object detection
   ├── EasyOCR text extraction
   ├── OpenCV YuNet face detection
   ├── librosa beat detection
   └── wav2vec2 emotion classification
   ↓
ProjectGraph: typed nodes + edges
   ↓ observe_window(start, end)
   ↓
text for LLM
```

## Why?

- **Open core.** Vendor lock kills AI video tools. Flow is the runtime.
- **5-verb API.** `observe / query / plan / execute / verify`. That's it.
- **No GPU required.** ffmpeg + open-source models on CPU.
- **LLM-agnostic.** The graph is text; any model can read it.

## Install

```bash
# Core only (metadata + scene + transcripts)
pip install flow-core

# With vision (CLIP, YOLO, OCR, faces)
pip install "flow-core[vision]"

# With audio features (beats, emotion)
pip install "flow-core[audio]"

# Everything
pip install "flow-core[all]"
```

## Python API

```python
import flow_core as flow

# Observe
graph = flow.observe("video.mp4")
# or pick depth explicitly
graph = flow.observe("video.mp4", depth="full")

# Query
scenes = flow.query(graph, "scenes")
transcripts = flow.query(graph, "transcript")
objects = flow.query(graph, "objects")
stats = flow.query(graph, "stats")

# Temporal windows
window = graph.observe_window(0.0, 30.0)  # what an LLM sees
window = graph.observe_window(60.0, 90.0)  # another segment

# Plan edits
actions = flow.plan(graph, "tighten", intent="remove dead air")

# Execute
result = flow.execute(actions, output_path="output.mp4")

# Verify
ok = flow.verify(expected, result)
```

## CLI

```bash
# Observe one video
py -m flow_core video.mp4

# Observe a folder (batch)
py -m flow_core folder/

# Options
py -m flow_core video.mp4 -d full          # depth
py -m flow_core video.mp4 -o ./out/        # output dir
py -m flow_core video.mp4 --no-summary     # skip .flow.txt
py -m flow_core video.mp4 --no-json        # skip .flow.json
py -m flow_core video.mp4 -q               # quiet
```

For every video, Flow writes:
- `<name>.flow.json` — the full graph, serializable
- `<name>.flow.txt` — the LLM-facing summary

Already-processed videos are skipped automatically.

## Architecture

```
flow_core/
  project_graph.py    # Typed DAG, Observable interface
  video_parser.py     # 4 phases: fast / speech / vision / full
  __main__.py         # CLI entry point
  _ffmpeg.py          # bundled binary discovery (no PATH dep)
  planner.py          # plan() — LLM-driven action generation
```

### The 4 phases

| Phase | What | When | Cost (CPU) |
|---|---|---|---|
| `fast` | metadata + scene detection | always | <1s |
| `speech` | + faster-whisper transcripts | opt-in | 2-5s |
| `vision` | + CLIP tags + YOLO + OCR + faces | opt-in | 5-15s |
| `full` | + VAD + RMS + beats + emotion | opt-in | 10-30s |

Auto-pick: short videos get `full`, medium get `vision`, long get `speech`.

## License

Apache 2.0
