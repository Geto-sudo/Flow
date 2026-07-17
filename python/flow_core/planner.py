"""
Planner — analyzes a ProjectGraph and proposes editing actions.

Sprint 1: heuristic planners (no LLM). Each planner implements one
editing style by analyzing transcript, scenes, and clip structure.

All planners return typed action dicts compatible with execute().

────────────────────────────────────────────────────────────────────────
ACTION SCHEMA (stable contract for LLM-agnostic agents)
────────────────────────────────────────────────────────────────────────

Each action is a dict with a required "action" field. Supported types:

  1. trim  — keep only [start, end] of a clip
        {"action": "trim", "clip": <clip_id>,
         "start": <sec>, "end": <sec>, "reason": "..."}

  2. split — cut a clip into two at `at` (sec)
        {"action": "split", "clip": <clip_id>,
         "at": <sec>, "reason": "..."}

  3. ripple — shift a clip by `by` seconds (negative = earlier)
        {"action": "ripple", "clip": <clip_id>,
         "by": <sec>, "reason": "..."}

  4. cut — remove [start, end] from the source (alias for plan output,
        not consumed by execute yet; kept for plan-side semantics)
        {"action": "cut", "start": <sec>, "end": <sec>, "reason": "..."}

  5. remove_object — propose cutting regions where `object_label` is
        detected. (e.g. remove segments with "sheep" misdetections)
        {"action": "remove_object", "label": "sheep",
         "ranges": [[s, e], ...], "reason": "..."}

All actions carry a `reason` field for explainability.
────────────────────────────────────────────────────────────────────────
"""

from .project_graph import ProjectGraph, Clip, TranscriptSegment
from typing import List, Dict, Optional


# ═══════════════════════════════════════════════════════════════════════════
# Action type definitions
# ═══════════════════════════════════════════════════════════════════════════

def action_trim(clip_id: str, start: float, end: float, reason: str = "") -> dict:
    return {
        "action": "trim",
        "clip": clip_id,
        "start": round(start, 2),
        "end": round(end, 2),
        "reason": reason,
    }

def action_split(clip_id: str, at_time: float, reason: str = "") -> dict:
    return {
        "action": "split",
        "clip": clip_id,
        "at": round(at_time, 2),
        "reason": reason,
    }

def action_ripple(clip_id: str, by: float, reason: str = "") -> dict:
    return {
        "action": "ripple",
        "clip": clip_id,
        "by": round(by, 2),
        "reason": reason,
    }

def action_cut(start: float, end: float, reason: str = "") -> dict:
    """Source-level cut: remove [start, end] from the source timeline."""
    return {
        "action": "cut",
        "start": round(start, 2),
        "end": round(end, 2),
        "reason": reason,
    }

