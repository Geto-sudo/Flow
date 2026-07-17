# Flow OTIO Extensions

| Field | Value |
|---|---|
| **Spec version** | 1.0.0 |
| **Status** | Draft |
| **Source RFCs** | RFC-0004 (Timeline Model) |
| **Source ADRs** | ADR-0002 (OTIO as Canonical Timeline) |

Flow extends OTIO in two ways:

1. **Metadata keys** under the `flow.*` namespace. Lossless, round-trippable through any OTIO reader.
2. **SchemaDef nodes** for AI-specific operations. Adds new node types via OTIO's plugin system.

Both extensions are designed to be **non-disruptive**: an OTIO reader that does not understand Flow extensions ignores them, and a Flow project loaded by a non-Flow tool still parses correctly.

## Metadata extensions

Every OTIO node has a `metadata` field (free-form JSON). Flow uses the following well-known keys:

| Key | Type | Where | Description |
|---|---|---|---|
| `flow.schema_version` | integer | Timeline | The Flow project schema version (1 for v1). |
| `flow.llm.intent` | string | Timeline, Clip | The free-text intent of the LLM that created this node. |
| `flow.llm.confidence` | number | Clip, Effect | The LLM's confidence in this decision (0.0 to 1.0). |
| `flow.llm.agent_id` | string | Timeline, Clip | The identifier of the agent that created this node. |
| `flow.llm.reasoning_trace` | string | Clip, Effect | The LLM's reasoning (chain of thought) that led to this decision. |
| `flow.user.id` | string | Clip, Effect | The user who approved this node (for human-in-the-loop). |
| `flow.user.approved_at` | string | Clip, Effect | ISO 8601 timestamp of approval. |
| `flow.action.id` | string | Clip, Effect | The action ID that created this node (links to `actions.jsonl`). |
| `flow.checkpoint.id` | string | Timeline | The checkpoint ID this state corresponds to. |
| `flow.tags` | array of string | Any | Free-form tags. |

### Example

```json
{
  "OTIO_SCHEMA": "Clip.1",
  "name": "interview_01",
  "metadata": {
    "flow": {
      "schema_version": 1,
      "llm_intent": "trim the boring intro",
      "llm_confidence": 0.87,
      "llm_agent_id": "claude-sonnet-4.5",
      "llm_reasoning_trace": "The user said 'cut the intro'; I trimmed 3s from the in-edge.",
      "action_id": "act_aabbccdd00112233aabbccdd00112233"
    }
  },
  "source_range": { /* ... */ },
  "media_reference": { /* ... */ }
}
```

## SchemaDef extensions

For Flow-specific **node types** (not just metadata), Flow registers new OTIO schemas via OTIO's SchemaDef plugin system. The first set of SchemaDef nodes:

| SchemaDef | Type | Purpose |
|---|---|---|
| `FlowAIOp.1` | Clip effect | An AI operation (transcription, scene detection, etc.) attached to a clip. |
| `FlowRenderPreset.1` | Marker | A named render preset. |
| `FlowPlan.1` | Timeline | A pre-execution plan (cost estimate, validation result). |

### `FlowAIOp.1`

```python
@register_schema_def
class FlowAIOp(SerializableObject):
    """An AI operation attached to a clip."""

    _schema_name = "FlowAIOp"
    _schema_version = 1

    def __init__(self, op_name, model_id, params, confidence=None):
        self.op_name = op_name        # e.g. "ai.upscale"
        self.model_id = model_id       # e.g. "real-esrgan-x4plus"
        self.params = params           # dict of operation-specific params
        self.confidence = confidence  # optional, 0.0-1.0
```

Serialized form:

```json
{
  "OTIO_SCHEMA": "FlowAIOp.1",
  "op_name": "ai.upscale",
  "model_id": "real-esrgan-x4plus",
  "params": { "scale": 2 },
  "confidence": 0.92
}
```

In a Flow project, `FlowAIOp` is attached to a Clip's `effects` list:

```json
{
  "OTIO_SCHEMA": "Clip.1",
  "name": "interview_01",
  "effects": [
    {
      "OTIO_SCHEMA": "Effect.1",
      "effect_name": "ai.upscale",
      "metadata": { "flow": { "schema_def": "FlowAIOp.1" } },
      "FlowAIOp": {
        "op_name": "ai.upscale",
        "model_id": "real-esrgan-x4plus",
        "params": { "scale": 2 }
      }
    }
  ]
}
```

## Rationale

We chose metadata + SchemaDef rather than a parallel Flow-specific format because:

- **Metadata is lossless.** Any OTIO reader can load a Flow project; the Flow-specific keys are just opaque JSON to it.
- **SchemaDef is type-safe.** When a Flow-specific node is used, the schema is validated; the data is not just an opaque blob.
- **OTIO is the interchange format.** When a Flow project is shared with a non-Flow tool (DaVinci, Resolve, custom scripts), it loads as a valid OTIO file. The Flow-specific bits are visible in `metadata` and `Flow*` fields but do not break the file.

## Conformance

A conformance test (`contract-tests/timeline/`) verifies that:

- A Flow project round-trips through OTIO (the timeline + metadata is preserved).
- The `flow.*` metadata keys are preserved.
- A non-Flow OTIO reader can load a Flow project (the file is valid OTIO, the Flow-specific fields are ignored).
- `FlowAIOp` nodes are loaded correctly when the Flow extension is registered.
