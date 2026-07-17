# Flow — Vision

> **Flow is an open runtime that enables AI agents to observe, reason about, edit, and verify complex video projects through structured actions rather than raw media.**

---

## 1. Mission

Flow is the **infrastructure layer** between AI agents and video. It does not render UI, does not interpret natural language, does not make creative decisions. It provides a structured surface for agents to work with video — typed, validated, observable, and efficient.

## 2. The Core Insight

Video editing by AI has a fundamental bottleneck: **context**. A 1-hour video with transcript, scenes, timeline, and audio analysis generates ~26,000 tokens per query. At scale, this makes AI editing economically impossible.

Flow solves this with a **Context Engine** — a Virtual Video Memory (VVM) that indexes the entire project and serves agents only the minimal pages needed for each decision. The agent receives ~90 tokens instead of 26,000.

This is not an optimization. It is the difference between a demo and a product.

## 3. The Four Phases

AI video editing is not "prompt → video." It is a loop:

```
Observe ──▶ Reason ──▶ Edit ──▶ Verify ──▶ (repeat)
```

| Phase | Agent does | Flow provides |
|---|---|---|
| **Observe** | Reads project state, transcript, scenes | Context Engine — minimal, relevant pages |
| **Reason** | Decides what edit to make | Structured context, not raw media |
| **Edit** | Emits typed JSON actions | Runtime — validate, execute, render |
| **Verify** | Checks correctness, iterates | Action log, diffs, render previews |

Every other approach collapses this into "LLM → FFmpeg CLI." Flow preserves the loop.

## 4. Why Flow Exists

Today, when an LLM wants to edit a video, it has four options:

| Approach | Problem |
|---|---|
| Write MoviePy/Python code | No project model, no undo, slow |
| Call FFmpeg CLI | Cold-start per operation, text-based filter graphs, no state |
| Use an NLE SDK | Designed for humans, not agents |
| Write custom code | Everyone reinvents the same pipeline |

None of these provide a typed, validated, observable, context-efficient surface for agents.

## 5. The Bet

Five principles that compound:

| Principle | What it means |
|---|---|
| **Structured actions** | Typed JSON, schema-validated, not raw CLI flags |
| **Context efficiency** | VVM — agents see 90 tokens, not 26,000 |
| **MCP-native** | Agents call Flow natively; no "wrap our API in a tool" |
| **Git-like persistence** | Action log, checkpoints, diffs, branches, rollback |
| **Open runtime** | Anyone can build on Flow, any language, any model |

## 6. What Flow Is Not

- Not an editor (no GUI).
- Not a codec library (FFmpeg does that).
- Not an AI model (just the runtime for them).
- Not a replacement for Premiere/DaVinci (they can consume Flow's output).

## 7. Target Users

| User | How they use Flow |
|---|---|
| **AI Agents** | Via MCP — observe, reason, edit, verify |
| **Python developers** | Via `flow-script` — script video pipelines |
| **CLI users** | Via `flow-cli` — `flow run`, `flow diff` |
| **Web apps** | Via `flow-server` HTTP API or `flow-web` SDK |

## 8. Ecosystem

```
                        AI Agents (Claude, GPT, Gemini)
                                │  MCP / HTTP
                                ▼
                    ┌──────────────────────┐
                    │     Flow Runtime      │
                    │                       │
                    │  ┌─────────────────┐  │
                    │  │ Context Engine  │  │
                    │  │  (VVM)          │  │
                    │  └─────────────────┘  │
                    │                       │
                    │  Actions → Final.mp4  │
                    └──────────────────────┘
                                │
              ┌─────────────────┼────────────────┐
              ▼                 ▼                ▼
        Editors           Pipelines         Custom apps
        (CapCut,          (automated        (anyone)
         OpenReel)         video)
```

Flow is infrastructure. Everything above it can be built by anyone.
