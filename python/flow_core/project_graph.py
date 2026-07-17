"""
ProjectGraph — Typed graph representing a video project.

Every node is Observable: agents call observe() and summary() without
knowing the concrete type. The Context Engine queries nodes through
this uniform interface. The Graph owns all edges and provides window()
for temporal queries.

Concrete types: Clip, Scene, TranscriptSegment, Person, DetectedObject,
AudioSegment, Effect, Asset, Project, Timeline, Track.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from collections import defaultdict


# ═══════════════════════════════════════════════════════════════════════════
# Observable — the uniform interface for AI agents
# ═══════════════════════════════════════════════════════════════════════════

class Observable:
    """Interface for every node an agent can observe.

    The Context Engine calls these without knowing the concrete type.
    Each node type overrides observe() / summary() to return the
    information an AI agent needs.
    """

    def observe(self) -> str:
        """Rich one-paragraph description for an AI agent."""
        return f"[{getattr(self, 'type', '?')}] {getattr(self, 'id', '?')}"

    def summary(self) -> str:
        """One-line compact form (~80 chars)."""
        return self.observe()[:80]

    @property
    def start(self) -> float:
        return 0.0

    @property
    def end(self) -> float:
        return 0.0


# ═══════════════════════════════════════════════════════════════════════════
# GraphNode — base for all typed nodes
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class GraphNode(Observable):
    id: str = ""
    type: str = ""

    def to_dict(self) -> dict:
        d = {"id": self.id, "type": self.type}
        for key, value in self.__dict__.items():
            if key not in ("id", "type") and not key.startswith("_"):
                d[key] = value
        return d


# ═══════════════════════════════════════════════════════════════════════════
# Concrete node types — each is Observable
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Project(GraphNode):
    type: str = "project"
    name: str = "untitled"
    fps: float = 24.0
    resolution: str = "1920x1080"
    duration: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def observe(self) -> str:
        m, s = divmod(int(self.duration), 60)
        h, m = divmod(m, 60)
        dur = f"{h}h{m}m{s}s" if h else f"{m}m{s}s"
        return (f"Project '{self.name}' — {dur}, {self.resolution}@{self.fps}fps")

    def summary(self) -> str:
        return f"Project '{self.name}'"


@dataclass
class Timeline(GraphNode):
    type: str = "timeline"
    name: str = "Main Timeline"
    fps: float = 24.0
    resolution: str = "1920x1080"

    def observe(self) -> str:
        return f"Timeline '{self.name}' — {self.resolution}@{self.fps}fps"

    def summary(self) -> str:
        return f"Timeline '{self.name}'"


@dataclass
class Track(GraphNode):
    type: str = "track"
    name: str = ""
    index: int = 0

    def observe(self) -> str:
        return f"Track {self.index} '{self.name}'"

    def summary(self) -> str:
        return f"Track {self.index}"


@dataclass
class Clip(GraphNode):
    type: str = "clip"
    start: float = 0.0
    end: float = 0.0
    duration: float = 0.0
    source: str = ""
    source_start: float = 0.0
    track: str = ""
    transition_in: Optional[str] = None
    transition_out: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def observe(self) -> str:
        src = self.source.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return (f"Clip from {_fmt(self.start)} to {_fmt(self.end)} "
                f"({_dur(self.duration)}) — source: {src}")

    def summary(self) -> str:
        return f"Clip {_fmt(self.start)}-{_fmt(self.end)}"


@dataclass
class Scene(GraphNode):
    type: str = "scene"
    start: float = 0.0
    end: float = 0.0
    duration: float = 0.0
    topic: str = ""
    location: str = ""
    activity: str = ""
    mood: str = ""
    people: List[str] = field(default_factory=list)

    def observe(self) -> str:
        parts = [f"Scene '{self.topic}' — {_fmt(self.start)} to {_fmt(self.end)}"]
        if self.people:
            parts.append(f"with {', '.join(self.people[:3])}")
        if self.mood:
            parts.append(f"mood: {self.mood}")
        if self.activity:
            parts.append(f"activity: {self.activity}")
        return " | ".join(parts)

    def summary(self) -> str:
        return f"Scene '{self.topic}' at {_fmt(self.start)}"


@dataclass
class TranscriptSegment(GraphNode):
    type: str = "transcript"
    start: float = 0.0
    end: float = 0.0
    text: str = ""
    speaker: str = ""
    confidence: float = 0.0
    scene_id: str = ""
    has_filler: bool = False

    def observe(self) -> str:
        text = self.text[:120] + ("..." if len(self.text) > 120 else "")
        return (f"[{_fmt(self.start)}] {self.speaker}: \"{text}\" "
                f"(conf: {self.confidence:.0%})")

    def summary(self) -> str:
        return f"[{_fmt(self.start)}] {self.speaker}: \"{self.text[:40]}...\""


@dataclass
class Person(GraphNode):
    type: str = "person"
    name: str = ""
    start: float = 0.0
    end: float = 0.0
    scene_id: str = ""

    def observe(self) -> str:
        return f"Person '{self.name}' appears {_fmt(self.start)}-{_fmt(self.end)}"

    def summary(self) -> str:
        return f"Person '{self.name}'"


@dataclass
class DetectedObject(GraphNode):
    type: str = "object"
    object_type: str = ""
    label: str = ""
    start: float = 0.0
    end: float = 0.0
    scene_id: str = ""
    confidence: float = 0.0
    bbox: Dict[str, Any] = field(default_factory=dict)
    attributes: Dict[str, Any] = field(default_factory=dict)

    def observe(self) -> str:
        # Prefer label (human-readable name) over object_type (machine tag)
        name = self.label or self.object_type
        conf = f" (conf={self.confidence:.2f})" if self.confidence else ""
        return f"Object '{name}'{conf} at {_fmt(self.start)}-{_fmt(self.end)}"

    def summary(self) -> str:
        name = self.label or self.object_type
        return f"Object '{name}'"


@dataclass
class AudioSegment(GraphNode):
    type: str = "audio"
    start: float = 0.0
    end: float = 0.0
    time: float = 0.0  # alias for start (midpoint in legacy stub)
    rms: float = 0.0
    beat: bool = False
    emotion: str = "neutral"
    noise_level: float = 0.0
    speech_active: bool = False

    def observe(self) -> str:
        flags = []
        if self.beat:
            flags.append("beat")
        if self.speech_active:
            flags.append("speech")
        if self.speech_active:
            label = f"Speech {_fmt(self.start)} → {_fmt(self.end)}"
        else:
            label = f"Silence {_fmt(self.start)} → {_fmt(self.end)}"
        return (f"{label} — RMS:{self.rms:.1f}dB "
                f"emotion:{self.emotion} noise:{self.noise_level:.2f}"
                + (f" [{', '.join(flags)}]" if flags else ""))

    def summary(self) -> str:
        kind = "Speech" if self.speech_active else "Silence"
        return f"{kind} {_fmt(self.start)} → {_fmt(self.end)}"


@dataclass
class Effect(GraphNode):
    type: str = "effect"
    effect_type: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    clip_id: str = ""

    def observe(self) -> str:
        return f"Effect '{self.effect_type}' on clip {self.clip_id}"

    def summary(self) -> str:
        return f"Effect '{self.effect_type}'"


@dataclass
class Asset(GraphNode):
    type: str = "asset"
    path: str = ""
    asset_type: str = "video"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def observe(self) -> str:
        name = self.path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        dur = self.metadata.get("duration", 0)
        codec = self.metadata.get("codec", "?")
        return f"Asset '{name}' — {self.asset_type}, {codec}, {_dur(dur)}"

    def summary(self) -> str:
        return f"Asset '{self.path.rsplit('/', 1)[-1]}'"


# ═══════════════════════════════════════════════════════════════════════════
# Edge
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class GraphEdge:
    """Directed, typed relationship."""
    source: str
    target: str
    relation: str

    def observe(self) -> str:
        return f"{self.source} --[{self.relation}]--> {self.target}"


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _fmt(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _dur(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}m{s}s" if m else f"{s}s"


NODE_CLASSES = {
    "project": Project, "timeline": Timeline, "track": Track,
    "clip": Clip, "scene": Scene, "transcript": TranscriptSegment,
    "person": Person, "object": DetectedObject, "audio": AudioSegment,
    "effect": Effect, "asset": Asset,
}


# ═══════════════════════════════════════════════════════════════════════════
# ProjectGraph
# ═══════════════════════════════════════════════════════════════════════════

class ProjectGraph:
    """Typed DAG representing a video project.

    Every node is Observable. Agents observe() nodes, query the graph
    by window() or search(), and traverse relationships().
    """

    def __init__(self, name: str = "untitled"):
        self.name = name
        self.nodes: Dict[str, GraphNode] = {}
        self._out: Dict[str, List[tuple]] = defaultdict(list)
        self._in: Dict[str, List[tuple]] = defaultdict(list)

    # ── Mutation ────────────────────────────────────────────────────────

    def add(self, node: GraphNode) -> GraphNode:
        if not node.id:
            import uuid
            node.id = f"{node.type}:{uuid.uuid4().hex[:8]}"
        self.nodes[node.id] = node
        return node

    def add_edge(self, source: str, target: str, relation: str = "contains"):
        if source not in self.nodes:
            raise KeyError(f"Source not found: {source}")
        if target not in self.nodes:
            raise KeyError(f"Target not found: {target}")
        self._out[source].append((target, relation))
        self._in[target].append((source, relation))

    def remove_node(self, node_id: str):
        for tgt, _ in list(self._out.get(node_id, [])):
            self._in[tgt] = [(s, r) for s, r in self._in.get(tgt, []) if s != node_id]
        for src, _ in list(self._in.get(node_id, [])):
            self._out[src] = [(t, r) for t, r in self._out.get(src, []) if t != node_id]
        self._out.pop(node_id, None)
        self._in.pop(node_id, None)
        self.nodes.pop(node_id, None)

    # ── Relationships ───────────────────────────────────────────────────

    def neighbors(self, node_id: str) -> List[GraphNode]:
        """All nodes connected to node_id by any edge (in or out)."""
        result = []
        seen = {node_id}
        for tgt, _ in self._out.get(node_id, []):
            if tgt not in seen:
                seen.add(tgt)
                result.append(self.nodes.get(tgt))
        for src, _ in self._in.get(node_id, []):
            if src not in seen:
                seen.add(src)
                result.append(self.nodes.get(src))
        return [n for n in result if n]

    def relationships(self, node_id: str) -> List[GraphEdge]:
        """All edges touching node_id."""
        edges = []
        for tgt, rel in self._out.get(node_id, []):
            edges.append(GraphEdge(source=node_id, target=tgt, relation=rel))
        for src, rel in self._in.get(node_id, []):
            edges.append(GraphEdge(source=src, target=node_id, relation=rel))
        return edges

    def children(self, node_id: str, relation: Optional[str] = None) -> List[GraphNode]:
        edges = self._out.get(node_id, [])
        if relation:
            edges = [(t, r) for t, r in edges if r == relation]
        return [self.nodes[t] for t, _ in edges if t in self.nodes]

    def parents(self, node_id: str, relation: Optional[str] = None) -> List[GraphNode]:
        edges = self._in.get(node_id, [])
        if relation:
            edges = [(s, r) for s, r in edges if r == relation]
        return [self.nodes[s] for s, _ in edges if s in self.nodes]

    # ── Temporal queries ────────────────────────────────────────────────

    def window(self, start: float, end: float) -> Dict[str, List[GraphNode]]:
        """Return all nodes active in [start, end], grouped by type.

        This is the primary query for agents: \"what's happening
        between 12:18 and 12:48?\" Returns clips, scenes, transcript,
        people, objects, and audio segments active in that window.
        """
        result: Dict[str, List[GraphNode]] = defaultdict(list)
        for node in self.nodes.values():
            ns = getattr(node, "start", None)
            ne = getattr(node, "end", None)
            if ns is not None and ne is not None:
                if ns < end and ne > start:  # overlap
                    result[node.type].append(node)
        # Sort each group by start time
        for key in result:
            result[key].sort(key=lambda n: getattr(n, "start", 0))
        return dict(result)

    def observe_window(self, start: float, end: float) -> str:
        """Rich textual observation of a time window for an AI agent.

        Returns a formatted string with all nodes in the window,
        using each node's observe() method. This is what the Context
        Engine would serve to the LLM.
        """
        w = self.window(start, end)
        lines = [f"Window {_fmt(start)} --> {_fmt(end)}:"]
        order = ["scene", "clip", "transcript", "person", "object", "audio"]
        for key in order:
            nodes = w.get(key, [])
            if nodes:
                lines.append(f"\n  {key}s ({len(nodes)}):")
                for n in nodes[:8]:  # cap at 8 per type
                    lines.append(f"    {n.observe()}")
        return "\n".join(lines)

    def at_time(self, t: float) -> List[GraphNode]:
        """All nodes active at exact time t."""
        result = []
        for n in self.nodes.values():
            ns = getattr(n, "start", None)
            ne = getattr(n, "end", None)
            if ns is not None and ne is not None and ns <= t < ne:
                result.append(n)
        return sorted(result, key=lambda n: getattr(n, "start", 0))

    # ── Typed properties ────────────────────────────────────────────────

    @property
    def clips(self) -> List[Clip]:
        return sorted(
            [n for n in self.nodes.values() if isinstance(n, Clip)],
            key=lambda x: x.start
        )

    @property
    def scenes(self) -> List[Scene]:
        return sorted(
            [n for n in self.nodes.values() if isinstance(n, Scene)],
            key=lambda x: x.start
        )

    @property
    def transcript(self) -> List[TranscriptSegment]:
        return sorted(
            [n for n in self.nodes.values() if isinstance(n, TranscriptSegment)],
            key=lambda x: x.start
        )

    @property
    def people(self) -> List[Person]:
        return [n for n in self.nodes.values() if isinstance(n, Person)]

    @property
    def objects(self) -> List[DetectedObject]:
        return [n for n in self.nodes.values() if isinstance(n, DetectedObject)]

    @property
    def audio(self) -> List[AudioSegment]:
        return sorted(
            [n for n in self.nodes.values() if isinstance(n, AudioSegment)],
            key=lambda x: x.time
        )

    @property
    def effects(self) -> List[Effect]:
        return [n for n in self.nodes.values() if isinstance(n, Effect)]

    @property
    def assets(self) -> List[Asset]:
        return [n for n in self.nodes.values() if isinstance(n, Asset)]

    # ── Queries ─────────────────────────────────────────────────────────

    def get(self, node_id: str) -> Optional[GraphNode]:
        return self.nodes.get(node_id)

    def __getitem__(self, node_id: str) -> GraphNode:
        return self.nodes[node_id]

    def find_by_type(self, cls):
        return [n for n in self.nodes.values() if isinstance(n, cls)]

    def search(self, query: str) -> List[GraphNode]:
        q = query.lower()
        results = []
        for n in self.nodes.values():
            d = n.to_dict()
            for v in d.values():
                if isinstance(v, str) and q in v.lower():
                    results.append(n)
                    break
                if isinstance(v, list):
                    for item in v:
                        if isinstance(item, str) and q in item.lower():
                            results.append(n)
                            break
                    else:
                        continue
                    break
        return results

    # ── Serialization ──────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [
                {"source": src, "target": tgt, "relation": rel}
                for src, edges in self._out.items()
                for tgt, rel in edges
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectGraph":
        g = cls(name=d["name"])
        for nd in d["nodes"]:
            cls_name = NODE_CLASSES.get(nd["type"])
            if cls_name:
                kwargs = {k: v for k, v in nd.items()
                          if k not in ("type",) and not k.startswith("_")}
                g.add(cls_name(**kwargs))
        for e in d["edges"]:
            g.add_edge(e["source"], e["target"], e["relation"])
        return g

    # ── Info ────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        type_counts = defaultdict(int)
        for n in self.nodes.values():
            type_counts[n.type] += 1
        edge_count = sum(len(v) for v in self._out.values())
        return {
            "name": self.name,
            "total_nodes": len(self.nodes),
            "total_edges": edge_count,
            "by_type": dict(type_counts),
        }

    def summary(self) -> str:
        s = self.stats()
        parts = [f"{c} {t}{'s' if c != 1 else ''}"
                 for t, c in sorted(s["by_type"].items())]
        parts.append(f"{s['total_edges']} edge{'s' if s['total_edges'] != 1 else ''}")
        return f"ProjectGraph({self.name}): " + ", ".join(parts)

    def __repr__(self):
        return self.summary()
