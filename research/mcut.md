# mcut — Reverse Engineering Notes

> **Status: No public artifact found under the name "mcut" matching the description in the Flow mission brief.**

---

## 1. What We Searched For

The mission brief lists "mcut (architecture orientée SDK/MCP)" as one of the 6 reference projects. Per the brief, mcut should be:
- An SDK-style architecture.
- MCP (Model Context Protocol) integration.
- AI architecture.
- A video editing timeline engine.
- A plugin system.

## 2. Search Results

We searched GitHub, web search (Tencent Cloud, Baidu), and a direct mcut video editor SDK query. Findings:

| Query | Result |
|---|---|
| `mcut video editor SDK architecture github` | Returns commercial C#/C++ video editor SDKs (Viscomsoft, Banuba, MeisheSDK, WsVideoEditor, VerySDK), but **none named "mcut"** with the described architecture. |
| `OpenReelio` (similar name) | Found Augani/openreel-video, an open-source browser video editor — see `openreelio.md`. This is the closest project to a "modern open-source video editor SDK" in the current ecosystem. |
| `mcut` alone | Returns nothing meaningful in the open-source ecosystem. The string appears as a typo for "cut" in some search results, but no project. |
| MCP + video editing | No project combining these two labels exists as of search date. |

**Hypothesis**: "mcut" may be:
1. A typo / shortened form of another project.
2. An internal / private project not yet public.
3. A planned but unreleased project.
4. A project hosted on a private platform not indexed by public search.

## 3. What We Could Not Do

Without a public artifact, we cannot:
- Read the codebase.
- Inspect the API.
- Verify the architecture.
- Validate the MCP integration claim.
- Confirm the plugin system.

Doing "reverse engineering" of a non-existent project would be fabrication, which is not what this research deliverable should produce.

## 4. What This Means for Flow

The absence of mcut does **not** invalidate any of Flow's architectural decisions. The remaining 5 reference projects (FFmpeg, MLT, OTIO, MoviePy, OpenReelio) provide a complete picture of the landscape:

- **FFmpeg** = the bytes engine.
- **MLT** = the multitrack editor engine.
- **OTIO** = the interchange format.
- **MoviePy** = the scripting API.
- **OpenReelio** = the modern browser editor reference.

What mcut *would* have given us (if it existed): a reference for an "SDK + MCP-native video editor." This is exactly Flow's territory. Its absence means Flow is defining this category, not joining it.

## 5. Possible Interpretations (Speculative)

If mcut was intended to refer to one of these projects, the analysis would change:

| If mcut = ... | Then see ... |
|---|---|
| MoviePy (typo) | `moviepy.md` |
| OpenCut (alternative open-source editor) | Similar analysis to OpenReelio |
| A private concept / internal name | Cannot analyze |

## 6. Recommendation

**We recommend the user clarify the source of "mcut"** — provide a URL, a GitHub repo, a paper, or a more specific description. If it's a private project, ask the maintainer for access. If it's a typo, point to the intended project.

In the absence of further information, **mcut is treated as a non-contributor to this research** and the Flow architecture is built on the 5 confirmed projects + the Flow mission brief's own design intent.

---

*This file intentionally short. Honesty > fabrication.*
