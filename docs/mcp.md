# Flow — MCP Surface

> The Model Context Protocol interface for AI agents.

---

## 1. What is MCP?

The [Model Context Protocol](https://modelcontextprotocol.io) is an open standard that lets LLM applications (Claude, GPT, Gemini) discover and call tools, read resources, and receive prompts from a server. Flow exposes its entire action surface over MCP, making it **natively callable by AI agents** without any custom glue code.

## 2. MCP Server

`flow-server` exposes an MCP endpoint at `/mcp`.

```
flow-server
  ├── HTTP (REST) — POST /v1/actions, GET /v1/jobs/:id
  ├── WebSocket — WS /v1/jobs/:id/stream
  └── MCP       — /mcp
```

## 3. Tools

Tools are the primary way agents drive Flow.

### Media

| Tool | Description |
|---|---|
| `flow.media.probe(path)` | Get media info (codec, resolution, duration) |
| `flow.media.list(path)` | List media files in a directory |

### Project

| Tool | Description |
|---|---|
| `flow.project.create(name)` | Create a new project |
| `flow.project.list()` | List all projects |
| `flow.project.log(id)` | Show action history |
| `flow.project.diff(id, before, after)` | Diff two timeline states |
| `flow.project.checkout(id, ref)` | Restore a prior state |
| `flow.project.branch(id, name)` | Create a branch |

### Timeline

| Tool | Description |
|---|---|
| `flow.timeline.get(project_id)` | Get current timeline as OTIO JSON |
| `flow.timeline.apply(project_id, action)` | Apply an action, return new timeline |
| `flow.timeline.plan(project_id, action)` | Validate without applying |

### Render

| Tool | Description |
|---|---|
| `flow.render.start(project_id, action)` | Start a render, return job ID |
| `flow.render.status(job_id)` | Poll job status |
| `flow.render.wait(job_id)` | Wait for completion |
| `flow.render.artifacts(job_id)` | List output files |
| `flow.render.cancel(job_id)` | Cancel a running render |

### Effects

| Tool | Description |
|---|---|
| `flow.effects.list()` | List all installed effects |
| `flow.effects.describe(effect_id)` | Get effect schema + docs |

## 4. Resources

Resources provide structured data that LLMs can read.

| URI | Description |
|---|---|
| `flow://project/{id}/timeline` | Current OTIO JSON |
| `flow://project/{id}/timeline?ref={ref}` | Timeline at a checkpoint |
| `flow://project/{id}/media` | Media references in the project |
| `flow://effects/{id}` | Effect schema + documentation |
| `flow://presets/{id}` | Render preset specification |
| `flow://schemas/{schema_name}` | Raw JSON Schema |

## 5. Example MCP Session

```
Agent connects to flow-server via MCP
  │
  ├── tools.call("flow.media.probe", { path: "interview.mov" })
  │   └── returns { codec: "h264", resolution: "3840x2160", duration: 842 }
  │
  ├── tools.call("flow.project.create", { name: "My Edit" })
  │   └── returns { project_id: "proj_01HXZ..." }
  │
  ├── tools.call("flow.timeline.apply", {
  │     project_id: "proj_01HXZ...",
  │     action: { op: "clip.add", ... }
  │   })
  │   └── returns { timeline: { ... }, actions_applied: 1 }
  │
  ├── resources.read("flow://project/proj_01HXZ.../timeline")
  │   └── returns OTIO JSON
  │
  └── tools.call("flow.render.start", { project_id: "proj_01HXZ...", ... })
      └── returns { job_id: "job_01HYA...", estimated_time: "37s" }
```

## 6. Why MCP for Flow?

| Without MCP | With MCP |
|---|---|
| Agent must write Python/curl | Agent calls tools natively |
| Custom tool wrapper per LLM | One MCP server works for all |
| No schema discovery | Schemas are resources |
| No progress streaming | WebSocket + MCP streaming |
| Every agent reimplements the same glue | Plug and play |

MCP is the difference between "Flow is a library" and "Flow is natively callable by any AI agent."
