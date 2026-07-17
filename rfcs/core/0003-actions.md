# RFC-0003: Action System

| Field | Value |
|---|---|
| Status | Draft |
| Author | Mavis |
| Created | 2026-07-17 |
| Depends on | RFC-0001, RFC-0002 |

---

# Summary

This RFC defines the **Action**, the unit of state change in Flow. An Action is a typed, validated, serializable operation that mutates the project state. Every mutation goes through the action system; there is no other way to change a project. The action system is the contract between agents (or humans) and the runtime.

# Motivation

The action system is the **single interface** between the deterministic runtime and the non-deterministic agents above it. To serve that role, it must satisfy four properties:

1. **Validity.** Every action can be checked against a JSON Schema before execution. A bad action never reaches the project state.
2. **Reversibility.** Every action has a deterministic inverse. Undo is applying the inverse. Redo is re-applying the original.
3. **Serializability.** Every action is JSON. It can travel over HTTP, over MCP, through a log file, in a chat message.
4. **Composability.** Complex actions can be built from primitives. The action set is closed under composition (a sequence of actions is itself an action).

These properties make the runtime safe to expose to LLMs: the LLM produces JSON, the runtime validates it, applies it, and either succeeds or returns a typed error. The LLM never has direct access to the in-memory state.

# Goals

- Define a closed set of primitive actions that covers all Flow operations.
- Provide a JSON Schema for every action and every action's parameters.
- Compute the inverse of every action deterministically.
- Validate actions before they reach the project state.
- Persist the action log as the source of truth (the in-memory state is derivable).
- Make the action log a first-class API: list, filter, replay, export, diff.
- Support batch actions (a list of primitives applied atomically).

# Non Goals

- This RFC does **not** define the in-memory representation of project state (RFC-0004).
- It does **not** define the on-disk project format (RFC-0010).
- It does **not** define the action schema for plugins (plugins declare their own action types via the plugin manifest, and the runtime registers them at load time).
- It does **not** define a visual action editor or a drag-and-drop interface.

# Guide-level explanation

An agent expresses intent as a list of actions:

```json
{
  "actions": [
    { "op": "clip.add", "source": "media://interview.mp4", "track": "V1", "at": 0 },
    { "op": "clip.trim", "clip": "clip_01", "edge": "in", "to": { "value": 5, "rate": 30 } },
    { "op": "clip.set_effect", "clip": "clip_01", "effect": "core.text.burn",
      "params": { "text": "Hello", "start": 0, "duration": 2 } },
    { "op": "render", "output": "out.mp4", "preset": "tiktok-vertical-1080" }
  ]
}
```

The runtime validates this batch, applies it atomically (or not at all), records it in the history, and returns the new state.

# Reference-level explanation

## The Action enum

```rust
#[derive(Serialize, Deserialize, JsonSchema)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Action {
    // Timeline-level
    TimelineSetFps { value: f64 },
    TimelineSetResolution { width: u32, height: u32 },

    // Track-level
    TrackAdd { kind: TrackKind, name: String, index: Option<usize> },
    TrackRemove { track: TrackId },
    TrackRename { track: TrackId, name: String },
    TrackReorder { track: TrackId, new_index: usize },

    // Clip-level
    ClipAdd { source: MediaRef, track: TrackId, at: RationalTime, in_range: Option<TimeRange> },
    ClipRemove { clip: ClipId },
    ClipTrim { clip: ClipId, edge: TrimEdge, to: RationalTime },
    ClipMove { clip: ClipId, to_track: TrackId, to_position: RationalTime },
    ClipSplit { clip: ClipId, at: RationalTime },
    ClipReplace { clip: ClipId, with: MediaRef },
    ClipSetSpeed { clip: ClipId, speed: f64 },
    ClipSetEnabled { clip: ClipId, enabled: bool },

    // Effect-level
    EffectAdd { target: EffectTarget, effect: EffectRef, params: serde_json::Value },
    EffectRemove { target: EffectTarget, effect: EffectInstanceId },
    EffectSetParam { target: EffectTarget, effect: EffectInstanceId, key: String, value: serde_json::Value },

    // Marker-level
    MarkerAdd { target: MarkerTarget, time: RationalTime, color: MarkerColor, label: Option<String> },
    MarkerRemove { marker: MarkerId },

    // Render
    Render { output: OutputSpec, preset: RenderPresetId, range: Option<TimeRange> },

    // Batch
    Batch { actions: Vec<Action> },

    // Undo/Redo (rare; usually managed by the runtime)
    Undo { count: usize },
    Redo { count: usize },
}
```

