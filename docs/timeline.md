# Flow — Timeline

> Canonical timeline model based on OpenTimelineIO.

---

## 1. The Data Model

Flow uses **OTIO (OpenTimelineIO)** as its canonical timeline format. The in-memory representation maps directly to the OTIO schema:

```
Timeline
└── Stack
    ├── Track (Video)
    │   ├── Clip          ──ExternalReference──▶  Media
    │   ├── Transition
    │   ├── Clip
    │   └── Gap
    ├── Track (Video)
    │   └── ...
    └── Track (Audio)
        └── ...
```

## 2. Flow Extensions to OTIO

Flow extends OTIO via its SchemaDef plugin system:

- **`FlowOp.1`** — new schema types for AI operations (transcription, scene detection, segmentation)
- **`flow.llm.intent`** — metadata namespace storing the original LLM intent
- **`flow.confidence`** — confidence score for AI-generated edits
- **`flow.agent_id`** — identifier of the agent that produced the action

## 3. Time Model

OTIO's `RationalTime` is used directly:

```rust
pub struct RationalTime {
    value: i64,     // tick count
    rate: f64,      // ticks per second
}
```

- No floating-point drift across hours-long timelines
- `TimeRange = RationalTime (start) + RationalTime (duration)`
- Source time (original media) ↔ range time (timeline) are distinct

## 4. Project Persistence

A project on disk:

```
my-project/
├── timeline.otio       # Canonical timeline (current state)
├── actions.jsonl        # Append-only action log (source of truth)
├── media/               # Local media cache
├── renders/             # Output files
└── project.toml         # Metadata (name, fps, resolution)
```

The action log is the **source of truth**. The OTIO file is the **current state** (regenerated from the log on demand — like `git` regenerating the working tree).

## 5. Git-Like Operations

| Command | What it does |
|---|---|
| `flow project log` | Show action history |
| `flow project diff` | Diff two timeline states |
| `flow project checkout` | Restore to a prior state |
| `flow project commit` | Named checkpoint |
| `flow project branch` | Try an alternate plan |

## 6. The JSON Serialization

Flow actions serialize to JSON:

```json
{
  "id": "act_01HXY...",
  "project": "proj_01HXZ...",
  "actions": [
    {
      "op": "clip.trim",
      "clip": "clip_abc",
      "edge": "in",
      "to": { "value": 2.5, "rate": 30 }
    },
    {
      "op": "clip.set_effect",
      "clip": "clip_abc",
      "effect": "core.text.burn",
      "params": {
        "text": "HELLO",
        "start": { "value": 3, "rate": 30 },
        "duration": { "value": 2, "rate": 30 },
        "position": "center",
        "style": "bold-overlay"
      }
    },
    {
      "op": "render",
      "output": { "path": "out.mp4", "format": "mp4" },
      "preset": "tiktok-vertical-1080"
    }
  ]
}
```

## 7. Diff & Merge

Timeline diff is computed at the action level:

```
Action A: clip.trim(clip_abc, in, 2.5s)
Action B: clip.set_effect(clip_abc, core.text.burn, {...})
```

- Two timelines are identical if their action logs produce the same state
- Merge = apply actions from branch B onto branch A's latest state
- Conflicts arise when the same clip is modified in both branches
