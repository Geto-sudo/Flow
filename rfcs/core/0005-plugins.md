# RFC-0005: Plugin System

| Field | Value |
|---|---|
| Status | Draft |
| Author | Mavis |
| Created | 2026-07-17 |
| Depends on | RFC-0001, RFC-0003, RFC-0004 |

---

# Summary

This RFC defines how **third parties extend the Flow runtime** without modifying its source. The plugin system supports four extension points, mirroring OTIO's plugin model:

1. **Effects** — new operations in the render graph.
2. **Media linkers** — resolvers that turn `ExternalReference` into local paths.
3. **AI backends** — ONNX, libtorch, remote HTTP, WebGPU.
4. **Schemas** — Flow-specific OTIO schema definitions and JSON Schemas for actions.

A plugin is a shared library (or a Python package for some extension types) that ships a `flow-plugin.toml` manifest and exposes a C ABI. The runtime discovers plugins at init time, validates their manifests, and registers their declarations.

# Motivation

The runtime is small. The ecosystem is large. Flow wins by making it cheap to add:

- A new effect that wraps a proprietary algorithm.
- A new AI model that solves a vertical problem.
- A new media linker that understands a studio's storage layout.
- A new schema that extends the timeline model.

The plugin model must support all of these **without recompilation, without restarting the host, and without compromising the runtime's stability**. A misbehaving plugin must be detectable, isolatable, and unloadable.

The plugin model also has to be **safe** for the agent use case. An LLM that calls a malicious plugin must not be able to escape the plugin's sandbox. (Sandboxing is a v2 feature; v1 relies on plugin authors behaving well.)

# Goals

- Support four extension points: effects, media linkers, AI backends, schemas.
- Discover plugins at runtime init (no recompilation).
- Support shared-library plugins (C ABI) for performance-critical extensions.
- Support Python plugins for slower, more flexible extensions.
- Validate plugin manifests at load time; reject plugins with manifest errors.
- Isolate plugin failures (a crash in one plugin must not crash the runtime).
- Provide a stable, versioned ABI for shared-library plugins.
- Document the plugin authoring workflow.

# Non Goals

- This RFC does **not** define the in-Rust effect API (effects are implemented in Rust by the runtime authors; the plugin ABI is a C interface).
- It does **not** define a plugin marketplace or a discovery service.
- It does **not** define sandboxing (planned for v2; out of scope for v1).
- It does **not** define how plugins are installed (system package manager, pip, npm, custom tool — left to the operator).

# Guide-level explanation

A plugin author writes a shared library:

```c
// my-effect/src/lib.rs (Rust source compiled to a .so/.dll/.dylib)
use flow_plugin::*;

flow_plugin_export! {
    fn declare() -> PluginManifest {
        PluginManifest {
            id: "vendor.effect.upscale",
            name: "Vendor Upscale",
            version: "1.0.0",
            rustc_version: "1.78",
            effects: vec![
                EffectDecl {
                    id: "vendor.upscale",
                    name: "Vendor AI Upscale",
                    param_schema: json!({ /* ... */ }),
                    inputs: vec![PortSpec::video("in")],
                    outputs: vec![PortSpec::video("out")],
                    is_ai: true,
                },
            ],
            ai_backends: vec![
                AiBackendDecl {
                    id: "vendor.remote-onnx",
                    kind: AiBackendKind::RemoteHttp,
                    config_schema: json!({ /* ... */ }),
                },
            ],
        }
    }

    fn create_effect(id: &str, params: serde_json::Value) -> Result<Box<dyn Effect>> {
        match id {
            "vendor.upscale" => Ok(Box::new(VendorUpscale::new(params)?)),
            _ => Err(FlowError::UnknownEffect(id.into())),
        }
    }
}
```

The author writes a `flow-plugin.toml` manifest:

```toml
[plugin]
id = "vendor.effect.upscale"
name = "Vendor Upscale"
version = "1.0.0"
abi_version = 1

[targets]
linux_x86_64 = "target/release/libvendor_upscale.so"
macos_arm64 = "target/release/libvendor_upscale.dylib"
windows_x86_64 = "target/release/vendor_upscale.dll"

[permissions]
filesystem = ["read:/opt/vendor/models"]
network = ["https://api.vendor.com"]
```

The user drops the plugin directory into `$FLOW_PLUGINS`. On next runtime init, the plugin is loaded and its effects are available.

