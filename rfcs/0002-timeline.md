# RFC 0002 — Timeline Model

| Field | Value |
|---|---|
| **Status** | Draft |
| **Author** | Flow Team |
| **Created** | 2026-07-17 |
| **Depends on** | RFC 0001 (Runtime) |

---

## Summary

Adopt OpenTimelineIO (OTIO) as Flow's canonical timeline format, with Flow-specific schema extensions for AI operations and agent metadata.

## Motivation

Every video tool has its own timeline format. OTIO is the industry standard for interchange. Using it means Flow projects are natively portable to DaVinci Resolve, Premiere Pro, and VFX pipelines.

## Design

### OTIO Schema (Canonical)

```
Timeline
└── Stack
    ├── Track (Video)
    │   ├── Clip ── ExternalReference
    │   ├── Transition
    │   ├── Clip
    │   └── Gap
    ├── Track (Video)
    └── Track (Audio)
```

All operations mutate this structure. No other timeline representation exists internally.

### Flow Extensions

Via OTIO's SchemaDef plugin system:

| Extension | Type | Purpose |
|---|---|---|
| `FlowOp.1` | SchemaDef | AI operation metadata |
| `flow.llm.intent` | metadata | Original LLM prompt |
| `flow.confidence` | metadata | AI confidence score |
| `flow.agent_id` | metadata | Agent identifier |
| `flow.session_id` | metadata | Session for traceability |

### Time Model

`RationalTime(value, rate)` — integer ticks + rational framerate. No floating-point drift. Use OTIO's `opentime` library directly.

### Project Persistence

```
my-project/
├── timeline.otio       # Current state
├── actions.jsonl        # Append-only log (source of truth)
├── media/               # Local cache
├── renders/             # Outputs
└── project.toml         # Metadata
```

The action log is append-only. Every mutation writes to it. The OTIO file is regenerated from the log on demand (like `git`).

### Diff & Merge

- Diff = compute missing actions between two logs
- Merge = apply branch B's actions onto branch A's tip
- Conflict = same clip modified in both branches

## Alternatives Considered

- **MLT XML** — tied to MLT's runtime model. Rejected.
- **Custom JSON** — why not use the standard? Rejected.
- **EDL/CMX3600** — too lossy. Rejected.

## Open Questions

- How many actions before the OTIO regeneration is slow?
- Should we store a snapshot periodically (like `git gc`)?

## Implementation Plan

1. OTIO C++ bindings for Rust
2. `Timeline` struct wrapping OTIO
3. Action application → OTIO mutation
4. Action log persistence
5. Diff between two timelines
6. Checkpoint / branch operations
