# RFC 0001 — Runtime Architecture

| Field | Value |
|---|---|
| **Status** | Draft |
| **Author** | Flow Team |
| **Created** | 2026-07-17 |
| **Depends on** | — |

---

## Summary

Define the core runtime architecture of Flow: a typed, AI-native video execution engine built in Rust, wrapping FFmpeg for codec operations and ONNX Runtime for AI inference.

## Motivation

No existing video runtime combines typed effect graphs, AI-native effects, and an agent-facing API. We must build one.

## Design

### Layered Architecture

```
Action Layer    — validates & executes Flow Actions
Timeline Layer  — OTIO-based in-memory timeline
Engine Layer    — typed DAG of Effect nodes → FFmpeg filter graph
Media Layer     — probe, decode, encode via FFmpeg
Foundation      — memory pool, plugin loader, logging
```

### Key Decisions

1. **Rust** — memory safety, zero-cost FFI, strong type system
2. **Push model** for rendering (AI is async/batch, not pull like MLT)
3. **In-process FFmpeg** via `ffmpeg-sys-next` — never subprocess
4. **Two-phase plan → execute** — validate before touching media
5. **Frame refcounting** via `Arc<Buffer>` — zero-copy pass-through

### Threading Model

- One thread per render pipeline
- AI effects run on separate GPU streams
- Async frame iterator (`MediaReader::frames()`)
- Progress reported via channels (not polling)

## Alternatives Considered

- **C++ core** — more ecosystem, less safety. Rejected.
- **MLT as engine** — wrong threading model, no AI hooks. Rejected.
- **Subprocess FFmpeg** — cold start per op, no state. Rejected.

## Open Questions

- Should the effect graph support dynamic reconfiguration mid-render?
- How do we surface GPU memory pressure to the planner?

## Implementation Plan

1. Rust workspace scaffold
2. FFmpeg FFI bindings (smoke test: decode → encode)
3. OTIO in-memory timeline
4. Action executor + undo/redo
5. Effect graph with 5 built-in effects
6. ONNX Runtime integration (1 AI effect)
7. MCP server
