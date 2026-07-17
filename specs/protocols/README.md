# specs/protocols/

# Flow Protocol Specs

This directory defines the **wire protocols** used by Flow. The primary protocol is **MCP (Model Context Protocol)**, which is how AI agents interact with Flow.

## Why MCP

MCP is the cross-vendor standard for agent-tool communication. It is supported by Claude, GPT (via plugins), Gemini, Cursor, Codex, and the open-source ecosystem. By speaking MCP natively, Flow plugs into the existing agent ecosystem without requiring custom clients.

## Structure

```
protocols/
├── README.md                  ← you are here
├── mcp-surface.md             ← the catalog of MCP tools, resources, and prompts
├── mcp-tools.json             ← JSON Schemas for every MCP tool
├── mcp-resources.json         ← JSON Schemas for every MCP resource
├── mcp-prompts.md             ← the catalog of MCP prompts
├── http-api.md                ← the non-MCP HTTP API (for human-facing tools)
└── streaming.md               ← the WebSocket streaming protocol for progress
```

## Transports

Flow supports two MCP transports:

- **stdio** — for subprocess-based agents.
- **HTTP** — for remote agents. Endpoint: `POST /mcp`.

Both implement JSON-RPC 2.0 over the wire, as specified by MCP.

## Non-MCP surfaces

For non-agent use cases (humans, scripts, web UIs), Flow also exposes:

- **REST HTTP** — for one-shot operations. See [`http-api.md`](./http-api.md).
- **WebSocket** — for streaming progress and events. See [`streaming.md`](./streaming.md).

These are conveniences, not the primary surface. The agent surface is MCP.

## Conformance

A conformance test (`contract-tests/protocols/`) connects to a Flow server via MCP and verifies:

- Every tool listed in [`mcp-surface.md`](./mcp-surface.md) is callable.
- Every resource is readable.
- Every prompt is available.
- Errors return the right codes (per `../errors/error-codes.md`).
- Streaming progress events arrive in order.
