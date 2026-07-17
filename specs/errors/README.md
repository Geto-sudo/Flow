# specs/errors/

# Flow Error Catalog

This directory defines **every error that Flow can return**. Errors are the single most fragile part of an API: if a caller does not know what an error means, the system is unusable. The catalog is the source of truth.

## Why errors deserve their own spec

Most APIs treat errors as afterthoughts. Flow treats them as a first-class contract:

- Every error has a **stable code** (e.g. `FLOW_001`).
- Every error has a **structured shape** (machine-readable + human-readable).
- Every error has a **recovery hint** (what the caller should do).
- Every error is **documented** (when it occurs, why, what to do).
- Every error is **testable** (conformance tests assert that the right code is returned for the right failure).

An agent that drives Flow does not need to guess what `Error: invalid state` means. It reads the code, looks it up in the catalog, and acts.

## Structure

```
errors/
├── README.md                  ← you are here
├── error-codes.md             ← the full catalog of FLOW_xxx codes
└── error-schema.json          ← JSON Schema for an error response
```

The catalog is a flat list. The schema is a JSON Schema describing the shape of an error response (used for validation, not for the codes themselves).

## Error shape

Every Flow error has the following shape:

```json
{
  "code": "FLOW_001",
  "name": "TimelineNotFound",
  "category": "validation",
  "severity": "error",
  "message": "Timeline not found: proj_abc...",
  "details": {
    "timeline_id": "proj_abc..."
  },
  "hint": "Check the project ID. Use flow.project.list to see available projects.",
  "documentation_url": "https://flow.dev/errors/FLOW_001",
  "retryable": false,
  "cause": null
}
```

| Field | Type | Description |
|---|---|---|
| `code` | string | Stable, machine-readable error code (e.g. `FLOW_001`). |
| `name` | string | Human-readable name (e.g. `TimelineNotFound`). |
| `category` | enum | One of: `validation`, `runtime`, `io`, `plugin`, `auth`, `internal`. |
| `severity` | enum | One of: `info`, `warning`, `error`, `fatal`. |
| `message` | string | One-line human-readable description. Localizable. |
| `details` | object | Structured context. Schema depends on the error. |
| `hint` | string | One-line actionable suggestion. |
| `documentation_url` | string | Link to the full documentation. |
| `retryable` | boolean | Whether the caller can retry the same operation. |
| `cause` | object or null | The underlying error, if any (chained errors). |

## Error code ranges

| Range | Category | Description |
|---|---|---|
| `FLOW_001`–`FLOW_099` | Validation | The input was malformed, referentially inconsistent, or precondition-violating. |
| `FLOW_100`–`FLOW_199` | Runtime | The action is valid but the operation failed (decode error, GPU OOM, etc.). |
| `FLOW_200`–`FLOW_299` | IO | File, network, or storage error. |
| `FLOW_300`–`FLOW_399` | Plugin | A plugin failed to load, crashed, or returned invalid data. |
| `FLOW_400`–`FLOW_499` | Auth | Authentication or authorization failure. |
| `FLOW_500`–`FLOW_599` | Internal | Unexpected internal error. Bug in Flow. |

## Versioning

Error codes are **stable forever**. Once `FLOW_001` is assigned, it always means the same thing. New errors get new codes. The catalog grows monotonically.

Deprecated codes are kept in the catalog with a `deprecated: true` flag. They are not removed.

## Conformance

A conformance test (`contract-tests/errors/`) reads the catalog and asserts that:

- Every declared code is documented.
- Every declared code has a `hint` field.
- The `error-schema.json` is consistent with the catalog.
- The runtime returns the right code for the right failure (sample tests).

A runtime passes conformance if it returns the correct code for at least 95% of the codes in the catalog, with the remaining 5% allowed as `not_yet_implemented` (for v1 only).
