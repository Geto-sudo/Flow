# Flow Event Codes

| Field | Value |
|---|---|
| **Spec version** | 1.0.0 |
| **Status** | Draft |
| **Source RFCs** | RFC-0003 (Action System), RFC-0006 (MCP) |

This is the **complete catalog of Flow event codes**. Every code is stable, documented, and testable. Events are how Flow communicates state changes to observers.

Conventions:

- `code` — the stable machine code (`FLOW_EVT_xxx`).
- `name` — human-readable name (PascalCase).
- `category` — lifecycle, progress, error, system.
- `trigger` — the action or condition that causes the event to be emitted.

---

## Lifecycle (FLOW_EVT_001–099)

State changes caused by actions.

| Code | Name | Trigger |
|---|---|---|
| `FLOW_EVT_001` | `ProjectCreated` | `project.create` action succeeded. |
| `FLOW_EVT_002` | `ProjectOpened` | A project was opened by a client. |
| `FLOW_EVT_003` | `ProjectClosed` | A project was closed. |
| `FLOW_EVT_004` | `ProjectDeleted` | `project.delete` action succeeded. |
| `FLOW_EVT_005` | `ProjectSaved` | A project was saved to disk. |
| `FLOW_EVT_006` | `CheckpointCreated` | A checkpoint was created. |
| `FLOW_EVT_010` | `TimelineUpdated` | Any timeline mutation succeeded. Fires for every action. |
| `FLOW_EVT_011` | `TimelineSetFps` | `timeline.set_fps` action succeeded. |
| `FLOW_EVT_012` | `TimelineSetResolution` | `timeline.set_resolution` action succeeded. |
| `FLOW_EVT_020` | `TrackCreated` | `track.add` action succeeded. |
| `FLOW_EVT_021` | `TrackRemoved` | `track.remove` action succeeded. |
| `FLOW_EVT_022` | `TrackRenamed` | `track.rename` action succeeded. |
| `FLOW_EVT_023` | `TrackReordered` | `track.reorder` action succeeded. |
| `FLOW_EVT_030` | `ClipCreated` | `clip.add` action succeeded. |
| `FLOW_EVT_031` | `ClipRemoved` | `clip.remove` action succeeded. |
| `FLOW_EVT_032` | `ClipTrimmed` | `clip.trim` action succeeded. |
| `FLOW_EVT_033` | `ClipMoved` | `clip.move` action succeeded. |
| `FLOW_EVT_034` | `ClipSplit` | `clip.split` action succeeded. |
| `FLOW_EVT_035` | `ClipReplaced` | `clip.replace` action succeeded. |
| `FLOW_EVT_036` | `ClipSpeedChanged` | `clip.set_speed` action succeeded. |
| `FLOW_EVT_037` | `ClipEnabledChanged` | `clip.set_enabled` action succeeded. |
| `FLOW_EVT_040` | `EffectAdded` | `effect.add` action succeeded. |
| `FLOW_EVT_041` | `EffectRemoved` | `effect.remove` action succeeded. |
| `FLOW_EVT_042` | `EffectParamChanged` | `effect.set_param` action succeeded. |
| `FLOW_EVT_050` | `MarkerAdded` | `marker.add` action succeeded. |
| `FLOW_EVT_051` | `MarkerRemoved` | `marker.remove` action succeeded. |
| `FLOW_EVT_060` | `AssetAdded` | `asset.add` action succeeded. |
| `FLOW_EVT_061` | `AssetRemoved` | `asset.remove` action succeeded. |
| `FLOW_EVT_062` | `AssetResolved` | A media reference was successfully resolved to a local path. |
| `FLOW_EVT_063` | `AssetMissing` | A media reference could not be resolved (now in `MissingReference` state). |
| `FLOW_EVT_070` | `ActionUndone` | `undo` action succeeded. |
| `FLOW_EVT_071` | `ActionRedone` | `redo` action succeeded. |
| `FLOW_EVT_072` | `ActionRejected` | An action was rejected by validation. The action is not in the history. |

## Progress (FLOW_EVT_100–199)

Long-running operation progress.

| Code | Name | Trigger |
|---|---|---|
| `FLOW_EVT_100` | `JobStarted` | A render or AI job started. |
| `FLOW_EVT_101` | `JobProgress` | A job reported progress. May be emitted many times per job. |
| `FLOW_EVT_102` | `JobStageChanged` | A job transitioned between stages (decoding, compositing, encoding, muxing). |
| `FLOW_EVT_103` | `JobCompleted` | A job completed successfully. |
| `FLOW_EVT_104` | `JobFailed` | A job failed. |
| `FLOW_EVT_105` | `JobCancelled` | A job was cancelled. |
| `FLOW_EVT_110` | `DecodeProgress` | A media file is being decoded (long files only). |
| `FLOW_EVT_111` | `EncodeProgress` | A media file is being encoded. |
| `FLOW_EVT_120` | `AiInferenceStarted` | An AI inference started. |
| `FLOW_EVT_121` | `AiInferenceProgress` | An AI inference reported progress. |
| `FLOW_EVT_122` | `AiInferenceCompleted` | An AI inference completed. |

## Error (FLOW_EVT_200–299)

Errors emitted as events (in addition to being returned from the action that caused them).

| Code | Name | Trigger |
|---|---|---|
| `FLOW_EVT_200` | `ActionFailed` | An action failed validation or execution. |
| `FLOW_EVT_201` | `PluginCrashed` | A plugin crashed during processing. |
| `FLOW_EVT_202` | `GpuOutOfMemory` | A GPU device ran out of memory. |
| `FLOW_EVT_203` | `NetworkFailure` | A network operation failed. |
| `FLOW_EVT_204` | `DiskFull` | The disk is full. |
| `FLOW_EVT_205` | `InternalError` | An unexpected internal error occurred. |

## System (FLOW_EVT_300–399)

Runtime-level events.

| Code | Name | Trigger |
|---|---|---|
| `FLOW_EVT_300` | `RuntimeStarted` | The runtime finished initialization. |
| `FLOW_EVT_301` | `RuntimeShutdown` | The runtime is shutting down. |
| `FLOW_EVT_302` | `PluginLoaded` | A plugin was successfully loaded. |
| `FLOW_EVT_303` | `PluginUnloaded` | A plugin was unloaded. |
| `FLOW_EVT_304` | `ConfigReloaded` | The runtime configuration was reloaded. |
| `FLOW_EVT_305` | `HealthCheck` | A health check completed. |

---

## Adding new events

To add a new event:

1. Pick the next available code in the appropriate range.
2. Add a row to the table above.
3. Implement the event emission in `flow-core` at the right point.
4. Add a test in `contract-tests/events/` that asserts the event is emitted for the right action.
5. Update the `event-schema.json` if the `data` shape is new.
