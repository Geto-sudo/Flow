# Flow — Final Recommendations

> Direct answers to the 6 questions in the Flow mission brief, plus a summary of what to build, what to keep, and what to avoid.

---

## Q1: Should Flow build on existing technology?

**Yes, aggressively.** The 6-project research surfaces a clear picture:

| Layer | Existing tech | Reuse strategy |
|---|---|---|
| **Codec / bytes** | FFmpeg (libav*) | Static link via `ffmpeg-sys-next` (Rust) or `ffmpeg-next`. Hide all raw libav types behind a Flow API. |
| **Timeline data** | OTIO | Wrap as `flow.timeline` (Rust bindings). Add `FlowOp.1` schema extensions via OTIO's plugin system. |
| **Plugin model** | MLT (concept) | Adopt MLT's `mlt_factory` model: dynamic libraries registered by manifest, loaded at runtime. |
| **Action system** | OpenReelio (concept) | Copy the `ActionExecutor + inverse + history` pattern, make it the only mutation API. |
| **LLM API shape** | MoviePy (concept) | `flow-script` Python package uses operator overloading and `.fx()`-style methods. |
| **Frame lifecycle** | FFmpeg + MLT | Lazy frame pull for preview; eager push for AI inference (different paths). |
| **Memory pool** | MLT (concept) | Rust `pool` crate + custom slab for large frame buffers. |
| **Color science** | libswscale | Reuse via FFI. |
| **AI inference** | ONNX Runtime | New. No good open alternative that supports WebGPU + native + mobile. |
| **MCP surface** | New | Build it. No video project ships one. |

**What to NOT build on**:
- MoviePy's render path (frame-sequence + subprocess FFmpeg). Reject entirely.
- MLT's consumer-pull threading model. We need push for AI.
- OpenReelio's browser-only stack. We need server + CLI + browser.

## Q2: Which project should become the execution engine?

**FFmpeg (libav*).** No serious alternative exists.

- `libavcodec` for decode/encode.
- `libavformat` for mux/demux/probe.
- `libavfilter` as the **conceptual model** for Flow's Effect Graph (but with typed wrappers, not raw filter strings).
- `libswscale` for color/scaling.
- `libavutil` for memory, logging, buffer refcounting.

The "engine" in Flow = FFmpeg + Flow's typed Effect Graph + AI backends.

**Why not MLT as the engine?**
- MLT's threading model is consumer-pull, real-time-paced. Wrong for AI (which is async, batch, GPU).
- MLT has no AI/ML hooks. Building them on top of MLT's RPN stacks would be a rewrite.
- MLT is C ABI. Modern Rust/C++ is more productive.
- LGPL compatibility is fine, but MLT is heavy for what we want.

**Why not OpenReelio?**
- Browser-only. No server counterpart.
- Not headless.
- Bundle size.

**Why not MoviePy?**
- Too slow.
- No timeline data model.

## Q3: Which timeline model should be adopted?

**OTIO (OpenTimelineIO).** Concretely:

- Flow's internal in-memory timeline is an OTIO `Timeline` object (with C++ or Python bindings).
- The on-disk format is `.otio` JSON.
- Flow's persisted project is a directory containing `timeline.otio` + `actions.jsonl` + media cache.
- Flow extends OTIO with:
  - `FlowOp.1` schema types for AI operations.
  - Flow-specific metadata namespaces (`flow.llm.intent`, `flow.confidence`, `flow.agent_id`).
  - A Flow media linker that resolves `ExternalReference` to Flow project storage.

**Why OTIO over MLT's tractor/field/multitrack?**
- OTIO is **data**, not a runtime. We can map it to whatever execution model we want.
- OTIO is **canonical and portable**. The same file works in any conform pipeline.
- OTIO is **already what the VFX industry uses**. Free interop with DaVinci, Premiere, etc.
- OTIO has **better plugin extension** (4 plugin types, all Python).

