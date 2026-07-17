# RFC-0009: Asset Management

| Field | Value |
|---|---|
| Status | Draft |
| Author | Mavis |
| Created | 2026-07-17 |
| Depends on | RFC-0001, RFC-0003, RFC-0004 |

*This is an extension RFC. Core RFCs must be self-contained; this RFC may reference but must not be required by any core RFC.*

---

# Summary

This RFC defines how the Flow runtime **manages media assets**: the storage layout on disk, the reference model, the resolution from abstract references to concrete files, the cache, and the lifecycle. Asset management is the bridge between a Flow project (which references media by abstract identifiers) and the underlying files (which live somewhere on disk or in cloud storage).

The key abstraction is the **Media Reference** (already defined in OTIO as `ExternalReference`, `GeneratedReference`, `MissingReference`). This RFC defines how Flow resolves, caches, and maintains these references.

# Motivation

Media assets are the largest, most fragile, and most distributed part of a Flow project. The same project may reference:

- Local files on the user's disk.
- Files on a shared network mount.
- Files in cloud storage (S3, GCS, Azure Blob).
- Generated content (a solid color, a noise pattern, a text card).
- Files that have been moved, renamed, or deleted since the project was last opened.
- Files that are being transcoded in the background.

The runtime must handle all of these uniformly. An agent (or a user) opens a project and the runtime resolves all references transparently, falling back gracefully when references are missing.

The asset system also has to support **portability**: a project can be moved from one machine to another, from local to cloud, from one user to another. The references are abstract; the resolution is per-environment.

# Goals

- Use OTIO's `MediaReference` schema as the underlying reference model.
- Support `ExternalReference` (file URL/path), `GeneratedReference` (synthesized), `MissingReference` (placeholder).
- Define a **Media Linker** plugin type (already in RFC-0005) for resolving references to concrete locations.
- Define a project-relative cache for transcoded and proxy media.
- Handle missing references gracefully: surface as `MissingReference`, do not crash.
- Support hot-swap of media (the user replaces a file in place; the runtime picks it up).
- Track file checksums to detect media changes.
- Support per-asset metadata (creation date, source URL, license, etc.).

# Non Goals

- This RFC does **not** define a content-addressable storage system (deferred).
- It does **not** define asset transcoding (separate from rendering; deferred).
- It does **not** define cloud storage backends (plugins handle that).
- It does **not** define a UI for asset management (out of scope).

# Guide-level explanation

A project references media by abstract identifiers:

```json
{
  "OTIO_SCHEMA": "ExternalReference.1",
  "target_url": "media://interview.mp4",
  "available_range": { "start_time": { "value": 0, "rate": 30 }, "duration": { "value": 1800, "rate": 30 } }
}
```

When the project is opened, the runtime asks the media linkers to resolve `media://interview.mp4` to a concrete file path. The resolution is per-environment: a developer's machine may resolve to `~/projects/footage/interview.mp4`, a CI runner may resolve to `/var/flow/footage/interview.mp4`, a cloud deployment may resolve to a signed S3 URL.

If the resolution fails, the reference is marked as `MissingReference` and the affected clips render as placeholders (a flat color with the asset name overlaid).

# Reference-level explanation

## The reference model

```rust
pub enum MediaReference {
    External(ExternalReference),
    Generated(GeneratedReference),
    Missing(MissingReference),
}

pub struct ExternalReference {
    pub target_url: String,                // abstract URL or path
    pub available_range: Option<TimeRange>, // known range of the source
}

pub struct GeneratedReference {
    pub kind: GeneratedKind,               // SolidColor | Noise | Text | ...
    pub params: serde_json::Value,         // kind-specific
}

pub struct MissingReference {
    pub original: Box<MediaReference>,     // what we tried to resolve
    pub reason: String,                    // why it failed
    pub last_known_path: Option<String>,
}
```

The runtime always works with a resolved `MediaReference`. The `ExternalReference` is a hint; the actual file path is determined by the media linkers at runtime.

## The media linker

A media linker is a plugin (RFC-0005) that resolves a `target_url` to a concrete path:

