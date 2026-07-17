# RFC-0008: Rendering Pipeline

| Field | Value |
|---|---|
| Status | Draft |
| Author | Mavis |
| Created | 2026-07-17 |
| Depends on | RFC-0001, RFC-0002, RFC-0003, RFC-0004 |

*This is an extension RFC. Core RFCs must be self-contained; this RFC may reference but must not be required by any core RFC.*

---

# Summary

This RFC defines how the Flow runtime **renders a project to a media file**: the planning phase, the Effect Graph that drives the actual decode/composite/encode pipeline, the GPU/CPU dispatch, and the output mux. Rendering is the runtime's hot path; everything in this RFC is performance-critical.

The rendering pipeline transforms a `RenderPlan` (a compiled DAG of effects) into a stream of encoded packets, demuxed into a container file, with progress reported as a stream and full cancellation support.

# Motivation

The runtime's value to an agent is the speed and quality of the final video. The agent decides *what* to do (RFC-0003); the rendering pipeline decides *how* to do it efficiently. Three properties drive the design:

1. **Hardware utilization.** A modern machine has CPU, GPU, NPU, and multiple hardware encoders. The pipeline must use whichever is available and fall back gracefully.
2. **Zero-copy where possible.** Each frame may be hundreds of kilobytes to megabytes. A render of 30 minutes at 1080p may touch 100+ GB of pixel data. Copying at every stage is not an option.
3. **Predictable progress.** An agent waiting on a render must know how long it will take. The pipeline reports progress in standard units (frames, percent, ETA) and reports stage transitions.

The pipeline must also be **deterministic** (given the same plan, the same input media, the same plugin set, the same output should be byte-identical) so that agents can reason about their work and so that golden tests are possible.

# Goals

- Compile a `RenderPlan` from a project state.
- Execute the plan with full GPU and hardware encoder support.
- Stream progress (frames, percent, ETA, current stage) via a channel.
- Support cancellation at frame boundaries.
- Maximize zero-copy: frames stay in GPU memory when possible.
- Support concurrent render jobs (one per GPU device, configurable).
- Be deterministic for a given input and plugin set.

# Non Goals

- This RFC does **not** define the action schema (RFC-0003).
- It does **not** define the in-memory project model (RFC-0004).
- It does **not** define the on-disk project format (RFC-0010).
- It does **not** define the plugin ABI (RFC-0005).
- It does **not** define real-time preview at interactive frame rates. Preview is a separate concern (out of scope for v1).

# Guide-level explanation

A render is submitted like any other action:

```rust
let job = project.apply(Action::Render {
    output: OutputSpec::mp4("out.mp4"),
    preset: "tiktok-vertical-1080".into(),
    range: Some(TimeRange::from_seconds(0.0, 60.0)),
})?;

// The action returns a JobHandle (see RFC-0002). The agent polls or waits.
for progress in job.progress() {
    println!("{}: {:.0}% (frame {})", progress.stage, progress.percent, progress.current_frame.unwrap_or(0));
}

let result = job.wait()?;
println!("output: {}", result.output_path);
println!("size: {} bytes", result.file_size);
println!("duration: {:?}", result.duration);
```

The runtime handles the rest: planning, GPU dispatch, hardware encoding, output mux.

# Reference-level explanation

## The RenderPlan

The first phase of rendering is planning. The runtime walks the timeline (RFC-0004) and produces a `RenderPlan`:

```rust
pub struct RenderPlan {
    pub input_graph: EffectGraph,     // the source-side DAG
    pub output_graph: EffectGraph,    // the sink-side DAG
    pub frames: FrameRange,            // which frames to render
    pub color_pipeline: ColorPipeline, // color space, range, transfer
    pub audio_pipeline: AudioPipeline, // mix, gain, sample rate
    pub output_spec: OutputSpec,       // codec, container, bitrate
    pub resource_estimate: ResourceEstimate, // GPU memory, CPU threads, disk
}

pub struct EffectGraph {
    pub nodes: Vec<EffectNode>,
    pub edges: Vec<Edge>,
    // Topological order is precomputed.
}

pub struct EffectNode {
    pub id: NodeId,
    pub effect: Box<dyn Effect>,
    pub stage: RenderStage,            // decode | process | encode
    pub device: ComputeDevice,         // cpu | cuda | vulkan | metal
}
```

