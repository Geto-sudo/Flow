# RFC-0001: Flow Runtime

| Field | Value |
|---|---|
| Status | Draft |
| Author | Mavis |
| Created | 2026-07-17 |
| Depends on | — |

---

# Summary

This RFC defines the **Flow Runtime**, the in-process engine that all Flow surfaces (`flow-cli`, `flow-server`, `flow-script`, third-party plugins) link against. The runtime is a single statically-linkable Rust crate (`flow-core`) with a stable C ABI for plugin authors and a stable Rust API for embedders.

The runtime is the **only** piece of Flow that has authority over the timeline, the action log, the render graph, and the media pipeline. Everything else — CLI, server, MCP, SDK, plugins — is a thin adapter around it.

# Motivation

Flow's mission is to be the **execution layer for AI video editing**. To fulfill that role, the runtime must satisfy five properties:

1. **Embeddable.** The same engine runs in a long-lived daemon, a one-shot CLI invocation, an in-process Python module, and a third-party editor's render pipeline. A single shared library is the only way to avoid divergent behavior across surfaces.
2. **Deterministic.** Given the same action log and the same plugin set, the runtime produces the same output. Reproducibility is non-negotiable for a system whose users are non-deterministic agents.
3. **Inspectable.** Every state change is recorded as an action; the action log is the source of truth. The runtime must support replay, diff, and audit without external observability infrastructure.
4. **Extensible.** The codec, color, and AI layers evolve faster than the core. The runtime must allow plugins to register new effects, new media linkers, new AI backends, and new schemas without recompilation.
5. **Boring under load.** Long renders, concurrent sessions, GPU contention, partial failures — the runtime must remain predictable when the agent stack above it gets weird.

# Goals

- Provide a single Rust crate (`flow-core`) that contains all Flow logic.
- Expose a stable C ABI (`flow-ffi`) for plugins and third-party embedders.
- Guarantee that any state change goes through the action system.
- Make the runtime **headless** — no UI, no event loop, no assumptions about the host.
- Support concurrent sessions within a single process (project isolation).
- Support the local-first model: a runtime is fully functional with no network connection.
- Document the public API as a complete surface (every public function, every public type).

# Non Goals

- The runtime is **not** an editor. It does not own a window, a render canvas, or user input.
- The runtime does **not** implement codecs. Codecs come from FFmpeg via FFI.
- The runtime does **not** implement an AI inference engine. AI backends are plugins.
- The runtime does **not** speak HTTP, MCP, or any network protocol. That is `flow-server`'s job.
- The runtime does **not** own the on-disk project format. It owns the in-memory model; serialization is a separate concern (RFC-0010).
- The runtime is **not** required to be safe to embed in a kernel or other restricted environment. It targets user-space applications.

# Guide-level explanation

A typical caller of the runtime looks like this:

```rust
use flow_core::{Runtime, Project, Action};

fn main() -> Result<()> {
    // 1. Initialize the runtime. Discovers plugins from $FLOW_PLUGINS.
    let runtime = Runtime::init()?;

    // 2. Open a project. Loads timeline.otio + replays actions.jsonl.
    let mut project = runtime.open_project("./my-project")?;

    // 3. Submit an action. The runtime validates, applies, records, and returns
    //    the inverse for undo.
    let action = Action::clip_add(/* ... */);
    let inverse = project.apply(action)?;

    // 4. Render to a file. The runtime builds the render graph and executes it.
    let job = project.render(RenderSpec::mp4("out.mp4"))?;
    job.wait()?;

    // 5. Save the project. Persists timeline.otio + appends to actions.jsonl.
    project.save()?;

    Ok(())
}
```

The runtime is a library. There is no `flow-core` binary. The `flow-cli` and `flow-server` binaries are separate crates that link against `flow-core` and add their own concerns (CLI parsing, HTTP, MCP).

# Reference-level explanation

## Crate layout