# Reference-level explanation

## The manifest

```toml
[plugin]
id = "vendor.effect.upscale"          # unique, reverse-DNS
name = "Vendor Upscale"               # human-readable
version = "1.0.0"                     # semver
abi_version = 1                       # which Flow plugin ABI this targets
authors = ["Vendor Inc <ops@vendor.com>"]
license = "Apache-2.0"
description = "AI super-resolution for video."

[targets]
linux_x86_64 = "build/libvendor_upscale.so"
macos_arm64 = "build/libvendor_upscale.dylib"
windows_x86_64 = "build/vendor_upscale.dll"

[effects.upscale]
name = "Vendor AI Upscale"
schema = "schemas/upscale.schema.json"
is_ai = true
default_params = { scale = 2 }

[ai_backends.remote_onnx]
kind = "remote_http"
config_schema = "schemas/backend.schema.json"

[media_linkers.vendor_storage]
name = "Vendor Storage"
config_schema = "schemas/linker.schema.json"

[schemas.flow_ai_op]
otio_schemadef = "schemas/flow_ai_op.py"
```

The manifest is the source of truth for what the plugin provides. The runtime validates it at load time and refuses to load a plugin with manifest errors.

## The C ABI

The ABI is a small set of C functions that the runtime calls. Everything else is opaque.

```c
typedef struct FlowPluginInfo {
    const char* id;
    const char* name;
    const char* version;
    uint32_t abi_version;
    size_t num_effects;
    const FlowEffectDesc* effects;
    size_t num_ai_backends;
    const FlowAiBackendDesc* ai_backends;
    size_t num_media_linkers;
    const FlowMediaLinkerDesc* media_linkers;
    // Reserved for future use.
    void* reserved[8];
} FlowPluginInfo;

// ABI version 1
FlowPluginInfo flow_plugin_info(void);
FlowStatus flow_plugin_init(FlowHost* host);
FlowStatus flow_plugin_shutdown(void);

// Effect factory
FlowStatus flow_create_effect(
    const char* effect_id,
    const char* params_json,
    FlowEffectHandle* out
);
FlowStatus flow_destroy_effect(FlowEffectHandle effect);

// Effect processing
FlowStatus flow_effect_process(
    FlowEffectHandle effect,
    FlowFrame** inputs,    // array of input frames
    size_t num_inputs,
    FlowFrame** outputs,   // array of output frames
    size_t num_outputs,
    FlowProgressCallback progress_cb,
    void* progress_userdata
);
```

The ABI is versioned. Major bumps are breaking; minor bumps add new functions (backward compatible). Plugin authors target a specific ABI version; the runtime refuses to load plugins targeting an unsupported version.

## Discovery and loading

```rust
impl Runtime {
    fn load_plugins(&self) -> Result<()> {
        for dir in self.plugin_dirs() {
            for entry in fs::read_dir(dir)? {
                let manifest_path = entry.path().join("flow-plugin.toml");
                if !manifest_path.exists() { continue; }
                let manifest = PluginManifest::from_file(&manifest_path)?;
                self.validate_manifest(&manifest)?;
                let target = self.pick_target(&manifest)?;
                let lib = unsafe { Library::new(&target) };
                // Wrap in a safe Rust handle.
                let plugin = Plugin::new(manifest, lib)?;
                self.plugins.register(plugin)?;
            }
        }
        Ok(())
    }
}
```

If a plugin fails to load (manifest invalid, shared library missing, init function returns error), the runtime logs the error and continues. A single broken plugin does not prevent the runtime from starting.

## Isolation

In v1, isolation is **process-level via panic-catching**. Each effect call is wrapped in `std::panic::catch_unwind`. If a plugin panics, the panic is caught, the effect call returns an error, and the runtime continues. The plugin is **disabled** for the rest of the session (configurable; could be just the current call).

In v2, isolation could be **process-level via separate processes** for untrusted plugins. Heavyweight; deferred.

## Hot reload (optional)

The runtime supports an opt-in hot-reload mode for development. On SIGHUP (or a runtime API call), the runtime re-scans plugin directories and reloads changed plugins. This is a developer convenience; production deployments should treat plugins as immutable.

# Architecture