```rust
pub trait MediaLinker: Send + Sync {
    fn id(&self) -> &str;
    fn link(&self, target_url: &str, context: &LinkContext) -> Result<LinkedMedia>;
    fn supports(&self, target_url: &str) -> bool;  // quick check
}

pub struct LinkedMedia {
    pub local_path: PathBuf,                // where the file is now
    pub metadata: MediaMetadata,            // probed info
    pub cache_hit: bool,                    // was this in the project cache?
}

pub struct LinkContext {
    pub project_path: PathBuf,              // the .flow/ directory
    pub flow_root: PathBuf,                 // $FLOW_ROOT env var
    pub user_dirs: Vec<PathBuf>,            // additional search dirs
}
```

Multiple media linkers may be registered. The runtime tries them in priority order until one returns a successful link.

### Built-in media linkers

- **File linker** (priority 100): resolves `file://` URLs and relative paths.
- **Project-relative linker** (priority 200): resolves paths relative to the project directory.
- **Flow cache linker** (priority 300): resolves `flow://cache/...` to the project's cache directory.
- **HTTP linker** (priority 400): downloads from `http://` or `https://` URLs (with cache).

Plugins can add more (S3, GCS, Azure, custom CDN, etc.).

## The project cache

Every Flow project has a cache directory:

```
my-project/
├── timeline.otio
├── actions.jsonl
├── media/
│   ├── original/                 # original media (if copied in)
│   ├── proxies/                  # low-res proxies for fast preview
│   └── transcoded/               # format-converted media
└── cache/
    ├── decoded/                  # cached decoded frames (LRU)
    ├── waveforms/                # audio waveform caches
    └── thumbnails/               # timeline thumbnails
```

The cache is **project-scoped** (lives inside the project directory) so projects are self-contained. The cache is **content-addressable** (files are named by their content hash) so cache entries can be shared across projects in the future.

v1 does not share caches across projects. v2 will.

## Proxies

For long media files, the runtime can create **proxies** (low-resolution, low-bitrate copies) for fast preview. Proxy creation is a separate operation from rendering; the user invokes it explicitly.

```rust
let job = project.create_proxies(ProxySpec::default())?;
job.wait()?;
```

After proxies are created, the runtime can use them for preview while keeping the originals for final render. v1 implements proxy-aware decode; v2 will implement proxy-aware rendering.

## The asset index

For fast lookup, the runtime maintains an in-memory index of all assets in the project:

```rust
pub struct AssetIndex {
    pub entries: HashMap<MediaId, AssetEntry>,
}

pub struct AssetEntry {
    pub id: MediaId,                     // stable ID, minted on first reference
    pub reference: MediaReference,
    pub resolved: Option<LinkedMedia>,    // None if not yet resolved
    pub metadata: MediaMetadata,
    pub checksum: Option<String>,        // content hash, computed lazily
    pub last_accessed: SystemTime,
    pub usage_count: u64,                 // how many clips reference this asset
}
```

The index is updated on every action that adds, removes, or modifies a clip. The index is **not** persisted (it is rebuilt on project open by walking the timeline).

## Media lifecycle

```
[1] Reference added
       │ (e.g. clip.add references media://foo.mp4)
       ▼
[2] Resolved lazily on first use
       │ (or eagerly on project open, configurable)
       ▼
[3] Media probed (ffprobe)
       │ → metadata + checksum
       ▼
[4] Available for rendering
       │
       ▼
[5] On access: last_accessed updated
       │ cache may evict cold entries
       ▼
[6] On project close: index dropped, cache persisted
```

Media is **never** copied or moved by the runtime unless explicitly requested (`asset.copy` action). The runtime always references the original.

## Hot-swap

If a file at the resolved path is modified (detected by mtime or checksum), the runtime:

1. Marks the asset entry as dirty.
2. On next render, re-probes and re-decodes.
3. Does not modify the timeline (the reference is the same).

If a file is deleted, the reference is marked as `MissingReference`. The clip is not removed; the user can replace it later.

## Checksums

The runtime computes a SHA-256 checksum of each media file on first access. The checksum is stored in the asset index (in memory) and optionally persisted in the project metadata.

Checksums are used for:
- Cache invalidation (cache entries are content-addressed).
- Detecting media changes (hot-swap).
- Deduplication (two references to the same file are recognized).

v1 computes checksums lazily on first access. v2 may compute them eagerly for small files.

## Asset-level actions

The action system (RFC-0003) includes asset-level operations:

```rust
pub enum Action {
    // ... core actions ...
    AssetAdd { reference: MediaReference, alias: Option<String> },
    AssetRemove { asset: MediaId },
    AssetRename { asset: MediaId, alias: String },
    AssetCopy { asset: MediaId, destination: String },  // copy into project cache
    AssetRevealInFinder { asset: MediaId },
}
```