```
crates/flow-core/
├── src/
│   ├── lib.rs                 // public re-exports
│   ├── runtime.rs             // Runtime struct, init, plugin discovery
│   ├── project/
│   │   ├── mod.rs
│   │   ├── state.rs           // Project, open, save, close
│   │   ├── actions.rs         // apply, undo, redo, history
│   │   └── lock.rs            // per-project mutex, optimistic concurrency
│   ├── action/
│   │   ├── mod.rs             // Action enum, ActionId, ActionResult
│   │   ├── schema.rs          // JSON Schema registry
│   │   ├── validator.rs       // validation pipeline
│   │   └── inverse.rs         // inverse computation
│   ├── timeline/
│   │   ├── mod.rs
│   │   ├── otio.rs            // OTIO C++ bindings
│   │   ├── mutation.rs        // mutation API (typed wrappers)
│   │   ├── query.rs           // query API
│   │   └── extensions.rs      // FlowOp schema extensions
│   ├── engine/
│   │   ├── mod.rs
│   │   ├── graph.rs           // Effect Graph (typed DAG)
│   │   ├── scheduler.rs       // scheduling + execution
│   │   ├── color.rs           // color engine
│   │   ├── audio.rs           // audio engine
│   │   └── ai.rs              // AI backend registry
│   ├── media/
│   │   ├── mod.rs
│   │   ├── probe.rs           // ffprobe wrapper
│   │   ├── reader.rs          // demux + decode
│   │   ├── writer.rs          // mux + encode
│   │   └── cache.rs           // media cache, frame cache
│   ├── pool/
│   │   ├── mod.rs             // slab allocator
│   │   └── buffer.rs          // refcounted buffer pool
│   ├── plugin/
│   │   ├── mod.rs
│   │   ├── manifest.rs        // plugin.toml parser
│   │   ├── loader.rs          // libloading wrapper
│   │   └── registry.rs        // effect/media linker/AI backend registry
│   ├── render/
│   │   ├── mod.rs             // render job, progress, cancellation
│   │   ├── plan.rs            // render plan (DAG from timeline)
│   │   └── execute.rs         // execution
│   └── observability/
│       ├── mod.rs
│       ├── log.rs             // structured logging
│       └── trace.rs           // spans for distributed tracing
└── tests/
    ├── integration/
    └── golden/                // golden output regression tests
```

## The `Runtime` struct

```rust
pub struct Runtime {
    config: RuntimeConfig,
    plugins: PluginRegistry,
    schemas: SchemaRegistry,
    effect_graph: EffectGraphRegistry,
    ai_backends: AiBackendRegistry,
    media_linkers: MediaLinkerRegistry,
    otio: OtioContext,
    ffmpeg: FfmpegContext,
    pool: Pool,
    log: LogContext,
    // No global mutable state. The Runtime is the only owner of these.
}

impl Runtime {
    pub fn init() -> Result<Arc<Runtime>> { /* discover plugins, init FFmpeg/OTIO */ }
    pub fn config(&self) -> &RuntimeConfig { &self.config }
    pub fn open_project(&self, path: &Path) -> Result<Project> { /* ... */ }
    pub fn create_project(&self, path: &Path, spec: ProjectSpec) -> Result<Project> { /* ... */ }
    pub fn plugins(&self) -> &PluginRegistry { &self.plugins }
    pub fn shutdown(self: Arc<Self>) { /* ... */ }
}
```

The `Runtime` is `Send + Sync` and is reference-counted via `Arc`. Multiple projects can be open within a single runtime instance. Each `Project` is its own struct with its own mutex.

## Plugin discovery

On `Runtime::init`, the runtime scans a list of plugin directories in this order:

1. `$FLOW_PLUGINS` (colon-separated).
2. `<runtime_dir>/plugins/`.
3. `<config_dir>/flow/plugins/`.

Each plugin directory contains a `flow-plugin.toml` manifest and one or more shared libraries. The runtime dlopens each shared library, calls its `flow_plugin_register` export, and registers the declared effects, media linkers, AI backends, and schemas.

## Concurrency model

- The `Runtime` is shared across threads via `Arc`. Its internal registries are read-mostly after init.
- A `Project` is owned by a single thread at a time. The runtime provides an `optimistic` mode for multi-writer scenarios via the action log: the agent submits an action with a `base_action_id`, the runtime validates against the current state, applies if the base still matches, and returns a conflict error otherwise.
- A `RenderJob` runs on a dedicated thread (or a thread pool) and reports progress via a channel.

# Architecture

