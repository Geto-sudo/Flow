# Flow — Runtime

> The execution engine: actions, effects, rendering.

---

## 1. Action Layer

The action layer is the **only** way to mutate state. Every operation is an action, every action has a deterministic inverse.

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
```

### 1.1 Clip Actions

```rust
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
```

### 1.2 Undo/Redo

```rust
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
                self.history.pop();
                self.inverse.push(forward);
                Ok(Some(inv))
            }
            None => Ok(None),
        }
    }
}
```

## 2. Effect Graph

The render graph is a **typed DAG of Effect nodes**. Inspired by `libavfilter` but with typed inputs/outputs and schema-validated parameters.

```rust
pub trait Effect: Send + Sync {
    fn id(&self) -> &str;
    fn inputs(&self) -> &[PortSpec];
    fn outputs(&self) -> &[PortSpec];
    fn param_schema(&self) -> &Schema;
    fn process(&self, ctx: &mut EffectContext, inputs: PortMap) -> Result<PortMap>;
    fn is_ai(&self) -> bool { false }
}
```

### 2.1 Built-in Effects

**Core:**
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

**AI:**
- `ai.upscale` — AI super-resolution
- `ai.denoise` — AI noise reduction
- `ai.transcribe` — speech-to-text (returns SRT)
- `ai.scene_detect` — scene boundaries
- `ai.beat_detect` — beat positions
- `ai.object_track` — motion tracking
- `ai.face_detect` — face bounding boxes
- `ai.segment` — semantic segmentation masks
- `ai.inpaint` — remove objects
- `ai.style_transfer` — visual style

### 2.2 Two-Phase Plan → Execute

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

## 3. Media Layer

Wraps FFmpeg's `libavformat` + `libavcodec`.

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

- `Media::probe(path) -> MediaInfo` — read container metadata
- `Media::open(path) -> MediaReader` — open file for frame-level access
- `MediaReader::seek(t) -> Frame` — seek to time
- `MediaReader::frames() -> FrameStream` — async frame iterator

## 4. AI Effects

AI effects call out to an inference backend:

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

The inference backend is pluggable:
- **ONNX Runtime** (cross-platform, most models)
- **libtorch** (PyTorch models)
- **Remote HTTP** (call a model server)
- **Browser**: WebGPU + ONNX Runtime Web

## 5. Performance Targets

| Operation | Target (p50) |
|---|---|
| `media.probe` | < 50ms |
| `timeline.apply` (single action) | < 10ms |
| `timeline.plan` (typical 5-action script) | < 500ms |
| render 1min 1080p30 (no AI) | < 30s |
| render 1min 1080p30 (1 AI effect) | < 90s |
| render 10min 4K (no AI) | < 5min |
| MCP round-trip | < 100ms |
