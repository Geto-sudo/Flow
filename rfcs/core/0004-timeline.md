# RFC-0004: Timeline Model

| Field | Value |
|---|---|
| Status | Draft |
| Author | Mavis |
| Created | 2026-07-17 |
| Depends on | RFC-0001, RFC-0003 |

---

# Summary

This RFC defines the **Timeline**, the in-memory data structure that represents a Flow project. The timeline is the projection of the action log onto a queryable, mutable data structure. It is the type that effects read from and write to during rendering.

The timeline is built on top of **OTIO (OpenTimelineIO)** as the underlying schema, with Flow-specific extensions for AI operations and agent metadata. The timeline is exposed to plugins and embedders as a typed Rust API; raw OTIO JSON is reserved for interop with external tools.

# Motivation

The timeline model must serve three audiences:

1. **The runtime**, which needs an efficient in-memory structure that supports mutations, queries, and concurrent reads during rendering.
2. **Effects**, which need a stable, typed API to read frames, ranges, and metadata from the timeline.
3. **External tools** (DaVinci, Premiere, FCPX, Blender, custom pipelines) that need to import and export Flow projects without loss.

OTIO is the right substrate for the third audience — it is the canonical editorial format in the VFX and post-production industry, has a battle-tested schema, supports versioning, and is the only format with native support in the major NLEs.

For the first two audiences, OTIO's C++/Python API is awkward in a Rust runtime. Flow wraps OTIO in a typed Rust API that exposes the common operations (`clip_at(track, time)`, `tracks_of_kind(kind)`, `effects_of(clip)`, etc.) and hides the OTIO representation.

# Goals

- Use OTIO as the underlying schema and on-disk format (no re-invention).
- Wrap OTIO in a typed Rust API for the runtime and effects.
- Extend OTIO with Flow-specific schemas for AI operations.
- Support the full OTIO schema (Timeline, Stack, Track, Clip, Gap, Transition, Marker, Effect, MediaReference).
- Guarantee that any OTIO file round-trips through Flow without loss.
- Support efficient queries on the timeline (clip-at-time, effects-on-clip, etc.).
- Make the timeline safe to query from multiple threads during rendering.

# Non Goals

- This RFC does **not** define how the timeline is serialized on disk (RFC-0010).
- It does **not** define how the timeline is rendered (RFC-0008).
- It does **not** define how OTIO is bound to Rust (FFI details; an internal implementation concern).
- It does **not** redefine OTIO concepts. If OTIO says it, Flow says it.

# Guide-level explanation

The timeline is queried with a small set of high-level operations:

```rust
let timeline = project.timeline();

// Find what's on track V1 at time 5.0s.
let clip = timeline.clip_at(track_id("V1"), rational_time(5.0, 30))?;

// Iterate all clips on a track.
for clip in timeline.clips_on(track_id("V1")) {
    println!("{} @ {}", clip.name(), clip.range());
}

// Find all effects on a clip.
let effects = timeline.effects_of(clip_id);

// Range of the entire timeline.
let range = timeline.duration();
```

Mutations go through the action system (RFC-0003), not the timeline API directly. The timeline API is a **read API** with a small set of internal mutators used by the action executor.

# Reference-level explanation

## The timeline type

```rust
pub struct Timeline {
    inner: otio::Timeline,             // OTIO C++ representation, behind a Mutex
    extensions: FlowExtensions,         // Flow-specific schemas
    cache: TimelineCache,              // memoized queries
}

impl Timeline {
    pub fn empty(spec: TimelineSpec) -> Self { /* ... */ }
    pub fn from_otio(otio: otio::Timeline) -> Self { /* ... */ }
    pub fn to_otio(&self) -> otio::Timeline { /* ... */ }

    // High-level queries
    pub fn duration(&self) -> TimeRange;
    pub fn tracks(&self) -> &[Track];
    pub fn tracks_of_kind(&self, kind: TrackKind) -> Vec<&Track>;
    pub fn clip_at(&self, track: TrackId, time: RationalTime) -> Option<&Clip>;
    pub fn clips_on(&self, track: TrackId) -> Vec<&Clip>;
    pub fn clip(&self, id: ClipId) -> Option<&Clip>;
    pub fn effects_of(&self, clip: ClipId) -> Vec<&Effect>;
    pub fn transitions_in(&self, track: TrackId) -> Vec<&Transition>;
    pub fn markers(&self) -> Vec<&Marker>;
}
```

