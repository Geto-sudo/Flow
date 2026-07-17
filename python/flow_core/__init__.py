"""
Flow Core — the open runtime for AI video editing.

Five verbs. That's the API:

    import flow_core as flow

    graph   = flow.observe("video.mp4")           # build ProjectGraph
    graph   = flow.observe("video.mp4", depth="speech")  # + transcript
    graph   = flow.observe("video.mp4", into=g, depth="full")  # enrich
    results = flow.query(graph, "revenue")        # explore the graph
    actions = flow.plan(graph, "tighten")         # propose edits
    result  = flow.execute(actions)               # render [stub]
    ok      = flow.verify(expected, result)       # validate [stub]
"""

from .project_graph import (
    ProjectGraph,
    Project, Timeline, Track, Clip, Scene, TranscriptSegment,
    Person, DetectedObject, AudioSegment, Effect, Asset,
    GraphNode, GraphEdge,
)
from .video_parser import (
    probe_video,
    detect_scenes,
    build_graph,
    enrich_graph,
    build_graph_synthetic,
    SCENARIO_SPECS,
)
from .planner import plan as _plan
from .executor import execute as _execute
from .context_engine import ContextEngine

from typing import Optional

__version__ = "0.3.0"
__all__ = [
    "observe", "query", "plan", "execute", "verify", "context",
    "ContextEngine",
    "ProjectGraph",
    "Clip", "Scene", "TranscriptSegment", "Person",
    "DetectedObject", "Asset", "GraphNode", "GraphEdge",
]


# ═══════════════════════════════════════════════════════════════════════════
# Observe — progressive multimodal extraction
# ═══════════════════════════════════════════════════════════════════════════

def observe(
    source: str,
    depth: str = "fast",
    into: Optional[ProjectGraph] = None,
    hf_token: Optional[str] = None,
    device: str = "cpu",
    model_size: str = "base",
) -> ProjectGraph:
    """Parse a video into a ProjectGraph, progressively.

    Phase 1 (fast, <5s):    ffprobe + scene detection
    Phase 2 (speech):       faster-whisper transcription (+ diarization)
    Phase 3 (vision):       CLIP + YOLO [stub]
    Phase 4 (full):         Audio features [stub]

    Args:
        source: Path to a video file, or a scenario name for synthetic data
                (\"podcast\", \"interview\", \"vlog\", \"tutorial\").
        depth: \"fast\" | \"speech\" | \"vision\" | \"full\".
        into: Existing graph to enrich (progressive enrichment).
        hf_token: HuggingFace token for speaker diarization (optional).
        device: \"cpu\" or \"cuda\".
        model_size: Whisper model: \"tiny\", \"base\", \"small\", etc.

    Returns:
        A ProjectGraph ready for querying.
    """
    import os

    # Synthetic scenarios
    if source in SCENARIO_SPECS:
        return build_graph_synthetic(source)

    # Real video file
    if os.path.exists(source):
        if into is not None:
            return enrich_graph(source, into, depth=depth,
                                hf_token=hf_token, device=device,
                                model_size=model_size)
        return build_graph(source, depth=depth,
                           hf_token=hf_token, device=device,
                           model_size=model_size)

    raise FileNotFoundError(
        f"'{source}' is not a valid file path or known scenario. "
        f"Known scenarios: {list(SCENARIO_SPECS.keys())}. "
        f"Or provide a path to a video file."
    )


# ═══════════════════════════════════════════════════════════════════════════
# v0.1 — Query
# ═══════════════════════════════════════════════════════════════════════════

