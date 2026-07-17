# MLT Framework — Reverse Engineering Notes

> Source: [mltframework.org/docs/framework/](https://mltframework.org/docs/framework/) (authoritative), [mltframework.org/doxygen](https://www.mltframework.org/doxygen/annotated.html), [github.com/mltframework/mlt](https://github.com/mltframework/mlt). Pure C99, no runtime deps beyond POSIX. LGPL 2.1+. Used by Kdenlive, Shotcut, Olive (legacy), and ~10 other NLEs.

---

## 1. What MLT Is

MLT is a **multimedia framework for non-linear video editing** — designed for television broadcasting. It provides:

- A **service-oriented architecture** (producers, filters, transitions, consumers).
- A **frame-pull** execution model (consumers pull frames, never push).
- A **plugin system** where every codec, format, filter, transition is a dynamic library loaded at runtime.
- A **serialization format** (MLT XML) that round-trips the entire network.

It is *not* an editor. It is the engine under Kdenlive and Shotcut. The mental model: MLT is to video what WebKit is to HTML.

## 2. The Core Class Hierarchy

From the framework design doc, this is the actual class tree:

```
mlt_properties              (base: name/value dict)
   ├── mlt_frame            (a unit of decoded media)
   └── mlt_service          (anything that produces or consumes frames)
        ├── mlt_producer    (0 inputs, 1 output)
        │    ├── mlt_playlist     (sequence of clips)
        │    ├── mlt_tractor      (multitrack + transitions wrapper)
        │    ├── mlt_chain        (producer wrapper with normalizing links)
        │    └── mlt_link         (a producer that can seek to other frames)
        ├── mlt_filter      (in/out: 1 each, stateless transform)
        ├── mlt_transition  (in: 2 (A, B), out: 1, mixer)
        └── mlt_consumer    (in: 1, output: 0, sink)

mlt_deque                   (RPN stack + queue)
mlt_pool                    (slab allocator for big memory)
mlt_factory                 (plugin loader, registry)
```

Each class extends the ones above-left via composition (MLT is C, not C++, so "extension" is by `parent` pointer + vtable).

## 3. The Producer/Consumer Pipeline (canonical Hello World)

```c
#include <framework/mlt.h>

int main(int argc, char *argv[]) {
    mlt_factory_init(NULL);                    // 1. discover plugins
    mlt_profile profile = mlt_profile_init(NULL);

    mlt_consumer hello = mlt_factory_consumer(profile, NULL, NULL);
    mlt_producer world = mlt_factory_producer(profile, NULL, argv[1]);

    mlt_consumer_connect(hello, mlt_producer_service(world));  // 2. wire
    mtl_consumer_start(hello);                                // 3. pull loop runs

    while (!mlt_consumer_is_stopped(hello)) sleep(1);

    mlt_consumer_close(hello);
    mlt_producer_close(world);
    mlt_profile_close(profile);
    mlt_factory_close();
}
```

**Key design point**: the *consumer* is threaded. It pulls frames, sleeps to maintain real-time, calls producer `get_frame` methods. The producer is single-threaded; it's a deterministic function from `position` to `frame`.

## 4. The Frame Lifecycle (the most important part)

A `mlt_frame` is the unit of data flowing through the system. Its lifecycle:

```
  ┌────────────┐                  ┌────────────┐
  │  Producer  │──── get_frame ──▶│   Filter   │── get_frame ──▶ Consumer
  └────────────┘                  └────────────┘
        │                                │
        │  produces a frame              │  may push transforms onto
        │  with image/audio stacks       │  image/audio stacks
        ▼                                ▼
   ┌──────────────────────────────────────────┐
   │  mlt_frame                               │
   │    properties: {position, speed, ...}    │
   │    image stack: [producer_get_image,     │
   │                  data1, data2,           │
   │                  filter_get_image]       │
   │    audio stack: [producer_get_audio,     │
   │                  data,                   │
   │                  filter_get_audio]       │
   └──────────────────────────────────────────┘
```

The frame uses **RPN (Reverse Polish Notation) stacks** for image and audio processing. When a filter "interests" itself in a frame, it pushes a getter and its data on the stack. When the consumer asks for the final image, the stack pops the filter getter → which pops the producer getter → which actually reads the file.

**This is lazy evaluation in its purest form**: a frame is built incrementally as different consumers ask for different parts of it.

## 5. The Multitrack Model (Tractor + Multitrack + Field)

This is MLT's most distinctive contribution to NLE architecture.

```
  +-----------------------------------------------+
  | tractor          +----------------------+    |
  |  +-----------+   |  +-+   +-+   +-+   +-+|   |
  |  |multitrack |   |  |f|   |f|   |t|   |t||   |
  |  |  +------+ |   |  |i|   |i|   |r|   |r||   |
  |  |  |track0|─|──▶|  |l|─▶|l|─▶|a|─▶|a||─▶─ output
  |  |  +------+ |   |  |t|   |t|   |n|   |n||   |
  |  |          |   |  |e|   |e|   |s|   |s||   |
  |  |  +------+ |   |  |r|   |r|   |i|   |i||   |
  |  |  |track1|─|──▶|  |0|─▶|1|─▶|t|─▶|t||   |
  |  |  +------+ |   |  | |   | |   |i|   |i||   |
  |  |          |   |  | |   | |   |o|   |o||   |
  |  |  +------+ |   |  | |   | |   |n|   |n||   |
  |  |  |track2|─|──▶|  | |─▶| |─▶|0|─▶|1||   |
  |  |  +------+ |   |  | |   | |   | |   | ||   |
  |  +-----------+   |  +-+   +-+   +-+   +-+|   |
  |                  +----------------------+    |
  +-----------------------------------------------+
```

- **Multitrack**: holds N tracks, each of which is itself a producer (playlist, chain, or another tractor).
- **Field**: a horizontal slice where filters and transitions are "planted." A transition has two inputs (A from track a, B from track b) and lives in a time range.
- **Tractor**: the orchestrator. Pulls one frame from each track, runs them through the field, elects the right output frame.

The "tractor/multitrack/field" metaphor is the entire reason MLT handles N-track composition cleanly. A multitrack alone is not a producer (it produces N frames, not 1); a tractor wraps it and presents it as a single producer to a consumer.

## 6. The Property System

Every `mlt_service` has a property bag:

```c
mlt_properties properties = mlt_producer_properties(producer);
mlt_properties_set(properties, "in", 0);
mlt_properties_set_int(properties, "out", 250);
mlt_properties_set_position(properties, "length", 5000);  // frames
```

Properties are:
- **String-keyed** (not typed field access).
- **Serially settable** to int/float/double/position/string/data.
- **Inheritable** (`mlt_properties_inherit`) — a child can pull unset values from a parent.
- **Mirrorring** (`mlt_properties_mirror`) — a child can reflect writes into a parent.
- **Prefix-based transient**: properties starting with `_` are *not* serialized (transient runtime state).

The convention: anything serialized to MLT XML must NOT start with `_`.

## 7. The Mix Pattern (NLE-friendly aliasing)

```c
mlt_transition t = mlt_factory_transition("luma", NULL);
mlt_playlist_mix(playlist, 0, 50, t);  // mix clip 0 and clip 1 over 50 frames
```

Internally, this creates a tractor/multitrack on the fly, inserts a transition track, and adjusts the playlist's "out" to reflect the shortened timeline. This is **huge**: it means the higher-level UI (Kdenlive) can treat transitions as edges between clips without managing tracks. The framework does the algebra.

## 8. The Service Factory & Plugin Model

- All services (producers, filters, transitions, consumers) are loaded as **dynamic libraries** from `$MLT_REPOSITORY` (default: `<prefix>/share/mlt/modules/`).
- Each module registers via `mlt_register()` macros and a `Module` struct.
- The factory is **late-bound**: services are resolved by name at runtime. You can ship a new filter without recompiling the host app.
- The default producer is `"loader"`, which probes the input file and picks a demuxer + normalizer filters (scaler, deinterlacer, resampler, field normalizer).

This is the model Flow should adopt for its plugin system.

## 9. MLT XML — The Serialization Format

A complete timeline is a `<mlt> <tractor> <multitrack> <track> <producer/> ... </track> ...` XML tree. Every property is a `<property name="...">value</property>` element.

```xml
<mlt LC_NUMERIC="C" version="7.40.0">
  <tractor id="main">
    <multitrack>
      <track producer="loader">
        <property name="resource">input.mp4</property>
        <property name="in">0</property>
        <property name="out">250</property>
      </track>
      <track producer="loader">
        <property name="resource">overlay.png</property>
      </track>
    </multitrack>
    <field>
      <transition in="0" out="50">
        <property name="a_track">0</property>
        <property name="b_track">1</property>
        <transition producer="luma"/>
      </transition>
    </field>
  </tractor>
</mlt>
```

The XML is the **canonical, round-trippable** representation of any project. Flow should ship a similar canonical format (and yes, OTIO is exactly that — see `otio.md`).

## 10. The Memory Pool

```c
void *mlt_pool_alloc(int size);
void *mlt_pool_realloc(void *ptr, int size);
void  mlt_pool_release(void *release);
```

A slab allocator with 24 power-of-two size classes (2^8 to 2^31 bytes). Allocations round up to the next class and pop from a per-class stack. Returns a header before the block recording the class so `release` can route it back.

Why? `malloc` makes kernel calls for blocks > 128 KB. MLT allocates huge image buffers per frame — a 1920×1080 YUV420 frame is ~3 MB. Going through the kernel each frame kills performance. The pool reuses slabs.

**Flow takeaway**: for any large-object allocation pattern, ship a slab allocator. Don't trust `malloc`.

## 11. Why Kdenlive and Shotcut Use MLT

- **Battle-tested**: 15+ years of use, used in real productions.
- **Format coverage**: hundreds of producers/consumers/filters via the plugin system.
- **Frame-accurate**: deterministic, position-driven frame pull.
- **Real-time capable**: consumer maintains frame pacing.
- **Free (LGPL)**: ships in Debian, Ubuntu, Fedora, openSUSE.
- **Language bindings**: Ruby, Python, C++, Java, Perl via SWIG.

The reasons are *infrastructure-grade* — it's the difference between building a NLE on top of a real engine vs. building one from scratch.

## 12. Should Flow Build on MLT?

**Options for Flow's execution engine:**

| Option | Pros | Cons |
|---|---|---|
| **Embed MLT as a library** | Free engine, 15 yrs of work, XML format | C ABI, GPL/LGPL entanglement, threading model is consumer-pull (Flow wants push for AI), no GPU effects, monolithic design |
| **Use MLT as inspiration, write our own** | Modern GPU/AI hooks, our own threading, our own plugin format | Reinventing the wheel for format support |
| **Bypass MLT, build directly on FFmpeg** | Maximum control, modern APIs | Lose the multitrack/transitions abstractions |
| **Hybrid: MLT for structure, FFmpeg for bytes** | Best of both | Two runtimes, two license regimes, complexity |

**Recommendation**: **Do not embed MLT.** Here's why:

1. MLT's threading model (consumer pull, real-time pacing) is wrong for Flow. Flow needs to *push* frames to AI inference backends asynchronously.
2. MLT's effect model is single-frame (RPN stacks) — not designed for multi-frame AI effects (style transfer, super-res, segmentation).
3. MLT is C, not C++; modern C++/Rust makes the same abstractions cleaner.
4. LGPL compatibility is workable, but MLT is a heavy dependency for what we want.

**What to steal** (the patterns, not the code):
- The **service factory / plugin registry** model.
- The **tractor/multitrack/field** pattern for composition.
- The **property bag** with `_` prefix for transient state.
- The **memory pool** for large frame buffers.
- The **frame-pull** model (for preview, not for inference).
- The **MLT XML** idea (Flow should have a canonical, diffable timeline format — and OTIO is the obvious answer, see `otio.md`).

## 13. Pros & Cons Summary

### Pros
- Most mature open-source NLE engine in existence.
- The producer/consumer pull model is conceptually clean.
- Multitrack/field/transition composition is elegantly captured.
- Real-time pacing built-in.
- Plugin system is exemplary.
- MLT XML is human-readable, git-friendly, round-trippable.

### Cons
- C89-style C with manual refcounting everywhere.
- No GPU effects (only OpenGL fragment shaders as a special case).
- No multi-frame/temporal effects (state across frames is via chains, not built-in).
- No AI/ML primitives.
- Documentation is sparse; you read source.
- No streaming output for live (real-time-only).
- API verbosity: 10+ lines to add one filter.

## 14. Verdict for Flow

| Question | Answer |
|---|---|
| Embed MLT? | **No.** Wrong threading model, no AI hooks, C ABI pain. |
| Learn from MLT? | **Yes, heavily.** Plugin system, multitrack pattern, property bag, frame model. |
| Steal the data model? | **No, use OTIO instead.** OTIO is a strict superset of MLT XML's purpose. |
| Steal the plugin format? | **No, design our own.** MLT's text-based "service name + properties" is not typed enough for AI. |

MLT is the proof that *the right abstractions* (producer/service/filter/transition + tractor + pluggable) win. Flow's job is to make those abstractions *first-class* in a modern, AI-native runtime.
