# specs/mcp-surface.md

# Flow MCP Surface — Version 1

| Field | Value |
|---|---|
| **Spec version** | 1.0.0 |
| **Status** | Draft |
| **Source ADRs** | [ADR-0008 (MCP as Primary Agent Interface)](../adrs/0008-mcp-agent-interface.md) |
| **Source RFCs** | [RFC-0006 (MCP Integration)](../rfcs/core/0006-mcp.md) |

This spec defines the **MCP (Model Context Protocol) surface** exposed by a Flow server. It is the contract between any MCP-aware agent and Flow. An agent that supports MCP can drive Flow without writing any Flow-specific code.

## Transport

The Flow MCP server supports two transports:

- **stdio** — for subprocess-based agents (Claude Desktop, VS Code Cline, Hermes).
- **HTTP** — for remote agents and web clients. Endpoint: `POST /mcp` with `Content-Type: application/json`.

Both transports implement JSON-RPC 2.0 over the wire, as specified by the MCP spec.

## Tools

The server exposes **18 tools**, organized into 5 categories.

### Media

#### `flow.media.probe`

Get metadata about a media file.

**Input schema** ([`mcp-tools.json#/flow.media.probe`](./mcp-tools.json)):

```json
{
  "path": "string (required, absolute path or media:// URL)"
}
```

**Output**:

```json
{
  "duration": { "value": 1800, "rate": 30 },
  "video": {
    "width": 1920, "height": 1080, "codec": "h264", "fps": 30,
    "color_space": "bt709", "color_range": "tv", "pixel_format": "yuv420p"
  },
  "audio": {
    "sample_rate": 48000, "channels": 2, "codec": "aac"
  },
  "bit_rate": 5000000,
  "container": "mp4",
  "checksum": "sha256:abc123..."
}
```

#### `flow.media.list`

List media files in a directory.

**Input**:

```json
{ "dir": "string (required, absolute path)" }
```

**Output**:

```json
{
  "items": [
    { "name": "interview.mp4", "path": "/abs/path/interview.mp4", "size": 52428800, "mtime": "2026-07-17T00:00:00Z" }
  ]
}
```

### Project

#### `flow.project.create`

Create a new project.

**Input**:

```json
{
  "path": "string (required, absolute path to project directory)",
  "spec": {
    "name": "string",
    "fps": 30.0,
    "resolution": { "width": 1920, "height": 1080 }
  }
}
```

**Output**: `{ "project_id": "string" }`

#### `flow.project.list`

List all projects on the server.

**Input**: `{}`

**Output**: `{ "projects": [{ "id": "string", "name": "string", "path": "string" }] }`

#### `flow.project.log`

Show the action history of a project.

**Input**: `{ "project_id": "string", "limit": "integer (default 50)", "since": "string (ISO 8601, optional)" }`

**Output**: `{ "entries": [{ "id": "string", "ts": "string", "actor": "string", "intent": "string", "action": {...} }] }`

#### `flow.project.diff`

Diff two timeline states.

**Input**: `{ "project_id": "string", "from_action_id": "string", "to_action_id": "string" }`

**Output**: `{ "diff": { "added": [...], "removed": [...], "modified": [...] } }`

#### `flow.project.checkout`

Restore a project to a prior state (creates a new action that reverts to it).

**Input**: `{ "project_id": "string", "action_id": "string" }`

**Output**: `{ "reverted_to": "string", "new_action_id": "string" }`

#### `flow.project.branch`

Create a named branch at the current state.

**Input**: `{ "project_id": "string", "name": "string" }`

**Output**: `{ "branch_name": "string" }`

### Timeline

#### `flow.timeline.get`

Get the current timeline as OTIO JSON.

**Input**: `{ "project_id": "string", "ref": "string (optional, action_id or branch_name)" }`

**Output**: `{ "otio": { ... OTIO JSON ... } }`

#### `flow.timeline.apply`

Apply an action or batch of actions.

**Input**: `{ "project_id": "string", "action": { ... Flow Action ... } }`

**Output**: `{ "action_id": "string", "state_hash": "string", "warnings": ["string"] }`

#### `flow.timeline.plan`

Validate an action without applying it. Returns a plan with cost estimates.

**Input**: `{ "project_id": "string", "action": { ... Flow Action ... } }`

**Output**:

```json
{
  "plan_id": "string",
  "valid": true,
  "actions_count": 3,
  "media_refs": 2,
  "estimated_time_seconds": 37,
  "estimated_gpu_memory_mb": 2400,
  "estimated_output_size_mb": 45,
  "steps": [
    { "action": "clip.trim", "description": "Trim clip_abc from 2.5s" }
  ],
  "warnings": []
}
```

### Render

#### `flow.render.start`

Start a render job.

**Input**: `{ "project_id": "string", "output": { "path": "string", "format": "string" }, "preset": "string", "range": { "start_time": {...}, "duration": {...} } }`

