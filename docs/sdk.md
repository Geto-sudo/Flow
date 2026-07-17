# Flow — SDK

> The developer surfaces: Python, CLI, Web, and Schemas.

---

## 1. flow-script (Python — LLM-Facing)

The primary API that LLM agents call. MoviePy-like fluency, backed by Flow's native runtime.

```python
from flow import Video, Audio, Text, Effect, Project

# Build a timeline with a fluent API
clip = (
    Video("interview.mp4")
    .trim(5, 15)
    .resize(1080, 1920)
    .set_audio(Audio("music.mp3").volume(0.3).duck_under(clip))
    + Text("Hello").at("center").duration(2)
    + Effect("ai.upscale", scale=2)
)

# Validate + plan
plan = clip.plan()
print(plan)  # human-readable description

# Execute
job = clip.render(output="out.mp4", preset="tiktok")
job.wait()
```

### Design Principles

- **Operator overloading**: `+` = composite, `|` = concatenate, `*` = loop
- **Immutable nodes**: every method returns a new node
- **Effects as functions**: `clip.fx(vfx.resize, width=480)`
- **Serializable**: every expression compiles to a Flow Action JSON
- **Dual-mode**: local (`flow-core` in-process) or remote (`flow-server` over HTTP)

### Architecture

```
┌─────────────────────────────────────┐
│   flow-script (Python)              │  ← LLM-facing, MoviePy-like
│   fluent API, operators, easy       │
└────────────────┬────────────────────┘
                 │  compiles to Flow Action JSON
                 ▼
┌─────────────────────────────────────┐
│   flow-core (Rust)                  │  ← Execution engine
│   OTIO timeline → render graph      │
│   filter graph → FFmpeg/native      │
└─────────────────────────────────────┘
```

## 2. flow-cli (Rust — Local)

Thin wrapper around `flow-core`.

| Command | Description |
|---|---|
| `flow plan <action.json>` | Validate and preview |
| `flow run <action.json>` | Execute, write output |
| `flow probe <media>` | Print media metadata |
| `flow transcribe <media>` | Extract audio + transcribe |
| `flow project new / open / close` | Manage local projects |
| `flow project log` | Show action history |
| `flow project diff` | Diff two versions |
| `flow project commit` | Named checkpoint |
| `flow project branch` | Try alternate plan |
| `flow server start` | Spawn `flow-server` |
| `flow effects list` | List installed effects |
| `flow plugin check` | Validate installed plugins |

## 3. flow-web (TypeScript — Browser)

Optional browser SDK for web-based agents.

```typescript
import { FlowClient } from "@flow/web";

const client = new FlowClient("http://localhost:8080");

// Build action
const action = {
  op: "clip.trim",
  clip: "clip_abc",
  edge: "in",
  to: { value: 2.5, rate: 30 }
};

// Execute via MCP or HTTP
const result = await client.execute(action);
```

## 4. JSON Schemas (Source of Truth)

All schemas live in `schemas/`:

| Schema | Description |
|---|---|
| `action.schema.json` | Flow Action structure |
| `timeline.schema.json` | OTIO with Flow extensions |
| `effect.schema.json` | Effect definitions |
| `media.schema.json` | Media references |

Schemas are the **canonical contract** between layers. The LLM is trained to produce valid action JSON. The runtime validates against the schema before execution.

## 5. SDK Language Support

| Layer | Language | Status |
|---|---|---|
| `flow-core` | Rust (C FFI) | v1 |
| `flow-cli` | Rust | v1 |
| `flow-server` | Rust | v1 |
| `flow-script` | Python 3.10+ | v1 |
| `flow-web` | TypeScript 5+ | v2 |
