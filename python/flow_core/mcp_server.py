"""
Flow MCP Server — exposes the 5-verb API as Model Context Protocol tools.

Run via:
    py -m flow_core_mcp

Or add to your MCP client config (e.g. Claude Desktop, Cursor, Zed):
    {
        "mcpServers": {
            "flow": {
                "command": "py",
                "args": ["-m", "flow_core_mcp"]
            }
        }
    }

────────────────────────────────────────────────────────────────────────
TOOLS
────────────────────────────────────────────────────────────────────────

flow_observe(video_path, depth="auto")
    Observe a video and return a ProjectGraph + LLM-facing summary.
    depth: "auto" | "fast" | "speech" | "vision" | "full"

flow_query(graph_id, query, **kwargs)
    Query a stored graph. query examples:
        "scenes" / "transcripts" / "objects" / "audios" / "stats"
        "find(<text>)" / "scene(<n>)" / "<node_id>"

flow_plan(graph_id, intent, **kwargs)
    Propose editing actions for a graph.
    intents: "cut_silences", "first_n:<sec>", "last_n:<sec>",
             "trim:<start>-<end>", "keep_only:<label>", etc.

flow_execute(graph_id, actions, output_path=None)
    Apply actions to a graph and prepare render commands.

flow_verify(expected, actual, re_transcribe=False, re_detect=False)
    Compare expected state to actual rendered output.

────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

# In-memory graph store (one MCP session = one process).
# For production, swap with sqlite/postgres.
_GRAPHS: Dict[str, Any] = {}


def _get_graph(graph_id: str):
    if graph_id not in _GRAPHS:
        raise ValueError(
            f"Graph '{graph_id}' not found. "
            f"Call flow_observe first to create one. "
            f"Known: {list(_GRAPHS.keys())}"
        )
    return _GRAPHS[graph_id]


def _register_graph(graph) -> str:
    """Register a graph and return its id."""
    gid = f"g{len(_GRAPHS) + 1}"
    _GRAPHS[gid] = graph
    return gid


# ═══════════════════════════════════════════════════════════════════════════
# Tool definitions
# ═══════════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "flow_observe",
        "description": (
            "Observe a video file and build a ProjectGraph. "
            "Returns a graph_id to use with the other tools, plus a "
            "text summary an LLM can read directly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "video_path": {
                    "type": "string",
                    "description": "Absolute path to the video file.",
                },
                "depth": {
                    "type": "string",
                    "enum": ["auto", "fast", "speech", "vision", "full"],
                    "default": "auto",
                    "description": "Analysis depth. 'auto' picks by video length.",
                },
            },
            "required": ["video_path"],
        },
    },
    {
        "name": "flow_query",
        "description": (
            "Query a stored ProjectGraph. Returns matching nodes and a count. "
            "Examples: 'scenes', 'transcripts', 'objects', 'audios', "
            "'find(person)', 'scene(0)', 'stats'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_id": {"type": "string"},
                "query": {
                    "type": "string",
                    "description": "Query string (see flow.query docs).",
                },
                "kwargs": {
                    "type": "object",
                    "description": "Optional filters (e.g. {\"object_type\": \"yolo_object\"}).",
                    "additionalProperties": True,
                },
            },
            "required": ["graph_id", "query"],
        },
    },
    {
        "name": "flow_plan",
        "description": (
            "Propose editing actions for a stored graph. Heuristic planners, "
            "no LLM needed. Returns a list of action dicts (see schema in "
            "flow_core.planner)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_id": {"type": "string"},
                "intent": {
                    "type": "string",
                    "description": (
                        "One of: 'cut_silences', 'tighten', 'remove_ums', "
                        "'jump_cuts', 'remove_dead_air', 'first_n:<sec>', "
                        "'last_n:<sec>', 'trim:<start>-<end>', "
                        "'keep_only:<label>', 'remove_label:<label>', "
                        "'tagged_scenes:<tag>'."
                    ),
                },
                "kwargs": {
                    "type": "object",
                    "additionalProperties": True,
                },
            },
            "required": ["graph_id", "intent"],
        },
    },
    {
        "name": "flow_execute",
        "description": (
            "Apply actions to a stored graph and prepare the ffmpeg render "
            "command. To actually render, run the returned cmd via your "
            "agent's shell tool. Returns: render cmd list, output path, "
            "actions_applied, errors."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "graph_id": {"type": "string"},
                "actions": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of action dicts (from flow_plan or your own LLM).",
                },
                "output_path": {
                    "type": "string",
                    "description": "Where the rendered video will be written.",
                },
            },
            "required": ["graph_id", "actions"],
        },
    },
    {
        "name": "flow_verify",
        "description": (
            "Compare expected state to actual rendered output. Returns "
            "ok=True if all checks pass, with per-check details and a diff "
            "for re-iteration. Re-transcribe and re-detect are opt-in "
            "(add ~3-5s each)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "expected": {
                    "type": "object",
                    "description": (
                        "Dict of expected properties. Supports: duration, "
                        "resolution, fps, has_audio, min_duration, "
                        "max_duration, codec, audio_codec, "
                        "transcript_contains, transcript_exact, label_present."
                    ),
                },
                "actual": {
                    "type": "string",
                    "description": "Path to the rendered video file.",
                },
                "re_transcribe": {"type": "boolean", "default": False},
                "re_detect": {"type": "boolean", "default": False},
            },
            "required": ["expected", "actual"],
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════
# Tool handlers
# ═══════════════════════════════════════════════════════════════════════════

def _handle_observe(args: Dict[str, Any]) -> Dict[str, Any]:
    import flow_core as flow
    video_path = args["video_path"]
    depth = args.get("depth", "auto")
    if depth == "auto":
        g = flow.video_parser.build_graph_smart(video_path, verbose=False)
    else:
        g = flow.video_parser.build_graph(video_path, depth=depth,
                                          model_size="tiny")
    gid = _register_graph(g)
    duration = 0.0
    if g.clips:
        duration = max(c.end for c in g.clips)
    elif g.scenes:
        duration = max(s.end for s in g.scenes)
    return {
        "graph_id": gid,
        "video": os.path.basename(video_path),
        "duration_seconds": round(duration, 2),
        "stats": g.stats(),
        "summary": g.observe_window(0.0, duration),
    }


def _handle_query(args: Dict[str, Any]) -> Dict[str, Any]:
    import flow_core as flow
    g = _get_graph(args["graph_id"])
    q = args["query"]
    kwargs = args.get("kwargs") or {}
    res = flow.query(g, q, **kwargs)
    return res


def _handle_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    import flow_core as flow
    g = _get_graph(args["graph_id"])
    res = flow.plan(g, args["intent"],
                    **(args.get("kwargs") or {}))
    return res


def _handle_execute(args: Dict[str, Any]) -> Dict[str, Any]:
    from .executor import execute as _exec
    g = _get_graph(args["graph_id"])
    out = args.get("output_path") or f"{g.name}_edited.mp4"
    res = _exec(g, args["actions"])
    res["output"] = out
    return res


def _handle_verify(args: Dict[str, Any]) -> Dict[str, Any]:
    import flow_core as flow
    return flow.verify(
        args["expected"], args["actual"],
        re_transcribe=args.get("re_transcribe", False),
        re_detect=args.get("re_detect", False),
    )


HANDLERS = {
    "flow_observe": _handle_observe,
    "flow_query": _handle_query,
    "flow_plan": _handle_plan,
    "flow_execute": _handle_execute,
    "flow_verify": _handle_verify,
}


# ═══════════════════════════════════════════════════════════════════════════
# JSON-RPC 2.0 server (stdio, the standard MCP transport)
# ═══════════════════════════════════════════════════════════════════════════

def _make_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _make_error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _handle_request(req: dict) -> dict:
    method = req.get("method", "")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return _make_response(req_id, {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "flow-core", "version": "0.3.0"},
            "capabilities": {"tools": {}},
        })

    if method == "notifications/initialized":
        return None  # no response for notifications

    if method == "tools/list":
        return _make_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments") or {}
        if tool_name not in HANDLERS:
            return _make_error(req_id, -32601,
                               f"Unknown tool: {tool_name}")
        try:
            result = HANDLERS[tool_name](args)
            return _make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}]
            })
        except Exception as e:
            return _make_response(req_id, {
                "content": [{"type": "text",
                             "text": json.dumps({"error": str(e)})}],
                "isError": True,
            })

    return _make_error(req_id, -32601, f"Method not found: {method}")


def main():
    """Run the MCP server on stdio."""
    print("flow-core MCP server ready on stdio", file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps(
                _make_error(None, -32700, f"Parse error: {e}")
            ) + "\n")
            sys.stdout.flush()
            continue
        resp = _handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
