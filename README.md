# CI Status

![Tests](https://github.com/Geto-sudo/Flow/actions/workflows/test.yml/badge.svg)

# Flow

> **Flow gives AI eyes, hands, and memory for video editing.**
> *"Flow donne aux IA des yeux pour observer les vidéos, des mains pour les modifier et une mémoire structurée pour travailler sur des projets complexes."*

The open-source runtime that lets any LLM agent observe, query, plan, execute, and verify edits on video projects.

```bash
pip install flow-core
```

```python
import flow_core as flow

graph = flow.observe("video.mp4")                       # eyes
plan   = flow.plan(graph, "cut_silences")               # hands
result = flow.execute(graph, plan["actions"])           # ffmpeg render
ok     = flow.verify({"duration": 3.0}, "output.mp4")   # memory check
```

## Why

AI video editing is fragmented. Each model vendor (OpenAI, Anthropic, Google) ships its own video API with its own format, its own latency, its own failure modes. Build on one, you're locked in.

Flow is the layer between any video and any LLM. **One graph format, one query API, one render pipeline, one verifier.** Today's LLM and tomorrow's LLM both work.

## The 5-verb cycle

| Verb | What | Speed (5s video) |
|---|---|---|
| `observe()` | video → ProjectGraph (4-phase multimodal) | 1-15s by depth |
| `query()` | explore by type/window/text | <10ms |
| `plan()` | propose edit actions (11 heuristic intents) | <50ms |
| `execute()` | apply actions + ffmpeg render | 1-3s |
| `verify()` | expected vs actual, re-loop friendly | <100ms |

Any LLM can drive this cycle. The graph is text.

## CLI

```bash
py -m flow_core video.mp4                # auto depth
py -m flow_core folder/                 # batch, skip already done
py -m flow_core video.mp4 -d full       # force depth
```

For every video, Flow writes `<name>.flow.json` (full graph) and `<name>.flow.txt` (LLM-facing summary) next to the source.

## Multimodal pipeline (inside `observe()`)

- **Phase 1 (fast, <1s)** — ffprobe metadata + ffmpeg scene detection
- **Phase 2 (speech, +3-5s)** — faster-whisper transcripts (+ optional pyannote diarization)
- **Phase 3 (vision, +5-10s)** — MobileCLIP-S2 tags + YOLOv8 objects + EasyOCR text + OpenCV YuNet faces
- **Phase 4 (audio, +5-10s)** — ffmpeg VAD + per-event RMS + librosa beats + wav2vec2-superb-er emotion

Smart auto-depth: short videos get `full`, medium get `vision`, long get `speech`.

## Install

```bash
# Core only (metadata + scene + transcripts, no torch/heavy models)
pip install flow-core

# With vision (CLIP, YOLO, OCR, faces)
pip install "flow-core[vision]"

# With audio features (beats, emotion)
pip install "flow-core[audio]"

# Speaker diarization
pip install "flow-core[diarization]"

# Everything
pip install "flow-core[all]"
```

Or from source:

```bash
git clone https://github.com/Geto-sudo/Flow.git
cd Flow/python
pip install -e ".[all]"
```

## Mission

> *"Aujourd'hui, les modèles d'IA savent raisonner, mais ils ne savent pas travailler efficacement sur des projets vidéo complexes. Flow est un runtime open source qui transforme une vidéo en un projet structuré que n'importe quelle IA peut observer, interroger, modifier et vérifier."*

## What Flow is NOT

- ❌ Not an LLM
- ❌ Not a video editor (no Premiere/Final Cut competitor)
- ❌ Not a SaaS wrapper around someone else's API
- ❌ Doesn't do the reasoning — that's the LLM's job

## Architecture

```
Flow/
├── python/                      # the package
│   ├── flow_core/
│   │   ├── __init__.py          # 5-verb public API
│   │   ├── __main__.py          # CLI
│   │   ├── project_graph.py     # typed DAG, Observable, window(), relationships()
│   │   ├── video_parser.py      # 4-phase multimodal pipeline
│   │   ├── planner.py           # 11 intent patterns
│   │   ├── executor.py          # action → ffmpeg render
│   │   ├── verifier.py          # expected vs actual, re-loop
│   │   └── _ffmpeg.py           # bundled binary discovery
│   ├── tests/
│   ├── pyproject.toml
│   ├── README.md
│   └── LICENSE
├── docs/                         # narrative guides
├── prototypes/                   # VVM Context Engine + early experiments
├── research/                     # competitor analysis
├── rfcs/                         # spec layer
├── specs/                        # spec layer
├── test_fixtures/                # sample videos
├── .github/workflows/            # CI
├── README.md
└── CHANGELOG.md
```

## License

Apache 2.0