def query(graph: ProjectGraph, what: str, **kwargs):
    """Query a Project Graph.

    Args:
        graph: A ProjectGraph from observe().
        what: What to query. One of:
            - typed accessors: \"clips\", \"scenes\", \"people\",
              \"transcript\", \"objects\", \"audio\", \"effects\", \"assets\"
            - \"timeline\" → the Timeline node
            - \"tracks\" → all Track nodes
            - \"stats\" → graph statistics
            - \"summary\" → human-readable summary
            - \"find(<text>)\" → full-text search
            - \"at(<seconds>)\" → nodes at a specific time
            - \"scene(<N>)\" → the Nth scene with children
            - \"<node_id>\" → a specific node with children

    Returns:
        Dict with \"nodes\", \"count\", and optionally \"suggestions\".
    """
    what_lower = what.lower().strip()

    # ── Typed accessors ──
    type_props = {
        "clips": "clips", "clip": "clips",
        "scenes": "scenes", "scene": "scenes",
        "people": "people", "person": "people",
        "transcript": "transcript", "transcripts": "transcript",
        "objects": "objects", "object": "objects",
        "audio": "audio",
        "effects": "effects", "effect": "effects",
        "assets": "assets", "asset": "assets",
    }
    if what_lower in type_props:
        nodes = getattr(graph, type_props[what_lower])
        for key, val in kwargs.items():
            nodes = [n for n in nodes if getattr(n, key, None) == val]
        return _format_result(graph, nodes, what_lower)

    # ── Timeline ──
    if what_lower == "timeline":
        nodes = graph.find_by_type(Timeline)
        return _format_result(graph, nodes, "timeline")

    # ── Tracks ──
    if what_lower in ("tracks", "track"):
        nodes = graph.find_by_type(Track)
        return _format_result(graph, nodes, "tracks")

    # ── Stats ──
    if what_lower == "stats":
        return graph.stats()

    # ── Summary ──
    if what_lower == "summary":
        return {"summary": graph.summary(), "stats": graph.stats()}

    # ── Find by text ──
    if what_lower.startswith("find(") and what_lower.endswith(")"):
        search_text = what_lower[5:-1].strip().strip('"').strip("'")
        nodes = graph.search(search_text)
        return _format_result(graph, nodes, f"find({search_text})")

    # ── At time ──
    if what_lower.startswith("at(") and what_lower.endswith(")"):
        try:
            t = float(what_lower[3:-1].strip())
        except ValueError:
            return {"error": f"Invalid time: {what_lower[3:-1]}"}
        nodes = graph.at_time(t)
        return _format_result(graph, nodes, f"at({t})")

    # ── Scene by index ──
    if what_lower.startswith("scene(") and what_lower.endswith(")"):
        try:
            idx = int(what_lower[6:-1].strip())
        except ValueError:
            return {"error": f"Invalid scene index: {what_lower[6:-1]}"}
        scenes = graph.scenes
        if 0 <= idx < len(scenes):
            scene = scenes[idx]
            children = graph.children(scene.id)
            return _format_result(graph, [scene] + children, f"scene({idx})")
        return {"error": f"Scene {idx} out of range (0-{len(scenes)-1})",
                "count": len(scenes)}

    # ── Node by ID ──
    node = graph.get(what)
    if node:
        children = graph.children(node.id)
        return _format_result(graph, [node] + children, what)

    return {"error": f"Unknown query: '{what}'",
            "suggestions": ["clips", "scenes", "people", "transcript",
                            "objects", "assets", "tracks", "timeline",
                            "stats", "summary",
                            "find(<text>)", "at(<seconds>)",
                            "scene(<n>)", "<node_id>"]}


def _format_result(graph: ProjectGraph, nodes: list, query_name: str) -> dict:
    result = {"query": query_name, "nodes": nodes, "count": len(nodes)}
    if nodes and len(nodes) <= 10:
        suggestions = []
        for n in nodes[:3]:
            children = graph.children(n.id)
            if children:
                child_types = set(c.type for c in children)
                suggestions.append(
                    f"query('{n.id}') to see {len(children)} children "
                    f"({', '.join(sorted(child_types))})"
                )
        if suggestions:
            result["suggestions"] = suggestions
    return result


