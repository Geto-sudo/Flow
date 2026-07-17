# OpenReelio — Reverse Engineering Notes

> Source: [github.com/Augani/openreel-video](https://github.com/Augani/openreel-video) (4.4k stars, 603 forks, MIT, active 2026). Online demo at [openreel.video](https://openreel.video).

---

## 1. What OpenReelio Is

OpenReelio is a **100% browser-based, professional-grade video editor** — an open-source CapCut alternative. It runs entirely client-side using:
- **WebCodecs** for hardware-accelerated decode/encode.
- **WebGPU** for GPU rendering and compositing.
- **Web Audio API** for audio mixing and effects.
- **IndexedDB** for local project storage.
- **MediaBunny** as the underlying media engine.
- **React 18 + TypeScript + Zustand** for the UI.

**Key positioning**: no server, no upload, no installation, no watermarks. Edit 4K video in Chrome. Export to MP4/WebM/ProRes.

## 2. Monorepo Architecture

```
openreel-video/
├── apps/
│   ├── web/                    # React frontend (~66k LOC)
│   │   └── src/
│   │       ├── components/
│   │       │   └── editor/      # Timeline, Preview, Inspector panels
│   │       ├── stores/          # Zustand state management
│   │       ├── services/        # Auto-save, shortcuts, recording
│   │       ├── bridges/         # Engine ↔ UI coordination
│   │       ├── hooks/           # React hooks
│   │       └── pages/           # Routing
│   └── image/                  # Image editor app
│
├── packages/
│   └── core/                   # Engine (~59k LOC)
│       └── src/
│           ├── video/          # Video engine, WebGPU rendering
│           ├── audio/          # Web Audio API, effects
│           ├── graphics/       # Canvas + THREE.js
│           ├── text/           # Text rendering + animations
│           ├── export/         # MP4/WebM/ProRes encoding
│           ├── timeline/       # Track + clip management
│           ├── actions/        # Edit action system (undo/redo)
│           ├── storage/        # IndexedDB persistence
│           ├── animation/      # Keyframe animation
│           ├── effects/        # Visual effects
│           ├── wasm/           # AssemblyScript modules (FFT, WAV, beat)
│           └── ai/             # AI features
│
├── infra/
│   └── transcribe-gpu/         # GPU transcription service
└── scripts/
```

Total ~130k LOC. Monorepo managed by `pnpm workspace`.

## 3. The Core Engine Architecture (the interesting part)

### 3.1 Engine Separation

Each engine is a **standalone, framework-agnostic** TypeScript module:

| Engine | LOC | Responsibility |
|---|---|---|
| `video-engine.ts` | ~67KB | Decode, composite, color grading, chroma key |
| `audio-engine.ts` | ~27KB | Mix, effects, beat detection |
| `graphics-engine.ts` | ~53KB | Shapes, SVG, stickers |
| `text-engine.ts` | (similar) | Titles, karaoke subtitles, 20+ animations |
| `export-engine.ts` | ~41KB | Encoding (WebCodecs) |
| `action-executor.ts` | ~41KB | Undoable action system |
| `action-validator.ts` | ~35KB | Action validation |
| `clip-manager.ts` | ~19KB | Timeline clip logic |
| `render-bridge.ts` | ~31KB | UI ↔ engine coordination |
| `effects-bridge.ts` | ~29KB | Effect application bridge |

This is a healthy **vertical separation by media type + horizontal separation by concern** (engine, action, bridge).

### 3.2 The Action System (the most reusable idea)

```typescript
interface Action {
  type: string;        // "clip.add" | "clip.trim" | "effect.apply" | ...
  payload: any;
  inverse?: Action;    // pre-computed for undo
}

class ActionExecutor {
  execute(action: Action): ActionResult {
    // 1. Validate
    validator.validate(action);
    // 2. Apply to state store
    store.dispatch(action);
    // 3. Generate inverse (if not pre-computed)
    if (!action.inverse) action.inverse = inverseGenerator.generate(action);
    // 4. Push to history
    history.push(action);
    // 5. Notify subscribers
    bridges.notify(action);
    return result;
  }

  undo(): void { ... }
  redo(): void { ... }
}
```

This is **the** pattern for any editor's state management. Every edit is an action, every action has an inverse, history is a stack. The validator rejects invalid actions before they reach state.

**Flow's take**: this is how Flow's `flow-core` should manage timeline mutations. Actions are serializable → agents can replay them, agents can plan them, humans can diff them.

### 3.3 The Bridge Pattern

The UI never touches engines directly. It goes through bridges:

```typescript
class PlaybackBridge {
  play() { return core.video.playback.start(); }
  pause() { return core.video.playback.pause(); }
  seek(time: number) { return core.video.playback.seek(time); }
}
class RenderBridge {
  requestFrame(time: number): Promise<VideoFrame> { ... }
  // debounced, queues rendering
}
class EffectsBridge {
  applyEffect(clipId: string, effect: EffectConfig) { ... }
}
```

This is the **same pattern as MLT's services** — the bridge wraps the engine with a clean interface. Flow should adopt this.

### 3.4 The State Store (Zustand)

```typescript
const useTimelineStore = create<TimelineState>((set) => ({
  tracks: [],
  clips: {},
  selectedClipId: null,
  playheadPosition: 0,
  // ... all derived state via selectors
}));
```

Zustand is a minimal reactive state container. Updates are immutable. Selectors are pure functions. The store is the single source of truth for the UI.

**Flow's take**: in `flow-server`, the in-memory state of an active project is a similar reactive store. In `flow-cli`, the same store can be a local SQLite or OTIO file.

### 3.5 The Export Pipeline

```typescript
class ExportEngine {
  async export(settings: VideoExportSettings): Promise<Blob> {
    // 1. Collect all timeline segments
    // 2. For each frame:
    //    a. Composite in WebGPU
    //    b. Encode via WebCodecs (hardware)
    // 3. Mux audio + video into MP4/WebM container
    // 4. Return Blob
  }
}
```

This is **synchronous frame-by-frame composition + WebCodecs encoding**. The WebCodecs `VideoEncoder` takes raw `VideoFrame` and produces encoded chunks. The browser handles the encoding, often on GPU.

**Limitation**: WebCodecs requires the browser to support it. Chrome/Edge 94+, Firefox 130+, Safari 16.4+. Older browsers fall back to canvas-based export (much slower).

### 3.6 The MediaBunny Dependency

OpenReelio recently moved from FFmpeg.wasm to **MediaBunny** (a TypeScript-first media library). This is significant because:
- MediaBunny is **modular**: you import only what you need.
- MediaBunny is **type-safe**: the API is fully typed.
- MediaBunny is **browser-native**: uses WebCodecs under the hood.

Flow should study MediaBunny's API as a reference for what a "modern media runtime in JS" looks like.

## 4. AI Integration (the relevant part for Flow)

OpenReelio has a dedicated `ai/` directory and ships these AI features:
- **AI upscaling** (WebGPU shaders, 2x/4x).
- **Speech-to-text** (for subtitles).
- **Beat detection** (WASM module).
- **AI-managed development** (the project itself is partially written by AI, with human oversight).

The AI integration pattern is:
- **AI as a service** in the engine, called by bridges.
- **WebGPU/WASM** for client-side AI (where the model fits).
- **External API** for larger models (transcription, LLM-based decisions).

## 5. State Management Details

```typescript
// Timeline state
{
  tracks: Track[];                 // ordered, with kind: video | audio | text | graphics
  clips: Record<string, Clip>;     // flat lookup, referenced by id
  playheadPosition: number;        // seconds
  inPoint, outPoint: number;       // selection range
  selectedClipIds: string[];
  // derived: clipOrderByTrack, totalDuration, etc.
}
```

The clip store is **normalized** (flat lookup by id, references via id). This is the canonical Redux/Zustand pattern. It enables O(1) lookups and clean subscriptions.

## 6. The Plugin System (planned, not yet shipped)

The README mentions a "Plugin system" in the roadmap. Currently, the project ships as a monolith. But the engine separation is a step toward it.

The expected plugin model: each engine exposes a `register(extension)` API. Plugins can register new effects, new transitions, new export presets, new media types.

## 7. What OpenReelio Does Well

- **UI/UX polish**: comparable to CapCut, which is high praise.
- **Engine separation**: clean module boundaries.
- **Action system**: undo/redo done right.
- **Progressive enhancement**: WebGPU → Canvas2D fallback.
- **Storage**: IndexedDB auto-save.
- **Export quality**: ProRes support is unusual for browser editors.
- **AI-managed development**: 1 human + 1 AI shipping fast.

## 8. What OpenReelio Does Poorly (or can't, due to browser limits)

- **No 100% timeline persistence to a portable format**: projects are IndexedDB blobs, not OTIO.
- **No multi-user / collaborative editing**: client-only.
- **No server-side rendering**: can't run headlessly.
- **Browser codec coverage is limited**: WebCodecs doesn't support every codec.
- **No FFmpeg-equivalent filter graph**: effects are JS functions, not fused into a graph.
- **Bundle size**: shipping 130k LOC of editor to a browser is heavy.
- **No timeline versioning/diff**: no git-friendly project file.

## 9. Why This Matters for Flow

OpenReelio is the **only modern, AI-aware, open-source video editor** in the ecosystem today. It's what a browser-native video editor looks like in 2026.

**Flow's relationship to OpenReelio**:
- OpenReelio is an **editor** (UI + engine).
- Flow is a **runtime** (no UI, no human in the loop).
- They are **complementary**: OpenReelio could be a frontend that uses Flow as its backend.
- OpenReelio's **action system, bridge pattern, and engine separation** are the most valuable ideas for Flow to copy.

**The killer feature for Flow**: a "headless OpenReelio" — keep the engine, the action system, the bridges; remove the React UI; expose the action API over HTTP/gRPC/MCP. That's `flow-server`.

## 10. The "Reusable Components" List

If Flow were to integrate with or learn from OpenReelio:

1. **Action system + history** → Flow's mutation API.
2. **Bridge pattern** → Flow's service interface.
3. **Engine separation by media type** → Flow's engine modules.
4. **Zustand-like reactive store** → Flow's in-memory state.
5. **WebCodecs-based export** → Flow's web export endpoint.
6. **IndexedDB auto-save** → Flow's project checkpointing.
7. **Action validator** → Flow's plan validator.
8. **WebGPU compositor** → Flow's web preview.

## 11. Architecture Diagrams

### 11.1 Module Dependency

```
                ┌──────────────────┐
                │   apps/web (UI)  │
                └─────────┬────────┘
                          │ uses bridges
                ┌─────────▼────────┐
                │   bridges/       │
                │  (UI ↔ engine)   │
                └─────────┬────────┘
                          │
       ┌──────────┬───────┴──────┬──────────┐
       ▼          ▼              ▼          ▼
   ┌──────┐  ┌──────┐      ┌──────┐   ┌──────┐
   │video │  │audio │      │text  │   │effects│
   │engine│  │engine│      │engine│   │engine │
   └──┬───┘  └──┬───┘      └──┬───┘   └──┬───┘
      └─────────┴──────────────┴──────────┘
                          │
                ┌─────────▼────────┐
                │   actions/       │
                │  (undo/redo)     │
                └─────────┬────────┘
                          │
                ┌─────────▼────────┐
                │   storage/       │
                │  (IndexedDB)     │
                └──────────────────┘
```

### 11.2 Action Lifecycle

```
User / Agent
     │
     ▼
Action { type, payload, inverse? }
     │
     ▼
ActionValidator
     │ (invalid → reject)
     ▼
Store.dispatch  →  state update
     │
     ▼
InverseGenerator  →  action.inverse
     │
     ▼
History.push
     │
     ▼
Bridges.notify  →  engines re-render
```

## 12. Pros & Cons Summary

### Pros
- Modern, clean architecture.
- Excellent action system.
- AI-native (AI-written code, AI features).
- Browser-native, no install.
- Professional export quality.
- Active development.
- 4.4k stars = real community validation.

### Cons
- Not headless — can't run server-side.
- Bundle size.
- No OTIO / portable timeline format.
- No multi-user.
- Limited to browser codec support.
- Plugin system not yet shipped.

## 13. Verdict for Flow

| Question | Answer |
|---|---|
| Use OpenReelio's code? | **No**, but study it heavily. |
| Copy the action system? | **Yes, almost verbatim.** This is the right pattern. |
| Copy the bridge pattern? | **Yes.** |
| Build a server counterpart? | **Yes — that's `flow-server`.** |
| Ship a browser counterpart? | **Yes — `flow-server` + a WebCodecs backend is the browser runtime.** |
| Replace? | **No.** OpenReelio is the UI; Flow is the runtime. They fit together. |

OpenReelio is **what Flow's user-facing web client could look like in 2027**. The most important lesson: ship the action system as a first-class API, not as an implementation detail.