## Track, Clip, Effect, etc.

These mirror OTIO's schema:

```rust
pub struct Track {
    pub id: TrackId,
    pub name: String,
    pub kind: TrackKind,    // Video | Audio | Text | Graphics
    pub source_range: Option<TimeRange>,
    pub children: Vec<TrackItem>,
}

pub enum TrackItem {
    Clip(Clip),
    Gap(Gap),
    Transition(Transition),
}

pub struct Clip {
    pub id: ClipId,
    pub name: String,
    pub source_range: TimeRange,       // window into the source media
    pub media_reference: MediaReference,
    pub effects: Vec<Effect>,
    pub markers: Vec<Marker>,
    pub enabled: bool,
    pub metadata: Metadata,
}

pub struct Effect {
    pub id: EffectInstanceId,
    pub effect_name: String,           // e.g. "core.text.burn"
    pub params: serde_json::Value,
}

pub struct Transition {
    pub id: TransitionId,
    pub name: String,
    pub transition_type: TransitionType,   // SMPTE_Dissolve, Custom, ...
    pub in_offset: RationalTime,
    pub out_offset: RationalTime,
}
```

## Flow extensions

Flow extends OTIO with two mechanisms:

### Mechanism 1: OTIO metadata (lossless, no schema change)

Most Flow-specific data is stored in OTIO's `metadata` field, which is a free-form JSON object on every OTIO node. Flow uses well-known keys:

```json
{
  "metadata": {
    "flow": {
      "llm_intent": "trim the boring intro",
      "llm_confidence": 0.87,
      "llm_agent_id": "claude-sonnet-4.5",
      "llm_reasoning_trace": "..."
    }
  }
}
```

This is lossless and round-trips through any OTIO reader.

### Mechanism 2: OTIO SchemaDef (typed, validated)

For Flow-specific *operations* (AI effects, agent-owned decisions), Flow registers new OTIO schema types via OTIO's SchemaDef plugin system:

```python
# flow-otio-extensions/src/schemadefs.py
@register_schema_def
class FlowAIOp(SerializableObject):
    """An AI operation attached to a Clip."""
    _schema_name = "FlowAIOp"
    _schema_version = 1

    def __init__(self, op_name, model_id, params, confidence=None):
        self.op_name = op_name
        self.model_id = model_id
        self.params = params
        self.confidence = confidence
```

The Rust runtime reads/writes these via the OTIO C++ extension API.

## ID generation

Clips, tracks, effects, markers, and transitions are identified by stable IDs (UUID v7). IDs are minted when the corresponding action is applied. IDs are **immutable**: even after undo/redo, the same logical entity keeps the same ID. This is what makes the action log replayable.

## Concurrency

The timeline is read-mostly during rendering. A render job:

1. Acquires a read lock on the timeline.
2. Walks the timeline to build a render plan (see RFC-0008).
3. Releases the lock.
4. Executes the plan (no longer holding the lock).

Mutations from the action executor take a write lock. They are short and serialized. There is no read-while-write on the same timeline; readers either see the old state or the new state, never a torn mix.

## The cache

The timeline cache memoizes expensive queries (e.g. "all clips overlapping time range R on track T"). The cache is invalidated on every mutation. The cache is per-timeline (not global) and lives in the same `Timeline` struct.

# Architecture

