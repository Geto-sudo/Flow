# specs/actions/

# Flow Actions

This directory defines **every Flow action type** as a self-contained JSON Schema. An agent reads these schemas to discover what actions are available and what parameters they accept. The runtime validates actions against these schemas before execution.

## Structure

```
actions/
├── README.md                  ← you are here
├── envelope.json              ← the Flow Action envelope (wrapper)
├── trim.json                  ← the schema for clip.trim
├── split.json                 ← the schema for clip.split
├── crop.json                  ← the schema for video crop
├── resize.json                ← the schema for video resize
├── speed.json                 ← the schema for clip.set_speed
├── subtitle.json              ← the schema for subtitle add/modify
├── transition.json            ← the schema for transition
├── audio.json                 ← the schema for audio operations
├── export.json                ← the schema for render/export
└── ...
```

Each action file is a **complete, focused, executable spec** for one action type. It includes:

- The JSON Schema.
- A short prose explanation.
- At least 3 examples (happy path, edge case, error case).
- References to related actions and to the error codes it can produce.

## The envelope

Every action is wrapped in an **envelope** (`envelope.json`). The envelope carries:

- The `v` (schema version).
- The `id` (UUID v7).
- The `ts` (timestamp).
- The `actor` (who issued it).
- The `intent` (free-text description).
- The `actions` (the array of actions to apply atomically).
- Optionally, the `base_state_hash` for optimistic concurrency.

The envelope is the same for every action. The action file is specific to one action type.

## Per-action spec

Each per-action file declares:

- The `op` string (e.g. `clip.trim`).
- The required and optional parameters.
- The references that must exist for the action to apply (e.g. a `clip` ID must reference a clip in the project).
- The preconditions (e.g. the trim point must be within the clip's range).
- The resulting state (what the action produces).
- The corresponding error codes (from `../errors/error-codes.md`).

## Conformance

A conformance test (`contract-tests/actions/`) reads each per-action file and asserts that:

- The JSON Schema is valid.
- Examples are valid against the schema.
- The runtime accepts a valid action and returns the right result.
- The runtime rejects an invalid action and returns the right error code.

A runtime passes conformance if it correctly implements at least 95% of the action types in the catalog.

## Versioning

Each per-action file has its own `version` field. The version is bumped when the action's parameters change. Old versions are kept in the catalog (under `deprecated/`) for backward compatibility.