```
                   ┌──────────────────────────────────────┐
                   │             flow-core                 │
                   │                                       │
   ┌──────────┐    │   ┌─────────┐    ┌──────────────┐     │
   │ flow-cli │────┼──▶│ Runtime │───▶│ Project(s)   │     │
   ├──────────┤    │   └────┬────┘    └──────┬───────┘     │
   │flow-     │    │        │                │             │
   │server    │────┼──┐     ▼                ▼             │
   ├──────────┤    │  │  ┌────────┐    ┌─────────────┐     │
   │flow-     │    │  │  │Action  │    │  Timeline   │     │
   │script    │────┼──┘  │Validator   │ (OTIO +      │     │
   ├──────────┤    │     └────┬────┘    │  Flow ext.) │     │
   │3rd-party │    │          │         └──────┬──────┘     │
   │plugin    │────┼──┐       ▼                ▼             │
   └──────────┘    │  │  ┌────────┐    ┌──────────────┐    │
                   │  │  │Effect  │    │  Render      │    │
                   │  │  │Graph   │    │  Plan        │    │
                   │  │  └────┬───┘    └──────┬───────┘    │
                   │  │       │               │             │
                   │  │       ▼               ▼             │
                   │  │  ┌──────────────────────────┐      │
                   │  │  │  Engine (FFmpeg + AI +   │      │
                   │  │  │  Color + Audio)          │      │
                   │  │  └──────────────────────────┘      │
                   │  │              │                      │
                   │  │              ▼                      │
                   │  │  ┌──────────────────────────┐      │
                   │  │  │  Foundation (pool, log,  │      │
                   │  │  │  plugin loader)          │      │
                   │  │  └──────────────────────────┘      │
                   │  │                                    │
                   │  └─ Plugin ABI (C, stable)            │
                   └──────────────────────────────────────┘
```

The diagram shows the four consumers of `flow-core` (CLI, server, Python, third-party plugins), the three internal layers (Project, Engine, Foundation), and the stable C ABI for plugins.

# Alternatives

### A. Single binary, not a library

**Rejected.** Forces all consumers to shell out to a subprocess, which costs cold start, loses state, breaks streaming progress, and prevents fine-grained concurrency. A library is the only way to support the full spectrum of consumers.

### B. Multiple crates (flow-runtime, flow-timeline, flow-engine, etc.)

**Considered.** Finer-grained decomposition is appealing but premature. The 7 RFCs in this core set describe a tightly coupled system. Premature split creates awkward public APIs and forces every plugin to depend on a specific combination of crates. We can extract sub-crates later if the public API stabilizes.

### C. Interpret a config file, not call a library

**Rejected.** That is what FFmpeg's CLI does, and it forces consumers to shell out. Same problems as option A.

### D. Use a managed runtime (JVM, BEAM, .NET)

**Rejected.** Flow must embed in native binaries, in browsers (via WASM later), and on edge devices. A managed runtime adds 50-200 MB to the binary and restricts platform support. Rust compiles to all of those targets.

# Drawbacks

- **A single library is a big library.** `flow-core` will be large. Mitigated by: (a) feature flags to disable unneeded subsystems, (b) optional sub-crates later, (c) careful module boundaries.
- **C ABI for plugins is a maintenance burden.** Any breaking change requires a major version bump. Mitigated by: (a) ABI-versioned shared libraries (`libflow_core.so.1`), (b) a small, narrow ABI surface.
- **A single process hosting multiple projects is a complexity multiplier.** Concurrent sessions, GPU resource contention, and log interleaving are all harder. Mitigated by: (a) per-project mutex, (b) explicit GPU resource budgets, (c) structured logging with project IDs.
- **No scripting layer inside the runtime.** Some video tools (After Effects, Nuke) have a built-in expression language. Flow does not, by design. Mitigated by: agents and `flow-script` (Python) cover the same use cases without bloating the runtime.

# Future Possibilities

- **WASM build of `flow-core`.** Enables a browser runtime (`flow-web`). The same Rust crate, compiled to a different target. Plugin ABI would have to be WASM-compatible.
- **GPU memory pooling across projects.** Right now each project has its own GPU buffer cache. A future runtime could share caches for common resolutions.
- **Distributed render.** A runtime could ship a render sub-job to a remote runtime over a thin RPC. Not in v1; complexity is high.
- **Stateful action subscriptions.** Today, agents poll for state. A future runtime could push state diffs to subscribers.
- **Capability-based security.** A future runtime could sandbox plugins via WebAssembly or a custom DSL, limiting file system and network access. Out of scope for v1.

# Unresolved Questions

1. **Plugin ABI version.** What goes in v1? (Effects yes, media linkers yes, AI backends yes, schemas maybe.) Need a concrete list before code freeze.
2. **Error type.** A single `FlowError` enum or a per-subsystem error hierarchy? Per-subsystem is more idiomatic in Rust; a single type is easier for plugin authors.
3. **FFmpeg major version pin.** FFmpeg 7 is current. Pin to 7.x? Or follow head? Pinning is safer; following is more flexible.
4. **OTIO C++ vs Python bindings.** C++ is faster, Python is more familiar. Decision deferred until performance benchmarks exist.
5. **Plugin manifest schema stability.** Once published, can it change without breaking plugins? Need a versioning convention.

---

**Next RFC**: RFC-0002 — Execution Model
