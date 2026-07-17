# RFC-0010: Project Format

| Field | Value |
|---|---|
| Status | Draft |
| Author | Mavis |
| Created | 2026-07-17 |
| Depends on | RFC-0001, RFC-0003, RFC-0004, RFC-0009 |

*This is an extension RFC. Core RFCs must be self-contained; this RFC may reference but must not be required by any core RFC.*

---

# Summary

This RFC defines the **on-disk format of a Flow project**: the directory layout, the file types, the serialization strategy, and the versioning conventions. A project is a self-contained directory (typically named `*.flow/`) that can be opened, edited, saved, copied, and shared.

The project format is the **contract between Flow and the outside world**. It must be:

- **Self-describing** — a third party can inspect a project directory and understand its structure.
- **Versioned** — old projects open cleanly on new runtimes; new projects are recognizable by old runtimes.
- **Diffable** — text changes in the project (timeline edits, action additions) are visible in `git diff`.
- **Portable** — moving a project between machines, users, and operating systems works without loss.
- **Resilient** — partial corruption (a truncated action log, a missing thumbnail) does not destroy the project.

# Motivation

Flow projects are the unit of work for agents and humans. They travel between:

- A developer's laptop and a CI server.
- One user and another (sharing a project via Git, Dropbox, or S3).
- A Flow v1 runtime and a Flow v2 runtime.
- A Flow runtime and a third-party conform tool (Resolve, Premiere, OTIO viewer).

Each of these scenarios requires a project format that is well-defined and stable. The format is also the audit log: a Flow project is, in effect, a git repository for video editing decisions. The action log is the commit history; the OTIO file is the working tree.

The format must be **simple to inspect**. A user who has never seen Flow can `cat` the project directory and understand what's in it. No binary blobs, no proprietary formats, no surprise.

# Goals

- Use a directory-based project format (`my-project.flow/`).
- Store the timeline as `timeline.otio` (OTIO JSON).
- Store the action log as `actions.jsonl` (append-only JSON Lines).
- Store project metadata as `project.toml` (TOML).
- Store media in a structured subdirectory (`media/`, `cache/`).
- Version every file with a schema version field.
- Use content-addressable storage for caches and large media.
- Be git-friendly (text files, line-based, no large binaries in the working tree).
- Support atomic saves (write to temp, rename).
- Support crash recovery (rebuild state from action log on next open).

# Non Goals

- This RFC does **not** define the in-memory representation (RFC-0004).
- It does **not** define the wire protocol for `flow-server` (out of scope).
- It does **not** define cloud storage of projects (a plugin concern).
- It does **not** define encryption or access control (a separate concern; out of scope for v1).
- It does **not** define a binary format for media (media is stored as-is, in its original format).

# Guide-level explanation

A Flow project is a directory:

```
my-launch-video.flow/
├── project.toml              # project metadata
├── timeline.otio            # current timeline state
├── actions.jsonl             # append-only action log
├── media/
│   ├── original/             # original media (only if copied in)
│   ├── proxies/              # low-res proxies
│   └── transcoded/           # format-converted media
├── cache/
│   ├── decoded/              # frame caches (LRU, content-addressable)
│   ├── waveforms/            # audio waveform caches
│   └── thumbnails/           # timeline thumbnails
├── checkpoints/              # named snapshots of the action log
└── .flow/
    ├── lock                  # advisory lock when project is open
    ├── session.json          # current session state
    └── logs/                 # runtime logs for this project
```

Opening a project:

```rust
let project = Runtime::open_project("./my-launch-video.flow/")?;
// The runtime:
// 1. Reads project.toml → project spec
// 2. Reads timeline.otio OR rebuilds from actions.jsonl
// 3. Loads asset index from the rebuilt timeline
// 4. Returns a Project handle
```

Saving a project:

```rust
project.save()?;
// The runtime:
// 1. Atomically writes timeline.otio (write to .otio.tmp, rename)
// 2. Appends new actions to actions.jsonl
// 3. Updates project.toml if metadata changed
// 4. Flushes any pending cache writes
```