`AssetAdd` adds a media reference to the project's asset index (without using it in a clip). `AssetCopy` copies the file into the project's `media/` directory and updates the reference. `AssetRevealInFinder` is a UI hint; the action system has no UI, but the SDK can react to it.

# Architecture

```
┌────────────────────────────────────────────────────────────┐
│                       Runtime                               │
│                                                              │
│  ┌────────────────┐                                          │
│  │ Asset Index    │  (in-memory, rebuilt on project open)    │
│  │                │                                          │
│  │ - MediaId →    │                                          │
│  │   MediaRef     │                                          │
│  │   LinkedMedia  │                                          │
│  │   Metadata     │                                          │
│  └────────┬───────┘                                          │
│           │                                                  │
│           ▼                                                  │
│  ┌──────────────────────────────────────┐                    │
│  │ Media Linker Registry                │                    │
│  │  ┌─────────────┐  ┌─────────────┐    │                    │
│  │  │ File linker │  │ HTTP linker │ ...│ (plugins)           │
│  │  └─────────────┘  └─────────────┘    │                    │
│  └────────┬─────────────────────────────┘                    │
│           │                                                  │
│           ▼                                                  │
│  ┌──────────────────────────────────────┐                    │
│  │ Project Cache                         │                    │
│  │  - media/original/                    │                    │
│  │  - media/proxies/                     │                    │
│  │  - media/transcoded/                  │                    │
│  │  - cache/decoded/  (LRU)              │                    │
│  │  - cache/waveforms/                   │                    │
│  │  - cache/thumbnails/                  │                    │
│  └──────────────────────────────────────┘                    │
│                                                              │
└────────────────────────────────────────────────────────────┘
```

# Alternatives

### A. Treat assets as part of the project (copy everything in)

**Rejected.** Doubles disk usage, breaks references to large original media, complicates collaboration.

### B. Use a content-addressable store (like git) for all assets

**Considered.** Content-addressable storage is elegant but requires copying on add. **Deferred** to v2; the v1 cache is content-addressable but assets live outside the project.

### C. Cloud-first (no local files, everything in S3)

**Rejected.** Local-first is a core principle of Flow (per ADR-0001 once accepted). Cloud is a plugin concern.

### D. Database for the asset index

**Rejected.** The index is small (one entry per asset) and rebuildable. A database is overkill. A flat file (or just in-memory) suffices.

# Drawbacks

- **Media linker resolution is sequential.** Each linker is tried in order. For deep linker chains, this adds latency. Mitigated by: a quick `supports()` check to skip non-matching linkers.
- **Cache invalidation is by content hash.** A small media change (one frame) invalidates the entire cache entry. Mitigated by: chunked content hashing (deferred to v2).
- **No deduplication across projects.** v1 does not detect that two projects reference the same file. Deferred to v2.
- **HTTP linker is bandwidth-heavy.** A 10 GB media file would take a long time to download. Mitigated by: streaming decode (deferred; v1 fully downloads then decodes).
- **Checksums are lazy.** A reference that is never rendered never has its checksum computed. This is a feature (don't read files we don't need) and a bug (we can't tell if a file changed without reading it).

# Future Possibilities

- **Content-addressable storage across projects.** Detect and share cache entries.
- **Streaming decode from HTTP.** Begin rendering before the full file is downloaded.
- **Asset transcoding as a first-class operation.** Convert a media file to a project-preferred format.
- **Asset metadata extraction.** Auto-extract EXIF, color space, audio loudness, and store as asset metadata.
- **Asset versioning.** Track changes to the same media file over time.
- **Asset search.** A full-text and metadata search over the project's assets.

# Unresolved Questions

1. **Cache size policy.** Default cap? Per-project? Global? User-configurable?
2. **HTTP linker auth.** How does the HTTP linker authenticate? Bearer tokens in the URL? OAuth? User-provided at resolve time?
3. **Proxy creation cost.** Proxy creation is itself a render. Should it be free? Billed? Capped?
4. **Cross-project asset references.** v1 forbids them. v2 may allow with a special linker.
5. **Asset deletion safety.** What if a clip references an asset that the user tries to delete? Refuse? Force? Show impact?

---

**Next**: `0003-project-format.md`