# ═══════════════════════════════════════════════════════════════════════════
# v0.2 — Plan
# ═══════════════════════════════════════════════════════════════════════════

def plan(graph: ProjectGraph, intent: str, **kwargs) -> dict:
    """Propose editing actions based on the project graph.

    Args:
        graph: A ProjectGraph from observe().
        intent: Edit style — \"tighten\", \"remove_ums\", \"jump_cuts\",
                \"remove_dead_air\", \"ripple\".
        **kwargs: Planner-specific options.

    Returns:
        {"intent": str, "actions": [...], "count": int, "planner": str}
    """
    return _plan(graph, intent, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# v0.3 — Execute (stub)
# ═══════════════════════════════════════════════════════════════════════════

def execute(graph: ProjectGraph, actions: list) -> dict:
    """Apply editing actions to a graph and produce render commands.

    Args:
        graph: A ProjectGraph from observe().
        actions: List of action dicts from plan().

    Returns:
        {"graph": ProjectGraph, "render": [...], "output": str,
         "actions_applied": int, "errors": [...]}
    """
    return _execute(graph, actions)


# ═══════════════════════════════════════════════════════════════════════════
# v0.4 — Verify
# ═══════════════════════════════════════════════════════════════════════════

from .verifier import verify as _verify


def verify(expected: dict, actual, re_transcribe: bool = False,
           re_detect: bool = False) -> dict:
    """Compare expected state to actual rendered output.

    Args:
        expected: Dict of expected properties. Supports:
            - duration (sec, ±0.5 tolerance)
            - resolution ("320x192")
            - fps (float, ±1.0 tolerance)
            - has_audio (bool)
            - min_duration / max_duration (sec)
            - codec / audio_codec (str)
            - transcript_contains / transcript_exact (str, requires re_transcribe)
            - label_present (str, requires re_detect)
        actual: Path to rendered video, or a ProjectGraph.
        re_transcribe: If True, re-run faster-whisper on actual to verify
            transcript content. Adds ~3-5s.
        re_detect: If True, re-run YOLO on actual to verify label presence.
            Adds ~2-3s.

    Returns:
        {
            "ok": bool,
            "checks": [{"name", "expected", "actual", "ok"}, ...],
            "errors": [str, ...],
            "warnings": [str, ...],
            "summary": str,
            "diff": {"mismatched": [...], "missing_in_actual": [...]}
        }
    """
    return _verify(expected, actual,
                   re_transcribe=re_transcribe,
                   re_detect=re_detect)


# ═══════════════════════════════════════════════════════════════════════════
# v0.4 — Context Engine (VVM): compress graph for LLM prompts
# ═══════════════════════════════════════════════════════════════════════════

def context(graph: ProjectGraph, query: str = "",
            budget_tokens: int = 2000,
            per_node_max_chars: int = 80) -> str:
    """Compress a ProjectGraph into LLM-friendly text under a token budget.

    This is the **VVM Context Engine**: it detects query intent
    (scenes / transcript / people / objects / audio / temporal / edit /
    summary), allocates the budget per node type, and renders a compact
    representation that fits inside an LLM context window.

    For a 1-hour podcast with ~200 nodes, a 2000-token budget is
    realistic and preserves enough structure for the LLM to reason
    about edits.

    Args:
        graph: A ProjectGraph from observe().
        query: Free-form question/intent to route the budget.
            Empty string returns a balanced summary.
        budget_tokens: Approx max tokens for the returned text.
        per_node_max_chars: Truncate individual node lines to this.

    Returns:
        A single text block, ready to be pasted into a system prompt.

    Example:
        >>> g = flow.observe("podcast.mp4", depth="full")
        >>> ctx = flow.context(g, "cut the silences", budget_tokens=2000)
        >>> # paste into your LLM call's system prompt
    """
    return ContextEngine(graph).serve(query=query,
                                      budget_tokens=budget_tokens,
                                      per_node_max_chars=per_node_max_chars)
