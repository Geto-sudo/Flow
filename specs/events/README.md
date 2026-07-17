# specs/events/

# Flow Event Catalog

This directory defines **every event that Flow can emit**. Events are how Flow communicates state changes to observers: UIs, orchestrators, and agents. Without a stable event catalog, an agent has no way to know that a clip was added, a render finished, or an AI inference completed.

## Why events deserve their own spec

A Flow runtime is stateful. An agent (or a UI, or another service) observing that state needs to know **what changed** and **when**. Polling is possible but wasteful. Events are the answer.

The event catalog is the contract between Flow and its observers. It defines:

- The **types** of events that can occur.
- The **shape** of each event payload.
- The **delivery guarantees** (at-least-once, ordering, retention).
- The **subscription model** (where events are surfaced — MCP, WebSocket, log).

## Structure

```
events/
├── README.md                  ← you are here
├── event-codes.md             ← the full catalog of FLOW_EVT_xxx codes
└── event-schema.json          ← JSON Schema for an event payload
```

The catalog is a flat list. The schema is the shape of an event.

## Event shape

Every Flow event has the following shape:

```json
{
  "id": "evt_0123456789abcdef0123456789abcdef",
  "ts": "2026-07-17T04:00:00.123Z",
  "code": "FLOW_EVT_001",
  "name": "ClipCreated",
  "category": "lifecycle",
  "project_id": "proj_0123456789abcdef0123456789abcdef",
  "actor": "agent:claude-sonnet-4.5",
  "action_id": "act_0123456789abcdef0123456789abcdef",
  "data": {
    "clip_id": "clip_...",
    "track_id": "V1",
    "at": { "value": 0, "rate": 30 }
  },
  "metadata": {}
}
```

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique event ID (UUID v7). |
| `ts` | string | Timestamp of the event, ISO 8601 UTC, with millisecond precision. |
| `code` | string | Stable event code (e.g. `FLOW_EVT_001`). |
| `name` | string | Human-readable name (e.g. `ClipCreated`). |
| `category` | enum | One of: `lifecycle`, `progress`, `error`, `system`. |
| `project_id` | string | The project the event relates to. May be empty for global events. |
| `actor` | string | Who triggered the event (agent, user, plugin, system). |
| `action_id` | string | The action that triggered the event, if any. |
| `data` | object | Event-specific payload. |
| `metadata` | object | Free-form metadata. |

## Event code ranges

| Range | Category | Description |
|---|---|---|
| `FLOW_EVT_001`–`099` | Lifecycle | A resource was created, modified, or deleted. |
| `FLOW_EVT_100`–`199` | Progress | A long-running operation is making progress. |
| `FLOW_EVT_200`–`299` | Error | An error occurred. |
| `FLOW_EVT_300`–`399` | System | Runtime-level events (startup, shutdown, config reload). |

## Delivery

Events are delivered via:

- **MCP notifications** — `notifications/event` for connected MCP clients.
- **WebSocket stream** — `GET /v1/projects/{id}/events` for HTTP clients.
- **Log file** — structured JSON log of all events.

Delivery is **at-least-once**. Events may be re-delivered after a reconnect. Consumers must deduplicate by `event.id`.

Ordering is **causal** within a project: if event A's action was applied before event B's action, A is delivered before B. There is no global ordering across projects.

## Versioning

Event codes are stable forever. The `data` shape of an event may grow additively within a major version. Removing fields requires a new major version.

## Conformance

A conformance test (`contract-tests/events/`) reads the catalog and asserts that:

- Every declared event is documented.
- Every declared event has a `data` schema.
- The runtime emits the right events for the right actions (sample tests).

A runtime passes if it emits the right events for at least 90% of the lifecycle events in the catalog, with the remaining 10% allowed as `not_yet_implemented` (for v1 only).