```
                ┌─────────────────────────────────────┐
                │              Timeline                 │
                │                                      │
   action ────▶ │  ┌────────────────────────────┐      │
   mutation     │  │  Action Executor           │      │
   (from RFC-   │  │  - applies mutation        │      │
    0003)       │  │  - invalidates cache       │      │
                │  └────────────┬───────────────┘      │
                │               │                      │
                │               ▼                      │
                │  ┌────────────────────────────┐      │
                │  │  OTIO Timeline (C++)       │      │
                │  │  - canonical schema        │      │
                │  │  - extensions via metadata │      │
                │  │    and SchemaDef           │      │
                │  └────────────┬───────────────┘      │
                │               │                      │
                │  ┌────────────▼───────────────┐      │
                │  │  Rust typed wrapper        │      │
                │  │  - high-level query API    │      │
                │  │  - ID management           │      │
                │  │  - cache invalidation      │      │
                │  └────────────┬───────────────┘      │
                │               │                      │
                │  ┌────────────▼───────────────┐      │
                │  │  Flow extensions            │      │
                │  │  - FlowAIOp SchemaDef       │      │
                │  │  - flow.* metadata keys    │      │
                │  │  - agent attribution        │      │
                │  └────────────────────────────┘      │
                │                                      │
                └───┬──────────────────────────────┬───┘
                    │                              │
                    ▼                              ▼
             read API for effects            write API
             (rendering, queries)            (action executor only)
```

# Alternatives

### A. Build a new schema, ignore OTIO

**Rejected.** Building a competing timeline format is a 5-year project. OTIO exists, is canonical, and is supported by the VFX industry. Flow's differentiator is the action system and the AI effects, not the timeline format.

### B. Use MLT's internal data model

**Rejected.** MLT's model is tied to its runtime (producers, consumers, tractor). It is not a clean data model. OTIO is.

### C. Use a generic document store (JSON tree, Protobuf, Cap'n Proto)

**Rejected.** We would lose the entire VFX interop story. OTIO is the format that Resolve, FCPX, and Avid understand. Reinventing this would lock Flow out of every existing pipeline.

### D. Use OpenTimelineIO C++ bindings directly in Rust

**Considered.** CXX or autocxx bindings to OTIO C++ would skip the wrapper layer. **Rejected** for v1 because: (a) the binding layer is fragile, (b) the wrapper is genuinely useful (typed Rust API > raw OTIO C++), (c) we can swap the wrapper for direct bindings in a future version if benchmarks demand it.

# Drawbacks

- **OTIO is in flux.** The ASWF governance is stable, but OTIO itself has had breaking changes between minor versions. Pinning to a specific OTIO version is necessary; upgrading requires validation.
- **The metadata channel is unbounded.** Storing arbitrary data in `metadata` is convenient but can lead to schema drift. Mitigated by: documented conventions, schema validation on read.
- **The Rust wrapper adds latency.** Every query goes through a C++ → Rust boundary. Mitigated by: aggressive caching, batch queries.
- **OTIO does not model AI operations.** We are extending it via SchemaDefs, but the upstream OTIO community may not accept our extensions. Mitigated by: keep the extensions as a plugin, not a core change to OTIO.

# Future Possibilities

- **Native Rust timeline (no OTIO).** If OTIO proves too slow or too constraining, Flow could maintain its own schema with OTIO as an import/export format only. Significant work.
- **Multi-timeline projects.** Today, one project = one timeline. A future version could allow a project to contain multiple timelines (a "project library").
- **Collaborative timelines.** A future CRDT layer could allow multiple agents to edit the same timeline concurrently, with automatic merge.
- **Schema migrations.** A future runtime could automatically upgrade old `.otio` files to new schema versions, recording the migration in the action log.

# Unresolved Questions

1. **OTIO version pin.** Which OTIO version does Flow target? Recommend 0.17+ (current, stable, ASWF-supported).
2. **Schema extension API.** Should Flow extensions be a separate `flow-otio-extensions` package, or vendored into Flow? Separate is more maintainable.
3. **Cache invalidation strategy.** Lazy (on next read), eager (on every write), or hybrid (eager for cheap invalidations, lazy for expensive ones)?
4. **Marker schema.** OTIO markers are flexible (color, label, metadata). Flow's convention for them?
5. **Spatial coordinates.** OTIO has a spatial coordinate system (RFC-0004 of OTIO). How does Flow use it? Bound to clips? Effects?

---

**Next RFC**: RFC-0005 — Plugin System