Every variant is `#[derive(JsonSchema)]`. The runtime registers the generated schemas in a central registry. Plugin-declared actions are added to the same registry at plugin load time.

## Inverse computation

Each action has a `compute_inverse(&self, state: &ProjectState) -> Result<Action>` method. For example:

- `ClipAdd { source, track, at, in_range }` → inverse is `ClipRemove { clip: <newly created id> }`. The runtime mints the clip ID, applies the action, and stores the inverse.
- `ClipTrim { clip, edge, to }` → inverse is `ClipTrim { clip, edge, to: <previous value> }`. The runtime reads the previous trim point from the state.
- `Batch { actions }` → inverse is `Batch { actions: <inverses in reverse order> }`.

Inverse computation is **deterministic** and **pure**: given the same state, the same action always produces the same inverse. This is what makes undo safe.

## Validation pipeline

Every action passes through three stages before mutation:

```
submitted Action
       │
       ▼
[1] Schema validation       → ensure the JSON matches the JSON Schema
       │ pass
       ▼
[2] Semantic validation    → ensure referents exist (clip_id is in the project,
       │ pass                  media_ref is resolvable, etc.)
       ▼
[3] Precondition check      → ensure the action is applicable in the current
       │ pass                  state (e.g. can't split a clip at a time
       │                       outside its range)
       ▼
applied to state, recorded in history
```

Each stage returns a typed error. Stage 1 errors are programmer bugs (the LLM emitted a malformed JSON). Stage 2 errors are referential bugs (the LLM is operating on a stale view of the state). Stage 3 errors are application bugs (the LLM is trying to do something invalid).

This three-stage split is important for **agent feedback**: an LLM that gets a Stage 2 error can re-probe the state and retry. An LLM that gets a Stage 1 error has emitted malformed JSON and needs to fix its output. An LLM that gets a Stage 3 error has misunderstood the semantics and needs different guidance.

## The history

Every applied action is appended to the project's history:

```rust
pub struct HistoryEntry {
    pub id: ActionId,
    pub timestamp: SystemTime,
    pub actor: Actor,            // "agent:claude-sonnet-4.5" | "user:alice" | "plugin:flow-ai-upscale"
    pub intent: Option<String>,  // free-text description, set by the agent
    pub action: Action,
    pub inverse: Action,
    pub result: ActionResult,
}
```

The history is append-only in memory. On save, the runtime persists it as `actions.jsonl` (one JSON object per line). Undo pops from the top, applies the inverse, pushes the inverse of the inverse (so redo works). Redo pops from the redo stack, applies, and pushes the inverse to the undo stack.

A future capability (out of scope for v1) is **branching history**: an agent could fork the history at a checkpoint, try a different sequence of actions, and merge or abandon.

# Architecture

