# RFC-0002: Execution Model

| Field | Value |
|---|---|
| Status | Draft |
| Author | Mavis |
| Created | 2026-07-17 |
| Depends on | RFC-0001 |

---

# Summary

This RFC defines how the Flow runtime **executes actions**: the lifecycle from submission to completion, the threading model, the scheduling of dependent operations, and the cancellation semantics. The execution model is the bridge between the static action schema and the live state of the project.

# Motivation

The runtime accepts actions from many sources — a CLI invocation, a server request, an MCP call, a third-party plugin. Each action may trigger work of widely varying cost:

- **Trivial** (sub-millisecond): rename a clip, toggle a flag, update a property.
- **Cheap** (milliseconds to a few seconds): re-probe a media file, re-validate a sub-tree.
- **Expensive** (seconds to minutes): re-plan a render, decode a long clip, run an AI model.

The runtime must accept all of these uniformly, return results promptly, allow concurrent execution where safe, and never block the submitter on long-running work.

Two existing projects demonstrate the failure modes this RFC must avoid:

- **MoviePy's frame-sequence model** forces all effects to execute in a single Python loop, with no concurrency and no way to cancel a long render without killing the process.
- **FFmpeg's blocking filter graph** ties the submitter to the render: you cannot start a render and walk away.

Flow's model is **asynchronous-by-default with synchronous ergonomics**: every action is a future; the runtime can complete cheap actions synchronously and expensive ones on a background executor, with progress reported through a channel.

# Goals

- Provide a single, uniform `submit(action) -> ActionResult` entry point.
- Return promptly for all actions, even those that schedule long work.
- Allow multiple actions to be in flight concurrently when they are independent.
- Serialize actions that touch the same project (no torn writes).
- Make every long-running operation cancellable.
- Expose progress (percent, current stage, ETA, current frame) for long operations.
- Make action results replayable (re-executing the same action against the same state is idempotent where possible).

# Non Goals

- This RFC does **not** define the action schema itself (see RFC-0003).
- It does **not** define how render jobs are scheduled across GPU devices (a future RFC).
- It does **not** define the wire protocol for cross-process execution (`flow-server` handles that).
- It does **not** define a scheduler for AI inference (each AI backend plugin owns its own scheduling).

# Guide-level explanation

A typical caller submits an action and either waits for the result or polls:

```rust
// Cheap action: returns synchronously inside submit.
let result = project.submit(Action::clip_rename(clip_id, "new_name"))?;

// Expensive action: returns immediately with a job handle.
let job = project.submit(Action::render(spec))?;

// Poll, wait, or stream progress.
job.wait()?;
for progress in job.progress() {
    println!("{}: {}", progress.stage, progress.percent);
}

// Cancel a long-running job.
job.cancel()?;
```

The runtime decides whether an action is "cheap" (synchronous) or "expensive" (asynchronous) based on the action's type and the current state. This is a runtime policy, not a caller concern.

# Reference-level explanation

## The submission pipeline

```
caller --submit(action)--> ActionQueue --[validate]--> ActionExecutor
                                 |                          |
                                 |                          v
                                 |                  Project state (mutate)
                                 |                          |
                                 |                          v
                                 |                  history.push(action, inverse)
                                 |                          |
                                 v                          v
                              error? <--yes-- ValidationError   return ActionResult
                                 |
                                 no
                                 v
                          ActionResult { inverse, side_effects }
```

If the action triggers an expensive side effect (e.g. a re-render, an AI inference), the executor schedules a `Job` on the runtime's executor pool and returns a `JobHandle` instead of a synchronous result.

## Threading model

```
┌─────────────────────────────────────────────────────────────┐
│                        Runtime                               │
│                                                              │
│  ┌──────────────┐                                            │
│  │  Scheduler   │  (single-threaded, owns the timeline)      │
│  │              │                                            │
│  │  - accepts   │                                            │
│  │    actions   │                                            │
│  │  - serializes│                                            │
│  │    writes    │                                            │
│  │  - dispatches│                                            │
│  │    jobs      │                                            │
│  └──────┬───────┘                                            │
│         │                                                    │
│         │ dispatches jobs to:                                │
│         ▼                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │  Render      │  │  Decode     │  │  AI          │  ...   │
│  │  Worker Pool │  │  Worker Pool│  │  Worker Pool │        │
│  │  (N threads) │  │ (N threads) │  │ (GPU + CPU)  │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
│                                                              │
│  Shared state: Project (behind a Mutex on the Scheduler)     │
└─────────────────────────────────────────────────────────────┘
```

### Properties

- The **Scheduler** is single-threaded. It owns the project state and serializes all mutations. This eliminates data races by construction.
- The **worker pools** are independent and may run concurrently. They communicate with the Scheduler through message passing (channels).
- The number of threads in each pool is configured at runtime init (default: `min(N_cpu, 8)`).
- A long-running job (render, AI inference) does not block the Scheduler. The Scheduler can accept new actions while the job runs.
- A `cancel()` on a job sets a cancellation flag; the worker checks the flag at safe points and unwinds.

## Action classification

Each `Action` variant declares its cost class:

```rust
pub enum CostClass {
    /// Completes in microseconds, no I/O, no GPU.
    Trivial,
    /// Completes in milliseconds, may probe media or compute layout.
    Cheap,
    /// Completes in seconds, may decode or re-plan.
    Expensive,
    /// Completes in minutes, render or AI inference.
    LongRunning,
}
```

The scheduler uses this to decide:
- **Trivial / Cheap** → execute synchronously on the Scheduler thread.
- **Expensive / LongRunning** → dispatch to a worker pool, return a `JobHandle`.

This is a hint, not a hard rule. The scheduler may upgrade (or downgrade) based on runtime pressure.

## Cancellation

