"""
Execute — applies plan actions to a ProjectGraph and emits ffmpeg commands.

Consumes the typed action dicts produced by plan(). Each action is
applied in order. The result is:
  1. A modified ProjectGraph reflecting the changes.
  2. A list of ffmpeg filter-complex arguments that render the result.

────────────────────────────────────────────────────────────────────────
ACTION SCHEMA (consumed — see planner.py for producers)
────────────────────────────────────────────────────────────────────────

  trim         — {"action": "trim", "clip": <id>, "start": <s>, "end": <e>}
  split        — {"action": "split", "clip": <id>, "at": <s>}
  ripple       — {"action": "ripple", "clip": <id>, "by": <d>}
  cut          — {"action": "cut", "start": <s>, "end": <e>}
                  Converted to trim via cuts_to_trims() before execution.
  remove_object — {"action": "remove_object", "label": <str>, "ranges": [[s,e],...]}
                  Converted to cut actions.
"""

from __future__ import annotations

from .project_graph import ProjectGraph, Clip
from . import _ffmpeg as _ff
from typing import List, Dict, Optional


def execute(graph: ProjectGraph, actions: List[dict]) -> Dict:
    """Apply editing actions to a graph and prepare render commands.

    Args:
        graph: The ProjectGraph from observe().
        actions: List of action dicts from plan().

    Returns:
        {
            "graph": ProjectGraph,          # modified graph
            "render": [str, ...],           # ffmpeg filter chain command line
            "output": str,                  # suggested output path
            "actions_applied": int,         # how many actions succeeded
            "errors": [str, ...],           # any failures
        }
    """
    errors = []
    applied = 0
    g = graph

    # Phase 0: convert cut/remove_object actions to trims
    preprocessed = _preprocess(g, actions)

    # Phase 1: apply each action
    for act in preprocessed:
        kind = act.get("action", "")
        try:
            if kind == "trim":
                _apply_trim(g, act)
                applied += 1
            elif kind == "split":
                _apply_split(g, act)
                applied += 1
            elif kind == "ripple":
                _apply_ripple(g, act)
                applied += 1
            elif kind == "cut":
                pass  # already converted in _preprocess
            else:
                errors.append(f"Unknown action '{kind}'")
        except Exception as e:
            errors.append(f"Action {kind} failed: {e}")

    # Phase 2: build ffmpeg filter chain
    render_cmd = _build_render(g)

    # Phase 3: suggested output path
    output_path = f"{g.name}_edited.mp4" if hasattr(g, 'name') else "output_edited.mp4"

    return {
        "graph": g,
        "render": render_cmd,
        "output": output_path,
        "actions_applied": applied,
        "errors": errors,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Preprocessing: convert cut/remove_object → trim
# ═══════════════════════════════════════════════════════════════════════════

def _preprocess(graph: ProjectGraph, actions: List[dict]) -> List[dict]:
    """Normalize all actions to trim/split/ripple before execution."""
    from . import planner as _pl

    result = []
    cuts_buffer = []

    for act in actions:
        kind = act.get("action", "")

        if kind == "cut":
            cuts_buffer.append(act)

        elif kind == "remove_object":
            for s, e in act.get("ranges", []):
                cuts_buffer.append({
                    "action": "cut",
                    "start": s,
                    "end": e,
                    "reason": f"remove_object '{act.get('label','')}'",
                })

        else:
            if cuts_buffer:
                trims = _pl.cuts_to_trims(cuts_buffer, graph)
                result.extend(trims)
                cuts_buffer = []
            result.append(act)

    if cuts_buffer:
        trims = _pl.cuts_to_trims(cuts_buffer, graph)
        result.extend(trims)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Action applicators
# ═══════════════════════════════════════════════════════════════════════════

def _find_clip(graph: ProjectGraph, clip_id: str) -> Optional[Clip]:
    for c in graph.clips:
        if c.id == clip_id:
            return c
    return None


def _is_linked(graph: ProjectGraph, clip_id: str, node_id: str) -> bool:
    """Check if node_id is linked to clip_id by any edge."""
    for edge in graph.relationships(node_id):
        if edge.source == clip_id or edge.target == clip_id:
            return True
    return False


def _apply_trim(graph: ProjectGraph, act: dict) -> None:
    """Trim creates a new clip from the source clip keeping only [start, end].

    The source clip is identified by the parent-child link: all child nodes
    within [start, end] are re-parented to the new clip. The original clip
    stays; subsequent trims on the same source also create new clips.
    This allows multiple trims from one source (e.g. cut silences).
    """
    source_clip_id = act["clip"]
    s, e = act["start"], act["end"]
    source_clip = _find_clip(graph, source_clip_id)
    if not source_clip:
        raise ValueError(f"Clip {source_clip_id} not found")

    # Create a new trimmed clip from the source
    import uuid
    new_clip = Clip(
        source=source_clip.source,
        start=s,
        end=e,
        source_start=source_clip.source_start + (s - source_clip.start),
        track=source_clip.track,
    )
    new_clip.id = f"clip:{uuid.uuid4().hex[:8]}"
    graph.add(new_clip)

    # Re-parent child nodes that fall within [s, e]
    for nid, node in list(graph.nodes.items()):
        if not hasattr(node, 'start') or not hasattr(node, 'end'):
            continue
        if node is source_clip or node is new_clip:
            continue
        if not _is_linked(graph, source_clip_id, nid):
            continue
        # If node overlaps with [s, e], link to new clip
        if node.start < e and node.end > s:
            rels = graph.relationships(nid)
            for edge in rels:
                if (edge.source == source_clip_id and edge.target == nid):
                    graph.add_edge(new_clip.id, nid, edge.relation)
                    break

    # Also link the new clip to the track
    for edge in graph.relationships(source_clip_id):
        if edge.source == source_clip_id:
            pass  # handled above
        elif edge.target == source_clip_id:
            # parent links to source clip — also link to new clip
            graph.add_edge(edge.source, new_clip.id, edge.relation)


def _apply_split(graph: ProjectGraph, act: dict) -> None:
    """Split a clip at `at` seconds into two clips."""
    clip_id = act["clip"]
    at_time = act["at"]
    clip = _find_clip(graph, clip_id)
    if not clip:
        raise ValueError(f"Clip {clip_id} not found")

    if at_time <= clip.start or at_time >= clip.end:
        raise ValueError(
            f"Split point {at_time} outside clip range [{clip.start}, {clip.end}]"
        )

    import uuid
    new_clip = Clip(
        source=clip.source,
        start=at_time,
        end=clip.end,
        source_start=clip.source_start + (at_time - clip.start),
        track=clip.track,
    )
    new_clip.id = f"clip:{uuid.uuid4().hex[:8]}"
    graph.add(new_clip)
    clip.end = at_time

    # Re-parent nodes to the correct clip.
    # Children with start >= at_time → new_clip.
    # Children that overlap both halves → keep on original (rare case).
    # Always REMOVE old edge before adding the new one (avoid duplicates).
    edges_to_remove = []
    for nid in list(graph.nodes.keys()):
        node = graph.nodes.get(nid)
        if not node or not hasattr(node, 'start'):
            continue
        if node is clip or node is new_clip:
            continue
        if not _is_linked(graph, clip_id, nid):
            continue
        if node.start >= at_time:
            # Find existing edge from clip_id to nid, mark for removal
            for edge in graph.relationships(nid):
                if edge.source == clip_id and edge.target == nid:
                    edges_to_remove.append((edge.source, edge.target, edge.relation))
                    break
            # Add the new edge to new_clip
            graph.add_edge(new_clip.id, nid, "contains_scene")

    # Remove old edges (separate pass to avoid mutating during iteration)
    for src, tgt, rel in edges_to_remove:
        if src in graph._out and (tgt, rel) in graph._out[src]:
            graph._out[src] = [(t, r) for t, r in graph._out[src]
                                 if not (t == tgt and r == rel)]
        if tgt in graph._in and (src, rel) in graph._in[tgt]:
            graph._in[tgt] = [(s, r) for s, r in graph._in[tgt]
                                 if not (s == src and r == rel)]


def _apply_trim(graph: ProjectGraph, act: dict) -> None:
    """Trim creates a new clip from the source clip keeping only [start, end].

    The source clip is identified by the parent-child link: all child nodes
    within [start, end] are re-parented to the new clip. The original clip
    stays; subsequent trims on the same source also create new clips.
    This allows multiple trims from one source (e.g. cut silences).
    """
    source_clip_id = act["clip"]
    s, e = act["start"], act["end"]

    # Validate
    if s >= e:
        raise ValueError(
            f"trim: start ({s}) must be < end ({e})"
        )
    if e - s < 0.01:
        raise ValueError(
            f"trim: range too small ({e - s:.3f}s)"
        )

    source_clip = _find_clip(graph, source_clip_id)
    if not source_clip:
        raise ValueError(f"Clip {source_clip_id} not found")

    # Clamp to source clip range
    s = max(s, source_clip.start)
    e = min(e, source_clip.end)
    if s >= e:
        raise ValueError(
            f"trim: range [{s}, {e}] outside source clip [{source_clip.start}, {source_clip.end}]"
        )


def _apply_ripple(graph: ProjectGraph, act: dict) -> None:
    """Shift a clip by `by` seconds. Negative = earlier."""
    clip_id = act["clip"]
    by = act["by"]
    clip = _find_clip(graph, clip_id)
    if not clip:
        raise ValueError(f"Clip {clip_id} not found")

    clip.start += by
    clip.end += by
    clip.source_start += by

    for nid, node in list(graph.nodes.items()):
        if not hasattr(node, 'start') or not hasattr(node, 'end'):
            continue
        if node is clip:
            continue
        if _is_linked(graph, clip_id, nid):
            node.start += by
            node.end += by


# ═══════════════════════════════════════════════════════════════════════════
# Render: build ffmpeg filter chain
# ═══════════════════════════════════════════════════════════════════════════

def _build_render(graph: ProjectGraph) -> List[str]:
    """Build an ffmpeg filter-complex command to render the result."""
    clips = sorted(graph.clips, key=lambda c: c.start)

    # Deduplicate: if a clip strictly contains another, it's the original
    # source clip that was split — remove it, keep the children.
    if len(clips) > 1:
        kept = []
        for ci in clips:
            is_superset = any(
                ci.start <= cj.start and ci.end >= cj.end
                and ci is not cj
                and (ci.start < cj.start or ci.end > cj.end)  # strict superset
                for cj in clips
            )
            if not is_superset:
                kept.append(ci)
        if kept:
            clips = kept

    if not clips:
        return []

    source = clips[0].source if clips[0].source else "input.mp4"

    video_chains = []
    audio_chains = []
    v_labels = []
    a_labels = []

    for i, clip in enumerate(clips):
        start_ts = clip.source_start if hasattr(clip, 'source_start') else clip.start
        dur = clip.end - clip.start
        end_ts = start_ts + dur
        v_label = f"v{i}"
        a_label = f"a{i}"
        video_chains.append(
            f"[0:v]trim={start_ts}:{end_ts},setpts=PTS-STARTPTS[{v_label}]"
        )
        audio_chains.append(
            f"[0:a]atrim={start_ts}:{end_ts},asetpts=PTS-STARTPTS[{a_label}]"
        )
        v_labels.append(f"[{v_label}]")
        a_labels.append(f"[{a_label}]")

    n = len(clips)
    concat_inputs = "".join(v_labels) + "".join(a_labels)
    concat = f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"
    filter_graph = ";".join(video_chains + audio_chains + [concat])

    output_name = f"{graph.name}_edited.mp4" if hasattr(graph, 'name') else "output_edited.mp4"

    cmd = [
        _ff.ffmpeg_path(), "-y",
        "-i", source,
        "-filter_complex", filter_graph,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-c:a", "aac",
        output_name,
    ]

    return cmd