**What we take from MLT**:
- The tractor/multitrack/field pattern as a **mental model** when implementing the render graph (not as a data structure).
- The idea that multitrack needs a wrapper (tractor) to be a valid producer.
- The "plant transitions in the field" idea (we'll re-implement as a transition node in the Effect Graph).

## Q4: Which APIs should be wrapped?

### Wrap tightly (Flow exposes its own API, hides the underlying)
- **FFmpeg libav*** → `flow.Media`, `flow.Frame`, `flow.Encoder`.
- **OTIO** → `flow.Timeline`, `flow.Clip`, `flow.Track`, `flow.Transition`.
- **ONNX Runtime** → `flow.AiModel`.
- **libswscale** → `flow.Color`.

### Expose as-is (no wrapper, just version-pin)
- **JSON Schemas** (Action, Effect, Timeline) — agents read these directly.
- **MCP tools** — the Flow Action surface, no translation.

### Expose with a thin Python/TS shim
- **CLI commands** — `flow run`, `flow plan` (no need to wrap more, the CLI is the API).
- **HTTP endpoints** — REST + gRPC + WebSocket, schema-documented via OpenAPI.

### Never expose
- Raw `AVPacket`, `AVFrame`, `AVCodecContext`.
- Raw OTIO JSON internals (the schema version, the `OTIO_SCHEMA` markers — those are OTIO's problem).
- Filter graph text syntax (we validate it before it ever reaches libavfilter).
- `avpriv_*` or `ff_*` symbols.

## Q5: Which components should be rewritten?

| Component | Decision | Reason |
|---|---|---|
| Effect Graph | **Rewrite** (new typed DAG) | OTIO is data, libavfilter is text. We need a typed middle layer. |
| Action System | **Rewrite** (port OpenReelio's idea) | No existing project has this as a first-class API. |
| MCP server | **New** | No video project has one. |
| Plugin loader | **Rewrite** (inspired by MLT) | MLT's C ABI is fine but Rust `libloading` + JSON manifest is cleaner. |
| Memory pool | **Rewrite** (in Rust) | MLT's C pool is fine; Rust ecosystem has equivalents + we need GPU buffers. |
| Color engine | **Wrap** (libswscale) | Don't reinvent. |
| Audio engine | **Wrap** (libswresample) | Don't reinvent. |
| Project persistence | **New** (git-like) | No project has action-log-based persistence. |
| Render scheduler | **New** (push model) | MLT's pull model is wrong for AI. Build push. |
| Preview engine | **New** (lazy frame pull) | MLT's pattern, but simpler. |
| Timeline validator | **New** (JSON Schema) | OTIO has no validator. We need one for LLM-generated actions. |
| Media linker | **Port OTIO's pattern** | OTIO has it; Flow uses a custom resolver. |
| Plugin manifest | **New** (JSON + semver) | MLT's text-based is too loose. |

## Q6: Which components should be avoided entirely?

| Component | Why avoid |
|---|---|
| **MLT's consumer-pull threading** | Wrong model for AI. |
| **MoviePy's frame-sequence render** | Catastrophically slow. |
| **Subprocess FFmpeg** | No state, cold start, no progress recovery. |
| **Text-based filter graph syntax** | Untyped, easy to typo, hard to validate. |
| **Browser-only stack (OpenReelio model)** | No server, no CLI. |
| **Custom codec implementations** | FFmpeg's moat. 20 years of optimization. |
| **Custom demuxer/muxer** | FFmpeg covers 200+ formats. |
| **OS-native windowing** | Flow is headless. UI is someone else's problem. |
| **Real-time preview as primary mode** | For AI work, batch render is fine; real-time is for UI (not Flow's job). |
| **Sticky project lock files** | Git-like persistence + named checkpoints is enough. |
| **C ABI for the public API** | Use C-ABI for plugins (FFI), Rust + Python for the main surface. |
| **GPL-licensed codecs** | License contamination. Stick to LGPL 2.1+ FFmpeg build. |

---

## The Build List (prioritized)

### Phase 1: Foundation (Days 1-30)
- [ ] Rust workspace setup (`crates/flow-core`).
- [ ] FFmpeg FFI bindings (`ffmpeg-next`).
- [ ] OTIO C++ bindings (or Python via PyO3).
- [ ] Media probe + decode + encode (smoke test).
- [ ] JSON Schema for Flow Action.
- [ ] Action validator + executor.
- [ ] OTIO timeline wrapper with mutation API.
- [ ] Undo/redo via action inverse.
- [ ] 5 built-in effects: cut, trim, concat, scale, volume.
- [ ] `flow-cli` with `plan`, `run`, `probe`.
- [ ] 1 golden test: trim + concat.

### Phase 2: Effects + AI (Days 31-60)
- [ ] Effect Graph (typed DAG).
- [ ] 10 more effects: crossfade, color, crop, opacity, speed, text burn, audio fade, pan, rotate, normalize.
- [ ] AI integration: ONNX Runtime backend.
- [ ] 5 AI effects: transcribe, scene detect, upscale, denoise, beat detect.
- [ ] `flow-script` Python package.
- [ ] MCP server in `flow-server`.
- [ ] 5 more golden tests.

### Phase 3: Production (Days 61-90)
- [ ] Plugin loader + 1 example plugin.
- [ ] Hardware accel paths (CUDA, NVDEC, VAAPI on Linux; VideoToolbox on macOS; Vulkan Video cross-platform).
- [ ] Project persistence (action log + OTIO + checkpoints).
- [ ] HTTP API (REST + WebSocket progress streaming).
- [ ] Documentation site (flow.dev).
- [ ] 10 example actions in `examples/`.
- [ ] Beta release.

### Phase 4: Ecosystem (Post-MVP)
- [ ] `flow-web` browser SDK.
- [ ] More AI effects (segmentation, inpainting, style transfer, motion tracking).
- [ ] Flow Cloud (hosted server, paid).
- [ ] Editor frontend (browser-based, using `flow-web`).
- [ ] Premiere/Resolve OTIO adapters verified end-to-end.
- [ ] Community plugin registry.

---

## The Anti-Patterns to Avoid

These are the mistakes that sink video tools. Flow must not do any of these.

1. **Building your own codec** — Never. FFmpeg exists.
2. **Subprocess-per-operation** — Slow and stateless. In-process FFmpeg always.
3. **Frame-sequence-to-disk render** — MoviePy's mistake. Never.
4. **Stringly-typed effects** — Validate against JSON Schema before render.
5. **Eagerly building the entire timeline on import** — Lazy probe. Cache aggressively.
6. **Treating media as files instead of references** — Use OTIO's MediaReference. Files can move.
7. **No undo** — Action system from day 1. Not a v2 feature.
8. **No project format** — Persist from day 1. Even a simple `.otio` + `.jsonl` works.
9. **No validation of LLM output** — The whole point of a typed schema is the runtime can reject bad plans.
10. **No streaming progress** — Long renders without progress are dead renders.
11. **Locking the project file** — Multi-agent collaboration requires shared state without locks.
12. **Tightly coupling the engine to one UI** — Engine is headless. UIs are swappable.
13. **Skipping FFI stability guarantees** — Pin a FFmpeg major version. Test the boundary.
14. **Writing a custom plugin language** — JSON manifest + native shared library is enough.
15. **Trying to be an editor** — Flow is a runtime. Editors are built on top.

---

## The Bet

**Typed + AI + MCP + git-like persistence is the winning combination for 2026-2030 video tools.**

- **Typed**: validated action schemas, typed effect graph, schema-versioned everything.
- **AI**: AI as first-class effects, not bolted on.
- **MCP**: native agent surface, not "wrap our CLI in a tool."
- **Git-like**: action log + checkpoints + diff. Project history is auditable and replayable.

No existing project has all four. FFmpeg has typed (C APIs) but no AI/MCP/git. OTIO has typed (schemas) but no engine/AI/MCP. OpenReelio has AI but no MCP/git/server. MoviePy has none of these.

Flow wins by **being the only one that combines them**.

---

## One-Sentence Positioning

> **Flow is to video editing what Docker is to applications, Git is to source code, and Stripe is to payments: a typed, AI-native, MCP-speaking runtime that turns structured plans into media.**

This sentence goes on the homepage, in the README, in every pitch.
