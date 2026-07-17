"""
Flow Context Engine v0.2 — Decision-Accurate Benchmark

What's new vs v0.1:
  - Modular Query Planner: Intent Parser → Resolver Pipeline → Cost Optimizer
  - Semantic Graph: entity-relationship queries
  - Adaptive Budget: planner says "need more tokens" instead of silently failing
  - Edit Accuracy: closed-loop benchmark (ground truth edits vs generated edits)
  - Offline/Online cost accounting
  - 4 real-world video scenarios (podcast, interview, vlog, tutorial)

Run: python context_engine_v2.py
"""

import json, random, time, sys, io, math, re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set, Tuple
from collections import defaultdict
from enum import Enum

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# ═══════════════════════════════════════════════════════════════════════════
# 1. COST MODEL
# ═══════════════════════════════════════════════════════════════════════════

class CostModel:
    """Tracks both offline (indexing) and online (query) costs."""

    def __init__(self):
        self.offline_tokens = 0   # tokens spent building indexes (amortized once)
        self.online_tokens = 0    # tokens spent on queries
        self.offline_sec = 0.0
        self.online_sec = 0.0
        self.query_count = 0

    def add_offline(self, tokens, seconds):
        self.offline_tokens += tokens
        self.offline_sec += seconds

    def add_online(self, tokens, seconds):
        self.online_tokens += tokens
        self.online_sec += seconds
        self.query_count += 1

    def total_cost(self, n_queries=100):
        """Amortized cost: offline / n_queries + online average."""
        return (self.offline_tokens / n_queries) + (self.online_tokens / max(1, self.query_count))

    def summary(self, n_queries=100):
        return {
            "offline_tokens": self.offline_tokens,
            "offline_sec": round(self.offline_sec, 2),
            "online_avg_tokens": self.online_tokens / max(1, self.query_count),
            "online_avg_ms": (self.online_sec / max(1, self.query_count)) * 1000,
            "amortized_tokens_per_query": self.total_cost(n_queries),
        }


# ═══════════════════════════════════════════════════════════════════════════
# 2. SCENARIO GENERATORS — Realistic video types
# ═══════════════════════════════════════════════════════════════════════════

SCENARIO_SPECS = {
    "podcast": {
        "duration_min": 45,
        "topics": ["Opening", "Guest Introduction", "Career Story", "Industry Trends",
                   "Controversial Take", "Advice Segment", "Rapid Fire", "Closing"],
        "speakers": ["Host_Alex", "Guest_Maya"],
        "locations": ["Studio"],
        "activities": ["Discussion", "Laughter", "Story", "Debate"],
        "edit_style": "tighten_pauses",
        "n_edits": 15,
    },
    "interview": {
        "duration_min": 25,
        "topics": ["Introduction", "Background", "Role Overview", "Technical Questions",
                   "Problem Solving", "Culture Fit", "Candidate Questions", "Wrap-up"],
        "speakers": ["Interviewer_Dan", "Candidate_Sam"],
        "locations": ["Meeting Room"],
        "activities": ["Q&A", "Whiteboarding", "Discussion", "Presentation"],
        "edit_style": "remove_ums",
        "n_edits": 20,
    },
    "vlog": {
        "duration_min": 15,
        "topics": ["Intro", "Setup", "Main Content", "B-roll", "Review", "Outro"],
        "speakers": ["Creator_Jo"],
        "locations": ["Home Office", "City Street", "Cafe", "Park"],
        "activities": ["Talking Head", "Walking", "Cooking", "Review"],
        "edit_style": "jump_cuts",
        "n_edits": 25,
    },
    "tutorial": {
        "duration_min": 30,
        "topics": ["Intro", "Prerequisites", "Step 1", "Step 2", "Step 3",
                   "Common Mistakes", "Results", "Next Steps"],
        "speakers": ["Teacher_Lee"],
        "locations": ["Desk", "Screen Capture"],
        "activities": ["Explanation", "Demo", "Screen Share", "Summary"],
        "edit_style": "remove_dead_air",
        "n_edits": 12,
    },
}

# Common keyword sets per topic type
TOPIC_KEYWORDS = {
    "Opening": ["welcome", "today", "episode", "excited", "introduce"],
    "Guest Introduction": ["guest", "join", "background", "experience", "known for"],
    "Career Story": ["started", "career", "journey", "industry", "moved", "company"],
    "Industry Trends": ["trend", "changing", "future", "technology", "shift", "growth"],
    "Controversial Take": ["unpopular", "opinion", "disagree", "actually", "wrong", "hot take"],
    "Advice Segment": ["advice", "recommend", "suggest", "lesson", "learned", "mistake"],
    "Rapid Fire": ["quick", "favorite", "best", "worst", "answer", "next"],
    "Closing": ["thanks", "follow", "subscribe", "next episode", "goodbye"],
    "Introduction": ["role", "position", "company", "apply", "background"],
    "Background": ["previous", "worked", "studied", "graduated", "experience"],
    "Role Overview": ["responsibilities", "team", "project", "daily", "report"],
    "Technical Questions": ["code", "system", "architecture", "solve", "problem"],
    "Problem Solving": ["approach", "solution", "design", "implement", "test"],
    "Culture Fit": ["team", "values", "collaborate", "culture", "environment"],
    "Candidate Questions": ["ask", "wonder", "curious", "benefits", "growth"],
    "Setup": ["setup", "camera", "light", "mic", "prepare"],
    "Main Content": ["review", "test", "compare", "show", "result"],
    "B-roll": [],  # no speech
    "Review": ["pros", "cons", "verdict", "recommend", "score"],
    "Outro": ["subscribe", "like", "comment", "next video", "bye"],
    "Prerequisites": ["need", "install", "require", "before", "version"],
    "Step 1": ["first", "start", "open", "create", "initial"],
    "Step 2": ["next", "configure", "set up", "connect", "add"],
    "Step 3": ["finally", "deploy", "run", "execute", "complete"],
    "Common Mistakes": ["error", "wrong", "mistake", "forget", "check"],
    "Results": ["output", "result", "working", "done", "finished"],
    "Next Steps": ["next", "learn more", "advanced", "practice", "project"],
    "Intro": ["hey", "welcome", "today", "video", "showing"],
    "Talking Head": ["think", "believe", "opinion", "honestly", "actually"],
    "Cooking": ["ingredients", "mix", "cook", "taste", "add"],
}