# Reference-level explanation

## The top-level layout

| File / dir | Format | Mutable? | Purpose |
|---|---|---|---|
| `project.toml` | TOML | yes | Project metadata: name, fps, resolution, schema version. |
| `timeline.otio` | OTIO JSON | yes (atomic) | Current timeline state. Derived from `actions.jsonl`. |
| `actions.jsonl` | JSON Lines | append-only | The source of truth. Every applied action. |
| `media/original/` | original files | yes | Original media (only if explicitly copied in). |
| `media/proxies/` | encoded media | yes | Proxies for fast preview. |
| `media/transcoded/` | encoded media | yes | Format-converted media. |
| `cache/decoded/` | binary frames | yes (LRU) | Cached decoded frames. |
| `cache/waveforms/` | binary | yes | Cached audio waveforms. |
| `cache/thumbnails/` | images (PNG/WebP) | yes | Timeline thumbnails. |
| `checkpoints/` | text | append-only | Named snapshots of the action log. |
| `.flow/lock` | text | yes | Advisory lock (PID + host). |
| `.flow/session.json` | JSON | yes | Current session state (open projects, etc.). |
| `.flow/logs/` | text | append-only | Runtime logs scoped to this project. |

The top-level `*.flow/` extension is a convention, not enforced. A Flow project is a directory; the extension is a hint to file managers and humans.

## `project.toml`

```toml
[project]
name = "My Launch Video"
schema_version = 1
created_at = "2026-07-17T00:00:00Z"
updated_at = "2026-07-17T04:00:00Z"

[spec]
fps = 30.0
resolution = { width = 1920, height = 1080 }
sample_rate = 48000
channels = 2
color_space = "bt709"

[media]
relative_paths = true   # store paths relative to the project dir
hash_algorithm = "sha256"

[render]
default_preset = "tiktok-vertical-1080"
hardware_accel = "auto"  # auto | cpu | cuda | metal | vulkan

[history]
checkpoint_interval = 50  # create a checkpoint every 50 actions
```

`schema_version` is the project format version. The runtime refuses to open a project with an unrecognized version (with a clear error message and migration instructions).

## `timeline.otio`

The current timeline as OTIO JSON. The schema is OTIO's `Timeline.1`. Flow extends it via OTIO metadata and SchemaDefs (see RFC-0004).

```json
{
  "OTIO_SCHEMA": "Timeline.1",
  "metadata": {
    "flow": {
      "schema_version": 1,
      "last_action_id": "act_01HXY..."
    }
  },
  "name": "My Launch Video",
  "tracks": {
    "OTIO_SCHEMA": "Stack.1",
    "children": [ /* tracks */ ]
  }
}
```

The file is rewritten atomically on save (write to `timeline.otio.tmp`, then rename). The file is not human-edited; it is a cache of the current state.

## `actions.jsonl`

One JSON object per line, append-only:

```jsonl
{"v":1,"id":"act_01HXY...","ts":"2026-07-17T00:01:00Z","actor":"agent:claude-sonnet-4.5","intent":"add interview clip","action":{"op":"clip.add",...},"inverse":{...},"result":{...}}
{"v":1,"id":"act_01HXY...","ts":"2026-07-17T00:01:05Z","actor":"user:alice","intent":"trim intro","action":{"op":"clip.trim",...},"inverse":{...},"result":{...}}
```

Properties:
- Append-only: lines are never deleted, modified, or reordered in the file.
- Each line is a complete, self-describing JSON object.
- The `v` field is the action schema version (independent of the project schema version).
- The `id` is a UUID v7 (time-ordered).
- The `actor` identifies who made the change.
- The `intent` is a free-text description (set by the agent or user).
- The `action` is the action itself.
- The `inverse` is the pre-computed inverse.
- The `result` is the result of the application.

The file is the **source of truth**. The `timeline.otio` is a cache that can be regenerated by replaying all actions.

## Recovery from corruption

If `timeline.otio` is corrupted or missing, the runtime rebuilds it by replaying `actions.jsonl`. This is the same algorithm used on a clean open, but starting from an empty timeline.

