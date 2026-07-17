# Flow — Plugin System

> Extending Flow at every layer.

---

## 1. Philosophy

Flow borrows from two proven models:

- **MLT's `mlt_factory`** — runtime-loadable shared libraries registered by convention
- **OTIO's 4 plugin types** — Adapters, MediaLinkers, SchemaDefs, HookScripts

The result: a **typed, versioned, language-agnostic** plugin system.

## 2. Plugin Types

| Type | What it does | Language |
|---|---|---|
| **Effect** | New video/audio effect node | Rust / C ABI |
| **Media Linker** | Resolve `ExternalReference` to local paths | Rust / C ABI |
| **Schema Extension** | Add new OTIO schema types | Python / JSON |
| **AI Backend** | New inference runtime (beyond ONNX) | C ABI |
| **Export Preset** | Named render configuration | JSON only |

## 3. Plugin Manifest

Each plugin ships with a `flow-plugin.toml`:

```toml
[plugin]
name = "my-blur"
version = "1.0.0"
api_version = "1"

[effects]
declare = ["core.blur.gaussian"]

[ai]
backend = "onnx"  # or "libtorch", "remote"

[dependencies]
"onnx-runtime" = ">=1.15"
```

## 4. Effect Plugin (Rust)

```rust
use flow_core::prelude::*;

#[derive(Effect)]
#[effect(id = "core.blur.gaussian", version = "1.0.0")]
struct GaussianBlur {
    radius: f64,
}

impl Effect for GaussianBlur {
    fn inputs(&self) -> &[PortSpec] {
        &[PortSpec::video("in")]
    }

    fn outputs(&self) -> &[PortSpec] {
        &[PortSpec::video("out")]
    }

    fn param_schema(&self) -> &Schema {
        // Returns JSON Schema for { radius: number }
    }

    fn process(&self, ctx: &mut EffectContext, inputs: PortMap) -> Result<PortMap> {
        let frame = inputs.video_frame("in")?;
        let blurred = gaussian_blur_cpu(frame, self.radius);
        Ok(PortMap::video("out", blurred))
    }
}

// Required C ABI entry points
#[no_mangle]
pub extern "C" fn flow_plugin_info() -> FlowPluginInfo { ... }

#[no_mangle]
pub extern "C" fn flow_plugin_register(host: &mut FlowHost) -> FlowStatus {
    host.register_effect::<GaussianBlur>()
}
```

## 5. Loading

Plugins are discovered at startup:

1. Scan `$FLOW_PLUGINS_DIR` (default: `~/.flow/plugins/`)
2. Read each `flow-plugin.toml`
3. `dlopen` the shared library (`.so` / `.dylib` / `.dll`)
4. Call `flow_plugin_register` with a `&mut FlowHost`
5. The host validates API version compatibility

## 6. Shipping a Plugin

```
my-blur/
├── Cargo.toml
├── src/lib.rs
└── flow-plugin.toml
```

Build → `my-blur.flowplugin` → drop in `$FLOW_PLUGINS_DIR` → loaded at next startup.

## 7. The Plugin Lifecycle

```
Startup
  │
  ▼
Scan directories ──▶ Read manifests ──▶ Load libraries
                                              │
                                              ▼
                                     Register with FlowHost
                                              │
                                              ▼
                                     Validate API version
                                              │
                                              ▼
                                     Ready (effects queryable)
```

## 8. API Stability

- Plugin API is versioned (`api_version = "1"`)
- Breaking changes increment the major version
- Old plugins are rejected with a clear error message
- Flow ships with a `flow plugin check` command to validate plugins
