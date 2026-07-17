# Flow — Architecture

> The layered design of the AI Video Runtime, from agent intent to final render.

---

## 1. Full Stack

```
                         ┌──────────────────┐
                         │    AI Agent       │
                         │  (Claude / GPT)   │
                         └────────┬──────────┘
                                  │ MCP / HTTP
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                     Flow Runtime                             │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Context Engine (VVM)                      │  │
│  │                                                       │  │
│  │  Intent → Query Planner → Indexes → Pages (90 tokens) │  │
│  │                                                       │  │
│  │  8 Indexes: Transcript, Scene, Timeline, Object,      │  │
│  │  Face, Audio, Asset, Effect                           │  │
│  │  + Semantic Graph (entity-relationship)               │  │
│  └───────────────────────────────────────────────────────┘  │
│                            │                                 │
│                            ▼                                 │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Action Layer                              │  │
│  │  Action types (serde), validator (JSON Schema),       │  │
│  │  executor (mutates Timeline), history (undo/redo)     │  │
│  └───────────────────────────────────────────────────────┘  │
│                            │                                 │
│                            ▼                                 │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Timeline Layer                            │  │
│  │  OTIO bindings, mutation API, diff + merge,           │  │
│  │  snapshot / restore                                   │  │
│  └───────────────────────────────────────────────────────┘  │
│                            │                                 │
│                            ▼                                 │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Engine Layer                              │  │
│  │  Render Graph (DAG), Filter Graph → FFmpeg,           │  │
│  │  Color + Audio engines, GPU + AI backends             │  │
│  └───────────────────────────────────────────────────────┘  │
│                            │                                 │
│                            ▼                                 │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              Media Layer                               │  │
│  │  Probe, demux, decode (hwaccel), mux                  │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  Foundation: memory pool, buffer refcounting, logging,      │
│  plugin loader (C ABI)                                     │
└─────────────────────────────────────────────────────────────┘
```

## 2. The Three Surfaces

```
                     ┌─────────────────┐
                     │   flow-core     │   ← Rust library
                     │   (the engine)  │
                     └────────┬────────┘
                              │ FFI
              ┌───────────────┴───────────────┐
              │                               │
       ┌──────▼──────┐                 ┌──────▼──────┐
       │  flow-cli   │                 │ flow-server │
       │  (local)    │                 │  (daemon)   │
       └──────┬──────┘                 └──────┬──────┘
              │ in-process                     │ HTTP / gRPC / MCP
              │                                │
       ┌──────▼──────────────────┐     ┌──────▼────────────┐
       │ flow-script (Python)    │     │ Any HTTP client   │
       │ LLM-facing fluent API   │     │ MCP-aware LLMs    │
       └─────────────────────────┘     └───────────────────┘
```

## 3. Context Engine (VVM)

The layer that solves the fundamental bottleneck: LLM context window.

```
Agent Intent: { "search": "revenue growth", "budget": 1000 }
        │
        ▼
┌───────────────────────────────────────────┐
│            Query Planner                   │
│                                            │
│  Intent Parser → Resolver Pipeline         │
│  (TextSearch, TimeRange, SemanticPath,     │
│   EditPoint)                               │
│                                            │
│  → Adaptive Cost Optimizer                 │
│  → Page Builder                            │
│                                            │
│  Output: Pages (90 tokens)                 │
└───────────────────────────────────────────┘
        │
        │ Indexes queried
        ▼
┌───────────────────────────────────────────┐
│  8 Structured Indexes + Semantic Graph     │
│                                            │
│  TranscriptIndex (FTS)                     │
│  SceneIndex (B-tree)                       │
│  TimelineIndex (B-tree)                    │
│  ObjectIndex, FaceIndex, AudioIndex,       │
│  AssetIndex, EffectIndex                   │
│  SemanticGraph (entities + relations)      │
└───────────────────────────────────────────┘
```

Read more: `docs/context-engine.md`, `rfcs/0006-context-engine.md`, `adrs/0009-vvm-context-engine.md`

## 4. Action Layer

| Component | Role |
|---|---|
| **Action Schema** | JSON Schema — every action is validated before execution |
| **Action Types** | `trim`, `split`, `ripple_delete`, `move_clip`, `add_effect`, `composite`, `export` |
| **Action Executor** | Applies action to Timeline, produces inverse for undo |
| **Action Log** | Append-only, Git-like — auditable, replayable, branchable |

## 5. External Dependencies

| Dependency | Role | Integration |
|---|---|---|
| **FFmpeg (libav*)** | Codec, mux/demux, filter graph | `ffmpeg-sys-next` (Rust FFI) |
| **OTIO (C++)** | Canonical timeline schema | C++ bindings via `otio-sys` |
| **ONNX Runtime** | AI inference | `ort` crate |
| **libswscale** | Color science | FFI |
| **libswresample** | Audio resampling | FFI |

## 6. Key Design Decisions

| Decision | Rationale |
|---|---|
| **Context Engine (VVM)** | 99% token reduction — agents see 90t, not 26,000t |
| **Rust for core** | Memory safety, zero-cost abstractions, FFI ergonomics |
| **C ABI for plugins** | Language-agnostic plugin interface |
| **JSON Schema as contract** | LLMs produce JSON natively; validation is automatic |
| **OTIO as canonical timeline** | Industry-standard, battle-tested, plugin-extensible |
| **Push model for rendering** | AI inference is async/batch; pull model (MLT) is wrong |
| **Two-phase plan → execute** | Validate before touching media |
| **MCP-native** | Agents call Flow natively via Model Context Protocol |
