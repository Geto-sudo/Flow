# RFC 0003 — Plugin System

| Field | Value |
|---|---|
| **Status** | Draft |
| **Author** | Flow Team |
| **Created** | 2026-07-17 |
| **Depends on** | RFC 0001 (Runtime) |

---

## Summary

Define a runtime-loadable plugin system for Flow that allows third parties to add effects, media linkers, AI backends, schema extensions, and export presets without modifying flow-core.

## Motivation

Flow must be extensible at every layer. Users need custom effects, studios need custom media resolvers, and the AI ecosystem evolves faster than any single runtime.

## Design

### Plugin Types

| Type | Interface | Language |
|---|---|---|
| **Effect** | `Effect` trait | Rust / C ABI |
| **Media Linker** | `MediaLinker` trait | Rust / C ABI |
| **Schema Extension** | OTIO SchemaDef | Python / JSON |
| **AI Backend** | `AiBackend` trait | C ABI |
| **Export Preset** | JSON manifest | JSON only |

### Manifest Format

Each plugin ships `flow-plugin.toml`:

```toml
[plugin]
name = "my-blur"
version = "1.0.0"
api_version = "1"

[effects]
declare = ["core.blur.gaussian"]

[ai]
backend = "onnx"

[dependencies]
"onnx-runtime" = ">=1.15"
```

### C ABI for Plugins

```c
typedef struct {
    const char* name;
    const char* version;
    uint32_t    api_version;
} FlowPluginInfo;

typedef enum {
    FLOW_OK = 0,
    FLOW_ERR_VERSION_MISMATCH,
    FLOW_ERR_REGISTRATION_FAILED,
} FlowStatus;

FlowPluginInfo flow_plugin_info();
FlowStatus flow_plugin_register(FlowHost* host);
```

### Loading Process

1. Scan `$FLOW_PLUGINS_DIR` (`~/.flow/plugins/`)
2. Discover `flow-plugin.toml` in each subdirectory or `.flowplugin` archive
3. `dlopen` / `LoadLibrary` the shared library
4. Call `flow_plugin_info()` to verify API version
5. Call `flow_plugin_register(host)` to register components
6. All registered effects appear in `flow.effects.list()`

### Plugin Isolation

- Each plugin runs in the same process space (no sandbox in v1)
- Plugin crashes may crash the host (à la FFmpeg, MLT)
- Future: subprocess plugins for isolation

## Alternatives Considered

- **WASM plugins** — more isolation, less capability. Future option.
- **Python plugins** — easiest, slowest. Future option for script-only plugins.
- **Built-in only** — not extensible. Rejected.

## Open Questions

- Should plugins be allowed to register new action types?
- How do we handle plugin dependency resolution (plugin A needs plugin B)?

## Implementation Plan

1. Define C ABI headers in `flow-ffi`
2. Implement `PluginLoader` in `flow-core`
3. Implement `FlowHost` registration API
4. Write example blur plugin
5. Document plugin authoring guide
6. Add `flow plugin check` CLI command