If `actions.jsonl` is partially corrupted (one bad line), the runtime:

1. Detects the bad line (JSON parse error).
2. Logs the error.
3. Replays all lines up to (but not including) the bad one.
4. Marks the project as `degraded` and surfaces a warning to the user.
5. Offers to repair (truncate the bad line, accept the loss).

If the corruption is in the middle of a `Batch` action (some lines valid, some not), the runtime rolls back the partial batch and treats the entire batch as failed.

## `checkpoints/`

Named snapshots of the action log. Created explicitly by the user (`project.checkpoint("before-render")`) or automatically at intervals (configurable in `project.toml`).

```
checkpoints/
├── initial.flow              # checkpoint at the start
├── before-render.flow        # user-named checkpoint
├── auto-2026-07-17.flow      # automatic checkpoint
└── ...
```

Each checkpoint is a copy (or hard link) of the action log up to a point. They enable "rewind to a known state" semantics.

The format of a checkpoint is identical to the action log, just truncated. Checkpoints are **immutable**: once created, they are not modified. To "go back" to a checkpoint, the runtime creates a new history that reverts to that state.

## The cache directory

The cache is content-addressable:

```
cache/decoded/
├── ab/
│   └── cd/
│       └── abcd1234...        # frames for content hash abcd1234...
└── ...

cache/waveforms/
├── foo.mp4.wav.json
└── ...

cache/thumbnails/
├── frame_0001.webp
├── frame_0030.webp
└── ...
```

The cache uses the **first 2 bytes of the SHA-256 hash as a 2-level subdirectory** to avoid having one giant directory. This is the same trick git uses for `.git/objects/`.

The cache is **safe to delete** at any time. The runtime rebuilds it on demand. Deleting the cache does not affect the project state.

## Atomic writes

Every file write in the project is atomic:

1. Write to `<file>.tmp`.
2. `fsync` the temp file.
3. Rename `<file>.tmp` to `<file>`.
4. `fsync` the parent directory.

The rename is atomic on POSIX and on Windows (with the right flags). This guarantees that the project is never observed in a half-written state, even if the runtime crashes mid-save.

## Crash recovery

If the runtime crashes (process killed, power loss), the next open:

1. Reads `timeline.otio` if it exists and is valid.
2. If `timeline.otio` is missing or corrupt, rebuilds from `actions.jsonl`.
3. Checks the last `action.id` in `timeline.otio` (if any) against the last `id` in `actions.jsonl`. If they differ, replays the missing actions.
4. Acquires the lock (creating `.flow/lock` if absent).
5. Opens the project.

The lock is a PID file: it contains the process ID and the hostname. If the process is dead, the lock is stale; the runtime removes it on open (with a warning). A live lock is respected: only one process opens the project for writing at a time. Multiple readers are allowed.

## Versioning

Two version numbers:

- **Project format version** (in `project.toml`): the version of the directory layout and file semantics.
- **Action schema version** (in each action line): the version of the action JSON structure.

The project format version is bumped on breaking changes (e.g. a new file in the layout, a renamed field). The runtime ships with a migration tool that upgrades projects between versions.

The action schema version is bumped when actions change. Old actions are still readable; new actions in old projects are flagged.

v1: project format version = 1, action schema version = 1.

## Portability

A project is portable across:

- **Machines** — file paths are relative or resolved via media linkers.
- **Users** — no user-specific data is stored in the project.
- **Operating systems** — paths use forward slashes; line endings are LF; character encoding is UTF-8.
- **Flow versions** — within the same major version, projects are forward-compatible.
- **Cloud storage** — the directory can be synced to S3, Dropbox, etc. without changes.

The portability cost: media is **not** included by default. A project that references a 50 GB media file on a local disk is not self-contained. The user can `flow project bundle` to create a self-contained `.flowbundle` archive that includes all referenced media (deferred to v2; v1 expects the user to handle media portability manually).

# Architecture