A `JobHandle` exposes `cancel() -> Result<()>`. Cancellation is cooperative:

- The worker checks `is_cancelled()` at safe points (per-frame for renders, per-batch for AI).
- On cancel, the worker stops, releases resources, and the job ends with status `Cancelled`.
- The project state is **not** rolled back; the action that triggered the job is either fully applied or not applied at all (atomicity is the action's responsibility, not the job's).

## Idempotency

A `Job` carries a `JobId` (UUID v7). Submitting the same action twice with the same ID is a no-op: the runtime returns the existing `JobHandle` if the job is still running, or the cached result if it has completed. This is the foundation for **at-least-once** semantics in distributed scenarios.

## Progress reporting

Each `Job` exposes a `Progress` stream:

```rust
pub struct Progress {
    pub stage: String,        // "decoding", "compositing", "encoding", ...
    pub percent: f32,         // 0.0 to 100.0
    pub current_frame: Option<u64>,
    pub total_frames: Option<u64>,
    pub eta_seconds: Option<f32>,
    pub message: Option<String>,
}
```

The stream is a Rust `mpsc::Receiver<Progress>`. The runtime drops the receiver on `cancel()`. The caller may drop the receiver to unsubscribe from progress without cancelling the job.

# Architecture

```
┌────────────────────────────────────────────────────────┐
│  Caller                                                 │
│  │                                                     │
│  ├──submit(action)──▶ ┌─────────────────┐              │
│  │                    │   Scheduler     │              │
│  │                    │   (single thr.) │              │
│  │                    │                 │              │
│  │                    │  - validate     │              │
│  │                    │  - apply state  │              │
│  │                    │  - record hist  │              │
│  │                    │  - dispatch job │              │
│  │                    └────────┬────────┘              │
│  │                             │                       │
│  │                             ▼                       │
│  │              ┌──────────────────────────┐           │
│  │              │   Worker Pool            │           │
│  │              │   ┌────────┐  ┌────────┐  │           │
│  │              │   │ Job A  │  │ Job B  │  │           │
│  │              │   └────┬───┘  └────┬───┘  │           │
│  │              │        │           │      │           │
│  │              │        ▼           ▼      │           │
│  │              │   progress      progress  │           │
│  │              │   channel       channel  │           │
│  │              └─────────┬────────┬───────┘           │
│  │                        ▼        ▼                    │
│  │                    Progress stream                   │
│  │                                                     │
│  └──wait() / poll()──▶ JobHandle                        │
└────────────────────────────────────────────────────────┘
```

The Scheduler is the single source of truth for project state. Worker pools are stateless; they accept jobs and report results.

# Alternatives

### A. Pure synchronous (FFmpeg-style)

**Rejected.** Cannot serve concurrent agents, cannot report progress, cannot cancel. Forces agents to implement their own retry/timeout logic on top.

### B. Actor model (per-project actor)

**Considered.** Each project is an actor with a mailbox. Messages are actions. Strong isolation; well-understood. **Rejected** because: (a) Rust actor frameworks (Actix, Bastion) add dependencies, (b) the project state does not need actor-style isolation when a single-threaded scheduler already provides it, (c) debugging actor systems is harder than debugging a single-threaded scheduler.

### C. Tokio-based async

**Considered.** All actions are async tasks. Tokio is the de facto standard. **Accepted as a dependency for the worker pools** (Tokio's runtime is excellent for I/O and concurrency). The Scheduler itself remains synchronous for clarity.

### D. Replay log (Kafka-style event sourcing)

**Considered.** The action log is the source of truth; the in-memory state is a cache. **Accepted** for the on-disk representation (see RFC-0010). **Rejected** for the in-memory representation: rebuilding state from a long log on every read is too slow for an interactive runtime.

# Drawbacks

- **Single-threaded Scheduler is a bottleneck.** All project mutations serialize through it. For typical projects (one editor, dozens of actions per second) this is fine. For pathological workloads (thousands of actions per second from a swarm of agents) it could become a bottleneck. Mitigated by: (a) per-project schedulers (independent projects don't contend), (b) bulk-action API for batch updates.
- **Cooperative cancellation is not free.** Workers must check the cancellation flag at safe points. Long inner loops (e.g. decoding a single frame) cannot be interrupted mid-frame. Mitigated by: bounding inner loop iterations.
- **Idempotency requires the caller to track JobIds.** If a caller does not provide one, the runtime mints a new one and duplicate submissions run twice. This is a sharp edge. Mitigated by: clear documentation, default behavior logged loudly.

# Future Possibilities

- **Pre-emption.** Today, a render job holds the GPU until it finishes or is cancelled. A future scheduler could time-slice GPU access across jobs.
- **Speculative execution.** The runtime could pre-decode the next clip in a render while the current clip encodes, hiding latency. Complex to implement, high payoff.
- **Distributed execution.** A future `flow-server` could ship sub-jobs to other servers. Requires a serialization layer for jobs (the project state and the action history must travel with the job).
- **Resource budgets.** The Scheduler could enforce a per-project memory or GPU budget. Today, all projects in a runtime share the same hardware.

# Unresolved Questions

1. **Default worker pool sizes.** What is a good default for render workers? For AI workers? Per-device budgets?
2. **Backpressure.** If the Scheduler is overwhelmed, what should happen to new submissions? Reject? Queue? Block?
3. **Action-level timeouts.** Should actions have a default timeout? Per-action-type? Configurable?
4. **Job persistence.** If the runtime crashes mid-job, can we resume? Today, no. Job state lives in memory only.
5. **Cancellation safety of AI backends.** Some AI models cannot be safely cancelled mid-inference. Do we accept the cost of letting them finish, or do we kill the worker thread (unsafe)?

---

**Next RFC**: RFC-0003 — Action System
