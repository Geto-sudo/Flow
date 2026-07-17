# OpenTimelineIO (OTIO) — Reverse Engineering Notes

> Source: [opentimelineio.readthedocs.io](https://opentimelineio.readthedocs.io/en/latest/), [github.com/AcademySoftwareFoundation/OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) (1.9k stars, 337 forks, ASWF project). C++ core + Python bindings via PyBind11. Apache 2.0.

---

## 1. What OTIO Is (and isn't)

OTIO is **an interchange format and API for editorial timeline information**. It is not a renderer, not a player, not an editor. It is a *data model + serialization + adapters*.

Why it exists: every NLE, finishing tool, and pipeline has its own internal timeline representation. Moving data between them (Final Cut Pro XML → DaVinci Resolve → custom Python pipeline → Unreal) was lossy. Pixar created OTIO to fix this. The Academy Software Foundation (ASWF, the Linux Foundation of VFX) now maintains it.

What it gives you:
- A **canonical schema** for editorial decisions (clips, tracks, gaps, transitions, markers, effects, metadata).
- A **JSON file format** (`.otio`) plus a **zipped bundle format** (`.otioz`) plus a **directory bundle** (`.otiod`).
- An **adapter plugin system** for reading/writing legacy formats: CMX 3600 EDL, Final Cut Pro XML, AAF, Avid DS, RV, etc.
- A **media linker plugin system** for resolving external media references.
- A **schema versioning system** for forward/backward compat.

What it does NOT do:
- Decode or encode media.
- Render or composite.
- Apply effects.
- Show anything to a user.

## 2. The Object Hierarchy (canonical schema)

```
Composable (abstract base)
├── Item (abstract)
│   ├── Clip            (a piece of media, with source_range and media_reference)
│   ├── Gap             (empty space, has duration)
│   ├── Transition      (between two items, has in/out and transition_type)
│   └── Marker          (colored labels on the timeline, no duration)
└── Composition (abstract, also extends Item)
    ├── Track           (linear sequence of Items, has kind: Video | Audio)
    ├── Stack           (parallel tracks composited together)
    └── Timeline        (top-level container, has global_metadata)

External (separate tree, referenced by Clip):
├── MediaReference (abstract)
│   ├── ExternalReference   (URL/path to file, with available_range)
│   ├── GeneratedReference  (synthesized, e.g. solid color)
│   └── MissingReference    (placeholder)
└── Effect (optional, attached to Clip or Track)

Time domain:
├── RationalTime        (value + rate)
└── TimeRange           (start_time + duration)
```

## 3. The Canonical Structure

```
Timeline
└── Stack
    ├── Track (Video)
    │   ├── Clip          ──external──▶  MediaReference
    │   ├── Transition
    │   ├── Clip
    │   └── Gap
    ├── Track (Video)
    │   └── ...
    └── Track (Audio)
        └── ...
```

Two levels of nesting:
- **Track** is a linear sequence of items (Clip/Gap/Transition).
- **Stack** composes Tracks in parallel (video over video over audio over audio).

This matches the NLE mental model exactly. Premiere, FCPX, Avid, Resolve — all use this shape.

## 4. The Time Model — Carefully Designed

OTIO separates **source time** (where on the original media file a clip's content lives) from **range time** (where on the timeline the clip sits). This is the single most important thing to understand.

```python
import opentimelineio as otio

clip = otio.schema.Clip(
    name="interview_01",
    media_reference=otio.schema.ExternalReference(
        target_url="interview_raw.mov"
    ),
    source_range=otio.opentime.TimeRange(
        start_time=otio.opentime.RationalTime(120, 24),  # start at 5s in source
        duration=otio.opentime.RationalTime(240, 24)     # 10s long
    )
)
```

- `clip.source_range` describes the *window* into the source media (5s → 15s in the file).
- The Clip's *position on the timeline* is determined by the parent Track.
- If you trim, you change `source_range`. If you slide, you change the Track's children.

`RationalTime` stores a fraction `(value, rate)` and is converted to seconds lazily. This avoids floating-point drift across hours-long timelines.

## 5. The JSON Serialization

`.otio` files look like this:

```json
{
  "OTIO_SCHEMA": "Timeline.1",
  "metadata": {},
  "name": "My Cut",
  "global_start_time": null,
  "tracks": {
    "OTIO_SCHEMA": "Stack.1",
    "metadata": {},
    "name": "tracks",
    "children": [
      {
        "OTIO_SCHEMA": "Track.1",
        "metadata": {},
        "name": "V1",
        "kind": "Video",
        "source_range": null,
        "children": [
          {
            "OTIO_SCHEMA": "Clip.1",
            "metadata": {},
            "name": "interview_01",
            "source_range": {
              "OTIO_SCHEMA": "TimeRange.1",
              "start_time": {"OTIO_SCHEMA": "RationalTime.1", "value": 120, "rate": 24},
              "duration":    {"OTIO_SCHEMA": "RationalTime.1", "value": 240, "rate": 24}
            },
            "media_reference": {
              "OTIO_SCHEMA": "ExternalReference.1",
              "metadata": {},
              "name": "",
              "available_range": {
                "OTIO_SCHEMA": "TimeRange.1",
                "start_time": {"OTIO_SCHEMA": "RationalTime.1", "value": 0, "rate": 24},
                "duration":    {"OTIO_SCHEMA": "RationalTime.1", "value": 7200, "rate": 24}
              },
              "target_url": "interview_raw.mov"
            },
            "markers": [],
            "effects": [],
            "enabled": true
          },
          {
            "OTIO_SCHEMA": "Transition.1",
            "metadata": {},
            "name": "crossfade",
            "transition_type": "SMPTE_Dissolve",
            "in_offset":  {"OTIO_SCHEMA": "RationalTime.1", "value": 12, "rate": 24},
            "out_offset": {"OTIO_SCHEMA": "RationalTime.1", "value": 12, "rate": 24}
          }
        ]
      }
    ]
  }
}
```

Notice the `"OTIO_SCHEMA": "..."` on every node. That's the version marker for the schema versioning system — old `.otio` files can be upgraded, new files can be downgraded (with validation).

## 6. The Plugin Systems (4 kinds)

### 6.1 Adapters
Read/write foreign formats. Built-in: `.otio`, `.otioz`, `.otiod`. Optional: CMX 3600 EDL, FCP7 XML, FCP X XML, AAF, Avid DS, RV, etc.

```python
timeline = otio.adapters.read_from_file("my_cut.fcpxml")
otio.adapters.write_to_file(timeline, "my_cut.otio")
```

### 6.2 Media Linkers
Resolve `ExternalReference.target_url` to actual local paths. Custom logic per studio ("our shared storage layout is X"). Lets OTIO files travel between studios without breaking media references.

### 6.3 SchemaDefs
Extend the schema with new node types. E.g. add a `CameraMove.1` schema to a Clip. Plugins define schema, version, serialization.

### 6.4 HookScripts
Python scripts that run at specific lifecycle points: pre-read, post-read, pre-write, post-write. Used to validate, transform, or annotate.

This **4-axis plugin system** is the model Flow should copy.

## 7. The C++ / Python Architecture

```
                ┌──────────────────────┐
                │   Python API layer   │  (idiomatic Python)
                │   (PyBind11)         │
                └──────────┬───────────┘
                           │
                ┌──────────▼───────────┐
                │   C++ Core           │  (SerializableObject, schemas)
                │   - no dependencies  │
                └──────────┬───────────┘
                           │
                ┌──────────▼───────────┐
                │   opentime (C++)     │  (RationalTime, TimeRange)
                │   - no dependencies  │
                └──────────────────────┘
```

- `opentime` is a standalone library for time math. No deps. Used by everyone.
- The C++ core uses a custom serialization system (`SerializableObject` with `Retainer<T>` smart pointers).
- Python bindings are autogenerated from C++ via PyBind11.
- Plugin system is registered via a manifest file in `OTIO_PLUGIN_MANIFEST_PATH`.

The decoupling of `opentime` from the schema is a great example: ship the time math as its own library so other tools can use it.

## 8. Why did Pixar Create OTIO?

- Pixar's pipeline moves cuts between PrPro, Avid, Resolve, their in-house tools, and Maya/Blender. Each tool has its own format. Each handoff was lossy.
- They needed a **neutral canonical** they could transform to/from without losing transitions, speed changes, nested sequences, markers, etc.
- Once standardized, third parties (Avid, Apple, Resolve vendors) could write official adapters. Today, OTIO is natively supported in Resolve, used in PrPro via the OpenTimelineIO panel, and supported in major VFX tools.

**Flow's parallel**: LLM agents will need to read timelines in many formats. Native LLM-readable format + canonical schema + adapters = OTIO. Flow should ship an OTIO adapter as a day-1 feature.

## 9. How Does OTIO Allow Interoperability?

1. **Lossless canonical schema**: the OTIO schema is expressive enough to represent the union of features across all supported formats. Loses are minimized.
2. **Format-specific adapters**: when you can't represent something 1:1 (e.g. an Avid-only effect), it goes in `metadata` as a side-channel.
3. **Versioning**: schema versions allow forward/backward compat without breaking older readers.
4. **Media Linkers**: media reference resolution is decoupled from the schema, so different environments can interpret the same file.

The **plugin system is the interoperability mechanism**. Flow should expose the same pattern.

## 10. Should Flow Use OTIO as Its Internal Format?

### Argument for YES
- Battle-tested by 1000+ VFX/post-production studios.
- Has the right abstractions (Track/Stack/Transition/Marker).
- JSON serialization is human-readable and diff-friendly.
- Plugin system is well-designed.
- Avoids reinventing the schema.
- LLM-friendly: an LLM can read an OTIO file and reason about it (smaller than FFmpeg XML, more semantic than EDL).
- Python and C++ bindings both available — Flow can consume from either.

### Argument for NO
- OTIO was designed for human editors, not agents. The schema has no concept of "intent" or "operation."
- No native support for AI operations (no `Effect` subtype for "transcribe then summarize").
- The 4 plugin types are general, but the schema itself is not extensible in a way that LLMs would naturally produce (too many nested object types).
- ASWF governance may move slower than Flow needs.

### Recommendation: **Use OTIO as the canonical interchange format, but wrap it in a Flow-specific action schema.**

```
LLM Output (Flow Action Schema)
        │
        ▼
flow-core translates to OTIO
        │
        ▼
OTIO file (canonical, git-friendly)
        │
        ▼
flow-core renders via FFmpeg / native engines
```

The Flow Action Schema is what the LLM produces. OTIO is what flows between tools. Two layers, one canonical truth.

## 11. Should Flow Extend OTIO?

Yes, via OTIO's own plugin system. Specifically:
- Add a `FlowOp.1` SchemaDef for AI operations (transcription, segmentation, scene detection, etc.).
- Add a Flow adapter to read/write the Flow Action Schema.
- Add a Flow media linker to resolve Flow-specific storage (cloud URLs, agent workspaces).

This keeps OTIO as the canonical representation while letting Flow add its own vocabulary.

## 12. Architecture Diagrams

### 12.1 Schema Tree

```
Timeline
└── Stack
    ├── Track V1
    │   ├── Clip ── ExternalReference ── (target_url)
    │   ├── Transition
    │   ├── Clip ── ExternalReference ── (target_url)
    │   └── Gap
    ├── Track V2
    └── Track A1
```

### 12.2 Plugin Architecture

```
┌──────────────────────┐    ┌──────────────────────┐
│   OTIO Core (C++)    │◀──▶│   Python Bindings    │
└──────────┬───────────┘    └──────────┬───────────┘
           │                           │
           │   ┌─────────────┐         │
           ├──▶│  Adapters   │◀────────┤
           │   │  (FCPXML,   │         │
           │   │   AAF, EDL) │         │
           │   └─────────────┘         │
           │   ┌─────────────┐         │
           ├──▶│ MediaLinker │◀────────┤
           │   │  (resolves  │         │
           │   │   URLs)     │         │
           │   └─────────────┘         │
           │   ┌─────────────┐         │
           ├──▶│ SchemaDef   │◀────────┤
           │   │  (new types) │         │
           │   └─────────────┘         │
           │   ┌─────────────┐         │
           └──▶│ HookScript  │◀────────┘
               │  (lifecycle) │
               └─────────────┘
```

## 13. Open Questions for Flow

1. **OTIO version pinning**: which version of OTIO does Flow target? Recommend 0.17+ (current, stable, Apache 2.0).
2. **C++ or Python consumption**: Flow-core in C++ means direct OTIO C++ consumption; in Python means PyBind11 round-trip. Pick one.
3. **Schema extensions**: which AI ops deserve first-class OTIO schema types vs. which stay in `metadata`? My vote: transcription, scene detection, beat detection, motion tracking. Others can wait.
4. **OTIOZ bundles**: should Flow ship project bundles (`.flowbundle`?) that contain the timeline + cached media refs + agent state? Yes — it's the unit of work.

## 14. Verdict for Flow

| Question | Answer |
|---|---|
| Use OTIO as interchange? | **Yes.** It's the best canonical editorial format that exists. |
| Use OTIO as Flow's internal model? | **Partially.** Wrap it in a Flow Action Schema for LLM output. |
| Extend OTIO? | **Yes, via SchemaDefs.** |
| Replace OTIO? | **No.** The cost of maintaining a competing canonical schema forever is too high. |
| Bind in C++ or Python? | **Either, but pick one.** C++ = lower latency; Python = faster iteration. |

OTIO solves the "what is the project" problem. Flow adds the "what should an agent do" problem on top.
