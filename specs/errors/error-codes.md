# Flow Error Codes

| Field | Value |
|---|---|
| **Spec version** | 1.0.0 |
| **Status** | Draft |
| **Source RFCs** | RFC-0003 (Action System) |

This is the **complete catalog of Flow error codes**. Every code is stable, documented, and tested. New codes are added in new spec versions; old codes are never removed.

Conventions:

- `code` — the stable machine code (`FLOW_xxx`).
- `name` — human-readable name (PascalCase).
- `category` — validation, runtime, io, plugin, auth, internal.
- `severity` — info, warning, error, fatal.
- `retryable` — whether the caller can retry the same operation.
- `http_status` — when the error is surfaced over HTTP, what status to return.
- `json_rpc_code` — when surfaced over JSON-RPC (MCP), what code to return.

---

## Validation (FLOW_001–099)

| Code | Name | HTTP | JSON-RPC | Retryable | Description |
|---|---|---|---|---|---|
| `FLOW_001` | `TimelineNotFound` | 404 | -32000 | false | A timeline ID was provided but does not exist. |
| `FLOW_002` | `InvalidClip` | 422 | -32602 | false | A clip operation was attempted on a clip that does not exist or is in an invalid state. |
| `FLOW_003` | `AssetMissing` | 422 | -32602 | true | A media reference could not be resolved. The asset is in `MissingReference` state. |
| `FLOW_004` | `PluginFailed` | 500 | -32603 | false | A plugin failed during initialization, registration, or processing. |
| `FLOW_005` | `ActionSchemaInvalid` | 400 | -32602 | false | The action JSON does not match the JSON Schema. (Stage 1 validation error.) |
| `FLOW_006` | `ActionSemanticInvalid` | 422 | -32602 | false | The action is well-formed but its references are stale or inconsistent. (Stage 2 validation error.) |
| `FLOW_007` | `ActionPreconditionViolated` | 422 | -32603 | false | The action is valid in form but cannot be applied in the current state. (Stage 3 validation error.) |
| `FLOW_008` | `EffectNotFound` | 404 | -32000 | false | The requested effect ID is not registered. |
| `FLOW_009` | `EffectParamInvalid` | 422 | -32602 | false | The effect's parameters do not match its JSON Schema. |
| `FLOW_010` | `TrackNotFound` | 404 | -32000 | false | A track ID was provided but does not exist. |
| `FLOW_011` | `MediaLinkerFailed` | 502 | -32603 | true | A media linker could not resolve a reference. |
| `FLOW_012` | `CheckpointNotFound` | 404 | -32000 | false | A checkpoint name or action ID was not found in the project's history. |
| `FLOW_013` | `ProjectAlreadyExists` | 409 | -32000 | false | A project already exists at the given path. |
| `FLOW_014` | `ProjectNotFound` | 404 | -32000 | false | A project ID was provided but the project does not exist on the server. |
| `FLOW_015` | `ConcurrentModification` | 409 | -32603 | true | Optimistic concurrency check failed: the action's `base_state_hash` no longer matches the current state. |
| `FLOW_016` | `ActionVersionUnsupported` | 400 | -32602 | false | The action's schema version is not supported by this runtime. |
| `FLOW_017` | `RenderRangeOutOfBounds` | 422 | -32602 | false | A render was requested for a time range that extends past the end of the timeline. |
| `FLOW_018` | `PresetNotFound` | 404 | -32000 | false | A render preset ID is not registered. |
| `FLOW_019` | `ActionBatchInvalid` | 422 | -32602 | false | A `batch` action contained an action that failed validation. |
| `FLOW_020` | `ActionTimeout` | 408 | -32000 | true | An action exceeded the configured timeout. |

## Runtime (FLOW_100–199)

| Code | Name | HTTP | JSON-RPC | Retryable | Description |
|---|---|---|---|---|---|
| `FLOW_100` | `DecodeFailed` | 500 | -32603 | true | A media file could not be decoded. |
| `FLOW_101` | `EncodeFailed` | 500 | -32603 | true | A render output could not be encoded. |
| `FLOW_102` | `MuxFailed` | 500 | -32603 | true | A container could not be written. |
| `FLOW_103` | `GpuOutOfMemory` | 507 | -32603 | true | A GPU device ran out of memory during a render or AI inference. |
| `FLOW_104` | `GpuNotAvailable` | 503 | -32603 | false | A hardware-accelerated operation was requested but no compatible GPU is available. |
| `FLOW_105` | `AiInferenceFailed` | 500 | -32603 | true | An AI model failed to produce a result. |
| `FLOW_106` | `AiModelNotFound` | 404 | -32000 | false | A requested AI model is not available. |
| `FLOW_107` | `RenderCancelled` | 499 | -32000 | false | A render was cancelled by the user. Not an error from the caller's perspective. |
| `FLOW_108` | `RenderTimeout` | 504 | -32000 | true | A render exceeded the maximum allowed time. |
| `FLOW_109` | `FrameAllocationFailed` | 500 | -32603 | true | A frame buffer could not be allocated. |
| `FLOW_110` | `HardwareAccelFailed` | 500 | -32603 | true | A hardware acceleration path failed. Runtime fell back to software. (Returned only if `hardware_accel: "required"` in the request.) |
| `FLOW_111` | `ColorConversionFailed` | 500 | -32603 | true | A color space conversion could not be performed. |
| `FLOW_112` | `AudioMixFailed` | 500 | -32603 | true | The audio mix could not be produced. |
| `FLOW_113` | `ResourceExhausted` | 507 | -32603 | true | A system resource (CPU, RAM, disk) was exhausted. |

