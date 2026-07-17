# Project Comparison Matrix

> Compares the 6 reference projects on dimensions relevant to Flow's mission as an **AI Video Runtime**.

---

## At a Glance

| Project | Role | Mature? | Perf | Extensibility | Plugin System | AI Ready? | MCP? | License |
|---|---|---|---|---|---|---|---|---|
| **FFmpeg** | Bytes engine (codec, mux, filter) | ★★★★★ | ★★★★★ | ★★★ (build-time) | ★★★ (build flags) | ★★ | ✗ | LGPL 2.1+ / GPL 2+ |
| **MLT** | NLE engine (multitrack, transitions) | ★★★★ | ★★★★ | ★★★★★ (runtime) | ★★★★★ (loadable .so) | ★ | ✗ | LGPL 2.1+ |
| **OTIO** | Editorial interchange format | ★★★★ | n/a (data) | ★★★★★ (schemas+adapters) | ★★★★★ (4 plugin types) | ★★ (extensible) | ✗ | Apache 2.0 |
| **MoviePy** | Python scripting layer | ★★★ | ★ | ★★★★ (pure functions) | ★★★ (drop-in files) | ★★★ (LLM-friendly) | ✗ | MIT |
| **mcut** | Not found | — | — | — | — | — | — | — |
| **OpenReelio** | Modern browser editor | ★★★ (beta) | ★★★ (WebCodecs) | ★★★ (engine sep, no plugin yet) | ★★ (planned) | ★★★★ (built-in) | ✗ | MIT |

---

## Detailed Comparison

### 1. Performance

| Project | Throughput | Why |
|---|---|---|
| **FFmpeg** | Excellent. 8K H.265 decode at 60fps on CPU; NVDEC/VAAPI for free. | SIMD, threading, hardware accel, 20-yr optimization. |
| **MLT** | Good. Realtime 1080p on a modern CPU. Limited by FFMpeg's codecs + its own multitrack overhead. | Inherits FFmpeg perf + adds tractor overhead. |
| **OTIO** | n/a. It's a data model, not a renderer. | — |
| **MoviePy** | Poor. ~1-5 fps for non-trivial 1080p operations. | Python per-frame, frame-sequence disk IO, subprocess FFmpeg. |
| **OpenReelio** | Good in Chrome/Edge with WebGPU + WebCodecs. Falls back to canvas (slow). | Hardware codec via WebCodecs; GPU compose via WebGPU. |

**Winner for Flow's engine**: FFmpeg (reused via libav).

### 2. Extensibility

| Project | How it extends | Verdict |
|---|---|---|
| **FFmpeg** | Write a new `AVCodec`, register in `allcodecs.c`, build. Not runtime-loadable (mostly). | Painful. |
| **MLT** | Write a `mlt_service` plugin, drop in `$MLT_REPOSITORY`. Loaded at runtime. | Best in class. |
| **OTIO** | Add an Adapter, MediaLinker, SchemaDef, or HookScript. All Python. | Best in class. |
| **MoviePy** | Subclass `Clip` or write a free function. | Trivial. |
| **OpenReelio** | Engine modules are separate; plugin API planned. | Good direction, immature. |

**Winner for Flow**: combine MLT's plugin format with OTIO's plugin types. Make Flow extensible at every layer.

### 3. Timeline Model

| Project | Model | Has Tracks? | Has Transitions? | Has Effects on Clips? |
|---|---|---|---|---|
| **FFmpeg** | None (frame-level filter graph) | No | No (use `xfade` filter) | Via filters |
| **MLT** | Tractor + Multitrack + Field | Yes | Yes (plant in field) | Yes (attached filters) |
| **OTIO** | Timeline → Stack → Track → Item | Yes | Yes (`Transition` items) | Yes (`Effect` on clip) |
| **MoviePy** | Nested clips + operators | No (implicit) | No (manual fade) | Yes (`.fx()`) |
| **OpenReelio** | Tracks + Clips + Effects + Transitions (in engine) | Yes | Yes | Yes |

