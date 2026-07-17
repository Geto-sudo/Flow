# specs/plugins/

# Flow Plugin Spec

This directory defines how third parties extend Flow with **plugins**. A plugin is a C-compatible shared library that the runtime loads at startup.

## Why a plugin system

Flow's core is small. The ecosystem is large. The plugin system lets third parties add:

- **Effects** — new operations in the render graph (e.g. a custom blur).
- **Media linkers** — resolvers that turn `ExternalReference` into local paths.
- **AI backends** — ONNX, libtorch, remote HTTP, WebGPU.
- **Schemas** — Flow-specific OTIO schema definitions.

A plugin is a **self-contained** shared library with a manifest. The runtime discovers, validates, and loads it.

## Structure

```
plugins/
├── README.md                       ← you are here
├── manifest-schema.json            ← the JSON Schema for flow-plugin.toml
├── effect-declaration.md           ← how to declare an effect in a plugin
├── media-linker-declaration.md     ← how to declare a media linker
├── ai-backend-declaration.md       ← how to declare an AI backend
└── example-plugin/                 ← a minimal example plugin (scaffolded later)
    ├── flow-plugin.toml
    ├── src/
    │   └── lib.rs
    └── README.md
```

## Loading

The runtime scans plugin directories in this order:

1. `$FLOW_PLUGINS` (colon-separated).
2. `<runtime_dir>/plugins/`.
3. `<config_dir>/flow/plugins/`.

Each directory may contain multiple plugin subdirectories. A plugin subdirectory must contain a `flow-plugin.toml` and at least one target shared library.

The manifest is validated against [`manifest-schema.json`](./manifest-schema.json). Invalid manifests prevent the plugin from loading.

## ABI

The plugin ABI is defined in [`../abi/`](../abi/). It is a stable C ABI with the following entry points:

```c
FlowPluginInfo flow_plugin_info(void);
FlowStatus     flow_plugin_register(FlowHost* host);
FlowStatus     flow_create_effect(const char* effect_id, const char* params_json, FlowEffectHandle* out);
void           flow_plugin_shutdown(void);
```

## Conformance

A conformance test (`contract-tests/plugins/`) includes:

- A reference plugin that exports all required entry points and registers one effect.
- A test driver that loads the reference plugin and validates the registration.
- A negative test for a plugin with a mismatched ABI version.
- A negative test for a plugin with an invalid manifest.

A runtime passes conformance if it correctly loads, validates, and calls a v1-compliant plugin.
