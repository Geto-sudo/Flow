# RFC 0004 — Action System

| Field | Value |
|---|---|
| **Status** | Draft |
| **Author** | Flow Team |
| **Created** | 2026-07-17 |
| **Depends on** | RFC 0001 (Runtime), RFC 0002 (Timeline) |

---

## Summary

Define Flow's action system: the typed, serializable, undoable mutation API that drives all timeline changes. Inspired by OpenReelio's `ActionExecutor` pattern.

## Motivation

Every mutation to the timeline must be:
- **Typed** — validated against JSON Schema before execution
- **Serializable** — LLMs can produce it, runtime can log it
- **Undoable** — every action has a deterministic inverse
- **Observable** — clients can stream progress and diffs

## Design

### Core Types

```rust
#[serde(tag = "type")]
pub enum Action {
    Timeline(TimelineAction),
    Clip(ClipAction),
    Effect(EffectAction),
    Render(RenderAction),
    Project(ProjectAction),
}
```

### Clip Actions

```rust
#[serde(tag = "op")]
pub enum ClipAction {
    Add     { source: MediaId, track: TrackId, at: RationalTime, in_range: TimeRange },
    Remove  { clip: ClipId },
    Trim    { clip: ClipId, edge: Edge, to: RationalTime },
    Move    { clip: ClipId, to_track: TrackId, to_position: RationalTime },
    Split   { clip: ClipId, at: RationalTime },
    Replace { clip: ClipId, with: MediaId },
    SetEffect    { clip: ClipId, effect: EffectId, params: Value },
    RemoveEffect { clip: ClipId, effect: EffectId },
    SetSpeed     { clip: ClipId, speed: f64 },
}
```

### Inverse Computation

Every action must be invertible:

| Action | Inverse |
|---|---|
| `ClipAction::Add` | `ClipAction::Remove` (same clip id) |
| `ClipAction::Trim(in, to)` | `ClipAction::Trim(in, original_start)` |
| `ClipAction::Split(at)` | `ClipAction::Remove` (second half) + `ClipAction::Trim` (first half restored) |
| `ClipAction::SetEffect(params)` | `ClipAction::SetEffect(original_params)` |

### Action Executor

```rust
struct ActionExecutor {
    validator: ActionValidator,
    history: Vec<Action>,
    inverses: Vec<Action>,
}

impl ActionExecutor {
    fn execute(&mut self, timeline: &mut Timeline, action: Action) -> Result<()> {
        self.validator.validate(&action)?;
        let inverse = timeline.compute_inverse(&action)?;
        timeline.apply(&action)?;
        self.history.push(action);
        self.inverses.push(inverse);
        // Notify subscribers
        Ok(())
    }

    fn undo(&mut self, timeline: &mut Timeline) -> Result<Option<Action>> { ... }
    fn redo(&mut self, timeline: &mut Timeline) -> Result<Option<Action>> { ... }
}
```

### JSON Schema (LLM Contract)

```json
{
  "$schema": "https://flow.dev/schemas/action.v1.json",
  "id": "act_01HXY...",
  "project": "proj_01HXZ...",
  "actor": { "type": "agent", "id": "claude-sonnet-4.5" },
  "intent": "Trim intro and add text overlay",
  "actions": [
    { "op": "clip.trim", "clip": "clip_abc", "edge": "in", "to": { "value": 2.5, "rate": 30 } },
    { "op": "clip.set_effect", "clip": "clip_abc", "effect": "core.text.burn", "params": { ... } },
    { "op": "render", "output": { "path": "out.mp4", "format": "mp4" }, "preset": "tiktok" }
  ]
}
```

## Alternatives Considered

- **Command pattern with manual inverse** — OpenReelio's approach. Too error-prone.
- **Immutable state + diff** — compute inverse from state diff. More general but expensive.

## Open Questions

- Should the inverse be pre-computed by the client (LLM) or by the runtime?
- How do we handle non-invertible operations (e.g., AI inference nondeterminism)?

## Implementation Plan

1. Define Action enum + JSON Schema
2. Implement `ActionValidator` (JSON Schema validation)
3. Implement `compute_inverse` for each action
4. Implement `ActionExecutor` with undo/redo stacks
5. Wire into `Timeline` mutation API
6. Add `flow plan` CLI command (dry-run validation)
7. Add action logging to project persistence