def action_remove_object(label: str, ranges: List[List[float]],
                        reason: str = "") -> dict:
    """Remove all time ranges where `label` was detected."""
    return {
        "action": "remove_object",
        "label": label,
        "ranges": [[round(s, 2), round(e, 2)] for s, e in ranges],
        "reason": reason,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Heuristic planners
# ═══════════════════════════════════════════════════════════════════════════

FILLER_WORDS = {"um", "uh", "like", "you know", "i mean", "sort of",
                "kind of", "right", "actually", "basically", "so", "well"}


def _clip_at(graph: ProjectGraph, t: float) -> Optional[Clip]:
    for c in graph.clips:
        if c.start <= t < c.end:
            return c
    return None


def plan_tighten_pauses(graph: ProjectGraph) -> List[dict]:
    """Remove filler words and long pauses between sentences."""
    actions = []
    for tx in graph.transcript:
        has_filler = tx.has_filler or any(
            fw in tx.text.lower() for fw in FILLER_WORDS
        )
        if has_filler:
            clip = _clip_at(graph, tx.start)
            if clip:
                actions.append(action_trim(
                    clip.id, tx.start, tx.end,
                    f"Filler: {tx.text[:60]}"
                ))
    return actions


def plan_remove_ums(graph: ProjectGraph) -> List[dict]:
    """Remove hesitation markers (um, uh)."""
    actions = []
    for tx in graph.transcript:
        words = set(tx.text.lower().split())
        if "um" in words or "uh" in words:
            clip = _clip_at(graph, tx.start)
            if clip:
                actions.append(action_trim(
                    clip.id, tx.start, tx.end,
                    f"Hesitation: {tx.text[:60]}"
                ))
    return actions


def plan_jump_cuts(graph: ProjectGraph, target_clip_duration: float = 8.0) -> List[dict]:
    """Split long clips into shorter segments for jump-cut style."""
    actions = []
    for clip in graph.clips:
        if clip.duration <= target_clip_duration:
            continue
        pos = clip.start + target_clip_duration
        while pos < clip.end - 1.0:
            actions.append(action_split(
                clip.id, pos, f"Jump cut at {pos:.1f}s"
            ))
            pos += target_clip_duration
    return actions


def plan_remove_dead_air(graph: ProjectGraph, silence_threshold: float = 3.0) -> List[dict]:
    """Remove transcript segments that contain no content keywords."""
    from .video_parser import TRANSCRIPT_SNIPPETS
    content_keywords = set()
    for snippet in TRANSCRIPT_SNIPPETS.values():
        if snippet:
            for w in snippet.lower().split():
                if len(w) > 3:
                    content_keywords.add(w)

    actions = []
    for tx in graph.transcript:
        words = set(tx.text.lower().split())
        has_content = bool(words & content_keywords)
        if not has_content:
            dur = tx.end - tx.start
            if dur >= silence_threshold:
                clip = _clip_at(graph, tx.start)
                if clip:
                    actions.append(action_trim(
                        clip.id, tx.start, tx.end,
                        f"Dead air: {dur:.1f}s"
                    ))
    return actions


def plan_ripple(graph: ProjectGraph, after_clip_id: str, gap: float = 0.0) -> List[dict]:
    """Close gaps between clips by ripple-editing subsequent clips."""
    actions = []
    clips_sorted = sorted(graph.clips, key=lambda c: c.start)
    for i, clip in enumerate(clips_sorted):
        if clip.id == after_clip_id and i + 1 < len(clips_sorted):
            nxt = clips_sorted[i + 1]
            current_gap = nxt.start - clip.end
            if current_gap > gap:
                actions.append(action_ripple(
                    nxt.id, -(current_gap - gap),
                    f"Close {current_gap:.1f}s gap"
                ))
    return actions


# ═══════════════════════════════════════════════════════════════════════════
# New intent: cut_silences (uses VAD audio events)
# ═══════════════════════════════════════════════════════════════════════════

def plan_cut_silences(graph: ProjectGraph,
                      min_silence: float = 0.5,
                      pad_ms: int = 100) -> List[dict]:
    """Remove silence regions detected by VAD.

    Uses AudioSegment nodes with speech_active=False. Pads each cut
    with `pad_ms` to avoid cutting into speech.

    Output: `cut` actions at the source-timeline level (consumable by
    execute() which resolves them against the source clip).
    """
    actions = []
    pad = pad_ms / 1000.0
    for a in graph.audio:
        if a.speech_active:
            continue
        dur = a.end - a.start
        if dur < min_silence:
            continue
        # Pad both ends inward so we keep the natural breath at boundaries
        s = a.start + pad
        e = a.end - pad
        if e <= s:
            continue
        actions.append(action_cut(
            s, e,
            reason=f"Silence {dur:.1f}s @ {a.start:.1f}-{a.end:.1f}"
        ))
    return actions


def plan_keep_only_label(graph: ProjectGraph, label: str) -> List[dict]:
    """Keep only segments where a DetectedObject with `label` is present.

    Inverse: emits `cut` actions for every range where the label is
    NOT detected. Useful for "show me only the scenes with X".
    """
    matching = [o for o in graph.objects
                if o.label.lower() == label.lower()
                and o.object_type in ("yolo_object", "face", "visual_tag")]
    import sys as _sys
    _sys.stderr.write(f"KEEP_ONLY matching={len(matching)}\n")
    if not matching:
        return []
    # Get full duration
    if graph.clips:
        duration = max(c.end for c in graph.clips)
    elif graph.scenes:
        duration = max(s.end for s in graph.scenes)
    else:
        duration = 0
    _sys.stderr.write(f"KEEP_ONLY duration={duration}\n")
    if duration <= 0:
        return []

    # Merge matching ranges
    keep = sorted([(o.start, o.end) for o in matching])
    merged = [keep[0]]
    for s, e in keep[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # Invert: cut everything not in `merged`
    cuts = []
    cursor = 0.0
    for s, e in merged:
        if s > cursor:
            cuts.append(action_cut(cursor, s, f"No '{label}' here"))
        cursor = e
    if cursor < duration:
        cuts.append(action_cut(cursor, duration, f"No '{label}' after"))
    return cuts


# ═══════════════════════════════════════════════════════════════════════════
# New intents: time + label-based
# ═══════════════════════════════════════════════════════════════════════════

def _clip_duration(graph: ProjectGraph) -> float:
    if graph.clips:
        return max(c.end for c in graph.clips)
    if graph.scenes:
        return max(s.end for s in graph.scenes)
    return 0.0


def _source_clip_id(graph: ProjectGraph) -> Optional[str]:
    """Return the id of the main source clip (the longest one)."""
    if not graph.clips:
        return None
    return max(graph.clips, key=lambda c: c.duration).id


def plan_trim(graph: ProjectGraph, start: float, end: float) -> List[dict]:
    """Trim the source to [start, end]. Returns one trim action."""
    clip_id = _source_clip_id(graph)
    if not clip_id:
        return []
    duration = _clip_duration(graph)
    end = min(end, duration)
    if end <= start:
        return []
    return [action_trim(clip_id, start, end, reason="plan_trim")]


def plan_first_n(graph: ProjectGraph, n_seconds: float) -> List[dict]:
    """Keep only the first `n_seconds` of the source."""
    return plan_trim(graph, 0.0, n_seconds)


def plan_last_n(graph: ProjectGraph, n_seconds: float) -> List[dict]:
    """Keep only the last `n_seconds` of the source."""
    duration = _clip_duration(graph)
    return plan_trim(graph, max(0.0, duration - n_seconds), duration)


def plan_remove_label(graph: ProjectGraph, label: str,
                      min_confidence: float = 0.5) -> List[dict]:
    """Remove all time ranges where `label` is detected (cut action).

    Inverse of `plan_keep_only_label`. Use case: YOLO mis-detects "sheep"
    in a dog video; agent calls plan_remove_label("sheep") to strip
    those misclassified regions.
    """
    matching = [o for o in graph.objects
                if o.label.lower() == label.lower()
                and o.confidence >= min_confidence
                and o.object_type in ("yolo_object", "face", "visual_tag")]
    if not matching:
        return []
    cuts = []
    for o in matching:
        cuts.append(action_cut(
            o.start, o.end,
            reason=f"Remove '{label}' (conf={o.confidence:.2f})"
        ))
    return cuts


def plan_tagged_scenes(graph: ProjectGraph, tag: str) -> List[dict]:
    """Keep only scenes that have a CLIP visual_tag matching `tag`."""
    matching = [o for o in graph.objects
                if o.object_type == "visual_tag"
                and o.label.lower() == tag.lower()]
    if not matching:
        return []
    duration = _clip_duration(graph)
    if duration <= 0:
        return []
    # Merge
    keep = sorted([(o.start, o.end) for o in matching])
    merged = [keep[0]]
    for s, e in keep[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    cuts = []
    cursor = 0.0
    for s, e in merged:
        if s > cursor:
            cuts.append(action_cut(cursor, s, f"No '{tag}' tag here"))
        cursor = e
    if cursor < duration:
        cuts.append(action_cut(cursor, duration, f"No '{tag}' tag after"))
    return cuts


# ═══════════════════════════════════════════════════════════════════════════
# Range → trim actions (helper for execute())
# ═══════════════════════════════════════════════════════════════════════════

def cuts_to_trims(cuts: List[dict], graph: ProjectGraph) -> List[dict]:
    """Convert a list of `cut` actions into a list of `trim` actions.

    A `cut` says "remove [s, e]". A `trim` says "keep [s, e]". To make
    execute()'s life simple, we invert: for every gap, emit a trim.

    The resulting list of trims, applied in order, reproduces the
    original video minus the cut ranges.
    """
    clip_id = _source_clip_id(graph)
    if not clip_id or not cuts:
        return []
    duration = _clip_duration(graph)
    # Sort and merge cuts (extract start/end from dicts)
    sorted_cuts = sorted(cuts, key=lambda c: c.get("start", 0))
    merged = []
    last_s, last_e = None, None
    for c in sorted_cuts:
        s, e = c["start"], c["end"]
        if last_s is not None and s <= last_e:
            last_e = max(last_e, e)
        else:
            if last_s is not None:
                merged.append((last_s, last_e))
            last_s, last_e = s, e
    if last_s is not None:
        merged.append((last_s, last_e))
    # Emit trims for the gaps
    trims = []
    cursor = 0.0
    for s, e in merged:
        if s > cursor + 0.01:
            trims.append(action_trim(
                clip_id, cursor, s,
                reason=f"Keep {cursor:.2f}-{s:.2f} (gap after cut)"
            ))
        cursor = max(cursor, e)
    if cursor < duration - 0.01:
        trims.append(action_trim(
            clip_id, cursor, duration,
            reason=f"Keep {cursor:.2f}-{duration:.2f} (trailing)"
        ))
    return trims


# ═══════════════════════════════════════════════════════════════════════════
# Unified plan()
# ═══════════════════════════════════════════════════════════════════════════

PLANNERS = {
    "tighten_pauses": plan_tighten_pauses,
    "tighten": plan_tighten_pauses,
    "remove_ums": plan_remove_ums,
    "jump_cuts": plan_jump_cuts,
    "remove_dead_air": plan_remove_dead_air,
    "dead_air": plan_remove_dead_air,
    "ripple": plan_ripple,
    "cut_silences": plan_cut_silences,
}


def plan(graph: ProjectGraph, intent: str, **kwargs) -> dict:
    """Propose editing actions based on intent.

    Args:
        graph: A ProjectGraph from observe().
        intent: One of:
          - "tighten" / "tighten_pauses"
          - "remove_ums"
          - "jump_cuts"  (kw: target_clip_duration=8.0)
          - "remove_dead_air" / "dead_air"  (kw: silence_threshold=3.0)
          - "ripple"  (kw: after_clip_id, gap=0.0)
          - "cut_silences"  (kw: min_silence=0.5, pad_ms=100)
          - "keep_only:<label>"  (e.g. "keep_only:person")
          - "remove_label:<label>"  (inverse, e.g. "remove_label:sheep")
          - "tagged_scenes:<tag>"  (e.g. "tagged_scenes:tiktok")
          - "first_n:<seconds>"  (e.g. "first_n:30")
          - "last_n:<seconds>"  (e.g. "last_n:10")
          - "trim:<start>-<end>"  (e.g. "trim:5-15")
        **kwargs: Planner-specific options.

    Returns:
        {
            "intent": str,
            "actions": [action_dict, ...],   # see ACTION SCHEMA at top of file
            "count": int,
            "planner": str | None,
            "error": str | None,             # only if intent unknown / invalid
        }

    Each action dict has a stable schema that any LLM agent can produce
    and that execute() consumes. See module docstring for the schema.
    """
    # Pattern intents: "<verb>:<arg>"
    if intent.startswith("keep_only:"):
        label = intent.split(":", 1)[1].strip()
        if not label:
            return _error(intent, "empty label after 'keep_only:'")
        actions = plan_keep_only_label(graph, label)
        return _ok(intent, actions, "plan_keep_only_label")

    if intent.startswith("remove_label:"):
        label = intent.split(":", 1)[1].strip()
        if not label:
            return _error(intent, "empty label after 'remove_label:'")
        actions = plan_remove_label(graph, label,
                                    min_confidence=kwargs.get("min_confidence", 0.5))
        return _ok(intent, actions, "plan_remove_label")

    if intent.startswith("tagged_scenes:"):
        tag = intent.split(":", 1)[1].strip()
        if not tag:
            return _error(intent, "empty tag after 'tagged_scenes:'")
        actions = plan_tagged_scenes(graph, tag)
        return _ok(intent, actions, "plan_tagged_scenes")

    if intent.startswith("first_n:"):
        try:
            n = float(intent.split(":", 1)[1].strip())
        except ValueError:
            return _error(intent, f"first_n: needs a number, got {intent}")
        actions = plan_first_n(graph, n)
        return _ok(intent, actions, "plan_first_n")

    if intent.startswith("last_n:"):
        try:
            n = float(intent.split(":", 1)[1].strip())
        except ValueError:
            return _error(intent, f"last_n: needs a number, got {intent}")
        actions = plan_last_n(graph, n)
        return _ok(intent, actions, "plan_last_n")

    if intent.startswith("trim:"):
        spec = intent.split(":", 1)[1].strip()
        try:
            s_str, e_str = spec.split("-", 1)
            s, e = float(s_str), float(e_str)
        except ValueError:
            return _error(intent, f"trim: needs 'start-end', got '{spec}'")
        actions = plan_trim(graph, s, e)
        return _ok(intent, actions, "plan_trim")

    # Standard planners
    planner_fn = PLANNERS.get(intent)
    if not planner_fn:
        return {
            "intent": intent,
            "actions": [],
            "count": 0,
            "error": f"Unknown intent: '{intent}'. "
                     f"Known: {list(PLANNERS.keys())} + "
                     f"keep_only:<label>, remove_label:<label>, "
                     f"tagged_scenes:<tag>, first_n:<sec>, last_n:<sec>, "
                     f"trim:<start>-<end>",
            "planner": None,
        }

    actions = planner_fn(graph, **kwargs)
    return _ok(intent, actions, planner_fn.__name__)


def _ok(intent: str, actions: List[dict], planner: str) -> dict:
    return {
        "intent": intent,
        "actions": actions,
        "count": len(actions),
        "planner": planner,
    }


def _error(intent: str, msg: str) -> dict:
    return {
        "intent": intent,
        "actions": [],
        "count": 0,
        "error": msg,
        "planner": None,
    }