FILLER_WORDS = ["um", "uh", "like", "you know", "I mean", "sort of", "kind of", "right",
                "actually", "basically", "so", "well", "just", "really", "very"]


def generate_scenario(scenario_type="podcast", seed=42):
    """Generate a realistic video project with ground truth edits."""
    spec = SCENARIO_SPECS[scenario_type]
    random.seed(seed)
    duration_sec = spec["duration_min"] * 60

    project = {
        "name": f"{scenario_type}_{spec['duration_min']}min",
        "scenario": scenario_type,
        "duration": duration_sec,
        "edit_style": spec["edit_style"],
        "scenes": [],
        "transcript": [],
        "timeline": [],
        "ground_truth_edits": [],
    }

    # Build scenes — evenly distributed
    topics = spec["topics"]
    scene_dur = duration_sec / len(topics)
    for i, topic in enumerate(topics):
        start = i * scene_dur
        end = min(start + scene_dur, duration_sec)
        speaker = random.choice(spec["speakers"])
        project["scenes"].append({
            "id": f"scene_{i:04d}",
            "start": round(start, 1),
            "end": round(end, 1),
            "topic": topic,
            "speakers": [speaker] if random.random() < 0.8 else spec["speakers"][:2],
            "location": random.choice(spec["locations"]),
            "activity": random.choice(spec["activities"]),
            "keywords": TOPIC_KEYWORDS.get(topic, []),
        })

    # Build transcript — spawn keywords at known positions for ground truth
    all_keywords = {}
    for scene in project["scenes"]:
        words = int((scene["end"] - scene["start"]) / 60 * 140)  # ~140 WPM
        kw_list = scene["keywords"] or ["discuss", "talk", "point"]
        scene_words = []
        # Sprinkle keywords + filler
        n_kw = min(len(kw_list) * 2, words // 20)
        if n_kw == 0:
            n_kw = 1
        kw_positions = sorted(random.sample(range(words // 10, max(words // 10 + 1, words - 5)), n_kw))
        kw_idx = 0
        for w in range(words):
            if kw_idx < len(kw_positions) and w == kw_positions[kw_idx]:
                kw = kw_list[kw_idx % len(kw_list)]
                scene_words.append(kw)
                if kw not in all_keywords:
                    all_keywords[kw] = []
                all_keywords[kw].append(scene["start"] + (w / words) * (scene["end"] - scene["start"]))
                kw_idx += 1
            elif random.random() < 0.05:  # 5% filler words
                scene_words.append(random.choice(FILLER_WORDS))
            else:
                scene_words.append(random.choice(
                    ["the", "a", "is", "was", "are", "and", "in", "on", "to", "for",
                     "with", "from", "by", "we", "they", "our", "this", "that", "it",
                     "have", "has", "will", "can", "about", "also", "now", "very"]))

        # Split into transcript segments
        seg_size = 30
        for s in range(0, len(scene_words), seg_size):
            seg_words = scene_words[s:s + seg_size]
            if not seg_words:
                continue
            seg_start = scene["start"] + (s / len(scene_words)) * (scene["end"] - scene["start"])
            seg_end = seg_start + (len(seg_words) / len(scene_words)) * (scene["end"] - scene["start"])
            project["transcript"].append({
                "id": f"tx_{len(project['transcript']):05d}",
                "start": round(seg_start, 1),
                "end": round(seg_end, 1),
                "text": " ".join(seg_words),
                "speaker": random.choice(scene["speakers"]),
                "scene_id": scene["id"],
                "has_filler": any(fw in seg_words for fw in FILLER_WORDS),
            })

    # Timeline: one clip per scene (simplified)
    for scene in project["scenes"]:
        project["timeline"].append({
            "id": f"clip_{scene['id']}",
            "track": "track_0",
            "start": scene["start"],
            "end": scene["end"],
            "source": f"{scenario_type}_raw.mp4",
            "scene_id": scene["id"],
        })

    # Generate ground truth edits based on scenario type
    edits = _generate_ground_truth_edits(project, spec)
    project["ground_truth_edits"] = edits

    return project, all_keywords


def _generate_ground_truth_edits(project, spec):
    """Generate ground truth edits appropriate for the scenario type."""
    edits = []
    style = spec["edit_style"]
    keyword_positions = {}

    # Collect keyword positions from transcript
    for tx in project["transcript"]:
        for kw in project["scenes"][0]["keywords"]:  # simplified — use first scene's keywords
            if kw in tx["text"].lower():
                if kw not in keyword_positions:
                    keyword_positions[kw] = []
                keyword_positions[kw].append(tx["start"])

    n = spec["n_edits"]

    if style == "tighten_pauses":
        # Cut out filler words and long pauses
        fillers = [tx for tx in project["transcript"] if tx["has_filler"]]
        for tx in random.sample(fillers, min(n, len(fillers))):
            edits.append({
                "id": f"edit_{len(edits):04d}",
                "type": "trim",
                "start": tx["start"],
                "end": tx["end"],
                "reason": f"Remove filler words from {tx['speaker']}",
                "scene_id": tx["scene_id"],
            })

    elif style == "remove_ums":
        # Cut specific um/uh segments
        for tx in project["transcript"]:
            if "um" in tx["text"] or "uh" in tx["text"]:
                edits.append({
                    "id": f"edit_{len(edits):04d}",
                    "type": "trim",
                    "start": tx["start"],
                    "end": tx["end"],
                    "reason": f"Remove hesitation from {tx['speaker']}",
                    "scene_id": tx["scene_id"],
                })
        edits = edits[:n]

    elif style == "jump_cuts":
        # Cut between speaking segments to tighten pacing
        speakers = list(set(tx["speaker"] for tx in project["transcript"]))
        for i in range(n):
            tx = random.choice(project["transcript"])
            edits.append({
                "id": f"edit_{len(edits):04d}",
                "type": "trim",
                "start": tx["start"],
                "end": tx["end"],
                "reason": "Jump cut to tighten pacing",
                "scene_id": tx["scene_id"],
            })

    elif style == "remove_dead_air":
        # Cut segments where no keyword appears (dead air)
        non_content = [tx for tx in project["transcript"]
                       if not any(kw in tx["text"].lower() for kw_list in TOPIC_KEYWORDS.values() for kw in kw_list)]
        for tx in random.sample(non_content, min(n, len(non_content))):
            edits.append({
                "id": f"edit_{len(edits):04d}",
                "type": "trim",
                "start": tx["start"],
                "end": tx["end"],
                "reason": "Remove dead air / non-content segment",
                "scene_id": tx["scene_id"],
            })

    # Pad with synthetic edits if not enough
    while len(edits) < n:
        tx = random.choice(project["transcript"])
        edits.append({
            "id": f"edit_{len(edits):04d}",
            "type": "trim",
            "start": tx["start"],
            "end": tx["end"],
            "reason": "Minor trim for pacing",
            "scene_id": tx["scene_id"],
        })

    # Remove duplicates
    seen = set()
    unique = []
    for e in edits:
        key = (e["start"], e["end"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique[:n]


# ═══════════════════════════════════════════════════════════════════════════
# 3. SEMANTIC GRAPH
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SemanticNode:
    id: str
    type: str      # "person", "topic", "event", "location", "key_moment"
    label: str
    time: float    # when it occurs
    properties: dict = field(default_factory=dict)


@dataclass
class SemanticEdge:
    source: str
    target: str
    relation: str  # "speaks_about", "precedes", "follows", "contains", "transitions_to"
    weight: float = 1.0


class SemanticGraph:
    """Entity-relationship graph for cross-modal queries."""

    def __init__(self):
        self.nodes: Dict[str, SemanticNode] = {}
        self.edges: List[SemanticEdge] = []
        self.adj_out: Dict[str, List[SemanticEdge]] = defaultdict(list)
        self.adj_in: Dict[str, List[SemanticEdge]] = defaultdict(list)

    def add_node(self, node: SemanticNode):
        self.nodes[node.id] = node

    def add_edge(self, edge: SemanticEdge):
        self.edges.append(edge)
        self.adj_out[edge.source].append(edge)
        self.adj_in[edge.target].append(edge)

    def build_from_project(self, project):
        """Auto-build semantic graph from project data."""
        # Person nodes
        all_speakers = set()
        for scene in project["scenes"]:
            for sp in scene["speakers"]:
                all_speakers.add(sp)
        for sp in all_speakers:
            self.add_node(SemanticNode(f"person:{sp}", "person", sp, 0))
            # Find all mentions
            for tx in project["transcript"]:
                if tx["speaker"] == sp:
                    self.add_node(SemanticNode(f"moment:{sp}_{tx['id']}", "key_moment",
                                               f"{sp} speaks", tx["start"],
                                               {"scene_id": tx.get("scene_id", "")}))
                    self.add_edge(SemanticEdge(f"person:{sp}", f"moment:{sp}_{tx['id']}", "speaks"))

        # Topic nodes — from scenes
        for scene in project["scenes"]:
            topic_id = f"topic:{scene['topic']}"
            self.add_node(SemanticNode(topic_id, "topic", scene["topic"], scene["start"],
                                       {"scene_id": scene["id"]}))
            # Connect speakers to topics
            for sp in scene["speakers"]:
                self.add_edge(SemanticEdge(f"person:{sp}", topic_id, "speaks_about"))

        # Sequential connections between scenes
        scenes = sorted(project["scenes"], key=lambda s: s["start"])
        for i in range(len(scenes) - 1):
            self.add_edge(SemanticEdge(
                f"topic:{scenes[i]['topic']}",
                f"topic:{scenes[i+1]['topic']}",
                "precedes", 0.8
            ))
            self.add_edge(SemanticEdge(
                f"topic:{scenes[i+1]['topic']}",
                f"topic:{scenes[i]['topic']}",
                "follows", 0.8
            ))

    def query_path(self, from_node: str, to_node: str, max_hops=4):
        """BFS to find a path between two nodes."""
        if from_node not in self.nodes or to_node not in self.nodes:
            return None
        visited = {from_node}
        queue = [(from_node, [from_node])]
        while queue:
            current, path = queue.pop(0)
            if current == to_node:
                return path
            if len(path) >= max_hops:
                continue
            for edge in self.adj_out.get(current, []):
                if edge.target not in visited:
                    visited.add(edge.target)
                    queue.append((edge.target, path + [edge.target]))
        return None

    def related_nodes(self, node_id: str, relations=None, max_depth=2):
        """Find all nodes connected to node_id within max_depth hops."""
        if node_id not in self.nodes:
            return []
        result = set()
        queue = [(node_id, 0)]
        visited = {node_id}
        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for edge in self.adj_out.get(current, []):
                if relations and edge.relation not in relations:
                    continue
                if edge.target not in visited:
                    visited.add(edge.target)
                    result.add(edge.target)
                    queue.append((edge.target, depth + 1))
            for edge in self.adj_in.get(current, []):
                if relations and edge.relation not in relations:
                    continue
                if edge.source not in visited:
                    visited.add(edge.source)
                    result.add(edge.source)
                    queue.append((edge.source, depth + 1))
        return list(result)

    def find_by_type(self, node_type: str):
        return [n for n in self.nodes.values() if n.type == node_type]


# ═══════════════════════════════════════════════════════════════════════════
# 4. INDEXES (same core, plus SemanticGraphIndex)
# ═══════════════════════════════════════════════════════════════════════════

class BTreeIndex:
    def __init__(self, key_fn):
        self.key_fn = key_fn
        self.items = []

    def build(self, items):
        self.items = sorted(items, key=self.key_fn)

    def range(self, lo, hi):
        return [it for it in self.items if lo <= self.key_fn(it) < hi]

    def nearest(self, value, n=1):
        scored = [(abs(self.key_fn(it) - value), it) for it in self.items]
        scored.sort(key=lambda x: x[0])
        return [it for _, it in scored[:n]]


class FTSIndex:
    def __init__(self, text_fn):
        self.text_fn = text_fn
        self.items = []

    def build(self, items):
        self.items = items

    def search(self, query, limit=5):
        terms = query.lower().split()
        scored = []
        for item in self.items:
            text = self.text_fn(item).lower()
            score = sum(text.count(t) for t in terms)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:limit]]


class TranscriptIndex:
    def __init__(self):
        self.by_time = BTreeIndex(lambda s: s["start"])
        self.by_text = FTSIndex(lambda s: s["text"])

    def build(self, tx):
        self.by_time.build(tx)
        self.by_text.build(tx)

    def search_text(self, q, limit=5):
        return self.by_text.search(q, limit)

    def range(self, s, e):
        return self.by_time.range(s, e)

    def at_time(self, t):
        r = self.by_time.nearest(t, 1)
        return r[0] if r else None


class SceneIndex:
    def __init__(self):
        self.by_time = BTreeIndex(lambda s: s["start"])

    def build(self, scenes):
        self.by_time.build(scenes)

    def at_time(self, t):
        r = self.by_time.nearest(t, 1)
        return r[0] if r else None

    def range(self, s, e):
        return self.by_time.range(s, e)

    def find_by_topic(self, topic):
        return [s for s in self.by_time.items if s["topic"].lower() == topic.lower()]


class TimelineIndex:
    def __init__(self):
        self.by_id = {}

    def build(self, clips):
        self.by_id = {c["id"]: c for c in clips}

    def get(self, cid):
        return self.by_id.get(cid)

    def at_time(self, t):
        for c in self.by_id.values():
            if c["start"] <= t < c["end"]:
                return c
        return None


# ═══════════════════════════════════════════════════════════════════════════
# 5. PAGES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Page:
    type: str
    id: str
    tokens: int
    content: str

    def __hash__(self):
        return hash((self.type, self.id))

    def __eq__(self, other):
        return self.type == other.type and self.id == other.id


def _est_tokens(text):
    return max(1, int(len(text.split()) / 0.75))


def _fmt_time(sec):
    return f"{int(sec//3600):02d}:{int(sec%3600//60):02d}:{int(sec%60):02d}"


class PageBuilder:
    def __init__(self, project):
        self.p = project
        self._cache = {}

    def scene_page(self, scene):
        dur = scene["end"] - scene["start"]
        ts = _fmt_time(scene["start"])
        text = (f"[SCENE] {ts} Topic: {scene['topic']} | "
                f"Speaker: {', '.join(scene['speakers'])} | Activity: {scene['activity']}")
        return Page("scene", scene["id"], _est_tokens(text), text)

    def transcript_page(self, segments):
        if not segments:
            return None
        text = " ".join(s["text"] for s in segments)
        tx_text = f"[TX {_fmt_time(segments[0]['start'])}] \"{text[:200]}\""
        return Page("transcript", f"tx_{segments[0]['start']}", _est_tokens(tx_text), tx_text)

    def clip_page(self, clip):
        ts = _fmt_time(clip["start"])
        te = _fmt_time(clip["end"])
        text = f"[CLIP {clip['id']}] {ts} -> {te} Source: {clip['source']}"
        return Page("clip", clip["id"], _est_tokens(text), text)

    def graph_page(self, nodes, edges):
        nl = ", ".join(n.label for n in nodes[:5])
        text = f"[GRAPH] Nodes: {nl} | Edges: {len(edges)}"
        return Page("graph", f"graph_{hash(nl)}", _est_tokens(text), text)

    def project_map(self):
        return (f"PROJECT: {self.p['name']} | {self.p['scenario']} | "
                f"Scenes: {len(self.p['scenes'])} | Duration: {int(self.p['duration']//60)}m")


# ═══════════════════════════════════════════════════════════════════════════
# 6. RESOLVER PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

class IntentType(Enum):
    TEXT_SEARCH = "text_search"
    TIME_LOOKUP = "time_lookup"
    TIME_RANGE = "time_range"
    CLIP_LOOKUP = "clip_lookup"
    SEMANTIC_PATH = "semantic_path"
    CROSS_REFERENCE = "cross_reference"
    FIND_EDIT_POINTS = "find_edit_points"


@dataclass
class Intent:
    type: IntentType
    params: dict
    confidence_required: float = 0.8
    max_tokens: int = 1000
    max_latency_ms: int = 500


@dataclass
class ResolverResult:
    pages: List[Page]
    tokens: int
    confidence: float  # 0..1
    needs_more_tokens: bool = False
    suggested_budget: int = 0
    metadata: dict = field(default_factory=dict)


class BaseResolver:
    """One resolver = one kind of query. Composable into a pipeline."""

    def can_handle(self, intent: Intent) -> bool:
        raise NotImplementedError

    def resolve(self, intent: Intent) -> ResolverResult:
        raise NotImplementedError


class TextSearchResolver(BaseResolver):
    def __init__(self, tx_idx, scene_idx, builder):
        self.tx_idx = tx_idx
        self.scene_idx = scene_idx
        self.builder = builder

    def can_handle(self, intent):
        return intent.type == IntentType.TEXT_SEARCH

    def resolve(self, intent):
        query = intent.params.get("query", "")
        matches = self.tx_idx.search_text(query, limit=5)
        if not matches:
            return ResolverResult([], 0, 0.0)

        pages = []
        # Transcript page
        tx_page = self.builder.transcript_page(matches[:3])
        if tx_page:
            pages.append(tx_page)

        # Scene containing first match
        mid_time = matches[0]["start"]
        scene = self.scene_idx.at_time(mid_time)
        if scene:
            pages.append(self.builder.scene_page(scene))

        total = sum(p.tokens for p in pages)
        # Confidence based on match score relative to query
        conf = min(0.95, 0.5 + len(matches) * 0.1)
        return ResolverResult(pages, total, conf)


class TimeRangeResolver(BaseResolver):
    def __init__(self, tx_idx, scene_idx, tl_idx, builder):
        self.tx_idx = tx_idx
        self.scene_idx = scene_idx
        self.tl_idx = tl_idx
        self.builder = builder

    def can_handle(self, intent):
        return intent.type in (IntentType.TIME_LOOKUP, IntentType.TIME_RANGE)

    def resolve(self, intent):
        t = intent.params.get("time")
        t_end = intent.params.get("time_end", t)
        pages = []

        if t is None:
            return ResolverResult([], 0, 0.0)

        # Expand range
        scenes = self.scene_idx.range(t, t_end + 1)
        for s in scenes[:3]:
            pages.append(self.builder.scene_page(s))

        # Transcript in range
        tx_matches = self.tx_idx.range(t, t_end + 30)
        if tx_matches:
            p = self.builder.transcript_page(tx_matches[:3])
            if p:
                pages.append(p)

        total = sum(p.tokens for p in pages)
        conf = min(0.9, 0.4 + len(scenes) * 0.15)
        return ResolverResult(pages, total, conf)


class SemanticPathResolver(BaseResolver):
    def __init__(self, graph, scene_idx, builder):
        self.graph = graph
        self.scene_idx = scene_idx
        self.builder = builder

    def can_handle(self, intent):
        return intent.type in (IntentType.SEMANTIC_PATH, IntentType.CROSS_REFERENCE)

    def resolve(self, intent):
        from_node = intent.params.get("from_node", "")
        to_node = intent.params.get("to_node", "")
        relation = intent.params.get("relation")

        if not from_node or not to_node:
            return ResolverResult([], 0, 0.0)

        # If exact node IDs not found, try fuzzy match
        if from_node not in self.graph.nodes:
            candidates = [nid for nid in self.graph.nodes if from_node.lower() in nid.lower()]
            from_node = candidates[0] if candidates else from_node
        if to_node not in self.graph.nodes:
            candidates = [nid for nid in self.graph.nodes if to_node.lower() in nid.lower()]
            to_node = candidates[0] if candidates else to_node

        path = self.graph.query_path(from_node, to_node)
        if not path:
            return ResolverResult([], 0, 0.1,
                                  metadata={"reason": f"No path from {from_node} to {to_node}"})

        pages = []
        for node_id in path:
            node = self.graph.nodes.get(node_id)
            if node and node.type == "topic":
                scenes = self.scene_idx.find_by_topic(node.label)
                for s in scenes[:1]:
                    pages.append(self.builder.scene_page(s))

        # Add graph context page
        nodes_on_path = [self.graph.nodes[nid] for nid in path if nid in self.graph.nodes]
        edges_on_path = [e for e in self.graph.edges
                         if e.source in path and e.target in path]
        pages.append(self.builder.graph_page(nodes_on_path, edges_on_path))

        total = sum(p.tokens for p in pages)
        conf = 0.7 if len(path) <= 3 else 0.5
        return ResolverResult(pages, total, conf)


class EditPointResolver(BaseResolver):
    """Finds candidate edit points based on transcript analysis."""

    def __init__(self, tx_idx, builder):
        self.tx_idx = tx_idx
        self.builder = builder

    def can_handle(self, intent):
        return intent.type == IntentType.FIND_EDIT_POINTS

    def resolve(self, intent):
        edit_type = intent.params.get("edit_type", "trim")
        scene_id = intent.params.get("scene_id")
        pages = []

        if edit_type == "remove_filler":
            # Find transcript segments with filler words
            candidates = []
            for tx in self.tx_idx.by_text.items:
                for fw in FILLER_WORDS:
                    if fw in tx["text"].lower():
                        candidates.append(tx)
                        break
            if candidates:
                pages.append(self.builder.transcript_page(candidates[:5]))
                conf = 0.85
            else:
                conf = 0.1
        elif edit_type == "remove_dead_air":
            # Find segments without keywords (this is a proxy for dead air)
            candidates = []
            for tx in self.tx_idx.by_text.items:
                has_kw = any(kw in tx["text"].lower()
                             for kw_list in TOPIC_KEYWORDS.values() for kw in kw_list)
                if not has_kw:
                    candidates.append(tx)
            if candidates:
                pages.append(self.builder.transcript_page(candidates[:5]))
                conf = 0.8
            else:
                conf = 0.1
        elif edit_type == "tighten_pauses":
            # Short segments (likely pauses)
            candidates = [tx for tx in self.tx_idx.by_text.items
                          if (tx.get("end", 0) - tx.get("start", 0)) < 3.0]
            if candidates:
                pages.append(self.builder.transcript_page(candidates[:5]))
                conf = 0.7
            else:
                conf = 0.1
        else:
            conf = 0.1

        total = sum(p.tokens for p in pages)
        return ResolverResult(pages, total, conf)


# ═══════════════════════════════════════════════════════════════════════════
# 7. ADAPTIVE COST OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════════

class AdaptiveCostOptimizer:
    """Decides whether to allocate more budget or degrade precision."""

    def optimize(self, intent: Intent, resolver_results: List[ResolverResult]) -> List[ResolverResult]:
        budget = intent.max_tokens
        confidence_required = intent.confidence_required

        total_tokens = sum(r.tokens for r in resolver_results)
        avg_confidence = (sum(r.confidence for r in resolver_results) /
                          max(1, len([r for r in resolver_results if r.pages])))

        # Case 1: Under budget with good confidence → accept
        if total_tokens <= budget and avg_confidence >= confidence_required:
            return resolver_results

        # Case 2: Under budget but low confidence → flag for more tokens
        if total_tokens <= budget and avg_confidence < confidence_required:
            # Mark the weakest resolver
            for r in resolver_results:
                if r.confidence < 0.5:
                    r.needs_more_tokens = True
                    r.suggested_budget = r.tokens * 3  # triple the budget for this resolver
            return resolver_results

        # Case 3: Over budget → drop low-confidence results
        if total_tokens > budget:
            kept = []
            remaining = budget
            # Keep results sorted by confidence
            sorted_results = sorted(resolver_results, key=lambda r: -r.confidence)
            for r in sorted_results:
                if remaining >= r.tokens or r.confidence >= 0.8:
                    kept.append(r)
                    remaining -= r.tokens
                else:
                    r.needs_more_tokens = True
                    r.suggested_budget = r.tokens
            return kept

        return resolver_results


# ═══════════════════════════════════════════════════════════════════════════
# 8. MODULAR QUERY PLANNER (v0.2)
# ═══════════════════════════════════════════════════════════════════════════

class QueryPlannerV2:
    def __init__(self, project, tx_idx, scene_idx, tl_idx, graph):
        self.project = project
        self.builder = PageBuilder(project)
        self.resolvers: List[BaseResolver] = [
            TextSearchResolver(tx_idx, scene_idx, self.builder),
            TimeRangeResolver(tx_idx, scene_idx, tl_idx, self.builder),
            SemanticPathResolver(graph, scene_idx, self.builder),
            EditPointResolver(tx_idx, self.builder),
        ]
        self.optimizer = AdaptiveCostOptimizer()

    def plan(self, intent: Intent) -> dict:
        """Execute resolver pipeline with adaptive cost optimization."""

        # Phase 1: Find resolvers that can handle this intent
        active = [r for r in self.resolvers if r.can_handle(intent)]
        if not active:
            return {
                "pages": [],
                "total_tokens": 0,
                "confidence": 0.0,
                "needs_more": True,
                "suggested_budget": intent.max_tokens * 2,
                "resolver_info": [],
            }

        # Phase 2: Execute resolvers
        results = []
        for resolver in active:
            t0 = time.perf_counter()
            result = resolver.resolve(intent)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            results.append(result)

            # Latency check
            if elapsed_ms > intent.max_latency_ms:
                result.metadata["latency_warning"] = f"{elapsed_ms:.0f}ms > {intent.max_latency_ms}ms"

        # Phase 3: Cost optimization
        optimized = self.optimizer.optimize(intent, results)

        # Phase 4: Assemble
        all_pages = []
        resolver_info = []
        needs_more = False
        suggested_budget = 0
        total_tokens = _est_tokens(self.builder.project_map())

        for r in optimized:
            all_pages.extend(r.pages)
            total_tokens += r.tokens
            resolver_info.append({
                "resolver": type(r).__name__,
                "pages": len(r.pages),
                "tokens": r.tokens,
                "confidence": round(r.confidence, 2),
                "needs_more": r.needs_more_tokens,
            })
            if r.needs_more_tokens:
                needs_more = True
                suggested_budget = max(suggested_budget, r.suggested_budget)

        avg_conf = (sum(r.confidence for r in optimized) /
                    max(1, len([r for r in optimized if r.pages]))) if all_pages else 0.0

        return {
            "pages": all_pages,
            "total_tokens": total_tokens,
            "confidence": round(avg_conf, 2),
            "needs_more": needs_more,
            "suggested_budget": suggested_budget,
            "resolver_info": resolver_info,
            "project_map": self.builder.project_map(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# 9. SIMULATED AGENT — Decision Accuracy
# ═══════════════════════════════════════════════════════════════════════════

class SimulatedEditor:
    """Simulates an LLM agent making editing decisions based on context pages.

    In production, this is the LLM. Here we use heuristics that mirror
    what an LLM would do with the same pages: look at transcript timestamps,
    identify filler words, propose trims.
    """

    def decide(self, pages: List[Page], project, edit_style="tighten_pauses"):
        """Given context pages, propose edits. Returns list of {start, end}."""
        edits = []

        for page in pages:
            if page.type != "transcript":
                continue

            content = page.content
            # Parse timestamps from page content
            time_match = re.search(r'(\d{2}:\d{2}:\d{2})', content)
            if not time_match:
                continue
            ts_str = time_match.group(1)
            parts = ts_str.split(":")
            base_time = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

            if edit_style == "tighten_pauses":
                # Cut filler segments
                for fw in FILLER_WORDS:
                    if fw in content.lower():
                        edits.append({
                            "start": base_time,
                            "end": base_time + random.uniform(1.5, 4.0),
                            "reason": f"Found filler: '{fw}'",
                        })
                        break

            elif edit_style == "remove_ums":
                if "um" in content.lower() or "uh" in content.lower():
                    edits.append({
                        "start": base_time,
                        "end": base_time + random.uniform(0.5, 2.0),
                        "reason": "Hesitation removal",
                    })

            elif edit_style == "jump_cuts":
                edits.append({
                    "start": base_time,
                    "end": base_time + random.uniform(0.3, 1.5),
                    "reason": "Jump cut point",
                })

            elif edit_style == "remove_dead_air":
                has_kw = any(kw in content.lower()
                             for kw_list in TOPIC_KEYWORDS.values() for kw in kw_list)
                if not has_kw:
                    edits.append({
                        "start": base_time,
                        "end": base_time + random.uniform(1.0, 3.0),
                        "reason": "Dead air removal",
                    })

        return edits[:15]  # Cap at 15 edits


def compute_edit_accuracy(generated_edits, ground_truth_edits, tolerance=3.0):
    """Compare generated edits to ground truth.

    Returns: precision, recall, f1 based on temporal overlap.
    Two edits match if their [start, end] overlap within tolerance seconds.
    """
    if not ground_truth_edits:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "matches": 0,
                "gen_count": 0, "gt_count": 0}

    gt_matched = [False] * len(ground_truth_edits)
    gen_matched = [False] * len(generated_edits)

    for gi, gen in enumerate(generated_edits):
        for gti, gt in enumerate(ground_truth_edits):
            if gt_matched[gti]:
                continue
            # Check if times overlap within tolerance
            overlap_start = max(gen["start"], gt["start"]) - tolerance
            overlap_end = min(gen["end"], gt["end"]) + tolerance
            if overlap_end > overlap_start:
                overlap = overlap_end - overlap_start
                gen_span = gen["end"] - gen["start"]
                gt_span = gt["end"] - gt["start"]
                if overlap >= min(gen_span, gt_span) * 0.5:  # At least 50% overlap
                    gt_matched[gti] = True
                    gen_matched[gi] = True
                    break

    tp = sum(gen_matched)
    fp = len(generated_edits) - tp
    fn = len(ground_truth_edits) - sum(gt_matched)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "matches": tp,
        "gen_count": len(generated_edits),
        "gt_count": len(ground_truth_edits),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 10. BENCHMARK v0.2
# ═══════════════════════════════════════════════════════════════════════════

BUDGETS = [250, 500, 1000, 2500, 5000]
SCENARIOS = ["podcast", "interview", "vlog", "tutorial"]


def run_benchmark_v2():
    print("=" * 80)
    print("  FLOW CONTEXT ENGINE v0.2 — DECISION-ACCURATE BENCHMARK")
    print(f"  {len(SCENARIOS)} scenarios x {len(BUDGETS)} budgets")
    print("  Metrics: Edit Accuracy, Confidence, Adaptive Budget")
    print("=" * 80)

    all_scenario_results = {}

    for scenario in SCENARIOS:
        print(f"\n{'─' * 80}")
        print(f"  SCENARIO: {scenario} ({SCENARIO_SPECS[scenario]['duration_min']} min)")
        print(f"  Style: {SCENARIO_SPECS[scenario]['edit_style']} | "
              f"Ground truth edits: {SCENARIO_SPECS[scenario]['n_edits']}")
        print(f"  {'─' * 80}")

        # --- OFFLINE: Build indexes ---
        cost_model = CostModel()
        t0 = time.time()
        project, keywords = generate_scenario(scenario, seed=42)

        tx_idx = TranscriptIndex()
        tx_idx.build(project["transcript"])
        scene_idx = SceneIndex()
        scene_idx.build(project["scenes"])
        tl_idx = TimelineIndex()
        tl_idx.build(project["timeline"])

        graph = SemanticGraph()
        graph.build_from_project(project)

        # Offline cost: indexing + graph construction
        offline_tokens = (
            sum(len(tx["text"].split()) for tx in project["transcript"]) +
            sum(len(s["topic"].split()) * 10 for s in project["scenes"]) +
            len(graph.nodes) * 5 + len(graph.edges) * 3
        )
        offline_sec = time.time() - t0
        cost_model.add_offline(offline_tokens, offline_sec)

        planner = QueryPlannerV2(project, tx_idx, scene_idx, tl_idx, graph)
        editor = SimulatedEditor()
        gt_edits = project["ground_truth_edits"]

        print(f"  Offline: {offline_tokens:,}t indexing | {offline_sec:.2f}s | "
              f"Graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

        # --- ONLINE: Query & edit ---
        # Build a diverse set of intents
        intents = _build_test_intents(project, scenario)
        n_queries = len(intents)

        budget_results = {}

        for budget in BUDGETS:
            cost_model.online_tokens = 0
            cost_model.online_sec = 0
            cost_model.query_count = 0

            all_edit_metrics = []
            all_confidence = []
            needs_more_count = 0

            for intent in intents:
                intent.max_tokens = budget

                t0 = time.perf_counter()
                result = planner.plan(intent)
                elapsed = time.perf_counter() - t0

                cost_model.add_online(result["total_tokens"], elapsed)

                if result["needs_more"]:
                    needs_more_count += 1

                # Simulate agent decision
                gen_edits = editor.decide(result["pages"], project,
                                          edit_style=SCENARIO_SPECS[scenario]["edit_style"])

                # Score against ground truth
                acc = compute_edit_accuracy(gen_edits, gt_edits)
                all_edit_metrics.append(acc)
                all_confidence.append(result["confidence"])

            # Aggregate
            avg_accuracy = {
                "precision": sum(m["precision"] for m in all_edit_metrics) / n_queries,
                "recall": sum(m["recall"] for m in all_edit_metrics) / n_queries,
                "f1": sum(m["f1"] for m in all_edit_metrics) / n_queries,
            }
            avg_confidence = sum(all_confidence) / n_queries
            cost_summary = cost_model.summary(n_queries)
            needs_more_pct = needs_more_count / n_queries

            budget_results[budget] = {
                "accuracy": avg_accuracy,
                "confidence": avg_confidence,
                "cost": cost_summary,
                "needs_more_pct": needs_more_pct,
                "n_queries": n_queries,
            }

        all_scenario_results[scenario] = budget_results

        # Print table
        print(f"\n  {'Budget':>7} {'Tok/Q':>7} {'Prec':>6} {'Recall':>6} {'F1':>6} "
              f"{'Conf':>6} {'NeedMore':>9} {'AmortTok':>9}")
        print(f"  {'─' * 64}")
        for budget in BUDGETS:
            r = budget_results[budget]
            print(f"  {budget:>7} "
                  f"{r['cost']['online_avg_tokens']:>7.0f} "
                  f"{r['accuracy']['precision']:>6.2f} "
                  f"{r['accuracy']['recall']:>6.2f} "
                  f"{r['accuracy']['f1']:>6.2f} "
                  f"{r['confidence']:>6.2f} "
                  f"{r['needs_more_pct']:>8.0%} "
                  f"{r['cost']['amortized_tokens_per_query']:>9.0f}")

    # ─── CROSS-SCENARIO SUMMARY ───
    print("\n" + "=" * 80)
    print("  CROSS-SCENARIO: Edit F1 Score Matrix")
    print("=" * 80)

    print(f"\n  {'Scenario':<12} ", end="")
    for budget in BUDGETS:
        print(f"{budget:>8}", end="")
    print(f"  {'Optimal':>8}")
    print(f"  {'─' * (12 + 9 * (len(BUDGETS) + 1))}")

    for scenario in SCENARIOS:
        print(f"  {scenario:<12} ", end="")
        best_f1 = 0
        best_budget = 0
        for budget in BUDGETS:
            f1 = all_scenario_results[scenario][budget]["accuracy"]["f1"]
            print(f"{f1:>8.3f}", end="")
            if f1 > best_f1:
                best_f1 = f1
                best_budget = budget
        print(f"  {best_budget:>5} ({best_f1:.3f})")

    # ─── ADAPTIVE BUDGET ANALYSIS ───
    print("\n" + "=" * 80)
    print("  ADAPTIVE BUDGET: When the planner says 'I need more'")
    print("=" * 80)

    for scenario in SCENARIOS:
        print(f"\n  {scenario}:")
        for budget in BUDGETS:
            r = all_scenario_results[scenario][budget]
            marker = " *** NEEDS MORE ***" if r["needs_more_pct"] > 0.3 else ""
            print(f"    Budget {budget:>5}t: F1={r['accuracy']['f1']:.3f} "
                  f"Conf={r['confidence']:.2f} NeedsMore={r['needs_more_pct']:.0%}{marker}")

    # ─── AMORTIZED COST ───
    print("\n" + "=" * 80)
    print("  AMORTIZED COST: Offline indexing spread across queries")
    print("=" * 80)

    for scenario in SCENARIOS:
        r = all_scenario_results[scenario][1000]  # mid-range budget
        c = r["cost"]
        n = r["n_queries"]
        print(f"\n  {scenario} ({n} online queries per session):")
        print(f"    Offline (once):    {c['offline_tokens']:>10,} tokens | {c['offline_sec']:>5.1f}s")
        print(f"    Online (avg):      {c['online_avg_tokens']:>10,.0f} tokens | {c['online_avg_ms']:>5.1f}ms")
        print(f"    Amortized/query:   {c['amortized_tokens_per_query']:>10,.0f} tokens")
        print(f"    Break-even:        after ~{int(c['offline_tokens'] / c['online_avg_tokens'])} queries")

    # ─── KEY INSIGHT ───
    print("\n" + "=" * 80)
    print("  KEY INSIGHT: Edit Accuracy vs Token Budget")
    print("=" * 80)
    print()
    for scenario in SCENARIOS:
        f1_250 = all_scenario_results[scenario][250]["accuracy"]["f1"]
        f1_5000 = all_scenario_results[scenario][5000]["accuracy"]["f1"]
        delta = f1_5000 - f1_250
        print(f"  {scenario}: F1@250t={f1_250:.3f}  F1@5000t={f1_5000:.3f}  "
              f"Delta={delta:+.3f}  ({(delta/f1_250*100) if f1_250 > 0 else 0:+.0f}%)")

    print("\n" + "=" * 80)
    print("  BENCHMARK v0.2 COMPLETE")
    print("=" * 80)


def _build_test_intents(project, scenario):
    """Build a diverse set of intents that test the resolver pipeline."""
    intents = []
    spec = SCENARIO_SPECS[scenario]

    # 1. Text searches — find keywords
    all_kw = set()
    for scene in project["scenes"]:
        all_kw.update(scene["keywords"])
    for kw in random.sample(list(all_kw), min(5, len(all_kw))):
        intents.append(Intent(IntentType.TEXT_SEARCH, {"query": kw}))

    # 2. Time lookups — inspect specific moments
    for _ in range(3):
        t = random.uniform(60, project["duration"] - 60)
        intents.append(Intent(IntentType.TIME_LOOKUP, {"time": t}))

    # 3. Time ranges — broader inspection
    for _ in range(2):
        t1 = random.uniform(60, project["duration"] - 120)
        t2 = t1 + random.uniform(30, 90)
        intents.append(Intent(IntentType.TIME_RANGE, {"time": t1, "time_end": t2}))

    # 4. Semantic path — person to topic
    speakers = spec["speakers"]
    topics = spec["topics"]
    for _ in range(2):
        sp = random.choice(speakers)
        tp = random.choice(topics)
        intents.append(Intent(IntentType.SEMANTIC_PATH,
                              {"from_node": f"person:{sp}", "to_node": f"topic:{tp}"}))

    # 5. Find edit points — scenario-specific
    for _ in range(3):
        intents.append(Intent(IntentType.FIND_EDIT_POINTS, {
            "edit_type": _edit_type_for_style(spec["edit_style"]),
            "scene_id": random.choice(project["scenes"])["id"],
        }))

    return intents


def _edit_type_for_style(style):
    mapping = {
        "tighten_pauses": "remove_filler",
        "remove_ums": "remove_filler",
        "jump_cuts": "tighten_pauses",
        "remove_dead_air": "remove_dead_air",
    }
    return mapping.get(style, "trim")


if __name__ == "__main__":
    run_benchmark_v2()
