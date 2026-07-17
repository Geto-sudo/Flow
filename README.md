# Flow

> **Flow gives AI eyes, hands, and memory for video editing.**
> *"Flow donne aux IA des yeux pour observer les vidéos, des mains pour les modifier et une mémoire structurée pour travailler sur des projets complexes."*

The open-source runtime that lets any LLM agent observe, query, plan, execute, and verify edits on video projects.

## What

Flow transforms a video into a typed Project Graph (the "memory") that any LLM can read and reason about. The LLM proposes edits (the "plan"), Flow renders them via ffmpeg, and verifies the result.

```
video.mp4
   ↓ observe()           — 4-phase multimodal pipeline
ProjectGraph             — typed nodes: scenes, transcripts, audios, objects
   ↓ query()             — explore by window, type, label, text
LLM reasoning            — runs anywhere: Claude, GPT, Gemini, DeepSeek
   ↓ plan()              — emits typed action JSON
execute()                — ffmpeg filter_complex render
   ↓ verify()            — metadata + content checks; re-loop if KO
```

## Why

AI video editing is fragmented. Each model vendor (OpenAI, Anthropic, Google) ships its own video understanding API with its own output format, its own latency, its own failure modes. If you build a product on one, you're locked in.

Flow is the layer between any video and any LLM. **One graph format, one query API, one render pipeline, one verifier.** Tomorrow's LLM and today's LLM both work.

## Mission

> *"Aujourd'hui, les modèles d'IA savent raisonner, mais ils ne savent pas travailler efficacement sur des projets vidéo complexes. Flow est un runtime open source qui transforme une vidéo en un projet structuré que n'importe quelle IA peut observer, interroger, modifier et vérifier."*

## Install

```bash
pip install flow-core
```

With all multimodal features (CLIP, YOLO, OCR, faces, beats, emotion):

```bash
pip install "flow-core[all]"
```

## Use

```python
import flow_core as flow

# 1. Observe
graph = flow.observe("video.mp4")          # auto depth by video length
graph = flow.observe("video.mp4", depth="full")  # full multimodal

# 2. Query
for scene in flow.query(graph, "scenes")["nodes"]:
    print(scene.start, scene.end, scene.topic)

# 3. Plan (heuristic, no LLM needed)
plan = flow.plan(graph, "cut_silences")
plan = flow.plan(graph, "keep_only:person")
plan = flow.plan(graph, "first_n:30")
# Or pass your own LLM-generated plan
plan = {"intent": "custom", "actions": [...]}

# 4. Execute
result = flow.execute(graph, plan["actions"])
# Apply the render command from result["render"] via subprocess

# 5. Verify
verdict = flow.verify({"duration": 3.0, "has_audio": True}, "output.mp4")
if not verdict["ok"]:
    # re-iterate: fix the plan based on verdict["diff"]
    ...
```

Or via CLI:

```bash
# One video
py -m flow_core video.mp4

# A folder of videos (skips already-processed)
py -m flow_core ./videos/

# Pick depth
py -m flow_core video.mp4 -d full
```

For every video, Flow writes `<name>.flow.json` (full graph) and `<name>.flow.txt` (LLM-facing summary) next to the source.

## The 5 verbs

| Verb | Purpose | Speed (5s video) |
|---|---|---|
| `observe()` | video → ProjectGraph | 1-15s by depth |
| `query()` | explore the graph | <10ms |
| `plan()` | propose edit actions (heuristic) | <50ms |
| `execute()` | apply actions + render | 1-3s |
| `verify()` | check expected vs actual | <100ms (or 3-5s with re-transcribe) |

## What Flow does NOT do

- ❌ It's not an LLM
- ❌ It's not a video editor (no Premiere/Final Cut competitor)
- ❌ It's not a SaaS wrapper around someone else's API
- ❌ It doesn't do the reasoning — that's the LLM's job

## Architecture

```
flow/
├── python/                      # the package
│   ├── flow_core/
│   │   ├── __init__.py          # 5-verb public API
│   │   ├── __main__.py          # CLI
│   │   ├── project_graph.py     # Typed DAG, Observable
│   │   ├── video_parser.py      # 4-phase multimodal pipeline
│   │   ├── planner.py           # 11 intent patterns
│   │   ├── executor.py          # action → ffmpeg render
│   │   ├── verifier.py          # expected vs actual
│   │   └── _ffmpeg.py           # bundled binary discovery
│   ├── tests/
│   ├── pyproject.toml
│   ├── README.md
│   ├── LICENSE
│   └── CHANGELOG.md
├── docs/                         # narrative guides
├── prototypes/                   # VVM Context Engine + early experiments
├── research/                     # competitor analysis
├── rfcs/                         # spec layer
├── specs/                        # spec layer
├── test_fixtures/                # sample videos
├── README.md                     # this file
└── CHANGELOG.md
```

## Roadmap

- [x] v0.3: full 5-verb cycle, multimodal pipeline, smart CLI
- [ ] v0.4: VVM Context Engine integration (V1 validated, not yet wired)
- [ ] v0.5: MCP server (`flow-core-mcp`) so any MCP-aware agent uses Flow
- [ ] v0.6: HTTP API (FastAPI wrapper) for SaaS
- [ ] v0.7: diarization (pyannote) for "who speaks when"
- [ ] v0.8: vertical SaaS #1 — AI Podcast Editor
- [ ] v1.0: stable API contract
- [ ] Future: Rust port (ADR-0001) for production perf

## License

Apache 2.0 — see [python/LICENSE](python/LICENSE).
