# specs/timeline/

# Flow Timeline Spec

This directory defines the **timeline data model** used by Flow. The model is built on top of **OpenTimelineIO (OTIO)** as the underlying schema, with Flow-specific extensions.

## Why OTIO

OTIO is the industry-standard editorial interchange format (Pixar/Disney/Netflix/ILM, ASWF). Flow adopts it because:

- It is the only format with native support in DaVinci Resolve, FCPX, Premiere, and Avid.
- Its schema (Timeline → Stack → Track → Clip/Gap/Transition/Marker) covers every NLE model.
- It has a plugin system (Adapters, MediaLinkers, SchemaDefs, HookScripts) that lets Flow extend without forking.
- It is JSON-serializable, human-readable, and git-friendly.
- It is Apache 2.0 licensed.

## Structure

```
timeline/
├── README.md                  ← you are here
├── otio-extensions.md         ← how Flow extends OTIO (metadata + SchemaDef)
├── effect-schema.json         ← JSON Schema for an OTIO Effect
├── marker-schema.json         ← JSON Schema for an OTIO Marker
└── transition-schema.json     ← JSON Schema for an OTIO Transition
```

## The OTIO schema (canonical reference)

The OTIO schema is defined by the OpenTimelineIO project at https://opentimelineio.readthedocs.io/. Flow does not redefine OTIO; it embeds it. The schemas in this directory describe Flow's **extensions** to OTIO, not OTIO itself.

The OTIO schema, at a glance:

```
Timeline
└── Stack
    ├── Track (Video)
    │   ├── Clip ── ExternalReference ── (target_url, available_range)
    │   ├── Transition
    │   ├── Clip
    │   └── Gap
    ├── Track (Video)
    └── Track (Audio)
```

For the full OTIO reference, see https://opentimelineio.readthedocs.io/en/latest/tutorials/otio-timeline-structure.html.

## Flow's extensions

Flow extends OTIO in two ways:

1. **Metadata keys** under the `flow.*` namespace. Lossless, no schema change.
2. **SchemaDef nodes** for AI-specific operations. Adds new node types to OTIO.

Both are documented in [`otio-extensions.md`](./otio-extensions.md).

## Conformance

A Flow runtime must accept any valid OTIO file and produce a Flow project from it. A Flow project must round-trip through OTIO (minus Flow-specific extensions, which are preserved as metadata).

The conformance test (`contract-tests/timeline/`) reads OTIO sample files, runs them through Flow, and verifies the output is equivalent.
