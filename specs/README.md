# specs/README.md

# Flow Specs

## What is a spec

A **spec** in the Flow project is a **public contract**. It defines how two components of Flow (or a component and a third party) interact. Specs are the source of truth for any implementation that wants to be Flow-compliant.

A spec is **not**:

- A description of how Flow implements the contract.
- A tutorial on how to use the contract.
- A rationale for why the contract was designed this way (that is what RFCs are for).

A spec **is**:

- A precise, machine-readable description of inputs, outputs, and behavior.
- Testable. Every spec ships with conformance tests that any implementation can run.
- Stable within a major version. Breaking changes require a new spec version.

## Specs vs RFCs vs ADRs

| Artifact | Question it answers | Mutable? |
|---|---|---|
| **Research** (`research/`) | "What did the existing ecosystem do, and what can we learn?" | Read-only history. |
| **RFC** (`rfcs/`) | "What design are we proposing, and why?" | Evolves during discussion. |
| **ADR** (`adrs/`) | "What decision did we make, and what did we reject?" | Immutable once Accepted. |
| **Spec** (`specs/`) | "What is the contract? How do I implement it?" | Stable within a major version. |
| **Doc** (`docs/`) | "How do I use Flow? How does it work in practice?" | Updated as the code evolves. |

The flow of authority is:

```
Research → RFC → ADR → Spec → Implementation
```

A spec is born from an accepted ADR. The ADR records the decision; the spec defines the contract. An implementation conforms to the spec; it does not redefine the contract.

## Directory layout

```
specs/
├── README.md                         ← you are here
├── action-schema.json                ← the canonical Flow Action schema
├── timeline-extensions.md            ← Flow's extensions to OTIO
├── plugin-abi.md                     ← the C ABI for plugin authors
├── plugin-abi.h                      ← the C header (binding contract)
├── plugin-abi-bindings.rs            ← Rust extern definitions (binding contract)
├── mcp-surface.md                    ← the MCP tool/resource catalog
├── mcp-tools.json                    ← JSON Schemas for every MCP tool
├── mcp-resources.json                ← JSON Schemas for every MCP resource
├── project-format.md                 ← the on-disk format of a Flow project
└── contract-tests/                   ← executable conformance tests
    ├── action-schema.test.js         ← Node.js conformance
    ├── action-schema.test.py         ← Python conformance
    ├── action-schema.test.rs         ← Rust conformance
    ├── plugin-abi.test.c             ← C conformance (links a sample plugin)
    ├── mcp-surface.test.py           ← Python MCP client conformance
    └── ...
```

## Spec versioning

Every spec carries a version:

- **Major version** (e.g. `1`, `2`): breaking changes. Implementations targeting major version `N` cannot read data targeting major version `N+1` or `N-1`.
- **Minor version** (e.g. `1.0`, `1.1`): additive, backward-compatible changes. Implementations targeting minor version `1.0` can read data targeting `1.1`; implementations targeting `1.1` may not understand `1.0` (rare).
- **Patch version** (e.g. `1.0.0`, `1.0.1`): documentation fixes, no semantic change.

Specs declare their version in a `version` field at the top of the file:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://flow.dev/schemas/action.v1.json",
  "version": "1.0.0",
  "title": "Flow Action",
  ...
}
```

## Conformance

A spec is **executable**. Every spec ships with at least one conformance test in `contract-tests/`. To claim Flow-compliance, an implementation must:

1. Pass the relevant conformance tests.
2. Document which spec version it targets.
3. List any deviations in a `DEVIATIONS.md` file at the root of its repository.

The conformance tests are the spec. If a test passes but the spec says it should fail, the spec is wrong. If the spec says a test should pass but it fails, the implementation is wrong. The tests are never the source of truth — the spec is.

## Authority and evolution

When a spec is `Draft`, it can change. When it is `Accepted`, changes require:

- A new ADR documenting the change.
- A new major or minor version.
- A migration path for existing implementations.

Specs in `specs/` are always `Draft` until the corresponding ADR is `Accepted`. The README of each spec file declares its current status.

## How to read a spec

1. **Read the top-level comment** for the scope and the version.
2. **Read the example** to see the contract in use.
3. **Read the schema/code** for the precise definition.
4. **Run the conformance tests** to verify your understanding.
5. **Read the related RFC and ADR** for the rationale.

The example is the most important section. If the example is clear, the rest is mechanical.
