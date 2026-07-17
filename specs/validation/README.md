# specs/validation/

# Flow Validation Specs

This directory defines **how Flow validates data**. Validation is a first-class concern: every input (action, manifest, effect params, MCP request) goes through a validation pipeline before it touches runtime state.

## Why a validation spec

Validation is one of the most failure-prone areas of any system. Bugs in validation cause:

- Crashes (passing null where a struct is expected).
- Security holes (passing unbounded strings that overflow buffers).
- Silent data corruption (passing a negative duration).
- Confusing error messages (the user does not know what went wrong).

A single, well-defined validation pipeline reduces all of these.

## Structure

```
validation/
├── README.md                       ← you are here
├── pipeline.md                     ← the three-stage validation pipeline
├── json-schema-rules.md            ← how JSON Schemas are written and validated
├── error-mapping.md                ← how validation errors map to FLOW_xxx codes
└── reference-validator.md          ← how to build a reference validator
```

## The validation pipeline

Every input to Flow goes through three stages:

```
[1] Schema validation    → does the input match its JSON Schema?
       │ pass
       ▼
[2] Semantic validation → do all references resolve? are IDs valid?
       │ pass
       ▼
[3] Precondition check  → is the action applicable in the current state?
       │
       ▼
applied to state
```

Each stage returns a typed error. The stages are documented in [`pipeline.md`](./pipeline.md).

## Conformance

A conformance test (`contract-tests/validation/`) includes:

- A reference JSON Schema for every input type.
- A test driver that feeds valid and invalid inputs and asserts the right stage's error is returned.
- A coverage test that asserts every error code in the validation range is reachable.

A runtime passes conformance if it correctly stages every input and returns the right code for every failure.
