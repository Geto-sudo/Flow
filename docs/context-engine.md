# Context Engine — Virtual Video Memory (VVM)

> *"What is the minimum information an agent needs to make the right decision?"*

---

## 1. The Problem

A 1-hour video project with full AI analysis produces ~26,000+ tokens of context:

```
Transcript:  15,000 tokens   (every spoken word)
Timeline:     6,700 tokens   (every clip, track, transition)
Scenes:       1,000 tokens   (every scene description)
Audio:        6,700 tokens   (waveform, beats, emotion)
---------------------------------------------------------
Total:       ~29,000 tokens   — per query, every query
```

At this scale, LLM-based editing is economically impossible. Every query costs the full context. A 50-query editing session burns 1.5 million tokens.

## 2. The Insight

An agent editing a video does not need to see everything. It needs to see **exactly what is relevant to the current decision**.

This is the same problem solved by:
- **Virtual memory** (OS): not all of RAM fits in physical memory → pages
- **Database query planners**: not all rows are scanned → indexes
- **Cursor/Aider**: not all files are sent to the LLM → retrieval
- **MemGPT (Letta)**: not all conversation history fits in context → paging

Flow's Context Engine applies this pattern to video.

## 3. Architecture

```
                        ┌─────────────┐
                        │  AI Agent   │
                        │ (Claude/GPT)│
                        └──────┬──────┘
                               │ Intent + Budget
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    CONTEXT ENGINE                             │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              QUERY PLANNER                            │    │
│  │  Parses agent intent → selects indexes → enforces     │    │
│  │  token budget → chooses precision level               │    │
│  └──────────────────────────────────────────────────────┘    │
│                         │                                    │
│            ┌────────────┼────────────┐                       │
│            ▼            ▼            ▼                       │
│  ┌──────────────┐ ┌──────────┐ ┌──────────┐                 │
│  │ TranscriptIdx│ │ SceneIdx │ │TimelineIdx│  ... ×8        │
│  │ (FTS+B-tree) │ │(Vec+Tree)│ │ (B-tree)  │                 │
│  └──────────────┘ └──────────┘ └──────────┘                 │
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              PAGE BUILDER                             │    │
│  │  Raw index results → typed Pages                     │    │
│  │  Precision: tiny / summary / normal / full            │    │
│  └──────────────────────────────────────────────────────┘    │
│                         │                                    │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              CACHE MANAGER                            │    │
│  │  Recently accessed pages · invalidation · pre-fetch   │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                               │
                               ▼ Pages (minimal context)
                        ┌─────────────┐
                        │  AI Agent   │  ← ~180 tokens, not ~26,000
                        └─────────────┘
```

## 4. Eight Indexes

Each index is optimized for its data type and query pattern.

| # | Index | Data | Structure | Query |
|---|---|---|---|---|
| 1 | **TranscriptIndex** | Time-aligned speech | FTS (tokenized text) + B-tree (time) | `search("revenue growth")` |
| 2 | **SceneIndex** | Scene summaries | B-tree (time) + vector (embedding) | `lookup(time)` |
| 3 | **TimelineIndex** | Clips on tracks | B-tree (track, start_time) | `at(track, time)` |
| 4 | **ObjectIndex** | Detected objects | Composite (type, time_range) | `type=person AND time IN range` |
| 5 | **FaceIndex** | Face identities | B-tree (identity, time) | `identity=CEO_John IN range` |
| 6 | **AudioIndex** | Waveform, beats, mood | B-tree (time) + array | `beats IN range` |
| 7 | **AssetIndex** | Media files | Hash (asset_id) | `get(asset_id)` |
| 8 | **EffectIndex** | Applied effects | B-tree (clip_id) | `effects_of(clip_id)` |

## 5. Pages

The output of the Context Engine is **Pages** — typed, formatted units designed for LLM consumption.

### Page Types

| Type | What it contains | Default precision |
|---|---|---|
| **ScenePage** | Topic, location, people, activity, mood, transcript snippet | Normal |
| **ClipPage** | Track, time, source, neighbors, transitions | Normal |
| **TranscriptPage** | Aligned text segments with speakers | Normal |
| **AudioPage** | RMS, beats, emotion, noise level | Summary |
| **AssetPage** | Metadata, dependencies, usage | Summary |
| **EffectPage** | Effect type, parameters, scope | Summary |

### Precision Levels

| Level | Size (tokens) | Content | When used |
|---|---|---|---|
| **Tiny** | ~50 | ID + timestamp | Budget < 500t |
| **Summary** | ~200 | Key metadata | Budget < 2000t |
| **Normal** | ~800 | Full description | Budget >= 2000t |
| **Full** | ~3000 | Everything: full transcript, audio data | Explicit request |

### Project Map

Served once at the start of every session. < 200 tokens. Replaces the naive "dump all metadata":

```
PROJECT: interview_edit_v2
Duration: 60m0s | Resolution: 1920x1080 | FPS: 24
Tracks: 5 | Clips: 253
Assets: 12 | Scenes: 30
Effects: 99 | AI analyses: transcript, faces, scenes, objects, audio
```

## 6. Query Planner

### Cost Model

The Query Planner uses **token cost** as its optimization metric, not CPU time or I/O:

- `cost(plan) = sum(token_cost(page) for page in plan)`
- `selectivity(index, query) = estimated result matches`
- `precision_level = f(budget_remaining)`
- `overflow strategy = degrade precision (normal → summary → tiny)`

### Budget Allocation

```
If budget >= 5000t  → normal precision, fetch all matching pages
If budget >= 2000t  → normal for current selection, summary for context
If budget >= 500t    → summary for all, tiny for background
If budget < 500t     → tiny only + "ask for expansion if needed"
```

### Query Resolution

1. Parse agent intent: `{ search, time, clip_id, track, need }`
2. Select indexes based on `need` and available data
3. Execute index queries in parallel
4. Resolve results into pages at the appropriate precision
5. Assemble final context: Project Map + pages
6. Report token cost to agent

## 7. Cache Manager

Pages are cached to avoid re-querying indexes:

- **Page Cache**: recently accessed pages (LRU eviction)
- **Invalidation**: any `timeline.apply` flushes affected pages
- **Pre-fetch**: the planner predicts likely next pages based on query history

## 8. Benchmark (Prototype)

From the prototype at `prototypes/context_engine.py`:

| Metric | Naive | VVM | Reduction |
|---|---|---|---|
| Per query (average) | 26,290 tokens | 181 tokens | **99.3%** |
| Per 10-query session | 262,900 tokens | 1,810 tokens | 99.3% |
| Per 100-query session | 2,629,000 tokens | 18,100 tokens | 99.3% |

The agent always receives exactly what it needs to make its decision — a transcript snippet with keyword matches, the containing scene, and neighboring clips.

## 9. Future Work

- **Real transcript data**: validate with actual video transcripts (not synthetic)
- **Embedding-based scene search**: "find me a scene like this one"
- **Multi-turn context accumulation**: agent builds a working set across queries
- **Streaming pages**: return first page immediately, load rest on demand
- **Cross-modal queries**: "find the scene where the speaker looks nervous"
