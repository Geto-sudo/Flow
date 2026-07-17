# FFmpeg — Reverse Engineering Notes

> Source: [ffmpeg.org/developer.html](https://www.ffmpeg.org/developer.html), [FFmpeg Doxygen](http://ffmpeg.org/doxygen/trunk/), public headers (`libavformat/avformat.h`, `libavcodec/avcodec.h`, `libavfilter/avfilter.h`, `libavutil/avutil.h`), `fftools/` CLI sources, public developer documentation.
> Project state: ~1.5M LOC across `libavformat`, `libavcodec`, `libavfilter`, `libavutil`, `libswscale`, `libswresample`, `fftools/` CLI, `doc/`. C11 + handwritten NASM/GAS assembly. LGPL 2.1+ (default) or GPL 2+ (with `--enable-gpl`).

---

## 1. What FFmpeg Actually Is

FFmpeg is **not a single program**. It is a collection of tightly-coupled libraries that share a common data model (`AVFrame`, `AVPacket`) and a common build system. The `ffmpeg` binary is just one consumer of those libraries (the CLI in `fftools/ffmpeg.c`). Kdenlive, Shotcut, OBS, VLC, Chromium, HandBrake, Telegram all link against the same libraries.

```
┌──────────────────────────────────────────────────────────────────┐
│                          FFmpeg Project                          │
├──────────────────────────────────────────────────────────────────┤
│  Applications (fftools/)                                         │
│    ├─ ffmpeg.c       transcoding CLI                             │
│    ├─ ffprobe.c      media inspector                             │
│    ├─ ffplay.c       SDL2 player                                 │
│    └─ ffedit.c       (in progress) timeline editor CLI           │
├──────────────────────────────────────────────────────────────────┤
│  Public Libraries (the real product)                             │
│    ├─ libavformat    container mux/demux                         │
│    ├─ libavcodec     codec encode/decode (200+ codecs)           │
│    ├─ libavfilter    graph-based signal processing              │
│    ├─ libavutil      utilities (memory, dict, log, hash, ...)    │
│    ├─ libswscale     image scaling & colorspace conversion       │
│    ├─ libswresample  audio resampling & mixing                   │
│    └─ libpostproc    post-processing (rarely used)               │
├──────────────────────────────────────────────────────────────────┤
│  Hardware Abstraction Layers                                     │
│    ├─ libavutil/hwcontext_*.c (VAAPI, QSV, CUDA, Vulkan, ...    │
│    ├─ libavcodec/hwaccels/      (per-codec hardware paths)       │
│    └─ configure --enable-... (compile-time feature selection)    │
└──────────────────────────────────────────────────────────────────┘
```

## 2. The Core Data Model

Everything in FFmpeg flows through two structures. Once you understand them, the rest is just dispatch.

```c
// A packet: compressed, muxed, opaque bytes + timing
typedef struct AVPacket {
    uint8_t        *data;      // compressed payload
    int             size;      // bytes
    int64_t         pts;       // presentation timestamp
    int64_t         dts;       // decode timestamp
    int64_t         duration;  // in stream timebase units
    int             stream_index;
    // ... + side data (HDR metadata, rotation, ...)
} AVPacket;

// A frame: decoded, raw samples/pixels + timing
typedef struct AVFrame {
    uint8_t       *data[AV_NUM_DATA_POINTERS];   // pixels or PCM
    int            linesize[AV_NUM_DATA_POINTERS]; // stride per plane
    uint8_t       **extended_data;               // for planar audio
    int            width, height, format;
    int            sample_rate, channels, nb_samples;
    int64_t        pts;
    int64_t        duration;
    AVRational     sample_aspect_ratio;
    // ... + color range/space, mastering display, ...
} AVFrame;
```

**The pipeline in one sentence**: `demuxer → AVPackets → decoder → AVFrames → filtergraph → encoders → AVPackets → muxer`.

## 3. Module Breakdown (read carefully — this is the architecture)

### 3.1 libavformat — I/O, Demuxers, Muxers, Protocol

- **`AVFormatContext`** holds everything about an open file/stream: `nb_streams`, `streams[]`, `iformat` (demuxer), `oformat` (muxer), `pb` (I/O context).
- A **demuxer** parses the container (MP4, MKV, MOV, WebM, AVI, FLV, TS, raw, ...) and produces `AVPacket`s.
- A **muxer** does the inverse: takes `AVPacket`s and writes them to a container.
- **Protocols** (`avio.h`) abstract the I/O layer: `file`, `http`, `https`, `rtmp`, `srt`, `tcp`, `udp`, `crypto`. New protocol = new `URLProtocol` struct.
- Format probing: `avformat_open_input` tries each registered demuxer's `read_probe` to identify the input.

### 3.2 libavcodec — Codecs (200+ Encoders + Decoders)

- **`AVCodec`** describes a single codec: `id`, `type` (video/audio/subtitle), `init`, `encode`, `decode`, `close`, capability flags.
- **`AVCodecContext`** holds per-stream state: width/height, pix_fmt, bit_rate, extradata, thread_count, hw_frames_ctx (for GPU).
- Decoder API: `avcodec_send_packet` → `avcodec_receive_frame`. Async-style even for sync codecs.
- Encoder API: `avcodec_send_frame` → `avcodec_receive_packet`. Symmetric.
- **Threading**: per-frame `thread_count` slice, `thread_type=slice|frame`. Hidden inside the codec; users just count CPUs.
- **Hardware accel**: `AVHWDeviceContext` (owns the device) + `AVHWFramesContext` (owns the GPU frame pool). `av_hwframe_transfer_data` bridges GPU ↔ CPU.

### 3.3 libavfilter — Graph-Based Signal Processing

This is the most powerful and most underused part.

- A **filter** takes frames in, produces frames out. Example: `scale`, `transpose`, `overlay`, `amerge`, `atrim`, `format=yuv420p`.
- **Filter graph** = DAG of filters + links. `avfilter_graph_parse_ptr` builds it from a textual description (e.g. `"[0:v]scale=1920:1080[s]; [s][1:v]overlay=10:10[v]"`).
- **Links** carry negotiated format/size/timebase between filters — they renegotiate when source changes.
- The same graph can be reused across many frames: pull `avfilter_graph_request_oldest` until empty.
- This is **the** abstraction that Flow should copy, not the codec API. See §7.

### 3.4 libavutil — The Foundation

- `av_malloc`/`av_free` — FFmpeg's own allocator (tracks allocations, supports `av_realloc`).
- `av_dict` — string→string dictionaries (used for codec options).
- `av_log` — leveled logging (`AV_LOG_DEBUG`..`AV_LOG_PANIC`).
- `av_buffer` — ref-counted buffers (key to zero-copy).
- `av_pix_fmt`, `av_sample_fmt` — enum of pixel + sample formats.
- `av_opt` — generic option parser (used by `ffmpeg -option`).
- `av_fourcc`, `av_q2d`, `av_rescale_q` — timebase math.

### 3.5 libswscale / libswresample

- **swscale**: 100+ scaling algorithms (bilinear, bicubic, lanczos, area, ...), color space conversion (BT.601, BT.709, BT.2020, sRGB ↔ YUV ↔ RGB), HDR tone-mapping.
- **swresample**: audio resampling (SoX-quality), channel layout remapping, dithering.

### 3.6 fftools/ — The CLI

`fftools/ffmpeg.c` is a 3000+ line state machine that:
1. Parses CLI options (huge custom parser in `cmdutils.c`).
2. Opens inputs, decodes, runs through a filter graph, encodes, muxes.
3. Manages multiple input/output streams, stream mapping, copy vs. re-encode decisions.

This is the model for any pipeline orchestrator. The Flow `flow-core` should follow the same dispatch shape.

## 4. Why Is FFmpeg So Fast?

This matters because Flow will rely on FFmpeg for the heavy lifting. The reasons:

| Technique | Where | Why it matters |
|---|---|---|
| **Handwritten SIMD** (`checkasm` tested) | `libavcodec/x86/`, `libavcodec/aarch64/`, ... | x264/x265/VP9 decoders run 3-10× faster than pure C |
| **Frame-level threading** | Inside each codec | `thread_count=0` → auto = #CPUs; codec dispatches slices per thread |
| **Decoder hardware offload** | `hwaccels/` | NVDEC, VAAPI, QSV, VideoToolbox, Vulkan Video — near-zero CPU for H.264/HEVC/AV1 |
| **Zero-copy via `AVBufferRef`** | Everywhere | GPU frames, codec frames, packet payloads share refcounts instead of memcpy |
| **Lazy format negotiation** in filtergraph | `libavfilter` | Only re-allocate buffers when format/size actually changes |
| **`-c copy`** stream copy | `fftools/ffmpeg.c` | When you don't need re-encode, just remux. ~100× faster |
| **Cached frame pool** | `libavutil/buffer.c` | Don't re-`malloc` per frame; reuse slabs |
| **Process-level pixel format tracking** | `av_pix_fmt` | Avoids expensive auto-detection per frame |

The 12 "Hard Rules" from `video-use` are all responses to FFmpeg gotchas. Flow should internalize them.

## 5. CLI vs libav APIs

- **CLI** (`ffmpeg -i in.mp4 -vf scale=720 -c:a copy out.mp4`): great for shell, but each invocation re-parses, re-probes, re-allocates, can't be inspected.
- **libav** (C API): persistent state, can read progress mid-pipeline, supports custom muxers/codecs/IO, integrates with other runtimes.
- **Rule for Flow**: expose libav, hide CLI. The CLI is a debugging tool, not a production interface.

## 6. Stable vs Unstable APIs

From the FFmpeg Developer Policy (`developer.html` §3.4):

- **Public APIs** (in installed headers) are ABI-stable within a major version: `libavcodec.so.61`, `libavformat.so.61`, etc.
- **Adding APIs** is easy. **Removing** is hard — requires deprecation cycle + major bump.
- **Internal symbols** are not stable: `ff_*` (intra-library) and `avpriv_*` (inter-library) are explicitly marked as "may change at any time."

**Implication for Flow**:
- Wrap only public APIs in your FFI layer.
- Never expose `avpriv_*` or `ff_*` even if they look useful.
- Pin to specific FFmpeg major versions in CI; expect to bump and recompile Flow when upstream majors.

## 7. What Flow Should Reuse vs Hide

### Reuse (do not rewrite)
- **libavcodec** for *all* decoding and encoding. Don't write your own H.264 decoder. Ever.
- **libavformat** for muxing, demuxing, probing, protocol layer. Mature, tested, handles 200+ formats.
- **libavfilter** as the **conceptual model** for Flow's effect graph (see `flow_architecture.md` §4).
- **libswscale** for color/scaling conversion.
- **libavutil** for memory, logging, dict, buffer refcounting.
- **Hardware accel** through `AVHWDeviceContext` — ship CUDA, VAAPI, VideoToolbox, Vulkan Video paths.

### Hide (never expose to Flow users)
- Raw `AVPacket` / `AVFrame` (handle them internally, expose Flow's own types).
- Filter graph text syntax (it's a stringly-typed footgun).
- `AVCodecContext` thread_count, debug flags, refcount gc.
- Format probing internals.
- Any `avpriv_*` symbol.

### Provide a higher-level abstraction
- `flow.Media` (wraps `AVFormatContext` + selected streams).
- `flow.Effect` (wraps a subset of filter graph, validated and typed).
- `flow.RenderJob` (wraps an entire transcode pipeline, persistent across calls).

## 8. Hardware Acceleration — Practical Notes

- **Decode path**: GPU produces `AVFrame` with `format=AV_PIX_FMT_CUDA` etc. → transfer to system memory via `av_hwframe_transfer_data` only when needed (e.g. before applying a CPU filter). For a pure GPU filter graph, keep frames on GPU.
- **Encode path**: similar. Many encoders accept GPU frames directly.
- **Multi-GPU**: each `AVHWDeviceContext` is bound to one device. Multi-GPU orchestration is the caller's job.
- **Fallback**: always detect failure and fall back to software. Hardware paths fail silently with cryptic errors.

## 9. Memory Management

- **Reference counting** via `AVBufferRef`. The same bytes can back a packet, multiple frames, and a filter input without copying.
- **Frame pools**: a codec may hold N decoded frames internally. `av_frame_ref` / `av_frame_unref` manage this.
- **Thread-safety**: each `AVCodecContext` is single-threaded. To parallelize across streams, give each stream its own context.
- **No malloc-in-loop**: the rule of thumb. Decode one packet → process → `av_packet_unref` → repeat.

## 10. Filter Graph — The Crown Jewel

The most important takeaway: **libavfilter is the pattern Flow's effect system should copy, not just call.**

```c
AVFilterGraph *graph = avfilter_graph_alloc();
AVFilterContext *src_ctx, *sink_ctx, *scale_ctx, *overlay_ctx;

// Input pad
avfilter_graph_create_filter(&src_ctx, avfilter_get_by_name("buffer"),
    "in", "video_size=1920x1080:pix_fmt=yuv420p:time_base=1/30", NULL, graph);

// Scale
avfilter_graph_create_filter(&scale_ctx, avfilter_get_by_name("scale"),
    "s", "w=1280:h=720", NULL, graph);

// Overlay
avfilter_graph_create_filter(&overlay_ctx, avfilter_get_by_name("overlay"),
    "ov", "x=10:y=10", NULL, graph);

// Output pad
avfilter_graph_create_filter(&sink_ctx, avfilter_get_by_name("buffersink"),
    "out", NULL, NULL, graph);

// Wire it up
avfilter_link(src_ctx, 0, scale_ctx, 0);
avfilter_link(scale_ctx, 0, overlay_ctx, 0);
avfilter_link(overlay_ctx, 0, sink_ctx, 0);

avfilter_graph_config(graph, NULL);
```

The genius: **the graph renegotiates format/size through links**. You can swap `scale` for `crop` without changing the surrounding code. The graph is *the* data structure that survives changes. Flow should have its own typed effect graph, but borrow this renegotiation discipline.

## 11. Limitations / Pain Points (so Flow knows what to fix)

| Pain point | FFmpeg reality | What Flow should do |
|---|---|---|
| API verbosity | 30+ lines to transcode one file | Single `flow.render(jobs)` |
| Filter graph text syntax | Easy to typo, hard to validate | Typed effect chains in code |
| Error handling | Return codes + `av_strerror` | Exceptions / Result types |
| Stateful codecs | Must drain on close (`avcodec_send_packet(NULL)`) | Lifecycle wrapper |
| Hardware API fragmentation | CUDA ≠ VAAPI ≠ QSV ≠ VideoToolbox | Hardware abstraction layer in `flow-core` |
| Probe errors | Cryptic `Invalid data found when processing input` | Better error messages mapped to user action |
| Timestamp drift | 1-2 frame jitter from VFR sources | Baked into `flow.Media` as canonical time |
| Long option parser | CLI parsing is its own DSL | JSON/YAML action schema in Flow |

## 12. Architecture Diagrams

### 12.1 Transcode Pipeline (single input → single output)

```
  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
  │ Demuxer  │──▶│ Decoder  │──▶│ Filter   │──▶│ Encoder  │──▶ Muxer
  │ (avf)    │ pkt│ (avc)    │ frm│ (avfil)  │ frm│ (avc)    │ pkt
  └──────────┘    └──────────┘    └──────────┘    └──────────┘
       │                                                │
       │           AVPacket → AVFrame → AVFrame → AVPacket
       │                                                │
       └─────────── AVFormatContext I/O ────────────────┘
```

### 12.2 Filter Graph (multi-input)

```
            ┌──────────┐
[in 0]─────▶│ scale    │──┐
            └──────────┘  │
                          ▼
            ┌──────────┐  ┌──────────┐
            │ overlay  │─▶│ buffersink│
[in 1]─────▶│ (x,y)    │  └──────────┘
            └──────────┘
```

## 13. Open Questions for Flow

1. **Custom filters**: do we need to write any (e.g. for AI inference as an effect)? Yes — see `flow_architecture.md` §6.4.
2. **Multi-output**: FFmpeg can produce N output files from one input. Flow should support the same.
3. **Real-time streaming**: not FFmpeg's strength. Flow should consider GStreamer or its own pipeline for live.
4. **GPU-resident effects**: when AI models run on GPU, keeping frames on GPU between decode → inference → encode saves a memcpy. Worth it.

## 14. Verdict for Flow

| Question | Answer |
|---|---|
| Reuse? | **Yes, aggressively.** libav* is the engine. |
| Wrap? | **Yes.** Never expose raw libav types. |
| Expose filter graph? | **Partially.** Use libavfilter internally; expose a typed, validated Flow effect API. |
| Ship our own demuxer? | **No.** libavformat covers 200+ formats. |
| Ship our own decoder? | **No.** libavcodec is a 20-year moat. |
| Ship our own effect engine? | **No, but design our effect graph to mirror libavfilter's pattern.** |

The rule of thumb: **FFmpeg does the bytes, Flow decides the bytes**.
