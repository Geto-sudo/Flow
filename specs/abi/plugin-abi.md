# specs/plugin-abi.md

# Flow Plugin ABI — Version 1

| Field | Value |
|---|---|
| **Spec version** | 1.0.0 |
| **Status** | Draft |
| **Source ADRs** | [ADR-0007 (C ABI for Plugins)](../adrs/0007-c-abi-plugin.md) |
| **Source RFCs** | [RFC-0005 (Plugin System)](../rfcs/core/0005-plugins.md) |

This spec defines the Application Binary Interface (ABI) between the Flow runtime and third-party plugins. A plugin is a C-compatible shared library that the runtime loads with `dlopen` / `LoadLibrary`. The ABI is the contract; the implementation is opaque.

## Versioning

The ABI is versioned with a single integer: the **API version**. This spec is API version `1`. A plugin declares the API version it targets in its `FlowPluginInfo` struct. The runtime refuses to load a plugin that targets an unsupported API version.

- **Major API bumps** are breaking. The runtime will not load a plugin built against an older major version.
- **Minor API bumps** are additive. A plugin built against API 1.0 works with a runtime implementing API 1.5 (it ignores new functions).

The current major version is `1`. This will not change within Flow v1.

## Required entry points

Every plugin **must** export two C functions:

```c
FlowPluginInfo flow_plugin_info(void);
FlowStatus     flow_plugin_register(FlowHost* host);
```

- `flow_plugin_info()` is called first. It returns a `FlowPluginInfo` struct describing the plugin.
- `flow_plugin_register()` is called second. The plugin calls `FlowHost` methods to register its effects, media linkers, AI backends, and schemas.

Both functions must be thread-safe (the runtime may call them from any thread, though typically only at init time).

## Memory and lifetime

- Strings are NUL-terminated UTF-8 (`const char*`). They must remain valid for the lifetime of the plugin (typically `static`).
- Buffers (`FlowBuffer*`) are refcounted. The plugin may add a reference via `flow_buffer_ref`. The runtime will release its reference when done.
- Frames (`FlowFrame*`) are owned by the runtime. Plugins must not retain a frame reference across an `flow_effect_process` call. If a plugin needs to retain a frame, it must call `flow_buffer_ref` on the underlying buffer.
- Error strings (`FlowError.message`) are owned by the plugin and must remain valid until the next call to the plugin from the runtime.

## The C header

The full ABI is defined in [`plugin-abi.h`](./plugin-abi.h). Plugins include this header and link against the runtime's import library.

## The Rust bindings

The runtime exposes Rust extern types for the ABI in [`plugin-abi-bindings.rs`](./plugin-abi-bindings.rs). This file is the **Rust view of the C ABI** — it is consumed by `flow-core` and by plugins written in Rust.

## Plugin manifest

Every plugin ships a `flow-plugin.toml` manifest alongside the shared library. The manifest is TOML:

```toml
[plugin]
id = "com.example.vendor.upscale"      # reverse-DNS, globally unique
name = "Vendor Upscale"
version = "1.0.0"
api_version = 1
authors = ["vendor@example.com"]
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

[ai_backends.remote_onnx]
kind = "remote_http"
config_schema = "schemas/backend.schema.json"
```

The runtime validates the manifest at load time. A manifest error prevents the plugin from loading.

## Discovery

The runtime scans a list of plugin directories (in order):

1. `$FLOW_PLUGINS` (colon-separated).
2. `<runtime_dir>/plugins/`.
3. `<config_dir>/flow/plugins/`.

Each directory may contain multiple plugins, each in its own subdirectory. A plugin directory must contain a `flow-plugin.toml` and at least one target shared library.

## Loading

1. The runtime reads the manifest.
2. It selects the appropriate target for the host platform.
3. It `dlopen`s (or `LoadLibrary`s) the shared library.
4. It calls `flow_plugin_info()` and validates the API version.
5. It calls `flow_plugin_register()` and the plugin registers its declarations via the `FlowHost` callbacks.
6. The plugin is now available to the runtime.

If any step fails, the plugin is skipped and the error is logged. The runtime continues loading other plugins.

## Effect processing contract

A registered effect implements processing by exporting `flow_effect_process`:

```c
FlowStatus flow_effect_process(
    FlowEffectHandle effect,
    FlowFrame** inputs, size_t num_inputs,
    FlowFrame** outputs, size_t num_outputs,
    FlowProgressCallback progress_cb,
    void* progress_userdata
);
```

Contract:

- The function returns `FLOW_OK` on success, or an error code.
- On success, `outputs[i]` contains a valid frame for each output port.
- On error, all `outputs[i]` are unchanged.
- The function may call `progress_cb` zero or more times to report progress (0.0 to 1.0).
- The function must check the cancellation flag via `flow_host_is_cancelled(host)` periodically (every ~10 ms of work).
- The function must not block indefinitely. The runtime will time out and terminate the plugin process (v2) or abort the call (v1).

## Isolation

In v1, a misbehaving plugin can crash the host. Mitigations:

- The runtime wraps each call in `std::panic::catch_unwind` (Rust side) / `setjmp` (C side).
- A plugin that panics / aborts is **disabled for the rest of the session**.
- The runtime logs the error and continues with other plugins.

In v2, untrusted plugins may be run in a subprocess with a narrower ABI. The v1 ABI is a strict subset of the v2 ABI.

## Conformance tests

The conformance test suite for this spec lives in [`contract-tests/plugin-abi/`](../contract-tests/plugin-abi/). The suite includes:

- A reference plugin (`ref-plugin.c`) that exports all required entry points and registers one effect.
- A test driver (`test-driver.c`) that loads the reference plugin, calls each entry point, and validates the contract.
- A negative test (`test-version-mismatch.c`) that verifies the runtime rejects plugins with the wrong API version.
- A negative test (`test-bad-manifest.c`) that verifies the runtime rejects plugins with invalid manifests.

A passing conformance test means the implementation can load, register, and call a v1-compliant plugin.