The plan is **immutable** once produced. It is the unit of work for a render job.

## The render pipeline

```
Timeline
   │
   ▼
[1] Plan Builder   (single-threaded, fast)
   │   walks the timeline
   │   produces RenderPlan
   │
   ▼
RenderPlan
   │
   ▼
[2] Resource Allocator   (single-threaded, fast)
   │   allocates GPU buffers, codec contexts, thread pools
   │   may fail → clear error
   │
   ▼
[3] Render Executor   (multi-threaded, long-running)
   │   ┌──────────────┐
   │   │  Demuxer     │ (per input file)
   │   │  workers     │
   │   └──────┬───────┘
   │          │ decoded frames
   │          ▼
   │   ┌──────────────┐
   │   │  Effect      │ (the compiled DAG)
   │   │  scheduler   │ runs nodes in topo order
   │   └──────┬───────┘
   │          │ composited frames
   │          ▼
   │   ┌──────────────┐
   │   │  Audio mix   │
   │   └──────┬───────┘
   │          │ frames + audio
   │          ▼
   │   ┌──────────────┐
   │   │  Encoder     │ (HW if available, SW fallback)
   │   └──────┬───────┘
   │          │ encoded packets
   │          ▼
   │   ┌──────────────┐
   │   │  Muxer       │ (writes the container)
   │   └──────────────┘
   ▼
Output file
   │
   ▼
[4] Cleanup   (release GPU buffers, codec contexts)
```

The Demuxer and Effect stages are parallel. The Encoder and Muxer are serial per output (one encoded stream per output).

## Effect scheduling

The Effect Graph is a DAG. The scheduler:

1. Performs a topological sort at plan time.
2. Schedules nodes in order, respecting dependencies.
3. For nodes that can run in parallel (no shared parent), dispatches them to the worker pool.
4. Maintains a per-node "in-flight" frame queue with a configurable depth (default: 4).
5. Checks the cancellation flag at every node boundary.

A node "processes" by pulling input frames, calling the effect's `process()` method, and pushing output frames downstream.

## GPU dispatch

GPU effects run on the same device as the GPU decoder and encoder. This minimizes memcpy:

```
            ┌─────────────────────┐
            │  GPU Memory         │
            │  ┌──────────────┐   │
            │  │ Decoded frame│   │  ← NVDEC
            │  └──────┬───────┘   │
            │         │           │
            │         ▼           │
            │  ┌──────────────┐   │
            │  │ Effect: scale│   │  ← CUDA
            │  └──────┬───────┘   │
            │         │           │
            │         ▼           │
            │  ┌──────────────┐   │
            │  │ Effect: text │   │  ← CUDA
            │  └──────┬───────┘   │
            │         │           │
            │         ▼           │
            │  ┌──────────────┐   │
            │  │ Encoded frame│   │  ← NVENC
            │  └──────────────┘   │
            │                     │
            └─────────────────────┘
```

When an effect is not GPU-capable (e.g. a CPU-only filter), the runtime transfers the frame to system memory, runs the effect, and transfers back. The cost is one round-trip; the runtime avoids this when possible.

## Hardware acceleration matrix

The runtime probes the system at init time and selects the best available path:

| Operation | Linux | macOS | Windows | Browser (v2) |
|---|---|---|---|---|
| Decode | NVDEC, VAAPI, QSV | VideoToolbox | NVDEC, QSV, D3D11VA | WebCodecs |
| Color | CUDA, Vulkan | Metal | CUDA, Vulkan, D3D12 | WebGPU |
| Effect | CUDA, Vulkan | Metal | CUDA, Vulkan, D3D12 | WebGPU |
| Encode | NVENC, VAAPI, QSV | VideoToolbox | NVENC, QSV | WebCodecs |
| AI | CUDA, ROCm, OneAPI | Metal, MLX | CUDA, DirectML | WebGPU + ORT Web |
| Fallback | libavcodec SW | libavcodec SW | libavcodec SW | libavcodec via WASM |

The runtime picks the best path for each device. If the hardware path fails (driver bug, OOM, format unsupported), it falls back to software. Fallback is logged.

## Audio pipeline

Audio is processed in a separate graph, parallel to the video graph:

```
[Per-clip audio] → [Decode] → [Effects: volume, fade, EQ] → [Mix] → [Master: normalize, loudnorm] → [Encode]
```

The audio pipeline runs on CPU (no GPU acceleration for audio in v1). It is sample-accurate (no drift vs. video) by anchoring to the video frame clock.

## The loudness pass

For social-media delivery, the runtime applies a final loudness pass:

- Target: -14 LUFS integrated, -1 dBTP peak, LRA 11 LU (YouTube/IG/TikTok/X standard).
- Two-pass `loudnorm` filter: measure first, apply with offset second.
- Output of the loudness pass is the final audio stream.

The pass is enabled by default for social-media presets; it can be disabled per-render.

## Color pipeline

The runtime manages color space conversions end-to-end:

- Source color space is read from the source media (libavformat probe).
- Intermediate color space is BT.709, full range, 8-bit for SDR; BT.2020, PQ, 10-bit for HDR.
- Output color space is determined by the output preset (preset metadata declares the target).

Conversions are explicit. The runtime does not auto-detect at the node level; the plan is built with the full color pipeline in mind.

## HDR handling

For HDR sources (HLG, PQ):

1. Detect the transfer function via `color_transfer` (libavformat).
2. Apply a tone-map chain (`zscale=t=linear:npl=100, format=gbrpf32le, zscale=p=bt709, tonemap=hable:desat=0, zscale=t=bt709:m=bt709:r=tv`).
3. Continue in SDR (BT.709).

v1 always outputs SDR. HDR output is a v2 feature.

## Progress reporting

The render job reports progress via a channel:

```rust
pub struct Progress {
    pub stage: String,                  // "decoding" | "compositing" | "encoding" | "muxing"
    pub percent: f32,                   // 0.0 to 100.0
    pub current_frame: Option<u64>,
    pub total_frames: Option<u64>,
    pub eta_seconds: Option<f32>,
    pub message: Option<String>,
}
```

Progress is reported at a throttled rate (default: 10 Hz) to avoid flooding the channel. The runtime guarantees that the *last* progress event before completion or cancellation reports a final state.

## Cancellation

A `cancel()` sets a flag that the scheduler checks at every frame boundary. On cancel:

- The current frame finishes processing.
- In-flight GPU work is flushed.
- Output buffers are released.
- Partial output files are deleted.
- The job ends with status `Cancelled`.

Cancellation is **cooperative**: the runtime cannot interrupt a frame mid-decode or mid-encode. For long frames (e.g. AI inference taking 10 seconds), the cancel is delayed until the frame returns.

# Architecture