## IO (FLOW_200–299)

| Code | Name | HTTP | JSON-RPC | Retryable | Description |
|---|---|---|---|---|---|
| `FLOW_200` | `FileNotFound` | 404 | -32000 | false | A file does not exist at the expected path. |
| `FLOW_201` | `FileAccessDenied` | 403 | -32000 | false | The runtime does not have permission to read or write a file. |
| `FLOW_202` | `FileCorrupted` | 422 | -32603 | false | A file exists but its content is corrupted. |
| `FLOW_203` | `DiskFull` | 507 | -32603 | true | The disk is full. |
| `FLOW_204` | `NetworkUnreachable` | 503 | -32603 | true | A network operation failed because the network is unreachable. |
| `FLOW_205` | `NetworkTimeout` | 504 | -32000 | true | A network operation timed out. |
| `FLOW_206` | `HttpError` | varies | -32603 | varies | An HTTP operation returned a non-2xx status. |
| `FLOW_207` | `DirectoryNotFound` | 404 | -32000 | false | A directory does not exist. |
| `FLOW_208` | `AtomicWriteFailed` | 500 | -32603 | true | An atomic file write failed. |
| `FLOW_209` | `CacheCorrupted` | 500 | -32603 | true | The project cache is corrupted. The runtime will attempt to rebuild it. |

## Plugin (FLOW_300–399)

| Code | Name | HTTP | JSON-RPC | Retryable | Description |
|---|---|---|---|---|---|
| `FLOW_300` | `PluginLoadFailed` | 500 | -32603 | false | A plugin shared library could not be loaded. |
| `FLOW_301` | `PluginVersionMismatch` | 500 | -32603 | false | A plugin targets a plugin ABI version the runtime does not support. |
| `FLOW_302` | `PluginManifestInvalid` | 500 | -32603 | false | A plugin's `flow-plugin.toml` is invalid. |
| `FLOW_303` | `PluginInitFailed` | 500 | -32603 | false | A plugin's `flow_plugin_register` returned an error. |
| `FLOW_304` | `PluginPanicked` | 500 | -32603 | true | A plugin panicked during effect processing. The plugin has been disabled. |
| `FLOW_305` | `PluginAborted` | 500 | -32603 | true | A plugin called `abort()` or terminated unexpectedly. |
| `FLOW_306` | `PluginTimeout` | 504 | -32000 | true | A plugin's effect processing exceeded the configured timeout. |
| `FLOW_307` | `PluginReturnedInvalidData` | 500 | -32603 | false | A plugin returned output that does not match its declared schema. |
| `FLOW_308` | `PluginNotFound` | 404 | -32000 | false | A plugin ID was requested but is not installed. |
| `FLOW_309` | `PluginAlreadyRegistered` | 409 | -32000 | false | Two plugins declared the same ID. The second was not loaded. |
| `FLOW_310` | `PluginCancelled` | 499 | -32000 | false | A plugin was cancelled mid-effect. |

## Auth (FLOW_400–499)

| Code | Name | HTTP | JSON-RPC | Retryable | Description |
|---|---|---|---|---|---|
| `FLOW_400` | `Unauthenticated` | 401 | -32000 | true | No credentials were provided. |
| `FLOW_401` | `InvalidCredentials` | 401 | -32000 | false | The provided credentials are invalid. |
| `FLOW_402` | `TokenExpired` | 401 | -32000 | true | The access token has expired. |
| `FLOW_403` | `Forbidden` | 403 | -32000 | false | The caller is authenticated but lacks permission for this operation. |
| `FLOW_404` | `RateLimitExceeded` | 429 | -32000 | true | The caller has exceeded the rate limit. |
| `FLOW_405` | `McpSessionExpired` | 401 | -32000 | true | The MCP session has expired. |

## Internal (FLOW_500–599)

| Code | Name | HTTP | JSON-RPC | Retryable | Description |
|---|---|---|---|---|---|
| `FLOW_500` | `InternalError` | 500 | -32603 | true | An unexpected internal error occurred. This is a bug in Flow. |
| `FLOW_501` | `NotImplemented` | 501 | -32603 | false | The requested feature is not implemented in this runtime. |
| `FLOW_502` | `InvariantViolated` | 500 | -32603 | true | An internal invariant was violated. This is a bug in Flow. |
| `FLOW_503` | `ConfigurationInvalid` | 500 | -32603 | false | The runtime configuration is invalid. |
| `FLOW_504` | `StateCorrupted` | 500 | -32603 | false | The in-memory or on-disk state is corrupted. |
| `FLOW_505` | `OutOfMemory` | 507 | -32603 | true | The runtime ran out of memory. |
| `FLOW_506` | `Panic` | 500 | -32603 | true | The runtime panicked. This is a bug. |
| `FLOW_507` | `Deadlock` | 500 | -32603 | true | The runtime detected a deadlock. |

---

## Adding new codes

To add a new error code:

1. Pick the next available code in the appropriate range.
2. Add a row to the table above.
3. Implement the error in `flow-core` and have it return the new code.
4. Add a test in `contract-tests/errors/` that asserts the code is returned for the right failure.
5. Update the `error-schema.json` if the `details` shape is new.
