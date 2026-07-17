# MoviePy — Reverse Engineering Notes

> Source: [zulko.github.io/moviepy](https://zulko.github.io/moviepy/), [github.com/Zulko/moviepy](https://github.com/Zulko/moviepy). Pure Python, MIT. Uses FFmpeg under the hood (via `subprocess`).

---

## 1. What MoviePy Is

MoviePy is a **Python library for video editing automation**. It's not an editor, not a render engine — it's a *fluent API on top of FFmpeg* that lets you script video edits in pure Python. Think: "FFmpeg for people who don't want to write bash."

```python
from moviepy import VideoFileClip, TextClip, CompositeVideoClip

clip = VideoFileClip("input.mp4").subclipped(0, 10)
title = TextClip("Hello World", fontsize=70, color="white").with_duration(3)
final = CompositeVideoClip([clip, title.with_position("center")])
final.write_videofile("output.mp4", fps=24)
```

That's the entire mental model in 4 lines. The library is beloved by:
- Data scientists generating plot animations.
- Researchers producing explainer videos.
- Anyone who wants to script video edits without learning FFmpeg's syntax.
- LLM agents doing simple video manipulation (it's the easiest API for them to call).

## 2. The Clip Abstraction

The single most important design decision in MoviePy: **everything is a Clip**.

```python
class Clip:
    def __init__(self):
        self.start = 0          # when this clip starts in the final output
        self.duration = None    # length
        self.end = None         # computed
        self.memoize = False    # cache frame data
        # ... + arbitrary attributes for subclasses

    # Subclass hooks (template method pattern)
    def get_frame(self, t): raise NotImplementedError
    def make_frame(self, t): return self.get_frame(t)  # user override

    # Compositional operations
    def with_duration(self, d): ...
    def with_start(self, t): ...
    def with_effects(self, fx): ...
    def with_audio(self, audio): ...
    def resized(self, newsize): ...

    # Combinators
    def __add__(self, other): return CompositeVideoClip([self, other])
    def __or__(self, other): return concatenate_videoclips([self, other])
    def __mul__(self, n): return self.loop(n)

    # Iteration
    def iter_frames(self): ...  # yields (t, frame) pairs
```

**Why this works**:
- `Clip` is abstract but the API is concrete enough to subclass easily.
- All transformations return new `Clip`s (immutable-by-convention, even though Python doesn't enforce it).
- Operator overloading (`+`, `|`, `*`) makes compositions read like prose.
- Subclasses are minimal: implement `get_frame(t)` → you're a clip.

Subclasses:
- `VideoClip` (base for video)
  - `VideoFileClip` (read from file via FFmpeg)
  - `ImageClip` (single image)
  - `TextClip` (PIL-based, with font/color/animation)
  - `ColorClip` (solid color)
  - `MaskClip`, `UpdatedVideoClip`, etc.
- `AudioClip` (base for audio)
  - `AudioFileClip`
  - `CompositeAudioClip`
  - `AudioArrayClip` (from numpy array)

## 3. The Effect System

Effects are functions that take a clip and return a clip:

```python
clip.fx(vfx.resize, width=480)        # 1
clip.with_effects([vfx.Resize(width=480)])  # 2 (v2 API)

# Or as a free function:
resized = vfx.resize(clip, width=480)

# Compose effects:
clip.with_effects([vfx.Resize(0.5), vfx.MultiplyColor(1.2)])
```

Effects are pure functions `Clip → Clip`. The convention:
- Implemented in `moviepy/video/fx/*.py`.
- Each is decorated so `clip.fx(name, **kwargs)` works as a shortcut.
- Some are Python-level (loop, freeze), most delegate to FFmpeg filters via the `mask`/`with_mask` mechanisms or `subprocess`.

The `with_effects([...])` API (v2) is *much* better than the old `clip.fx()` because:
- Effects are first-class objects, can be inspected.
- Composable into lists.
- Serializable (theoretically).

## 4. The Rendering Pipeline

`write_videofile()` is the entire render path:

```python
def write_videofile(self, filename, fps=24, codec="libx264",
                    audio_codec="aac", bitrate=None, preset="medium",
                    threads=None, ffmpeg_params=None, logger="bar"):
    # 1. Make audio
    if self.audio:
        self.audio.write_audiofile(audiofile, fps=audio_fps, ...)
    # 2. Make video frames
    for i, frame in enumerate(self.iter_frames(fps=fps)):
        frame.save(framefile_i, ...)
    # 3. Stitch with ffmpeg
    subprocess.call([
        "ffmpeg", "-y",
        "-r", str(fps),
        "-i", pattern,   # video frames
        "-i", audiofile, # audio
        "-c:v", codec, "-preset", preset,
        "-c:a", audio_codec,
        filename
    ])
```

Notice: **MoviePy renders to a frame sequence, then calls FFmpeg to encode.** This is the worst possible approach for performance (more on that below).

In v2, this was partially improved with `write_videofile` using a `default_ffmpeg_pipe` mode, but the architecture is still "frames out → ffmpeg in."

## 5. Why MoviePy is Easy to Use

- Pure Python, no compilation.
- Operator overloading reads like English.
- Subclassing is trivial.
- Effects are functions — easy to write new ones.
- Plays well with numpy/PIL.
- The docstring style is exemplary.
- LLM-friendly: the API is so simple that Claude/ChatGPT can write MoviePy code reliably.

## 6. Why MoviePy is Slow

1. **Frame iteration is Python-level.** Every frame is a numpy array processed by a Python function. No SIMD, no GPU.
2. **All effects run per-frame in Python.** A 1-hour 30fps video is 108,000 Python function calls.
3. **The frame-sequence pattern is brutal.** Writing 108,000 PNGs to disk and stitching them is IO-bound hell.
4. **FFmpeg is invoked as a subprocess.** Cold start, no persistent state, no zero-copy.
5. **No threading across effects.** A pipeline of N effects runs sequentially.
6. **No GPU.** Even compositing happens in numpy.
7. **Garbage collection pressure.** Lots of small array allocations.

For a 10-second 1080p clip, MoviePy is fine. For a 30-minute 4K timeline, it dies.

## 7. The Architectural Decisions — What's Good

| Decision | Why it's good |
|---|---|
| Clip as base class | Composition over inheritance, but flexible enough for custom clips |
| Operator overloading | Reads like prose |
| Immutable-by-convention | Easier to reason about |
| Pure Python effects | Trivial to write a new effect |
| FFmpeg under the hood | Don't reinvent codecs |
| Compositing via PIL | Solid for static compositing |
| Audio is a first-class Clip | Not bolted on |

## 8. The Architectural Decisions — What's Bad

| Decision | Why it's bad |
|---|---|
| Frame-sequence render | Slowest possible pattern |
| Python-only effects | No SIMD, no GPU |
| Subprocess FFmpeg | Cold start every time, no in-process state |
| No filter graph | Each effect is independent, can't fuse |
| No preview without writing frames | Can't scrub a timeline live |
| No timeline data structure | Just nested clips; no track/transition model |
| No undo/redo | Stateless API |
| No real project file | Saving a project = pickling the Python state |
| Memory leaks | Common complaint (refs held in cache) |
| No thread safety | Effects share global state |
| `os.system` / `subprocess` for FFmpeg | No progress, no error recovery |

## 9. The Big Idea MoviePy Validates

**The fluent, composable, "everything is a clip" API is exactly what an LLM agent wants to call.** When Claude writes video code, it writes MoviePy-style code. The pattern of `clip.fx(...)` returning a new clip is *the right shape* for programmatic video.

MoviePy proves the demand exists. The problem is performance.

## 10. What Flow Should Take from MoviePy

### Take
- The **Clip abstraction** as the primary user-facing type. (Even if Flow's Clip wraps an OTIO Clip, the LLM-facing API should look like MoviePy.)
- **Operator overloading** for composition (`+` = composite, `|` = sequence, `*` = loop).
- **Effects as functions** `Clip → Clip`. Especially for LLM authoring — agents can write "apply X" by writing a function call.
- **Pure Python top layer**. The LLM-facing layer should be in Python (or TS for browser, or both). The performance-critical core is C++/Rust.
- **Excellent docstrings and named arguments.** LLMs use these.

### Don't take
- The **frame-sequence render path**. Disgustingly slow. Use a filter graph.
- **Subprocess FFmpeg**. Always in-process.
- **Python-level effect execution**. Move all effects to native code (FFmpeg filter, custom GPU kernel, ML model).
- **Stateless API**. Flow needs persistent projects (OTIO files), undo/redo, preview.
- **No track model**. Use MLT/OTIO's track concept.

## 11. The Tension: Easy vs Fast

MoviePy is at one extreme (easy, slow). FFmpeg is at the other (fast, hard). Flow needs to be **both**.

The architecture that achieves this is two layers:

```
┌─────────────────────────────────────┐
│   flow-script (Python)              │  ← LLM-facing, MoviePy-like
│   fluent API, operators, easy       │
└────────────────┬────────────────────┘
                 │  compiles to:
                 ▼
┌─────────────────────────────────────┐
│   flow-core (Rust/C++)              │  ← Execution engine
│   OTIO timeline → render graph      │
│   filter graph → FFmpeg/native      │
└─────────────────────────────────────┘
```

The Python layer validates and plans. The native layer executes. The LLM never has to write native code; the user never has to wait for Python.

## 12. The API Flow Should Ship (inspired by MoviePy)

```python
from flow import Video, Audio, Text, Effect

clip = (
    Video("interview.mp4")
    .trim(start=5, end=15)
    .resize(width=1080)
    .set_audio(Audio("music.mp3").volume(0.3))
    + Text("Hello").at("center").with_duration(2)
)

clip.save("out.mp4", preset="tiktok")
```

Behind the scenes:
- Each method returns a new immutable node.
- The whole expression compiles to an OTIO timeline.
- `save` triggers `flow-core` which builds a filter graph and renders via FFmpeg.

## 13. Pros & Cons Summary

### Pros
- Best-in-class ergonomics for scripting video.
- LLMs can write MoviePy code reliably.
- Excellent docs and examples.
- Active community.
- MIT licensed.
- Plays well with the scientific Python stack.

### Cons
- Catastrophically slow for any non-trivial work.
- No timeline data model.
- No real-time preview.
- No track/transition/undo.
- No project file format.
- Memory leaks in long-running sessions.
- Subprocess FFmpeg is a non-starter for production.

## 14. Verdict for Flow

| Question | Answer |
|---|---|
| Use MoviePy directly? | **No.** Too slow for production. |
| Copy the API shape? | **Yes.** Operator overloading, fluent methods, effects as functions. |
| Copy the implementation? | **No.** Filter graph, in-process FFmpeg, native execution. |
| Replace? | **Build a better version.** Flow's `flow-script` should be the "MoviePy that scales." |

MoviePy is the prototype that proves the API. Flow is the production version of that API, backed by a real runtime.