```
┌──────────────────────────────────────────────────────────┐
│                       Runtime                             │
│                                                           │
│  ┌────────────────┐                                       │
│  │ Plugin         │  ┌─────────────────┐                 │
│  │ Registry       │  │ Effect Registry │                 │
│  │                │  │  - core.*       │                 │
│  │ - vendor.ai    │─▶│  - vendor.*     │                 │
│  │ - vendor.io    │  │  - user.*       │                 │
│  │ - user.fx      │  └─────────────────┘                 │
│  └────────┬───────┘                                       │
│           │                                               │
│           ▼                                               │
│  ┌──────────────────────────────────────┐                │
│  │ Plugin Loader                         │                │
│  │  - discover from $FLOW_PLUGINS        │                │
│  │  - validate manifests                  │                │
│  │  - dlopen shared libraries            │                │
│  │  - panic-isolate per call             │                │
│  └──────────────────────────────────────┘                │
│                                                           │
│  ┌──────────────────────────────────────┐                │
│  │ Plugin Author API (Rust)              │                │
│  │  - flow_plugin_export! macro          │                │
│  │  - safe Rust wrappers over C ABI      │                │
│  └──────────────────────────────────────┘                │
│                                                           │
└──────────────────────────────────────────────────────────┘
                          ▲
                          │ shared library
                          │ (dlopen, C ABI)
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   ┌────▼─────┐    ┌─────▼────┐    ┌───────▼──────┐
   │ vendor   │    │ vendor   │    │ user         │
   │ upscale  │    │ remote   │    │ custom-fx    │
   │ .so      │    │ backend  │    │ .dll         │
   └──────────┘    └──────────┘    └──────────────┘
```

# Alternatives

### A. Subprocess plugins (RPC over stdio)

**Considered.** Each plugin is a separate process. Strong isolation, simple ABI (JSON over stdio), works across language boundaries. **Rejected** for v1 because: (a) per-call process overhead is too high for a render hot path, (b) state passing is awkward, (c) we can add subprocess plugins in v2 for untrusted code.

### B. WASM plugins

**Considered.** WASM gives us sandboxing, cross-platform, cross-language. **Deferred** to v2 because: (a) the WASM ecosystem for media and AI is immature, (b) the WASI interfaces for GPU and file I/O are still in flux, (c) we can ship a WASM plugin backend once the underlying tech stabilizes.

### C. Lua/embedded scripting plugins

**Rejected.** Adds a scripting runtime, a sandbox, and a debug story. None of the four extension points benefit from this; the actual logic is either performance-critical (effects) or model-invocation (AI backends), and both want native code.

### D. No plugins, all in core

**Rejected.** Would force Flow to ship every effect, every AI model, every media linker. Unsustainable.

# Drawbacks

- **The C ABI is a maintenance burden.** Every change requires careful version management. Mitigated by: a narrow ABI, strict version policy, automated ABI tests.
- **Panic-catching is not real isolation.** A plugin that calls `abort()` or hangs in an infinite loop still takes down the host. Mitigated by: encouraging plugins to behave well, planning subprocess isolation for v2.
- **Plugin discovery is filesystem-based.** A plugin not on disk cannot be loaded. No remote loading, no dynamic registration. Mitigated by: documented installation workflow, the option to point `FLOW_PLUGINS` at any directory.
- **ABI version 1 is small.** v1 only supports effects, AI backends, and media linkers. Schemas as native plugins is deferred to a future ABI version.

# Future Possibilities

- **Subprocess plugins** for untrusted code (e.g. community-contributed effects).
- **WASM plugins** for cross-platform sandboxing.
- **Plugin marketplace** with signed packages and automatic updates.
- **Capability-based permissions** (filesystem, network, GPU access) declared in the manifest and enforced by the runtime.
- **Plugin-to-plugin composition.** A plugin that depends on another plugin's effect.

# Unresolved Questions

1. **ABI stability promise.** Once we publish ABI v1, when can we break it? Recommend: never within a major Flow version; ABI v2 may be incompatible with v1.
2. **Plugin versioning policy.** When a plugin author updates a plugin, does the old version stay registered? Overwrite? Require explicit opt-in?
3. **Conflict resolution.** If two plugins declare the same `effect_id`, who wins? First loaded? Last loaded? Error?
4. **Python plugin performance.** Python plugins will be slow for effect processing. Should we ban Python effects and only allow Python for media linkers / schemas?
5. **Plugin signing.** Should the runtime verify a cryptographic signature on the plugin shared library? Critical for production, deferred to v2.

---

**Next RFC**: RFC-0006 — MCP Integration
