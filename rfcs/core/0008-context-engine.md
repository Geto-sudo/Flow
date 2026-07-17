# RFC-0008: Context Engine (Virtual Video Memory)

| Field | Value |
|---|---|
| **Status** | Draft |
| **Author** | Flow Team |
| **Created** | 2026-07-17 |
| **Depends on** | RFC-0001 (Runtime), RFC-0006 (MCP), RFC-0007 (SDK) |

---

# Summary

The Context Engine is the layer between AI agents and the Flow Runtime. It implements a **Virtual Video Memory (VVM)** model: the project data stays on disk, indexed across 8 specialized indexes; the agent receives only the **pages** relevant to its current query, typically **99% fewer tokens** than a naive context dump.

The engine is exposed to agents as a set of MCP tools (`flow.context.query`, `flow.context.expand`, `flow.context.project_map`). It is independent of the runtime's action system: the engine retrieves context, the runtime executes actions. They can evolve separately.

# Motivation

A 1-hour video project with full AI analysis produces **~26,000+ tokens** of context (transcript, timeline, scenes, audio, objects, faces, effects). Sending the full context to an LLM on every query is:

- **Economically prohibitive.** At $3/M tokens (Claude pricing), a 50-query editing session burns 1.3M tokens just in context. Output and tool calls add to that.
- **Quality-degrading.** The LLM has to find the relevant information in a 26K-token haystack. Decision quality drops as context grows.
- **Latency-expensive.** Larger contexts mean longer inference time per query.

The prototype at `prototypes/context_engine.py` validates the VVM hypothesis: **99.3% reduction** (26,290 → 181 tokens per query) without losing decision-relevant information. The engine's job is to make this reduction the default for every agent query, not an optimization.

# Goals

