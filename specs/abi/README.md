# specs/abi/

# Flow ABI Specs

This directory defines the **Application Binary Interfaces (ABIs)** that Flow uses to interoperate with other software. The primary ABI is the **plugin ABI**, a stable C ABI for third-party plugins.

## Why ABIs

ABIs are how software written in different languages and compiled by different toolchains interoperate at the binary level. They are the **lowest-level** contract Flow exposes. A plugin author who targets the v1 plugin ABI can be confident their plugin will work with any v1-compatible runtime, regardless of how the runtime was built.

## Structure

```
abi/
├── README.md                       ← you are here
├── plugin-abi.md                   ← the full specification of the plugin ABI
├── plugin-abi.h                    ← the C header (binding contract)
└── plugin-abi-bindings.rs          ← the Rust extern types (binding contract)
```

The three files form a single spec: the prose spec (`plugin-abi.md`) is the source of truth, the C header is the binding for C/C++ plugins, and the Rust extern file is the binding for Rust plugins.

## Stability

The plugin ABI follows **strict semver**:

- The ABI major version (`FLOW_PLUGIN_ABI_VERSION_MAJOR`) is bumped on breaking changes.
- The ABI minor version is bumped on additive changes (new functions, new fields).
- The ABI patch version is bumped on documentation fixes.

A plugin built against ABI v1.0 works with a runtime implementing ABI v1.5. A plugin built against ABI v1.5 may not work with a runtime implementing ABI v1.0 if it uses the new functions.

The current major version is `1`. It will not change within Flow v1.

## Conformance

A conformance test (`contract-tests/abi/`) includes:

- A reference plugin (`ref-plugin.c`) that exports all required entry points.
- A test driver that loads the reference plugin and validates the contract.
- Negative tests for ABI version mismatches, missing entry points, and invalid manifests.

A runtime passes conformance if it can load, validate, and call a v1-compliant plugin.