```
                ┌─────────────────────────────────────┐
                │          Action pipeline             │
                │                                      │
   Action ────▶ │  ┌──────────────┐                    │
   (JSON or     │  │   Stage 1    │                    │
    typed)      │  │   Schema     │                    │
                │  │   validation │                    │
                │  └──────┬───────┘                    │
                │         │ ok                         │
                │         ▼                            │
                │  ┌──────────────┐                    │
                │  │   Stage 2    │                    │
                │  │   Semantic   │                    │
                │  │   validation │                    │
                │  └──────┬───────┘                    │
                │         │ ok                         │
                │         ▼                            │
                │  ┌──────────────┐                    │
                │  │   Stage 3    │                    │
                │  │  Precondition│                    │
                │  │   check      │                    │
                │  └──────┬───────┘                    │
                │         │ ok                         │
                │         ▼                            │
                │  ┌──────────────┐                    │
                │  │   Apply      │                    │
                │  │   mutation   │                    │
                │  └──────┬───────┘                    │
                │         │                            │
                │         ▼                            │
                │  ┌──────────────┐                    │
                │  │  Compute     │                    │
                │  │  inverse     │                    │
                │  └──────┬───────┘                    │
                │         │                            │
                │         ▼                            │
                │  ┌──────────────┐                    │
                │  │  Append to   │                    │
                │  │  history     │                    │
                │  └──────┬───────┘                    │
                │         │                            │
                │         ▼                            │
                └─────────┴─────────────────────────────┘
                          │
                          ▼
                  ActionResult
```

# Alternatives

### A. Direct mutation API (no actions)

**Rejected.** No undo, no replay, no audit log, no way for an agent to express intent.

### B. CRDT (Conflict-free Replicated Data Types)

**Considered.** CRDTs would give us free conflict resolution and distributed collaboration. **Rejected** for v1 because: (a) CRDTs for rich timeline data are an open research problem, (b) the action-log model is sufficient for the local-first case, (c) we can add CRDT semantics on top of the action log later.

### C. Event sourcing without validation

**Rejected.** Without validation, malformed or referentially-inconsistent actions would corrupt the project. Validation must be in the runtime, not in the caller.

### D. Custom DSL (Lua, RHAI, etc.) for actions

**Considered.** A scripting language would be more expressive. **Rejected** because: (a) JSON is the lingua franca of LLMs, (b) a DSL adds a parser, runtime, and security model, (c) action composition is sufficient for v1.

# Drawbacks

- **The action set is closed.** Adding a new action requires modifying the runtime. Plugins can extend the action set (see RFC-0005), but the core enum is fixed per runtime version.
- **Inverse computation is hand-written per action.** It is easy to introduce a bug where the inverse does not perfectly undo the action. Mitigated by: (a) property-based tests for every action, (b) a "replay forward + replay inverse" golden test.
- **Action idempotency is partial.** Applying the same `ClipTrim` twice produces different results (the second trim has nothing to trim). This is intentional but can confuse LLMs. Mitigated by: clear documentation, action result includes the actual change made.
- **The JSON representation may grow.** Action schemas must evolve without breaking existing logs. Mitigated by: strict version field on every action (`"v": 1`), forward-compatible schema migrations.

# Future Possibilities

- **Action subscriptions.** Plugins or external observers can subscribe to action events on a project. Used for live multi-agent collaboration or for triggering downstream pipelines.
- **Conditional actions.** `ClipRemoveIf { clip, predicate }` — actions that depend on runtime state. Risky for determinism; deferred.
- **Action macros.** User-defined action sequences exposed as a single action. Could be implemented in `flow-script`.
- **Optimistic concurrency control.** Actions carry a `base_state_hash`; the runtime rejects if the hash no longer matches. Enables safe multi-agent editing.
- **Cross-project actions.** Today, every action operates on one project. A future version could allow cross-project references (e.g. reuse a clip from a project library).

# Unresolved Questions

1. **Action versioning policy.** When we change an action's schema, how do we handle old `actions.jsonl` files? Block-load? Auto-upgrade? Reject on disk write?
2. **Plugin action types.** What constraints apply? Can a plugin redefine the meaning of a core action? (No.) Can a plugin add a new op? (Yes, with registration.)
3. **Action graph dependencies.** Some actions depend on the result of others (e.g. `Render` after `ClipAdd`). Should the runtime automatically order a batch by dependency, or trust the agent to order correctly?
4. **Atomicity of `Batch`.** A `Batch` with one invalid action rolls back the whole batch. Is this the right semantic? Or should we apply what we can and return a partial result?
5. **Action-side free-text fields.** Where do agents put their reasoning? In a `reasoning` field on the action? In the `intent` field on the history entry? Both?

---

**Next RFC**: RFC-0004 — Timeline Model