- Reduce agent context by **≥ 99%** compared to naive full-project dumps (validated by prototype).
- Serve any agent query in **< 50ms (in-memory)** / **< 200ms (cold load)**.
- Expose a **stable JSON Schema** for queries, pages, and the project map.
- Support the **8 core index types** (transcript, scene, timeline, object, face, audio, asset, effect).
- Survive project mutations through **deterministic cache invalidation**.
- Integrate with **MCP** as `flow.context.*` tools (RFC-0006).
- Be **testable in isolation**: index logic, query planning, and page building have no render dependency.
- Emit **events** for query patterns (RFC's `EventCatalog`): hot pages can be pre-fetched, slow queries can be optimized.

# Non Goals

- **Render execution.** That is `flow-core` (RFC-0001). The Context Engine only retrieves.
- **Timeline data model.** That is OTIO (RFC-0004). The engine reads timelines; it does not redefine them.
- **Plugin execution.** That is the plugin system (RFC-0005). The engine consumes plugin-produced analysis (e.g., transcripts) but does not orchestrate plugin calls.
- **Cross-modal video understanding.** "Find the scene where the speaker looks nervous" is a v2 feature.
- **Content generation via AI.** The engine retrieves; it does not infer. AI effects that generate new content live in the engine's effect graph (RFC-0001), not here.
- **Replacing the runtime's own indexes** for action validation. Action validation has different consistency and latency requirements.

# Guide-level explanation

An agent interacts with the Context Engine through a typed query:

```python
# Agent: "Find the revenue mention and understand its context"
result = context.query(
    intent={
        "search": "revenue growth",
        "need": ["transcript", "scene", "timeline"]
    },
    budget=3000  # tokens
)

# Returns:
# {
#   "pages": [TranscriptPage, ScenePage],
#   "total_tokens": 191,
#   "project_map": "PROJECT: interview_edit_v2 ...",  # served once per session
#   "budget_used": 0.064
# }
```

The agent's LLM call now includes the returned pages (191 tokens) instead of the full project (26,290 tokens). The agent can reason, decide, and call the runtime to execute an action.

For exploratory queries ("what's in this project?"), the agent calls `flow.context.project_map` first (200 tokens), then drills down with `flow.context.query`.

For deep dives ("show me the full transcript of the revenue scene"), the agent requests `precision: "full"` on a specific page (3,000 tokens), knowing it is paying the cost.

# Reference-level explanation

## Indexes (8)

| # | Index | Data | Structure | Common query |
|---|---|---|---|---|
| 1 | **TranscriptIndex** | Time-aligned speech segments | FTS (tokenized text) + B-tree (time) | `search("revenue growth")`, `range(t1, t2)` |
| 2 | **SceneIndex** | Scene summaries | B-tree (time) + vector (embedding, optional) | `lookup(time)`, `topic(query)` |
| 3 | **TimelineIndex** | Clips on tracks | B-tree (track, start_time) | `at(track, time)`, `neighbors(clip_id)` |
| 4 | **ObjectIndex** | Detected objects | Composite (type, time_range) | `type=person AND time IN range` |
| 5 | **FaceIndex** | Face identities | B-tree (identity, time) | `identity=CEO_John IN range` |
| 6 | **AudioIndex** | Waveform, beats, mood | B-tree (time) | `beats IN range`, `mood=excited IN range` |
| 7 | **AssetIndex** | Media files | Hash (asset_id) | `get(asset_id)`, `dependents(clip_id)` |
| 8 | **EffectIndex** | Applied effects | B-tree (clip_id, effect_type) | `effects_of(clip_id)` |

Each index is built on project load (and incrementally on `timeline.apply` actions). The indexes are stored alongside the project in `<project>/indexes/` (content-addressable, like the cache).

## Page types (6)

A **page** is a typed, formatted unit of context designed for LLM consumption.

| Type | Contains | Default precision |
|---|---|---|
| **ScenePage** | Topic, location, people, activity, mood, transcript snippet | Normal |
| **ClipPage** | Track, time, source, neighbors, transitions | Normal |
| **TranscriptPage** | Time-aligned text segments with speakers and confidence | Normal |
| **AudioPage** | RMS, beats, emotion, noise level | Summary |
| **AssetPage** | Metadata, dependents, usage count | Summary |
| **EffectPage** | Effect type, parameters, scope | Summary |

## Precision levels (4)

| Level | Size (tokens) | Content | When used |
|---|---|---|---|
| **Tiny** | ~50 | ID + timestamp only | Budget < 500t |
| **Summary** | ~200 | Key metadata (no full transcript) | Budget < 2000t |
| **Normal** | ~800 | Full description + relevant transcript | Budget >= 2000t |
| **Full** | ~3000 | Everything: full transcript, full audio | Explicit `precision: "full"` |

The precision level is chosen by the Query Planner based on the agent's stated budget. If a query overflows, the planner degrades precision (Normal → Summary → Tiny) rather than dropping pages.

## Project Map

A compact overview served **once at the start of every session**. < 200 tokens. Replaces the naive "dump all metadata":

```
PROJECT: interview_edit_v2
Duration: 60m0s | Resolution: 1920x1080 | FPS: 24
Tracks: 5 | Clips: 253
Assets: 12 | Scenes: 30
Effects: 99 | AI analyses: transcript, faces, scenes, objects, audio
```

The Project Map is the only context the agent strictly needs to know what the project is. All other queries drill down into specific pages.

## Query Planner

The planner is a **cost-based optimizer** where the cost is tokens, not CPU.

### Cost model

- `cost(plan) = sum(token_cost(page) for page in plan)`
- `selectivity(index, query) = estimated result matches`
- `precision_level = f(budget_remaining)`
- `overflow strategy = degrade precision (Normal → Summary → Tiny)`

### Budget allocation

```
If budget >= 5000t  → Normal precision for all matching pages
If budget >= 2000t  → Normal for current selection, Summary for context
If budget >= 500t   → Summary for all, Tiny for background
If budget < 500t    → Tiny only + "ask for expansion if needed"
```

### Query resolution

1. Parse agent intent: `{ search, time, clip_id, track, need }`.
2. Select indexes based on `need` and which indexes are available.
3. Execute index queries in parallel.
4. Resolve results into pages at the appropriate precision.
5. Assemble final context: Project Map + pages.
6. Report token cost to the agent.

## Cache Manager

Pages are cached to avoid re-querying indexes:

- **Page cache**: LRU eviction, default 10,000 pages or 100 MB.
- **Invalidation**: any `timeline.apply` action flushes affected pages. Granularity is per-track for timeline pages, per-scene for scene pages, per-segment for transcript pages.
- **Pre-fetch**: the planner observes the agent's query history and pre-fetches likely next pages (e.g., after a search match, the planner pre-fetches the surrounding transcript and the containing scene).

# Architecture

```
                        ┌─────────────┐
                        │  AI Agent   │
                        │ (Claude/GPT)│
                        └──────┬──────┘
                               │ Intent + Budget
                               ▼ MCP tool call
┌──────────────────────────────────────────────────────────────────┐
│                       CONTEXT ENGINE                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌────────────────────────────────────────────────────────┐     │
│   │                   QUERY PLANNER                         │     │
│   │   - parses intent                                      │     │
│   │   - selects indexes                                    │     │
│   │   - enforces budget                                    │     │
│   │   - chooses precision                                  │     │
│   │   - cost model (tokens as cost)                        │     │
│   └─────────────┬──────────────────────────────────────────┘     │
│                 │                                                 │
│      ┌──────────┼──────────┬──────────┬──────────┐                │
│      ▼          ▼          ▼          ▼          ▼                │
│  ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐                │
│  │Transc.│ │Scene  │ │Time-  │ │Object │ │Face   │  ... 3 more    │
│  │Index  │ │Index  │ │line   │ │Index  │ │Index  │                │
│  │(FTS+  │ │(B-   │ │Index  │ │(Comp.)│ │(B-   │                │
│  │ Btree)│ │ tree) │ │(B-   │ │       │ │ tree) │                │
│  │       │ │(+vec)│ │ tree) │ │       │ │       │                │
│  └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘                │
│      │         │         │         │         │                     │
│      └─────────┴─────────┴─────────┴─────────┘                     │
│                          │                                        │
│                          ▼                                        │
│   ┌────────────────────────────────────────────────────────┐     │
│   │                   PAGE BUILDER                          │     │
│   │   - raw index results → typed Pages                     │     │
│   │   - applies precision level                            │     │
│   │   - formats for LLM consumption                        │     │
│   └─────────────┬──────────────────────────────────────────┘     │
│                 │                                                 │
│                 ▼                                                 │
│   ┌────────────────────────────────────────────────────────┐     │
│   │                  CACHE MANAGER                          │     │
│   │   - LRU page cache (10K pages / 100 MB)                 │     │
│   │   - invalidation on timeline mutations                 │     │
│   │   - pre-fetch based on query history                    │     │
│   └─────────────┬──────────────────────────────────────────┘     │
│                 │                                                 │
└─────────────────┼─────────────────────────────────────────────────┘
                  │
                  ▼ Typed Pages (~180 tokens avg)
           ┌─────────────┐
           │  AI Agent   │  ← decisions, actions
           └─────────────┘
```

# Alternatives

### A. Dump everything

Send the full project context on every query. **Rejected.** 26K tokens per query is economically and technically infeasible.

### B. Sliding window by time

Return a window of the timeline (e.g., "the last 5 minutes") plus the current focus. **Rejected.** Misses cross-references ("the scene like the one at 12:00").

### C. LLM manages its own context

Give the LLM the full project and let it decide what to focus on. **Rejected.** The LLM cannot efficiently search 26K tokens; it loses precision as context grows.

### D. Compression / summarization

Pre-summarize the project, return the summary. **Rejected.** Loses precision when the agent actually needs details. The Context Engine already supports precision levels for this reason.

### E. MemGPT / Letta-style paging

Use a paging mechanism in the LLM agent framework itself. **Considered for v2.** Could be combined with our engine: the engine returns the right pages, the agent framework manages the conversation history.

# Drawbacks

- **Index building cost.** Indexes must be built on project load and updated on every `timeline.apply`. For a 1-hour project, this is ~1-2 seconds. For very large projects (10+ hours, many tracks), the index build can be slower.
- **Index quality depends on upstream AI.** A bad transcript, missed scene boundary, or wrong face identification propagates. The engine cannot fix the input; it can only surface it efficiently.
- **Cache invalidation is non-trivial.** When the timeline is mutated mid-session, affected pages must be flushed. Per-clip granularity avoids over-invalidation but is more complex than "invalidate all."
- **Adds a new layer to the architecture.** The runtime has Action → Timeline → Engine. The Context Engine sits as a peer to the Engine, not inside it. This is a clean separation but adds operational complexity.
- **The prototype uses synthetic data.** Real-world video data (multiple speakers, overlapping dialogue, music) may produce different reduction ratios. The 99.3% number is a lower bound, not a guarantee.
- **Vector indexes are optional but useful.** Without them, semantic queries ("scenes about leadership") are limited to keyword matching. Adding vector indexes adds storage and build cost.

# Future Possibilities

- **Real-data validation.** Benchmark against a corpus of 100+ real video projects to confirm the 99.3% reduction holds across content types (interviews, tutorials, montages, etc.).
- **Embedding-based scene search.** "Find a scene like this one" — use a vector index on scene embeddings.
- **Multi-turn context accumulation.** The agent builds a working set of pages across queries; the engine tracks which pages are "in context" and serves related pages preferentially.
- **Streaming pages.** Return the first page immediately, load the rest on demand. Useful for slow disk-backed indexes.
- **Cross-modal queries.** "Find the scene where the speaker looks nervous" — combines face index, emotion index, and audio index.
- **Personalized page formats.** Different LLM providers may prefer different page layouts. The engine could adapt based on the requesting model.
- **Federated indexes.** Multiple agents querying the same project share indexes (and pages) through a server. Reduces duplicate computation.

# Unresolved Questions

1. **Cache invalidation granularity.** Per-clip is precise but complex. Per-track is coarser but simpler. What is the right balance?
2. **Vector index integration.** When should the engine use vector search vs keyword search? Hybrid scoring is common but has cost implications.
3. **Audio representation.** Should audio waveforms be served as ASCII charts, numerical arrays, or pre-rendered thumbnails? Different agents may prefer different formats.
4. **Cross-project queries.** Can the engine serve queries across multiple projects (e.g., "find a clip like this in any of my projects")? This requires a global index.
5. **Real-time updates.** When the timeline is mutated mid-session, should the engine immediately re-query, or wait for the next agent query? Immediate updates add latency to mutations; deferred updates risk stale context.
6. **Privacy.** Some pages may contain sensitive data (e.g., faces of minors). Should the engine support page-level redaction policies? Out of scope for v1; v2 concern.
7. **The "Ask for expansion" pattern.** When the budget forces Tiny precision, the engine returns a hint to "ask for expansion." How does this interact with the agent's tool-use loop? Should it be a structured tool call (`flow.context.expand`) or a free-text hint?
8. **Index storage format.** The indexes are stored in `<project>/indexes/`. Should they be content-addressable (like the cache) or directly tied to the project version? If the timeline is mutated, are indexes rewritten or patched?

---

**Related**:
- [ADR-0009](../adrs/0009-vvm-context-engine.md) — Virtual Video Memory (Context Engine) decision
- [docs/context-engine.md](../docs/context-engine.md) — narrative documentation
- [prototypes/context_engine.py](../../prototypes/context_engine.py) — validation prototype
- [RFC-0001](./0001-runtime.md) — Runtime architecture
- [RFC-0006](./0006-mcp.md) — MCP surface
- [RFC-0007](./0007-sdk.md) — SDK