**Winner for Flow's timeline**: OTIO (canonical, well-documented, plugin-extensible, agent-readable JSON).

### 4. Rendering Engine

| Project | Engine | GPU? | Filter graph? |
|---|---|---|---|
| **FFmpeg** | `libavfilter` | Yes (via hwcontext) | Yes (DAG) |
| **MLT** | MLT services + FFmpeg | Partial (OpenGL fragment shaders) | No (each service is a link) |
| **OTIO** | n/a | n/a | n/a |
| **MoviePy** | Per-frame Python + subprocess FFmpeg | No | No |
| **OpenReelio** | WebGPU compositor + WebCodecs encoder | Yes | No (effects are JS functions) |

**Winner for Flow's render engine**: FFmpeg's `libavfilter` (model) + WebGPU for browser / NVDEC/VAAPI for native.

### 5. AI Readiness

| Project | AI Features | Extensible to AI? |
|---|---|---|
| **FFmpeg** | None built-in, but inference can be wrapped as a custom filter. | Yes (write `ff_libfi_inference` or similar). |
| **MLT** | None. | Awkward (multi-frame state in chains). |
| **OTIO** | None, but schema is extensible. | Yes (SchemaDef). |
| **MoviePy** | None, but LLMs write it well. | Yes (LLM-friendly surface). |
| **OpenReelio** | Speech-to-text, beat detection, AI upscale, AI-managed dev. | Yes (engine separation supports AI modules). |

**Winner for Flow's AI extensibility**: OpenReelio's engine-separation pattern (each engine can have an AI sibling).

### 6. MCP / Agent Protocol Compatibility

None of the 6 projects natively speak MCP. But:

- **FFmpeg**: exposeable via MCP server (FFmpeg CLI wrapped as MCP tools). Existing MCP servers exist.
- **MLT**: same — `melt` CLI wrapped as MCP tools.
- **OTIO**: ideal for MCP — its JSON is LLM-readable; OTIO file ops are perfect MCP resources.
- **MoviePy**: already used by LLM agents via Python execution.
- **OpenReelio**: not directly (browser-only).

**Winner for Flow's MCP integration**: OTIO as the resource type, with Flow's action system as the tools.

### 7. SDK Quality

| Project | API stability | Documentation | Bindings |
|---|---|---|---|
| **FFmpeg** | ★★★★★ (libav* ABI stable per major) | ★★★ (Doxygen + wiki, no narrative) | C only (others via bindings) |
| **MLT** | ★★★★ (stable C API) | ★★★ (Doxygen + design doc) | C, C++, Ruby, Python, Java, Perl (SWIG) |
| **OTIO** | ★★★★ (stable, "mature") | ★★★★★ (readthedocs is excellent) | C++, Python (PyBind11), Swift |
| **MoviePy** | ★★★ (v2 broke compat with v1) | ★★★★★ (the best docs in this list) | Python only |
| **OpenReelio** | ★★ (beta, moving fast) | ★★★ (README + monorepo) | TypeScript only |

**Winner for Flow's SDK surface**: OTIO's documentation quality + FFmpeg's stability.

### 8. Community & Adoption

| Project | GitHub stars | Used in production? |
|---|---|---|
| **FFmpeg** | n/a (git only) — but 100% of video tools use it | Everywhere |
| **MLT** | ~1k | Kdenlive, Shotcut, OpenShot, Olive |
| **OTIO** | 1.9k | Pixar, Disney, Netflix, ILM, Resolve, FCPX, Unreal |
| **MoviePy** | 13k | Scientific Python ecosystem |
| **OpenReelio** | 4.4k | New, growing fast |

**Winner for Flow's community confidence**: FFmpeg + OTIO are non-controversial choices. OpenReelio is the bet on "AI-era" tooling.

### 9. License Friendliness

