# Flow — Proposed Architecture

> The AI Video Runtime. Not an editor. An execution layer that AI agents call to edit videos.

---

## 1. Mission Recap

```
User Prompt
        │
        ▼
   LLM Planner                  ← Claude, GPT, Gemini, etc.
        │
        │ produces
        ▼
   Flow Action (JSON)           ← Canonical, schema-validated
        │
        ▼
   Flow Runtime                 ← This document
        │
        ▼
   Final Video                  ← .mp4 / .webm / .mov
```

Flow is the **runtime layer**. It does not interpret user prompts. It does not have a UI. It does not make creative decisions. It executes a validated, structured plan and produces media.

**Analogy**:
- Docker accepts a `Dockerfile` and produces a running container.
- Git accepts commits and produces a repository.
- Stripe accepts API calls and produces a payment.
- **Flow accepts a Flow Action and produces a video.**

## 2. Repository Layout

```
flow/
├── crates/                        # Rust workspace (the core)
│   ├── flow-core/                 # The runtime engine
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── action/            # Action types, validator, executor
│   │   │   ├── timeline/          # OTIO bindings, mutations
│   │   │   ├── engine/            # Render graph, filter graph
│   │   │   │   ├── ffmpeg.rs      # FFmpeg FFI wrapper
│   │   │   │   ├── filter.rs      # Effect node types
│   │   │   │   ├── graph.rs       # DAG executor
│   │   │   │   ├── color.rs       # Color science
│   │   │   │   ├── audio.rs       # Audio engine
│   │   │   │   └── gpu.rs         # GPU acceleration (CUDA/Metal/Vulkan)
│   │   │   ├── media/             # Media probing, decoding
│   │   │   ├── export/            # Final output rendering
│   │   │   ├── pool/              # Frame slab allocator
│   │   │   ├── otio/              # OTIO schema bindings
│   │   │   └── plugin/            # Plugin loader
│   │   └── Cargo.toml
│   ├── flow-ffi/                  # C ABI for flow-cli and others
│   │   └── src/lib.rs
│   └── flow-server/               # The HTTP/gRPC daemon
│       └── src/
│           ├── main.rs
│           ├── api/               # REST + gRPC endpoints
│           ├── mcp/               # MCP server
│           ├── state/             # Project state, sessions
│           └── auth/              # API keys, OAuth
│
├── crates-ext/                    # Optional/native-only
│   ├── flow-gpu/                  # GPU backend (Vulkan/Metal/CUDA)
│   └── flow-ai/                   # AI inference backend (ONNX, libtorch)
│
├── flow-script/                   # Python package (LLM-facing)
│   ├── src/
│   │   ├── flow/
│   │   │   ├── __init__.py
│   │   │   ├── clip.py            # Clip, Video, Audio, Text
│   │   │   ├── timeline.py        # Timeline, Track
│   │   │   ├── effect.py          # Effect base + registry
│   │   │   ├── action.py          # Action serializer
│   │   │   ├── backend.py         # IPC to flow-core/flow-server
│   │   │   └── schemas.py         # Pydantic schemas
│   ├── tests/
│   └── pyproject.toml
│
├── flow-cli/                      # Local CLI
│   ├── src/
│   │   ├── main.rs                # CLI entry
│   │   ├── commands/              # `flow run`, `flow plan`, etc.
│   │   └── ipc/                   # Spawns/connects to flow-core
│   └── Cargo.toml
│
├── flow-web/                      # Browser SDK (optional, for browsers)
│   ├── src/
│   │   ├── index.ts
│   │   ├── client.ts              # WebSocket client
│   │   └── schemas.ts
│   └── package.json
│
├── schemas/                       # JSON Schemas (source of truth)
│   ├── action.schema.json
│   ├── timeline.schema.json       # Mirrors OTIO with Flow extensions
│   ├── effect.schema.json
│   └── media.schema.json
│
├── examples/                      # Example Flow Actions
│   ├── trim.json
│   ├── concat.json
│   ├── ai_upscale.json
│   └── ai_subtitles.json
│
├── tests/
│   ├── integration/
│   └── golden/                    # Golden output tests
│
├── Cargo.toml                     # Workspace manifest
├── README.md
├── LICENSE
└── ROADMAP.md
```