```
┌────────────────────────────────────────────────────────────┐
│                     my-project.flow/                         │
│                                                              │
│   project.toml         ─── metadata                          │
│   timeline.otio        ─── current state (cache)             │
│   actions.jsonl        ─── source of truth                   │
│   media/               ─── original + proxies + transcoded   │
│   cache/               ─── decoded + waveforms + thumbnails  │
│   checkpoints/         ─── named snapshots                   │
│   .flow/                                                    │
│     lock              ─── advisory lock                       │
│     session.json      ─── current session                     │
│     logs/             ─── runtime logs                        │
│                                                              │
└────────────────────────────────────────────────────────────┘
              │                                       │
              │ save                                  │ open
              ▼                                       ▼
       ┌────────────────┐                    ┌────────────────┐
       │  Project        │                   │  Project        │
       │  State          │                   │  State          │
       │  (in-memory)    │                   │  (in-memory)    │
       └────────────────┘                    └────────────────┘
```

# Alternatives

### A. Single-file project format (e.g. `project.zip`)

**Considered.** A single zip file is easier to share. **Rejected** for v1 because: (a) hard to inspect without unzipping, (b) cache invalidation is harder, (c) git does not handle zip files well. A `.flowbundle` zip may come in v2 for sharing.

### B. Database file (SQLite) for everything

**Rejected.** Loses git-diff-friendliness, harder to inspect, harder to recover from corruption, more dependencies.

### C. JSON file with everything (no `actions.jsonl`)

**Rejected.** A single JSON file for the action log is unwritable for large projects; the entire file must be rewritten on every action. JSON Lines is append-only and streamable.

### D. Per-timeline-version files (timeline_v1.otio, timeline_v2.otio)

**Rejected.** Complicates the on-disk format. The version is in the file itself.

# Drawbacks

- **Many small files.** A typical project has dozens of files. Mitigated by: clear directory layout, well-documented in `docs/`.
- **No atomicity across files.** A crash between writing `timeline.otio` and appending to `actions.jsonl` could leave them inconsistent. Mitigated by: write `timeline.otio` last (so it reflects the new state), and replay on open if inconsistency is detected.
- **Cache bloat.** The cache can grow without bound. Mitigated by: configurable cap, LRU eviction, manual `flow cache clean` command.
- **Lock semantics.** The advisory lock is not bulletproof (a crashed process leaves a stale lock; a network filesystem may not honor flock). Mitigated by: the lock is a hint, not a guarantee; the runtime also uses action IDs for optimistic concurrency.
- **OTIO dependency.** The on-disk timeline format is OTIO. If OTIO makes a breaking change, Flow must follow. Mitigated by: pinning OTIO versions in Flow.

# Future Possibilities

- **`.flowbundle` archives.** A zip-based format that includes media, for true single-file portability.
- **Cloud-backed projects.** The project directory lives in S3; the runtime syncs lazily.
- **Content-addressable media.** v2 may move media into a CAS, sharing files across projects.
- **Encrypted projects.** v2 may support encrypted projects for sensitive content.
- **Branching projects.** A v2 feature: fork a project, edit both, merge or abandon.

# Unresolved Questions

1. **Cross-platform line endings.** Force LF on all platforms? Allow CRLF on Windows? Currently planning LF everywhere; need to verify git on Windows handles it.
2. **Large file storage (LFS).** Should Flow projects integrate with git-lfs for media? Out of scope for v1 but worth documenting.
3. **Symlinks.** Should the runtime follow symlinks in the project directory? Or treat them as opaque files?
4. **Hidden directories.** Is `.flow/` the right name? `.flow/` (dot prefix) hides it on Unix but not Windows. Acceptable.
5. **Permissions.** When the project is on a shared filesystem, should the runtime chmod files to a specific mode? Out of scope for v1.

---

**End of extension RFCs.** With RFCs 0008-0010, the core and extensions of the Flow architecture are specified.

The next phase is **ADRs** (decisions that have been made) and then **Specs** (contracts to be implemented). The Specs are written from these RFCs; the RFCs are the input, not the output, of the Spec phase.