| Project | License | Flow compatible? |
|---|---|---|
| **FFmpeg** | LGPL 2.1+ (default) or GPL 2+ (with `--enable-gpl`) | Yes if `--enable-gpl` is avoided. Some codecs (libx264, libx265) are GPL — separate. |
| **MLT** | LGPL 2.1+ | Yes. |
| **OTIO** | Apache 2.0 | Yes (most permissive, includes patent grant). |
| **MoviePy** | MIT | Yes. |
| **OpenReelio** | MIT | Yes. |

**Winner**: OTIO (Apache 2.0 — most permissive for a commercial product).

### 10. Future Viability

| Project | 5-year outlook |
|---|---|
| **FFmpeg** | Will be the codec engine for 10+ more years. Boring. |
| **MLT** | Stable, slow-moving. May lose to ML-based editors. |
| **OTIO** | ASWF backing, growing adoption. |
| **MoviePy** | Stable. Risk of stagnation. |
| **OpenReelio** | High risk, high reward. AI-native, could become the standard. |

**Winner for Flow's 5-year bet**: FFmpeg (engine) + OTIO (interchange) + Flow (the AI runtime). OpenReelio is the bet to watch.

---

## Architectural Influence Map

```
                    ┌──────────┐
                    │   Flow   │
                    └─────┬────┘
           ┌──────────────┼──────────────┐
           │              │              │
           ▼              ▼              ▼
       ┌──────┐       ┌──────┐       ┌──────┐
       │Engine│       │Inter-│       │ API  │
       │layer │       │change│       │layer │
       └──┬───┘       └──┬───┘       └──┬───┘
          │              │              │
          │ adopts       │ adopts       │ adopts
          ▼              ▼              ▼
   ┌──────────────┐ ┌──────────┐ ┌──────────────┐
   │  FFmpeg      │ │  OTIO    │ │  MoviePy     │
   │  (libav)     │ │  (canon) │ │  (LLM API)   │
   │              │ │          │ │              │
   │  + MLT       │ │          │ │  + OpenReelio│
   │  (plugin     │ │          │ │  (action     │
   │   model)     │ │          │ │   system)    │
   └──────────────┘ └──────────┘ └──────────────┘
```

| Flow component | Inspired by | Why |
|---|---|---|
| **Codec/decode/encode** | FFmpeg (libavcodec, libavformat) | Best-in-class, no reason to rewrite. |
| **Filter graph** | FFmpeg (libavfilter) | DAG with renegotiating links is the right pattern. |
| **Memory pool** | MLT (mlt_pool) | For large frame buffers, slab allocator wins. |
| **Service factory / plugin loader** | MLT (mlt_factory) | Runtime-loadable plugins via convention. |
| **Multitrack/transition model** | MLT (tractor/field) + OTIO | MLT's pattern, OTIO's data shape. |
| **Canonical format** | OTIO (.otio JSON) | Apache 2.0, battle-tested, plugin-extensible. |
| **Media linker** | OTIO | Resolves external media refs to local paths. |
| **Fluent scripting API** | MoviePy | Best LLM-facing shape. |
| **Action system** | OpenReelio (ActionExecutor) | First-class undo/redo with inverses. |
| **Bridge pattern** | OpenReelio | Clean engine ↔ UI separation. |
| **Reactive state store** | OpenReelio (Zustand) | Single source of truth for state. |
| **Auto-save / checkpoints** | OpenReelio (IndexedDB) | Background checkpointing. |

---

## The Synthesis

None of the 6 projects is "the answer." Each has a piece:

- **FFmpeg**: bytes (decode, encode, mux, demux, filter, color convert).
- **MLT**: plugin system, multitrack/transition model, frame lifecycle.
- **OTIO**: canonical timeline format.
- **MoviePy**: LLM-friendly scripting API.
- **OpenReelio**: action system, bridge pattern, modern architecture.
- **mcut**: n/a (not found).

Flow's job is to **assemble these into a unified runtime** with an AI-native action layer that none of them have. See `flow_architecture.md` for the concrete design.