**Why this layout**:
- `crates/flow-core` is the **dependency-free core**. Can be statically linked into anything.
- `flow-server` is the **headless daemon**. Long-running, manages state.
- `flow-cli` is the **local front-end** to `flow-core` (in-process) or `flow-server` (over network).
- `flow-script` is the **LLM-facing Python API**. Calls into `flow-core` (in-process) or `flow-server` (HTTP).
- `flow-web` is the **browser SDK** for web-based agents.
- `schemas/` is the **canonical contract** between layers and between Flow and agents.

## 3. The Three Surfaces

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
              │ in-process                     │ HTTP / gRPC / WebSocket / MCP
              │                                │
       ┌──────▼──────────────────┐     ┌──────▼────────────┐
       │ flow-script (Python)    │     │ Any HTTP client   │
       │ LLM-facing fluent API   │     │ - Python          │
       │ - MoviePy-like          │     │ - TypeScript      │
       │ - Calls into flow-core  │     │ - curl            │
       │   or flow-server        │     │ - MCP-aware LLM   │
       └─────────────────────────┘     │   (Claude, etc.)  │
                                       └───────────────────┘
```

### 3.1 flow-core (Rust, no UI)

The engine. See §4.

### 3.2 flow-cli (Rust, local)

Thin wrapper around `flow-core`. Subcommands:
- `flow plan <action.json>` — validate a Flow Action, show what will happen.
- `flow run <action.json>` — execute, write to output path.
- `flow probe <media>` — print media metadata.
- `flow transcribe <media>` — extract audio + transcribe (calls external service).
- `flow project new / open / close` — manage local projects.
- `flow server start` — spawn `flow-server` in background.

### 3.3 flow-server (Rust, daemon)

Long-running process. State:
- Active projects (in-memory + persisted to OTIO files on disk).
- Active render jobs.
- WebSocket clients.
- MCP sessions.
- API keys, rate limits.

API surface:
- `POST /v1/actions` — submit a Flow Action, get back a job ID.
- `GET /v1/jobs/:id` — poll job status.
- `GET /v1/jobs/:id/artifacts` — list outputs.
- `WS /v1/jobs/:id/stream` — real-time progress + logs.
- `MCP /mcp` — Model Context Protocol endpoint.
- `GET /v1/projects` — list projects.
- `POST /v1/projects` — create project.
- `GET /v1/schemas/*` — serve JSON Schemas.

### 3.4 flow-script (Python, LLM-facing)

```python
from flow import Video, Audio, Text, Effect, Project

# Build a timeline
clip = (
    Video("interview.mp4")
    .trim(5, 15)
    .resize(1080, 1920)
    .set_audio(Audio("music.mp3").volume(0.3).duck_under(clip))
    + Text("Hello").at("center").duration(2)
    + Effect("ai.upscale", scale=2)
)

# Validate + plan
plan = clip.plan()
print(plan)  # human-readable description

# Execute
job = clip.render(output="out.mp4", preset="tiktok")
job.wait()
```

This compiles to a Flow Action (JSON), sends to `flow-core` (in-process) or `flow-server` (HTTP), gets back a job ID, and streams progress.

## 4. flow-core: Internal Architecture

```
┌────────────────────────────────────────────────────────────┐
│                      flow-core                              │
├────────────────────────────────────────────────────────────┤
│  Action Layer                                              │
│    ├─ Action types (serde)                                 │
│    ├─ Action validator (JSON Schema)                       │
│    ├─ Action executor (mutates Timeline)                   │
│    └─ History (undo/redo, inverses)                        │
├────────────────────────────────────────────────────────────┤
│  Timeline Layer                                            │
│    ├─ OTIO bindings (in-memory model)                      │
│    ├─ Mutation API                                         │
│    ├─ Diff + merge                                         │
│    └─ Snapshot / restore                                   │
├────────────────────────────────────────────────────────────┤
│  Engine Layer                                              │
│    ├─ Render Graph (DAG of Effect nodes)                   │
│    ├─ Filter Graph → FFmpeg (libavfilter)                  │
│    ├─ Color engine (libswscale)                            │
│    ├─ Audio engine (libswresample)                         │
│    ├─ GPU engine (CUDA/Metal/Vulkan)                       │
│    └─ AI engine (ONNX Runtime, pluggable backends)         │
├────────────────────────────────────────────────────────────┤
│  Media Layer                                               │
│    ├─ Probe (libavformat)                                  │
│    ├─ Demux (libavformat)                                  │
│    ├─ Decode (libavcodec, with hwaccel)                    │
│    └─ Mux (libavformat)                                    │
├────────────────────────────────────────────────────────────┤
│  Foundation                                                │
│    ├─ Memory pool (slab allocator for frames)              │
│    ├─ Buffer refcounting (zero-copy)                       │
│    ├─ Logging                                              │
│    └─ Plugin loader (cdylib + ABI-stable C)                │
└────────────────────────────────────────────────────────────┘
```

### 4.1 The Action Layer

```rust
#[derive(Serialize, Deserialize, JsonSchema)]
#[serde(tag = "type")]
pub enum Action {
    Timeline(TimelineAction),
    Clip(ClipAction),
    Effect(EffectAction),
    Render(RenderAction),
    Project(ProjectAction),
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "op")]
pub enum ClipAction {
    Add { source: MediaId, track: TrackId, at: RationalTime, in_range: TimeRange },
    Remove { clip: ClipId },
    Trim { clip: ClipId, edge: Edge, to: RationalTime },
    Move { clip: ClipId, to_track: TrackId, to_position: RationalTime },
    Split { clip: ClipId, at: RationalTime },
    Replace { clip: ClipId, with: MediaId },
    SetEffect { clip: ClipId, effect: EffectId, params: Value },
    RemoveEffect { clip: ClipId, effect: EffectId },
    SetSpeed { clip: ClipId, speed: f64 },
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "op")]
pub enum RenderAction {
    Render {
        timeline: TimelineId,
        output: OutputSpec,
        preset: RenderPreset,
        range: Option<TimeRange>,
    },
}
```

Every action has a deterministic inverse. The executor computes the inverse at apply-time (or accepts a pre-computed one for client-side planning). Undo = apply inverse.

### 4.2 The Timeline Layer

Wraps OTIO. Flow extends OTIO with:
- `FlowOp.1` schema types for AI operations.
- Flow-specific media reference resolvers.
- Flow-specific metadata namespaces (`flow.llm.intent`, `flow.confidence`, `flow.agent_id`).

```rust
pub struct Timeline {
    inner: otio::Timeline,
    history: Vec<Action>,
    inverse: Vec<Action>,
}

impl Timeline {
    pub fn apply(&mut self, action: Action) -> Result<()> {
        let inverse = self.compute_inverse(&action)?;
        self.apply_no_history(&action)?;
        self.history.push(action);
        self.inverse.push(inverse);
        Ok(())
    }

    pub fn undo(&mut self) -> Result<Option<Action>> {
        match self.inverse.pop() {
            Some(inv) => {
                let forward = self.compute_inverse(&inv)?;
                self.apply_no_history(&inv)?;
                self.history.push(inv.clone());
                self.history.pop();  // remove the forward
                self.inverse.push(forward);
                Ok(Some(inv))
            }
            None => Ok(None),
        }
    }
}
```

### 4.3 The Engine Layer

The render graph is a **typed DAG of Effect nodes**. Inspired by `libavfilter` but with:

- **Typed inputs/outputs** (not stringly-typed).
- **Schema-validated parameters** (every Effect has a JSON Schema for its params).
- **Async, multi-frame** semantics (effects can request multiple frames).
- **AI effects** as first-class nodes.

```rust
pub trait Effect: Send + Sync {
    fn id(&self) -> &str;
    fn inputs(&self) -> &[PortSpec];
    fn outputs(&self) -> &[PortSpec];
    fn param_schema(&self) -> &Schema;
    fn process(&self, ctx: &mut EffectContext, inputs: PortMap) -> Result<PortMap>;
    fn is_ai(&self) -> bool { false }
}

pub struct EffectGraph {
    nodes: HashMap<NodeId, Box<dyn Effect>>,
    edges: Vec<Edge>,
}
```

#### Built-in effects (v1)
- `core.cut` — trim
- `core.concat` — sequential join
- `core.crossfade` — transition
- `core.scale` — resolution
- `core.crop` — region
- `core.opacity` — transparency
- `core.volume` — gain
- `core.speed` — playback rate
- `core.color.lift_gamma_gain` — color correction
- `core.color.lut` — LUT apply
- `core.text.burn` — subtitle burn
- `core.transcribe` — speech-to-text (returns a `.srt` or a structured transcript)
- `ai.upscale` — AI super-resolution
- `ai.denoise` — AI noise reduction
- `ai.scene_detect` — returns scene boundaries
- `ai.beat_detect` — returns beat positions
- `ai.object_track` — motion tracking
- `ai.face_detect` — face bounding boxes
- `ai.segment` — semantic segmentation masks
- `ai.inpaint` — remove objects
- `ai.style_transfer` — visual style

#### Why typed effects matter
- The LLM can request an effect by name. The runtime validates parameters against the schema.
- Errors are caught **before** render starts.
- The graph can be introspected: `flow plan` shows the exact DAG that will execute.
- Effects can be added by third parties (plugins).

### 4.4 The Media Layer

Wraps FFmpeg's `libavformat` + `libavcodec`. Provides:

- `Media::probe(path) -> MediaInfo` — read container metadata.
- `Media::open(path) -> MediaReader` — open a file for frame-level access.
- `MediaReader::seek(t) -> Frame` — seek to time, get a frame.
- `MediaReader::frames() -> FrameStream` — async frame iterator.
- `Writer::new(spec) -> MediaWriter` — open an output.

```rust
pub struct Frame {
    pub pts: RationalTime,
    pub duration: RationalTime,
    pub width: u32,
    pub height: u32,
    pub format: PixelFormat,
    pub planes: Vec<Plane>,  // zero-copy via Arc<Buffer>
    pub audio: Option<AudioBuffer>,
}
```

The frame uses a refcounted buffer pool — no copies on pass-through.

### 4.5 The Foundation

- **Memory pool** for frame-sized allocations (slab by power of 2, like MLT).
- **Buffer refcounting** via `Arc<Buffer>` (Rust's built-in).
- **Plugin loader** via `libloading` (dlopen/cdylib). Each plugin exports a C ABI:
  ```c
  FlowPluginInfo flow_plugin_info();
  FlowStatus flow_plugin_register(FlowHost* host);
  ```

## 5. The Flow Action Schema (canonical LLM ↔ Runtime contract)

This is what the LLM produces. The runtime validates and executes it.

```json
{
  "$schema": "https://flow.dev/schemas/action.v1.json",
  "id": "act_01HXY...",
  "created_at": "2026-07-17T04:00:00Z",
  "project": "proj_01HXZ...",
  "actor": { "type": "agent", "id": "claude-sonnet-4.5" },
  "intent": "Trim intro and add bouncy text overlay",
  "actions": [
    {
      "op": "clip.trim",
      "clip": "clip_abc",
      "edge": "in",
      "to": { "value": 2.5, "rate": 30 }
    },
    {
      "op": "clip.set_effect",
      "clip": "clip_abc",
      "effect": "core.text.burn",
      "params": {
        "text": "HELLO",
        "start": { "value": 3, "rate": 30 },
        "duration": { "value": 2, "rate": 30 },
        "position": "center",
        "style": "bold-overlay"
      }
    },
    {
      "op": "render",
      "output": { "path": "out.mp4", "format": "mp4" },
      "preset": "tiktok-vertical-1080"
    }
  ]
}
```

The schema is the **contract**. It's defined in `schemas/` as JSON Schema. The LLM is trained to produce it. The runtime validates against it. The OTIO file is the **persisted state** (after action application).

## 6. The MCP Surface

`flow-server` exposes an MCP server. Tools:

- `flow.media.probe(path)` — get media info.
- `flow.media.list(path)` — list media in a directory.
- `flow.project.create(name)` — create a new project.
- `flow.project.list()` — list projects.
- `flow.timeline.get(project_id)` — get the current timeline as OTIO JSON.
- `flow.timeline.apply(project_id, action)` — apply an action, return the new timeline.
- `flow.timeline.plan(project_id, action)` — validate without applying.
- `flow.timeline.diff(project_id, before, after)` — diff two timeline states.
- `flow.render.start(project_id, action)` — start a render job, return job ID.
- `flow.render.status(job_id)` — poll job status.
- `flow.render.wait(job_id)` — wait for completion.
- `flow.render.artifacts(job_id)` — list output files.
- `flow.effects.list()` — list all available effects.
- `flow.effects.describe(effect_id)` — get an effect's schema and docs.

Resources:
- `flow://project/{id}/timeline` — current OTIO JSON.
- `flow://project/{id}/media` — media references.
- `flow://effects/{id}` — effect schema + docs.
- `flow://presets/{id}` — render preset spec.

This is **the** agent-facing API. LLMs that speak MCP (Claude, GPT, Gemini) can drive Flow without writing any other code.

## 7. The Plugin Model

Flow ships with built-in effects in `flow-core`. Third parties can add:

- **Custom effects** (Rust or C ABI shared library):
  ```
  my-effect/
  ├── Cargo.toml
  ├── src/lib.rs
  └── flow-plugin.toml    # name, version, effect declarations
  ```
  Build → `my-effect.flowplugin` → drop in `$FLOW_PLUGINS_DIR` → loaded at startup.

- **Custom media linkers** (resolve `ExternalReference` to local paths).

- **Custom schemas** (extend OTIO with `FlowOp.1` types).

- **Custom AI backends** (ONNX, libtorch, remote HTTP inference).

The plugin system borrows from MLT (loadable modules) and OTIO (4 plugin types).

## 8. Hardware Acceleration

- **Native (Linux/Windows)**: CUDA, VAAPI, QSV, NVDEC, Vulkan Video.
- **Native (macOS)**: VideoToolbox, Metal.
- **Browser (flow-web)**: WebCodecs, WebGPU.

The hardware path is **opt-in per operation**. The runtime picks the best available path. If hardware fails, falls back to software (FFmpeg's `libavcodec` software path).

## 9. The "AI Effects" Category

The killer feature. AI effects are **effects that call out to an inference backend**:

```rust
pub struct AiUpscale {
    model: ModelHandle,
    scale: u32,
}

impl Effect for AiUpscale {
    fn process(&self, ctx: &mut EffectContext, inputs: PortMap) -> Result<PortMap> {
        let frame = inputs.video_frame("in")?;
        let upscaled = self.model.run(frame)?;  // GPU inference
        Ok(PortMap::video("out", upscaled))
    }

    fn is_ai(&self) -> bool { true }
}
```

The AI backend is pluggable:
- **ONNX Runtime** (cross-platform, supports most models).
- **libtorch** (PyTorch models).
- **Remote HTTP** (call a model server — useful for huge models).
- **Browser**: WebGPU + ONNX Runtime Web.

**This is the differentiator**. MoviePy can't do AI upscale because it's per-frame Python. FFmpeg can't because it has no model runtime. MLT can't because it has no GPU/AI hooks. OpenReelio can for a few effects but not as a general mechanism.

Flow ships with:
- `ai.upscale` (Real-ESRGAN, 2x/4x).
- `ai.denoise` (multiple backends).
- `ai.transcribe` (Whisper / ElevenLabs).
- `ai.scene_detect` (content-aware scene boundary detection).
- `ai.beat_detect` (audio analysis).
- `ai.object_segment` (SAM-style masks).
- `ai.style_transfer` (visual style).

Third parties can add more.

## 10. State, Persistence, Projects

A project is:
- A directory on disk with:
  - `timeline.otio` — canonical timeline.
  - `actions.jsonl` — append-only action log (like a git log).
  - `media/` — local media cache.
  - `renders/` — output files.
  - `project.toml` — metadata (name, fps, resolution, etc.).

The action log is the **source of truth** for replay/debug. The OTIO file is the **current state** (regenerated from the log on demand, like `git` regenerating the working tree).

This is git-like:
- `flow project log` — show action history.
- `flow project diff` — diff two versions.
- `flow project checkout` — restore to a prior state.
- `flow project commit` — checkpoint (named state).
- `flow project branch` — try an alternate plan.

## 11. The "Two-Phase" Plan → Execute Model

```
LLM
  │ produces Flow Action (high-level intent)
  ▼
flow-server
  │ Phase 1: Plan (dry-run, no side effects)
  │   - validate JSON Schema
  │   - resolve media references
  │   - probe all input files
  │   - estimate cost (time, GPU, $)
  │   - return Flow Plan (human-readable summary)
  ▼
  │ User/agent confirms
  ▼
  │ Phase 2: Execute
  │   - build render graph
  │   - acquire resources
  │   - render (streaming progress)
  │   - upload outputs
  │   - emit completion event
  ▼
Done
```

This is the **"ask → confirm → execute"** pattern from `video-use` SKILL.md, but **typed and validated**.

## 12. Architecture Diagrams

### 12.1 Component Map

```
┌────────────────────────────────────────────────────────────┐
│                                                             │
│                       Flow Runtime                          │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Action     │  │  Timeline   │  │   Effect    │         │
│  │  Validator  │─▶│   Layer     │─▶│   Graph     │         │
│  │  (Schema)   │  │  (OTIO)     │  │  (DAG)      │         │
│  └─────────────┘  └─────────────┘  └──────┬──────┘         │
│                                            │                │
│                          ┌─────────────────┼────────────┐  │
│                          ▼                 ▼            ▼  │
│                   ┌──────────┐      ┌──────────┐  ┌──────┐ │
│                   │ FFmpeg   │      │  Color   │  │  AI  │ │
│                   │ Engine   │      │  Engine  │  │Engine│ │
│                   │ (libav)  │      │ (swscale)│  │(ONNX)│ │
│                   └────┬─────┘      └────┬─────┘  └──┬───┘ │
│                        │                 │           │     │
│                        └────────┬────────┴───────────┘     │
│                                 │                          │
│                        ┌────────▼─────────┐                │
│                        │   Media Layer    │                │
│                        │  (probe/mux/demux│                │
│                        │   /decode)       │                │
│                        └────────┬─────────┘                │
│                                 │                          │
│                        ┌────────▼─────────┐                │
│                        │   Foundation     │                │
│                        │  pool / log /    │                │
│                        │  plugin loader  │                │
│                        └──────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

### 12.2 LLM → Runtime Data Flow

```
┌──────────┐   Flow Action   ┌──────────────┐
│   LLM    │────(JSON)──────▶│ flow-server  │
└──────────┘                 │ (validates)  │
                             └──────┬───────┘
                                    │  (typed, validated)
                                    ▼
                             ┌──────────────┐
                             │  flow-core   │
                             │  (executes)  │
                             └──────┬───────┘
                                    │
                          ┌─────────┼─────────┐
                          ▼         ▼         ▼
                       ┌─────┐  ┌─────┐  ┌─────┐
                       │Trim │  │Scale│  │ Burn│
                       │     │  │     │  │Text │
                       └──┬──┘  └──┬──┘  └──┬──┘
                          └────┬────┴────┬───┘
                               ▼         ▼
                            ┌──────┐  ┌──────┐
                            │Mux to│  │Encode│
                            │MP4   │  │H.264 │
                            └──────┘  └──────┘
```

## 13. Performance Targets

| Operation | Target (p50) | Notes |
|---|---|---|
| `media.probe` | < 50ms | Already cached after first call |
| `timeline.apply` (single action) | < 10ms | In-memory mutation |
| `timeline.plan` (typical 5-action script) | < 500ms | Includes media probe |
| `render` of 1min 1080p30 (no AI) | < 30s | Realtime or better on modern CPU + GPU encode |
| `render` of 1min 1080p30 (with 1 AI effect) | < 90s | Depends on AI model + GPU |
| `render` of 10min 4K (no AI) | < 5min | Hardware encode required |
| MCP round-trip | < 100ms | For non-render operations |

## 14. MVP Scope (90 days, solo dev)

1. `flow-core` with OTIO + FFmpeg integration.
2. Basic Effect Graph: cut, concat, scale, trim, fade, color, audio gain.
3. 5 AI effects: transcribe, scene detect, upscale, denoise, beat detect.
4. `flow-cli` with `plan`, `run`, `probe`.
5. `flow-server` with HTTP + MCP.
6. `flow-script` Python package (basic).
7. JSON Schemas for Action, Timeline (Flow schema), Effect.
8. Golden tests: 10 reproducible outputs.
9. Documentation: `flow.dev` site.

## 15. Open Questions (to resolve during build)

1. **License**: Apache 2.0 (matches OTIO, most permissive for a runtime).
2. **Rust vs C++ for core**: Rust for safety + ergonomics; C++ only if forced.
3. **ONNX Runtime vs custom**: ONNX Runtime for v1; custom backend for v2.
4. **First-party AI model hosting**: do we ship model weights, or require user to provide? Start with "require" (Whisper, Real-ESRGAN as separate downloads).
5. **Cloud vs self-hosted**: both. `flow-server` runs anywhere; cloud is a hosted offering later.
6. **Pricing model**: open-source core, hosted server is paid (Stripe pattern).

## 16. The Verdict

Flow is a **concrete, buildable, differentiated** runtime. It:

- Reuses FFmpeg, OTIO, MLT's plugin model, MoviePy's API shape, OpenReelio's action system.
- Adds a typed Effect Graph (no other project has this).
- Adds AI as first-class effects (no other project has this).
- Adds MCP as the agent surface (no other project has this).
- Adds an action-log-based project persistence model (git-like).
- Has a clear 90-day MVP path.

This is not vapor. The components exist. The architecture is sound. The bet is on **typed + AI + MCP + git-like persistence** being the right combination for the 2026-2030 era of AI-driven video tools.