**Output**: `{ "job_id": "string" }`

#### `flow.render.status`

Get the status of a render job.

**Input**: `{ "job_id": "string" }`

**Output**:

```json
{
  "job_id": "string",
  "status": "running | completed | failed | cancelled",
  "progress": {
    "stage": "string",
    "percent": 42.5,
    "current_frame": 1250,
    "total_frames": 3000,
    "eta_seconds": 12
  },
  "started_at": "string",
  "finished_at": "string (if completed)"
}
```

#### `flow.render.wait`

Block until a render job completes.

**Input**: `{ "job_id": "string", "timeout_seconds": 600 (default) }`

**Output**: same as `flow.render.status`, with `status: "completed | failed | cancelled"`.

#### `flow.render.artifacts`

List the output files of a completed render.

**Input**: `{ "job_id": "string" }`

**Output**: `{ "artifacts": [{ "path": "string", "size": 0, "checksum": "string" }] }`

#### `flow.render.cancel`

Cancel a running render job.

**Input**: `{ "job_id": "string" }`

**Output**: `{ "cancelled": true }`

### Effects

#### `flow.effects.list`

List all available effects.

**Input**: `{ "category": "string (optional, e.g. 'video', 'audio', 'ai')" }`

**Output**:

```json
{
  "effects": [
    {
      "id": "core.cut",
      "name": "Cut",
      "category": "video",
      "is_ai": false,
      "description": "Cut a clip at a point."
    }
  ]
}
```

#### `flow.effects.describe`

Get the full schema and documentation for an effect.

**Input**: `{ "effect_id": "string" }`

**Output**:

```json
{
  "id": "core.cut",
  "name": "Cut",
  "category": "video",
  "is_ai": false,
  "description": "...",
  "param_schema": { ... JSON Schema ... },
  "inputs": [{ "name": "in", "kind": "video" }],
  "outputs": [{ "name": "out", "kind": "video" }],
  "example_params": { ... }
}
```

## Resources

The server exposes **6 resources**, all read-only.

| URI | MIME type | Content |
|---|---|---|
| `flow://project/{id}/timeline` | `application/x-otio+json` | The current timeline as OTIO JSON. |
| `flow://project/{id}/timeline?ref={ref}` | `application/x-otio+json` | The timeline at a checkpoint or branch. |
| `flow://project/{id}/media` | `application/json` | The media references in the project. |
| `flow://effects/{id}` | `application/json` | The full schema and documentation of an effect. |
| `flow://presets/{id}` | `application/json` | The spec of a render preset. |
| `flow://schemas/{schema_name}` | `application/schema+json` | A raw JSON Schema (action, timeline, effect, media, project). |

Resources are subscribable: a client that subscribes to `flow://project/{id}/timeline` receives a notification when the timeline changes.

## Prompts

The server exposes **6 prompts** to guide agent behavior.

| Prompt | Parameters | Description |
|---|---|---|
| `flow.quickstart` | — | Introduction to using Flow as an agent. |
| `flow.trim` | `{ clip_id, edge, to }` | Step-by-step guide for trimming a clip. |
| `flow.transcribe` | `{ clip_id, language }` | Guide for AI-powered transcription. |
| `flow.upscale` | `{ clip_id, scale, model }` | Guide for AI super-resolution. |
| `flow.debug.render_failure` | `{ job_id }` | "A render failed. Here's how to diagnose it." |
| `flow.collaborate` | — | Protocol for working with other agents on the same project. |

## Error handling

Errors follow the JSON-RPC 2.0 standard error codes:

| Code | Meaning | When |
|---|---|---|
| `-32700` | Parse error | Malformed JSON received. |
| `-32600` | Invalid request | Wrong request shape. |
| `-32601` | Method not found | Unknown tool. |
| `-32602` | Invalid params | Stage 1 (schema) error in the action. |
| `-32603` | Internal error | Stage 2 (semantic) or Stage 3 (precondition) error in the action. |
| `-32000` to `-32099` | Server error | Runtime errors, render failures, OOM, etc. |

Error responses include a `data` field with a structured Flow error:

```json
{
  "code": -32602,
  "message": "Invalid params",
  "data": {
    "flow_error_code": "SchemaValidation",
    "instance_path": "/actions/0/to",
    "schema_path": "/properties/to/type",
    "message": "expected object, got number"
  }
}
```

## Conformance

The conformance test suite is in [`contract-tests/mcp-surface/`](../contract-tests/mcp-surface/). It includes:

- A reference server (`ref-server.py`) that implements the full surface.
- A test driver (`test-driver.py`) that connects via MCP, calls every tool, reads every resource, and validates the responses.
- A schema test (`test-schemas.py`) that verifies every tool's input/output schema against the JSON Schemas in `mcp-tools.json`.
- An error test (`test-errors.py`) that verifies the server returns the right error codes for the right failures.

A server passes conformance if all tests pass and the JSON Schemas in its responses are valid.
