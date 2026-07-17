"""
Flow Context Engine — compresses a ProjectGraph into LLM-friendly text.

The problem: a 1-hour podcast ProjectGraph has ~200 nodes. Naively
formatted as JSON, that's 26,000 tokens — too much to fit in an LLM
context window alongside the system prompt and conversation history.

The Context Engine:
  1. Ranks nodes by relevance to the query
  2. Allocates a token budget per node-type
  3. Emits a compact text representation that preserves the
     most useful information for the LLM

────────────────────────────────────────────────────────────────────────
USAGE
────────────────────────────────────────────────────────────────────────

from flow_core.context_engine import ContextEngine

g = flow.observe("podcast.mp4", depth="full")
engine = ContextEngine(g)
context = engine.serve(budget_tokens=2000)
# Pass `context` to the LLM as part of the system prompt

────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
from typing import Optional, List, Dict, Tuple
from collections import defaultdict
import re


# Rough token estimate: 1 token ≈ 0.75 words (English ratio)
def _est_tokens(text: str) -> int:
    return max(1, int(len(text.split()) / 0.75))


def _fmt_time(sec: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    sec = max(0, int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# Query intent detection — simple keyword routing
_INTENT_KEYWORDS = {
    "scenes":      ("scenes",      ["scene", "act", "part", "segment", "section"]),
    "transcript":  ("transcript",  ["transcript", "say", "speak", "talk", "word", "phrase", "text"]),
    "people":      ("people",      ["who", "person", "people", "speaker", "face", "character"]),
    "objects":     ("objects",     ["what", "object", "thing", "item", "see", "show", "visible", "dog", "cat"]),
    "audio":       ("audio",       ["audio", "sound", "music", "silence", "beat", "noise", "emotion", "voice"]),
    "temporal":    ("temporal",    ["when", "time", "first", "last", "before", "after", "between", "during"]),
    "edit":        ("edit",        ["cut", "trim", "edit", "remove", "split", "where"]),
    "summary":     ("summary",     ["summary", "overview", "describe", "what is", "about"]),
}


def _detect_intent(query: str) -> str:
    """Map a free-form query to a coarse intent for budget allocation."""
    q = query.lower()
    scores: Dict[str, int] = defaultdict(int)
    for intent, (_, keywords) in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", q):
                scores[intent] += 1
    if not scores:
        return "summary"
    return max(scores.items(), key=lambda x: x[1])[0]


# Budget allocation per intent — which node types get most tokens.
# Keys match the actual `node.type` strings emitted by ProjectGraph
# (lowercase, snake_case). Update these if the graph schema changes.
_BUDGET_ALLOCATION = {
    "scenes": {
        "scene": 0.40, "clip": 0.20, "timeline": 0.10,
        "transcript": 0.10, "object": 0.10,
        "audio": 0.05, "person": 0.05,
    },
    "transcript": {
        "transcript": 0.60, "scene": 0.15, "person": 0.10,
        "audio": 0.10, "clip": 0.05,
    },
    "people": {
        "person": 0.40, "object": 0.25, "scene": 0.15,
        "transcript": 0.15, "clip": 0.05,
    },
    "objects": {
        "object": 0.50, "scene": 0.20, "clip": 0.10,
        "transcript": 0.10, "person": 0.10,
    },
    "audio": {
        "audio": 0.50, "transcript": 0.20, "scene": 0.15,
        "clip": 0.10, "person": 0.05,
    },
    "temporal": {
        "scene": 0.30, "clip": 0.20, "transcript": 0.20,
        "audio": 0.15, "object": 0.10, "person": 0.05,
    },
    "edit": {
        "scene": 0.30, "audio": 0.20, "transcript": 0.20,
        "clip": 0.15, "object": 0.10, "person": 0.05,
    },
    "summary": {
        "scene": 0.25, "transcript": 0.20, "object": 0.15,
        "audio": 0.15, "person": 0.10, "clip": 0.10,
        "timeline": 0.05,
    },
}


# Compact line per node type
def _render_node(node, max_chars: int) -> str:
    """Render a single node as a compact one-liner for LLM context."""
    t = node.type
    if t == "scene":
        topic = getattr(node, "topic", "") or ""
        return f"[Scene] {_fmt_time(node.start)}-{_fmt_time(node.end)} topic={topic!r}"
    if t == "clip":
        return f"[Clip] {_fmt_time(node.start)}-{_fmt_time(node.end)}"
    if t == "timeline":
        return f"[Timeline] fps={getattr(node, 'fps', '?')} res={getattr(node, 'resolution', '?')}"
    if t == "transcript":
        text = (getattr(node, "text", "") or "").strip()
        text = text[:max_chars] + ("..." if len(text) > max_chars else "")
        speaker = getattr(node, "speaker", "") or "?"
        return f"[Tx {speaker}] {_fmt_time(node.start)} \"{text}\""
    if t == "person":
        return f"[Person] {getattr(node, 'name', '?')} {_fmt_time(node.start)}-{_fmt_time(node.end)}"
    if t == "object":
        label = getattr(node, "label", "") or "?"
        otype = getattr(node, "object_type", "") or "?"
        conf = getattr(node, "confidence", 0)
        return f"[Obj {otype}] {label} (conf={conf:.2f}) {_fmt_time(node.start)}-{_fmt_time(node.end)}"
    if t == "audio":
        kind = "Speech" if getattr(node, "speech_active", False) else "Silence"
        em = getattr(node, "emotion", "neutral")
        beat = " [BEAT]" if getattr(node, "beat", False) else ""
        return f"[Audio {kind}] {_fmt_time(node.start)}-{_fmt_time(node.end)} emo={em}{beat}"
    if t == "asset":
        path = getattr(node, "path", "") or ""
        return f"[Asset] {path.rsplit('/', 1)[-1].rsplit(chr(92), 1)[-1]}"
    if t == "project":
        return f"[Project] {getattr(node, 'name', '?')} {getattr(node, 'duration', 0):.1f}s"
    return f"[{t}]"


class ContextEngine:
    """Compress a ProjectGraph into LLM-friendly text under a token budget.

    The engine:
      - Detects query intent (scenes/transcript/people/objects/audio/temporal/edit/summary)
      - Allocates budget per node type based on intent
      - Ranks nodes within each type (by temporal span, confidence, etc.)
      - Renders compact one-liners until budget exhausted

    The output is a single text block. When the LLM needs more detail
    on a specific node, it can call flow_query() to fetch the full record.
    """

    def __init__(self, graph):
        self.g = graph

    def serve(self,
              query: str = "",
              budget_tokens: int = 2000,
              per_node_max_chars: int = 80) -> str:
        """Build a context text under the given budget.

        Args:
            query: Free-form question/intent. Used to route budget.
                Empty string = balanced summary.
            budget_tokens: Approx max tokens for the returned text.
            per_node_max_chars: Truncate individual node lines to this.

        Returns:
            A text block, ready to be pasted into a system prompt.
        """
        intent = _detect_intent(query) if query else "summary"
        allocation = _BUDGET_ALLOCATION[intent]

        # Group nodes by type
        by_type: Dict[str, List] = defaultdict(list)
        for n in self.g.nodes.values():
            by_type[n.type].append(n)

        # Order nodes within each type
        ordered: Dict[str, List] = {}
        for t, ns in by_type.items():
            ordered[t] = self._order_nodes(t, ns, intent)

        # Build header
        header = self._render_header(intent, query)
        header_tokens = _est_tokens(header)
        body_budget = max(0, budget_tokens - header_tokens)

        # Allocate budget per type
        type_budgets: Dict[str, int] = {}
        for t, ns in ordered.items():
            share = allocation.get(t, 0.0)
            type_budgets[t] = int(body_budget * share)

        # Render each type
        sections: List[str] = []
        total_used = header_tokens
        for t, ns in ordered.items():
            if not ns:
                continue
            section = self._render_section(t, ns, type_budgets[t],
                                            per_node_max_chars)
            if section:
                sections.append(section)
                total_used += _est_tokens(section)

        # Add a footer with stats
        footer = self._render_footer()
        total_used += _est_tokens(footer)

        body = "\n\n".join(sections)
        full = f"{header}\n\n{body}\n\n{footer}" if body else f"{header}\n\n{footer}"

        # Note budget status (helps the LLM know if it's truncated)
        if total_used > budget_tokens:
            remaining = max(0, len(self.g.nodes) - sum(
                1 for s in sections for _ in s.split("\n")
                if _.startswith("[")
            ))
            full += f"\n[Note: {remaining} more nodes not shown, increase budget_tokens for more detail]"

        return full

    # ── Internals ────────────────────────────────────────────────────

    def _order_nodes(self, t: str, nodes: list, intent: str) -> list:
        """Order nodes within a type for relevance to the intent."""
        if t == "scene":
            return sorted(nodes, key=lambda n: n.start)
        if t == "transcript":
            return sorted(nodes, key=lambda n: n.start)
        if t == "audio":
            return sorted(nodes, key=lambda n: n.start)
        if t == "object":
            # By confidence desc, then by start
            return sorted(nodes, key=lambda n: (-getattr(n, "confidence", 0),
                                                n.start))
        if t == "person":
            return sorted(nodes, key=lambda n: n.start)
        if t == "clip":
            return sorted(nodes, key=lambda n: n.start)
        if t == "asset":
            return nodes
        if t == "project":
            return nodes
        if t == "timeline":
            return nodes
        return nodes

    def _render_header(self, intent: str, query: str) -> str:
        s = self.g.stats()
        n = s.get("name", "untitled")
        nodes = s.get("total_nodes", 0)
        edges = s.get("total_edges", 0)
        by_type = s.get("by_type", {})
        # Find duration
        duration = 0.0
        if self.g.clips:
            duration = max(c.end for c in self.g.clips)
        elif self.g.scenes:
            duration = max(s.end for s in self.g.scenes)
        # Type counts
        type_str = ", ".join(f"{k}:{v}" for k, v in
                            sorted(by_type.items(),
                                   key=lambda x: -x[1])[:5])
        if query:
            header = (f"# Project: {n} | {duration:.1f}s | "
                      f"{nodes} nodes, {edges} edges\n"
                      f"# Query: {query}\n"
                      f"# Focus: {intent}\n"
                      f"# Top types: {type_str}")
        else:
            header = (f"# Project: {n} | {duration:.1f}s | "
                      f"{nodes} nodes, {edges} edges\n"
                      f"# Top types: {type_str}")
        return header

    def _render_section(self, t: str, nodes: list,
                        budget: int, max_chars: int) -> str:
        """Render one type-section under its allocated budget."""
        if budget <= 0 or not nodes:
            return ""
        lines: List[str] = [f"## {t}s ({len(nodes)} total)"]
        used = _est_tokens(lines[0])
        for n in nodes:
            line = _render_node(n, max_chars)
            line_tokens = _est_tokens(line)
            if used + line_tokens > budget:
                remaining = len(nodes) - len(lines) + 1
                if remaining > 0:
                    lines.append(f"... ({remaining} more {t}s not shown)")
                break
            lines.append(line)
            used += line_tokens
        return "\n".join(lines)

    def _render_footer(self) -> str:
        s = self.g.stats()
        # Compact by_type string
        type_counts = s.get("by_type", {})
        types = ", ".join(f"{k}={v}" for k, v in
                          sorted(type_counts.items()))
        return f"# Stats: {types}"