```
┌────────────────────────────────────────────────────────────┐
│                  Render Executor                            │
│                                                             │
│  ┌────────────────┐                                         │
│  │ Plan Builder   │  → RenderPlan (immutable)               │
│  └────────────────┘                                         │
│                                                             │
│  ┌────────────────┐                                         │
│  │ Resource       │  → GPU buffers, codec contexts          │
│  │ Allocator      │                                         │
│  └────────────────┘                                         │
│                                                             │
│  ┌────────────────────────────────────────────┐             │
│  │ Worker Pool                                 │             │
│  │                                             │             │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  │             │
│  │  │ Demuxer  │  │ Effect   │  │ Encoder  │  │             │
│  │  │ worker   │─▶│ scheduler│─▶│ worker   │  │             │
│  │  └──────────┘  └──────────┘  └──────────┘  │             │
│  │        │             │             │        │             │
│  │        ▼             ▼             ▼        │             │
│  │  GPU frames    GPU/CPU frames  Encoded      │             │
│  │  (NVDEC)       (CUDA / CPU)    (NVENC)      │             │
│  └────────────────────────────────────────────┘             │
│                                                             │
│  ┌────────────────┐                                         │
│  │ Muxer          │  → output file                          │
│  └────────────────┘                                         │
│                                                             │
│  ┌────────────────┐                                         │
│  │ Progress       │  → channel → JobHandle.progress()        │
│  │ Reporter       │                                         │
│  └────────────────┘                                         │
│                                                             │
└────────────────────────────────────────────────────────────┘
```

# Alternatives

### A. FFmpeg CLI as a black box

**Rejected.** CLI gives us no progress, no cancellation, no GPU control beyond what the CLI exposes. We need programmatic access to the codec and filter APIs.

### B. MLT's consumer-pull model

**Considered.** MLT pulls frames from a producer; the consumer paces the pipeline. **Rejected** for v1 because: (a) it is hard to integrate GPU effects (they want to push), (b) cancellation is awkward, (c) the model assumes a real-time consumer, which we do not have.

### C. Distributed render (across machines)

**Deferred** to a future RFC. The complexity of distributing a render across machines is high; the win is significant for very long renders; not v1.

### D. Stream the rendered output to the agent

**Considered.** Instead of writing a file, stream the encoded bytes back to the caller over MCP. **Rejected** for v1 because: (a) most use cases want a file, (b) streaming requires a different mux design, (c) deferred to a v2 RFC.

# Drawbacks

- **GPU dispatch is platform-fragmented.** CUDA, Metal, Vulkan, D3D12 — each has its own API quirks. Mitigated by: a thin GPU abstraction layer in `flow-core`, with platform-specific implementations.
- **Determinism vs. performance.** Multi-threaded rendering is fast but introduces non-determinism (thread scheduling). Mitigated by: pinning threads, fixed worker counts, deterministic GPU kernels.
- **Hardware encoder quality varies.** NVENC and QSV produce slightly different output from x264 for the same parameters. Mitigated by: preset-based parameter sets that are tuned per encoder.
- **Color pipeline complexity.** Every color conversion is a place to introduce a bug. Mitigated by: a single, well-tested color engine wrapping `libswscale`.
- **Cancellation safety.** AI effects that hold GPU memory cannot be safely interrupted. Mitigated by: per-frame cancellation points, documenting the cancellation granularity.

# Future Possibilities

- **Real-time preview.** A separate pipeline that uses the same Effect Graph but renders to a display surface at 30+ fps. Requires a display server abstraction.
- **Distributed render.** Ship sub-jobs to other runtimes for very long renders.
- **HDR output.** v2.
- **Streaming output.** Render to a network destination instead of a file.
- **Smart caching.** Reuse decoded frames across renders (when the same media is used). Significant complexity; deferred.
- **Render farms.** Multiple runtimes coordinated by a scheduler for very high throughput.

# Unresolved Questions

1. **GPU device selection.** When multiple GPUs are available, how does the runtime pick? Round-robin? User preference? Per-job?
2. **Encoder parameter presets.** Who maintains the per-encoder quality presets? The Flow team? Community contributions?
3. **Resource budgets.** Should the runtime enforce a memory cap per job? What happens when a render needs more than is available?
4. **Frame-accurate seeking.** When a render range starts at `t=5.0s`, can we seek to the exact keyframe before `t`? Or do we decode from the previous keyframe and discard? Trade-off between speed and determinism.
5. **Audio-video sync drift.** Over long renders, audio and video can drift by a few milliseconds. Should we add a resync mechanism?

---

**Next**: `0002-asset-management.md`
