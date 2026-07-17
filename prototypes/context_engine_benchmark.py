"""
Flow Context Engine — Benchmark Suite

Tests the VVM hypothesis across:
  - 5 video sizes (5min .. 8h)
  - 6 token budgets (250 .. 10000)
  - 3 methods (Naive dump, simple RAG, Flow VVM)
  - 100 queries (simple to hard, with ground truth)
  
Metrics: precision, recall, F1, success rate, tokens, latency

Run: python context_engine_benchmark.py
"""

import json, random, time, sys, io, math
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


# ═══════════════════════════════════════════════════════════════════════════
# 1. DATA GENERATION
# ═══════════════════════════════════════════════════════════════════════════

TOPICS = ["Introduction", "Company History", "Market Overview", "Revenue Growth",
          "Product Demo", "Team Interview", "Customer Testimonials",
          "Technical Deep Dive", "Future Roadmap", "Q&A Session", "Closing Remarks"]
LOCATIONS = ["Boardroom", "Office", "Studio", "Rooftop", "Lab", "Lobby", "Stage", "Cafe"]
PEOPLE = ["CEO_John", "CFO_Sarah", "CTO_Mike", "Host_Anna", "Engineer_Alex",
          "Engineer_Lisa", "Customer_Tom", "Investor_Kate", "Designer_Paul"]
ACTIVITIES = ["Presentation", "Interview", "Walking", "Demo", "Meeting", "B-roll", "Setup", "Q&A"]

KEYWORDS = {
    "Revenue Growth": ["revenue", "growth", "quarter", "profit", "increase",
                       "percentage", "million", "billion", "target", "forecast"],
    "Product Demo": ["product", "feature", "demo", "launch", "interface", "user",
                     "click", "workflow", "platform", "release", "pricing"],
    "Technical Deep Dive": ["architecture", "code", "system", "API", "database",
                            "server", "deploy", "scale", "latency", "throughput"],
    "Team Interview": ["team", "culture", "collaborate", "project", "challenge",
                       "solution", "learn", "grow", "mission", "values"],
    "Market Overview": ["market", "competitor", "trend", "industry", "share",
                        "analysis", "report", "data", "segment", "opportunity"],
    "Future Roadmap": ["roadmap", "future", "plan", "next", "vision", "goal",
                       "milestone", "timeline", "launch", "quarter"],
    "Customer Testimonials": ["customer", "experience", "love", "recommend",
                              "feedback", "improve", "support", "happy", "result"],
    "Introduction": ["welcome", "today", "present", "introduce", "agenda",
                     "overview", "begin", "start", "topic", "cover"],
    "Q&A Session": ["question", "answer", "ask", "clarify", "wonder",
                    "explain", "detail", "example", "scenario", "case"],
    "Closing Remarks": ["thank", "summary", "conclusion", "final", "wrap",
                        "appreciate", "join", "contact", "follow", "end"],
}

FILLER = ["the", "a", "is", "was", "are", "were", "and", "or", "but", "in", "on",
          "at", "to", "for", "with", "from", "by", "as", "of", "that", "this", "it",
          "we", "they", "our", "their", "have", "has", "had", "been", "can", "will",
          "would", "could", "so", "very", "really", "about", "also", "just", "now"]


def generate_project(duration_minutes=60, seed=42):
    """Generate a video project of the given duration (in minutes)."""
    random.seed(seed)
    duration_sec = duration_minutes * 60

    p = {
        "name": f"video_{duration_minutes}min",
        "duration": duration_sec,
        "resolution": "1920x1080",
        "fps": 24,
        "tracks": 5,
        "scenes": [],
        "transcript": [],
        "timeline": [],
        "objects": [],
        "faces": [],
        "audio": [],
        "effects": [],
    }

    # Scenes: ~1 scene per 2 minutes
    n_scenes = max(3, duration_minutes // 2)
    scene_dur = duration_sec / n_scenes
    for i in range(n_scenes):
        start = i * scene_dur + random.uniform(-5, 5)
        dur = scene_dur * random.uniform(0.6, 1.4)
        end = min(start + max(dur, 10), duration_sec)
        p["scenes"].append({
            "id": f"scene_{i:04d}",
            "start": round(start, 1),
            "end": round(end, 1),
            "duration": round(end - start, 1),
            "topic": random.choice(TOPICS),
            "location": random.choice(LOCATIONS),
            "people": random.sample(PEOPLE, k=random.randint(1, 4)),
            "activity": random.choice(ACTIVITIES),
            "mood": random.choice(["Professional", "Energetic", "Serious",
                                   "Casual", "Inspirational", "Technical"]),
        })

    # Transcript: ~150 words per minute
    for scene in p["scenes"]:
        words = int((scene["duration"] / 60) * 150)
        scene_words = _gen_scene_words(scene, words)
        seg_count = max(1, words // 25)
        words_per_seg = max(10, words // seg_count)
        for s in range(seg_count):
            seg_words = scene_words[s * words_per_seg:(s + 1) * words_per_seg]
            if seg_words:
                seg_start = scene["start"] + (s / seg_count) * scene["duration"]
                p["transcript"].append({
                    "id": f"tx_{len(p['transcript']):05d}",
                    "start": round(seg_start, 1),
                    "end": round(seg_start + 5, 1),
                    "text": " ".join(seg_words),
                    "speaker": random.choice(scene["people"] + ["Unknown"]),
                    "confidence": round(random.uniform(0.85, 0.99), 2),
                })

    # Timeline: clips on tracks
    clip_id = 0
    tracks = ["track_0", "track_1", "track_2", "track_3", "track_4"]
    sources = ["cam_a.mp4", "cam_b.mp4", "broll_office.mp4", "broll_city.mp4",
               "broll_product.mp4", "intro.mp4", "outro.mp4"]
    for scene in p["scenes"]:
        pos = scene["start"]
        remaining = scene["duration"]
        while remaining > 2:
            chunk = min(remaining, random.uniform(3, 30))
            p["timeline"].append({
                "id": f"clip_{clip_id:04d}",
                "track": random.choice(tracks),
                "start": round(pos, 1),
                "end": round(pos + chunk, 1),
                "duration": round(chunk, 1),
                "source": random.choice(sources),
                "source_start": round(random.uniform(0, 3600), 1),
                "transition_in": random.choice([None, "cut", "fade"]),
                "transition_out": random.choice([None, "cut", "fade"]),
            })
            clip_id += 1
            remaining -= chunk
            pos += chunk

    p["total_clips"] = len(p["timeline"])
    p["total_assets"] = len(sources)

    # Objects, faces, audio
    obj_types = ["person", "laptop", "screen", "whiteboard", "microphone",
                 "chair", "table", "phone", "document", "camera"]
    for scene in p["scenes"]:
        for _ in range(random.randint(1, 5)):
            t = random.uniform(scene["start"], max(scene["start"] + 1, scene["end"] - 1))
            p["objects"].append({
                "id": f"obj_{len(p['objects']):05d}",
                "type": random.choice(obj_types),
                "start": round(t, 1),
                "end": round(t + random.uniform(1, 30), 1),
                "scene_id": scene["id"],
            })

    for scene in p["scenes"]:
        for person in random.sample(scene["people"], min(2, len(scene["people"]))):
            t = random.uniform(scene["start"], max(scene["start"] + 1, scene["end"] - 2))
            p["faces"].append({
                "id": f"face_{len(p['faces']):05d}",
                "identity": person,
                "start": round(t, 1),
                "end": round(t + random.uniform(2, 20), 1),
                "scene_id": scene["id"],
            })

    for t in range(0, int(duration_sec), 2):
        scene = _find_scene(p, t)
        p["audio"].append({
            "time": t,
            "rms": round(random.uniform(-30, -5), 1),
            "beat": random.random() < 0.1,
            "emotion": random.choice(["neutral", "happy", "serious", "excited"]),
            "noise_level": round(random.uniform(0.01, 0.3), 2),
            "speech_active": scene and scene["activity"] not in ("B-roll", "Setup"),
        })

    return p


def _gen_scene_words(scene, count):
    kw = KEYWORDS.get(scene["topic"], ["discuss"])
    words = []
    i = 0
    # Sprinkle keywords deterministically at known positions for ground truth
    key_positions = sorted(random.sample(range(max(1, count // 15), count), min(len(kw) * 3, count // 10)))
    ki = 0
    for i in range(count):
        if ki < len(key_positions) and i == key_positions[ki]:
            words.append(random.choice(kw))
            ki += 1
        else:
            words.append(random.choice(FILLER))
    return words


def _find_scene(p, time):
    for s in p["scenes"]:
        if s["start"] <= time < s["end"]:
            return s
    return None


# ═══════════════════════════════════════════════════════════════════════════
# 2. INDEXES (same as POC)
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


class TimelineIndex:
    def __init__(self):
        self.by_id = {}
        self.by_track_time = BTreeIndex(lambda c: (c["track"], c["start"]))
    def build(self, clips):
        self.by_id = {c["id"]: c for c in clips}
        self.by_track_time.build(clips)
    def get(self, cid):
        return self.by_id.get(cid)
    def at_time(self, track, t):
        for c in self.by_track_time.items:
            if c["track"] == track and c["start"] <= t < c["end"]:
                return c
        return None
    def neighbors(self, cid):
        c = self.by_id.get(cid)
        if not c:
            return None, None
        track_items = [i for i in self.by_track_time.items if i["track"] == c["track"]]
        for i, item in enumerate(track_items):
            if item["id"] == cid:
                return (track_items[i - 1] if i > 0 else None,
                        track_items[i + 1] if i + 1 < len(track_items) else None)
        return None, None


# ═══════════════════════════════════════════════════════════════════════════
# 3. PAGES & BUILDER
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Page:
    type: str
    id: str
    tokens: int
    summary: str = ""
    normal: str = ""

    def render(self, level="normal"):
        return self.normal if level == "full" else (self.summary if level == "summary" else self.normal)

    def __hash__(self):
        return hash((self.type, self.id))
    def __eq__(self, other):
        return self.type == other.type and self.id == other.id


def _est_tokens(text):
    return max(1, int(len(text.split()) / 0.75))


def _fmt_time(sec):
    return f"{int(sec//3600):02d}:{int(sec%3600//60):02d}:{int(sec%60):02d}"


def _fmt_dur(sec):
    return f"{int(sec//60)}m{int(sec%60)}s"


class PageBuilder:
    def __init__(self, project):
        self.p = project

    def scene_page(self, scene, level="normal"):
        dur = scene["duration"]
        ts = _fmt_time(scene["start"])
        normal = (
            f"[SCENE {scene['id']}] {ts} ({_fmt_dur(dur)}) "
            f"Topic: {scene['topic']} | People: {', '.join(scene['people'][:3])} "
            f"Activity: {scene['activity']} | Mood: {scene['mood']}"
        )
        summary = f"[SCENE {scene['id']}] {ts} Topic: {scene['topic']}"
        return Page("scene", scene["id"], _est_tokens(normal), summary=summary, normal=normal)

    def clip_page(self, clip, level="normal"):
        ts = _fmt_time(clip["start"])
        te = _fmt_time(clip["end"])
        normal = (
            f"[CLIP {clip['id']}] {ts} -> {te} Track: {clip['track']} "
            f"Source: {clip['source']} Trans: {clip['transition_in']}/{clip['transition_out']}"
        )
        summary = f"[CLIP {clip['id']}] {ts} Track: {clip['track']}"
        return Page("clip", clip["id"], _est_tokens(normal), summary=summary, normal=normal)

    def transcript_page(self, segments, level="normal"):
        if not segments:
            return None
        text = " ".join(s["text"] for s in segments)
        normal = f"[TX] {_fmt_time(segments[0]['start'])}: \"{text[:300]}\""
        summary = f"[TX] {_fmt_time(segments[0]['start'])}: \"{text[:100]}\""
        return Page("transcript", f"tx_{segments[0]['start']}", _est_tokens(normal),
                    summary=summary, normal=normal)

    def audio_page(self, segment, level="normal"):
        if not segment:
            return None
        s = segment[0]
        normal = f"[AUDIO {_fmt_time(s['time'])}] RMS:{s['rms']} Emotion:{s['emotion']}"
        return Page("audio", f"aud_{s['time']}", _est_tokens(normal), summary=normal, normal=normal)

    def project_map(self):
        return (
            f"PROJECT: {self.p['name']} | Duration: {_fmt_dur(self.p['duration'])} "
            f"Tracks: {self.p['tracks']} | Clips: {self.p['total_clips']} "
            f"Scenes: {len(self.p['scenes'])} | Assets: {self.p['total_assets']}"
        )

    def all_pages_for_scene(self, scene):
        """Generate ALL pages that exist for a scene (used for ground truth)."""
        pages = set()
        pages.add(self.scene_page(scene))
        for tx in self.p["transcript"]:
            if scene["start"] <= tx["start"] < scene["end"]:
                pages.add(self.transcript_page([tx]))
        for clip in self.p["timeline"]:
            if clip["start"] >= scene["start"] and clip["end"] <= scene["end"]:
                pages.add(self.clip_page(clip))
        return pages

    def all_pages_for_time(self, t, margin=30):
        """All pages that touch a time range."""
        pages = set()
        scene = _find_scene(self.p, t)
        if scene:
            pages.add(self.scene_page(scene))
        for clip in self.p["timeline"]:
            if clip["start"] - margin <= t <= clip["end"] + margin:
                pages.add(self.clip_page(clip))
        for tx in self.p["transcript"]:
            if tx["start"] - margin <= t <= tx["end"] + margin:
                pages.add(self.transcript_page([tx]))
        return pages


# ═══════════════════════════════════════════════════════════════════════════
# 4. QUERY PLANNER (Flow VVM)
# ═══════════════════════════════════════════════════════════════════════════

class QueryPlanner:
    def __init__(self, project, tx_idx, scene_idx, tl_idx):
        self.project = project
        self.tx_idx = tx_idx
        self.scene_idx = scene_idx
        self.tl_idx = tl_idx
        self.builder = PageBuilder(project)

    def plan(self, intent, budget=5000):
        pages = []
        budget_class = self._precision(budget)
        remaining = budget
        pmap = self.builder.project_map()
        pmap_tokens = _est_tokens(pmap)
        remaining -= pmap_tokens

        t = intent.get("time")
        search_text = intent.get("search")
        clip_id = intent.get("clip_id")
        need = intent.get("need", ["scene", "timeline", "transcript"])

        # TEXT SEARCH
        if search_text:
            matches = self.tx_idx.search_text(search_text, limit=5)
            if matches:
                if "transcript" in need:
                    p = self.builder.transcript_page(matches[:3], level=budget_class)
                    if p:
                        pages.append(p)
                        remaining -= p.tokens

                mid_time = matches[0]["start"]
                scene = self.scene_idx.at_time(mid_time)
                if scene and "scene" in need:
                    p = self.builder.scene_page(scene, level=budget_class)
                    pages.append(p)
                    remaining -= p.tokens

                if "timeline" in need:
                    for clip in self.tl_idx.by_track_time.items:
                        if clip["start"] <= mid_time + 5 and clip["end"] >= mid_time - 5:
                            p = self.builder.clip_page(clip, level=budget_class)
                            pages.append(p)
                            remaining -= p.tokens
                            if remaining < 0:
                                break

                # Neighbors
                if remaining > 200 and "timeline" in need:
                    main_clip = self.tl_idx.at_time("track_0", mid_time)
                    if main_clip:
                        prev, nxt = self.tl_idx.neighbors(main_clip["id"])
                        for nb in [prev, nxt]:
                            if nb and remaining > 50:
                                p = self.builder.clip_page(nb, level="summary")
                                pages.append(p)
                                remaining -= p.tokens

        # TIME LOOKUP
        elif t is not None:
            scene = self.scene_idx.at_time(t)
            if scene and "scene" in need:
                p = self.builder.scene_page(scene, level=budget_class)
                pages.append(p)
                remaining -= p.tokens

            clip = self.tl_idx.at_time(intent.get("track", "track_0"), t)
            if clip and "timeline" in need:
                p = self.builder.clip_page(clip, level=budget_class)
                pages.append(p)
                remaining -= p.tokens
                prev, nxt = self.tl_idx.neighbors(clip["id"])
                for nb in [prev, nxt]:
                    if nb and remaining > 50:
                        p = self.builder.clip_page(nb, level="summary")
                        pages.append(p)
                        remaining -= p.tokens

            if "transcript" in need and remaining > 50:
                tx_range = self.tx_idx.range(t - 3, t + 10)
                if tx_range:
                    p = self.builder.transcript_page(tx_range[:3], level=budget_class)
                    pages.append(p)
                    remaining -= p.tokens

        # CLIP LOOKUP
        elif clip_id:
            clip = self.tl_idx.get(clip_id)
            if clip and "timeline" in need:
                p = self.builder.clip_page(clip, level=budget_class)
                pages.append(p)
                remaining -= p.tokens
                scene = self.scene_idx.at_time(clip["start"])
                if scene and "scene" in need and remaining > 50:
                    p = self.builder.scene_page(scene, level=budget_class)
                    pages.append(p)
                    remaining -= p.tokens

        return {
            "pages": pages,
            "total_tokens": sum(p.tokens for p in pages) + pmap_tokens,
            "budget_class": budget_class,
            "remaining": remaining,
            "project_map": pmap,
        }

    def _precision(self, budget):
        if budget >= 5000:
            return "normal"
        elif budget >= 1000:
            return "normal"
        elif budget >= 500:
            return "summary"
        else:
            return "summary"


# ═══════════════════════════════════════════════════════════════════════════
# 5. SIMPLE RAG BASELINE
# ═══════════════════════════════════════════════════════════════════════════

class RAGBaseline:
    """TF-IDF style retrieval over transcript + scene chunks. Not Flow VVM."""

    def __init__(self, project):
        self.project = project
        self.builder = PageBuilder(project)
        self.chunks = []
        self._build_chunks()

    def _build_chunks(self):
        # Chunk: every transcript segment + every scene as a retrievable unit
        for tx in self.project["transcript"]:
            self.chunks.append({
                "type": "transcript",
                "text": tx["text"],
                "data": tx,
            })
        for scene in self.project["scenes"]:
            self.chunks.append({
                "type": "scene",
                "text": f"{scene['topic']} {scene['location']} {' '.join(scene['people'])}",
                "data": scene,
            })
        # Build vocabulary
        self.doc_freq = defaultdict(int)
        self.N = len(self.chunks)
        for ch in self.chunks:
            unique = set(ch["text"].lower().split())
            for w in unique:
                self.doc_freq[w] += 1

    def query(self, intent, budget=5000):
        query_terms = ""
        if intent.get("search"):
            query_terms = intent["search"].lower()
        elif intent.get("time") is not None:
            # Time-bounded: retrieve chunks near that time
            query_terms = f"time_{int(intent['time'])}"
        elif intent.get("clip_id"):
            query_terms = intent["clip_id"]

        # Compute TF-IDF scores
        terms = query_terms.split()
        scored = []
        for ch in self.chunks:
            text = ch["text"].lower()
            score = 0
            for t in terms:
                if t in text:
                    tf = text.count(t) / max(1, len(text.split()))
                    idf = math.log(self.N / (1 + self.doc_freq.get(t, 0)))
                    score += tf * idf
            if score > 0:
                scored.append((score, ch))
        scored.sort(key=lambda x: -x[0])

        # Convert to pages, respecting budget
        pages = []
        tokens_used = 0
        for _, ch in scored:
            if ch["type"] == "transcript":
                p = self.builder.transcript_page([ch["data"]], level="summary")
            else:
                p = self.builder.scene_page(ch["data"], level="summary")
            if p and tokens_used + p.tokens <= budget - 200:
                pages.append(p)
                tokens_used += p.tokens
            if tokens_used >= budget - 200:
                break

        pmap = self.builder.project_map()
        pmap_tokens = _est_tokens(pmap)
        return {
            "pages": pages,
            "total_tokens": tokens_used + pmap_tokens,
            "project_map": pmap,
        }


# ═══════════════════════════════════════════════════════════════════════════
# 6. QUERY GENERATOR WITH GROUND TRUTH
# ═══════════════════════════════════════════════════════════════════════════

QUERY_TEMPLATES = [
    # (name, difficulty, template type, generator fn receives project)
    "simple_text",       # "Find mention of X"
    "simple_time",       # "Inspect clip at time T"
    "simple_clip",       # "Get clip by ID"
    "multi_step",        # "Find X then retrieve Y and Z"
    "temporal_range",    # "Find everything between T1 and T2"
    "cross_reference",   # "Find the scene after X where person Y appears"
]


def generate_queries(project, n=100):
    """Generate n random queries with ground truth (relevant page IDs)."""
    random.seed(hash(project["name"]) % 2**31)
    queries = []
    topics = [s["topic"] for s in project["scenes"]]
    people = list(set(f["identity"] for f in project["faces"])) or PEOPLE
    keywords = set()
    for k_list in KEYWORDS.values():
        keywords.update(k_list[:5])

    attempts = 0
    while len(queries) < n and attempts < n * 5:
        attempts += 1
        qtype = random.choice(QUERY_TEMPLATES)
        builder = PageBuilder(project)

        if qtype == "simple_text":
            keyword = random.choice(list(keywords))
            scene_with_kw = None
            for scene in project["scenes"]:
                if scene["topic"] in KEYWORDS and keyword in KEYWORDS.get(scene["topic"], []):
                    scene_with_kw = scene
                    break
            if not scene_with_kw:
                continue
            intent = {"search": keyword, "need": ["transcript", "scene", "timeline"]}
            # Ground truth: transcript segments with keyword + containing scene + clips
            relevant = set()
            relevant.add(builder.scene_page(scene_with_kw))
            for tx in project["transcript"]:
                if keyword in tx["text"].lower():
                    relevant.add(builder.transcript_page([tx]))
            for clip in project["timeline"]:
                if clip["start"] >= scene_with_kw["start"] and clip["end"] <= scene_with_kw["end"]:
                    relevant.add(builder.clip_page(clip))

        elif qtype == "simple_time":
            t = random.uniform(0, project["duration"] - 10)
            track = random.choice(["track_0", "track_1", "track_2"])
            intent = {"time": t, "track": track, "need": ["timeline", "scene", "transcript"]}
            relevant = builder.all_pages_for_time(t)
            # Limit ground truth to a reasonable set
            relevant = set(list(relevant)[:8])

        elif qtype == "simple_clip":
            if not project["timeline"]:
                continue
            clip = random.choice(project["timeline"])
            intent = {"clip_id": clip["id"], "need": ["timeline", "scene"]}
            relevant = set()
            relevant.add(builder.clip_page(clip))
            scene = _find_scene(project, clip["start"])
            if scene:
                relevant.add(builder.scene_page(scene))

        elif qtype == "multi_step":
            # "Find X keyword, then get the clip before and the scene after"
            keyword = random.choice(list(keywords))
            scene_with_kw = None
            for scene in project["scenes"]:
                if scene["topic"] in KEYWORDS and keyword in KEYWORDS.get(scene["topic"], []):
                    scene_with_kw = scene
                    break
            if not scene_with_kw:
                continue
            intent = {"search": keyword, "need": ["transcript", "scene", "timeline"]}
            relevant = set()
            relevant.add(builder.scene_page(scene_with_kw))
            for tx in project["transcript"]:
                if keyword in tx["text"].lower():
                    relevant.add(builder.transcript_page([tx]))
            # Add clips in that scene
            for clip in project["timeline"]:
                if clip["start"] >= scene_with_kw["start"] and clip["end"] <= scene_with_kw["end"]:
                    relevant.add(builder.clip_page(clip))

        elif qtype == "temporal_range":
            t1 = random.uniform(0, project["duration"] - 120)
            t2 = t1 + random.uniform(30, 120)
            intent = {"time": (t1 + t2) / 2, "need": ["scene", "timeline"]}
            relevant = set()
            for scene in project["scenes"]:
                if scene["start"] <= t2 and scene["end"] >= t1:
                    relevant.add(builder.scene_page(scene))
            for clip in project["timeline"]:
                if clip["start"] <= t2 and clip["end"] >= t1:
                    relevant.add(builder.clip_page(clip))
            relevant = set(list(relevant)[:10])

        elif qtype == "cross_reference":
            # "Find scene after topic X where person Y appears"
            topic = random.choice(topics)
            person = random.choice(people)
            intent = {"search": topic, "need": ["scene", "timeline"]}
            relevant = set()
            for scene in project["scenes"]:
                if scene["topic"] == topic:
                    relevant.add(builder.scene_page(scene))
                    for other in project["scenes"]:
                        if other["start"] > scene["end"] and person in other["people"]:
                            relevant.add(builder.scene_page(other))
                            break
                    break
                if scene["topic"] == topic and person in scene["people"]:
                    relevant.add(builder.scene_page(scene))

        if not relevant:
            continue

        queries.append({
            "id": f"q_{len(queries):04d}",
            "type": qtype,
            "intent": intent,
            "ground_truth": relevant,
            "n_relevant": len(relevant),
        })

    return queries[:n]


# ═══════════════════════════════════════════════════════════════════════════
# 7. METRICS
# ═══════════════════════════════════════════════════════════════════════════

def compute_metrics(retrieved_pages, ground_truth):
    """Compute precision, recall, F1, success."""
    retrieved_ids = set((p.type, p.id) for p in retrieved_pages)
    relevant_ids = set((p.type, p.id) for p in ground_truth)

    tp = len(retrieved_ids & relevant_ids)
    fp = len(retrieved_ids - relevant_ids)
    fn = len(relevant_ids - retrieved_ids)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    success = 1.0 if recall >= 1.0 else 0.0  # All relevant pages found

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "success": success,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def naive_context(project):
    """Estimate tokens for dumb dump."""
    tx_text = " ".join(s["text"] for s in project["transcript"])
    tl_text = json.dumps(project["timeline"], indent=2)
    sc_text = json.dumps([{"id": s["id"], "topic": s["topic"]} for s in project["scenes"]], indent=2)
    all_text = tx_text + " " + tl_text + " " + sc_text
    return int(len(all_text.split()) / 0.75)


def naive_query(project, intent):
    """Naive: return all pages (simulated — we return all scene + clip pages)."""
    builder = PageBuilder(project)
    pages = []
    for scene in project["scenes"]:
        pages.append(builder.scene_page(scene, level="summary"))
    for clip in project["timeline"]:
        pages.append(builder.clip_page(clip, level="summary"))
    # Truncate to simulate max budget (use all)
    return {"pages": pages, "total_tokens": naive_context(project)}


# ═══════════════════════════════════════════════════════════════════════════
# 8. BENCHMARK RUNNER
# ═══════════════════════════════════════════════════════════════════════════

BUDGETS = [250, 500, 1000, 2500, 5000, 10000]
VIDEO_SIZES = [5, 30, 60, 180, 480]  # minutes
N_QUERIES = 100


def run_benchmark():
    print("=" * 80)
    print("  FLOW CONTEXT ENGINE — FULL BENCHMARK SUITE")
    print(f"  {len(BUDGETS) * len(VIDEO_SIZES)} configs x {N_QUERIES} queries x 3 methods")
    print("=" * 80)

    all_results = {}

    for vid_min in VIDEO_SIZES:
        print(f"\n{'─' * 80}")
        print(f"  Video size: {vid_min} min")
        print(f"  {'─' * 80}")

        t0 = time.time()
        project = generate_project(duration_minutes=vid_min, seed=42)
        gen_t = time.time() - t0

        # Build indexes
        tx_idx = TranscriptIndex()
        tx_idx.build(project["transcript"])
        scene_idx = SceneIndex()
        scene_idx.build(project["scenes"])
        tl_idx = TimelineIndex()
        tl_idx.build(project["timeline"])
        planner = QueryPlanner(project, tx_idx, scene_idx, tl_idx)
        rag = RAGBaseline(project)

        # Generate queries
        queries = generate_queries(project, N_QUERIES)

        naive_tok = naive_context(project)
        print(f"  Clips: {project['total_clips']} | Scenes: {len(project['scenes'])} | "
              f"TX segs: {len(project['transcript'])} | Naive: {naive_tok:,}t")
        print(f"  Generated {len(queries)} queries | Gen time: {gen_t:.2f}s")

        size_results = {}
        for budget in BUDGETS:
            budget_results = {"naive": defaultdict(float), "rag": defaultdict(float),
                            "vvm": defaultdict(float), "count": 0}
            for q in queries:
                gt = q["ground_truth"]

                # Naive
                t0 = time.perf_counter()
                naive_r = naive_query(project, q["intent"])
                naive_lat = time.perf_counter() - t0
                naive_m = compute_metrics(naive_r["pages"], gt)
                budget_results["naive"]["precision"] += naive_m["precision"]
                budget_results["naive"]["recall"] += naive_m["recall"]
                budget_results["naive"]["f1"] += naive_m["f1"]
                budget_results["naive"]["success"] += naive_m["success"]
                budget_results["naive"]["tokens"] += naive_r["total_tokens"]
                budget_results["naive"]["latency"] += naive_lat

                # RAG
                t0 = time.perf_counter()
                rag_r = rag.query(q["intent"], budget=budget)
                rag_lat = time.perf_counter() - t0
                rag_m = compute_metrics(rag_r["pages"], gt)
                budget_results["rag"]["precision"] += rag_m["precision"]
                budget_results["rag"]["recall"] += rag_m["recall"]
                budget_results["rag"]["f1"] += rag_m["f1"]
                budget_results["rag"]["success"] += rag_m["success"]
                budget_results["rag"]["tokens"] += rag_r["total_tokens"]
                budget_results["rag"]["latency"] += rag_lat

                # Flow VVM
                t0 = time.perf_counter()
                vvm_r = planner.plan(q["intent"], budget=budget)
                vvm_lat = time.perf_counter() - t0
                vvm_m = compute_metrics(vvm_r["pages"], gt)
                budget_results["vvm"]["precision"] += vvm_m["precision"]
                budget_results["vvm"]["recall"] += vvm_m["recall"]
                budget_results["vvm"]["f1"] += vvm_m["f1"]
                budget_results["vvm"]["success"] += vvm_m["success"]
                budget_results["vvm"]["tokens"] += vvm_r["total_tokens"]
                budget_results["vvm"]["latency"] += vvm_lat

                budget_results["count"] += 1

            n = budget_results["count"]
            for method in ["naive", "rag", "vvm"]:
                for metric in ["precision", "recall", "f1", "success", "tokens", "latency"]:
                    budget_results[method][metric] /= n

            size_results[budget] = budget_results

        all_results[vid_min] = size_results

        # Print table for this video size
        print(f"\n  {'Method':<8} {'Budget':>7} {'Tokens':>8} {'Prec':>6} {'Recall':>6} {'F1':>6} {'Success':>8} {'Lat(ms)':>8}")
        print(f"  {'─' * 65}")
        last_budget = 10000  # show naive only once
        for budget in BUDGETS:
            r = size_results[budget]
            nv = r["naive"]
            rg = r["rag"]
            vv = r["vvm"]
            if budget == last_budget:
                print(f"  {'naive':<8} {'all':>7} {nv['tokens']:>8,.0f} "
                      f"{nv['precision']:>6.2f} {nv['recall']:>6.2f} "
                      f"{nv['f1']:>6.2f} {nv['success']:>7.1%} "
                      f"{nv['latency']*1000:>7.1f}")
            print(f"  {'RAG':<8} {budget:>7} {rg['tokens']:>8,.0f} "
                  f"{rg['precision']:>6.2f} {rg['recall']:>6.2f} "
                  f"{rg['f1']:>6.2f} {rg['success']:>7.1%} "
                  f"{rg['latency']*1000:>7.1f}")
            print(f"  {'VVM':<8} {budget:>7} {vv['tokens']:>8,.0f} "
                  f"{vv['precision']:>6.2f} {vv['recall']:>6.2f} "
                  f"{vv['f1']:>6.2f} {vv['success']:>7.1%} "
                  f"{vv['latency']*1000:>7.1f}")
            print()

    # ─── GRAND SUMMARY ───
    print("\n" + "=" * 80)
    print("  GRAND SUMMARY: Success Rate vs Budget (all video sizes)")
    print("=" * 80)

    for vid_min in VIDEO_SIZES:
        print(f"\n  {vid_min} min video:")
        print(f"  {'Budget':>8} {'Naive':>8} {'RAG':>8} {'VVM':>8} {'VVM Tokens':>12}")
        print(f"  {'─' * 52}")
        for budget in BUDGETS:
            r = all_results[vid_min][budget]
            print(f"  {budget:>8} "
                  f"{r['naive']['success']:>7.1%} "
                  f"{r['rag']['success']:>7.1%} "
                  f"{r['vvm']['success']:>7.1%} "
                  f"{r['vvm']['tokens']:>11,.0f}")

    # ─── FAILURE ANALYSIS ───
    print("\n" + "=" * 80)
    print("  FAILURE ANALYSIS: Where VVM breaks (worst recall queries)")
    print("=" * 80)

    project = generate_project(duration_minutes=60, seed=42)
    tx_idx = TranscriptIndex()
    tx_idx.build(project["transcript"])
    scene_idx = SceneIndex()
    scene_idx.build(project["scenes"])
    tl_idx = TimelineIndex()
    tl_idx.build(project["timeline"])
    planner = QueryPlanner(project, tx_idx, scene_idx, tl_idx)
    queries = generate_queries(project, 50)

    failures = []
    budget = 1000
    for q in queries:
        r = planner.plan(q["intent"], budget=budget)
        m = compute_metrics(r["pages"], q["ground_truth"])
        failures.append({"recall": m["recall"], "f1": m["f1"], "query": q, "result": r,
                         "retrieved": len(r["pages"]), "relevant": q["n_relevant"],
                         "precision": m["precision"]})

    failures.sort(key=lambda x: x["recall"])  # worst first
    print(f"  Budget: {budget}t | Showing 5 worst queries:\n")
    for i, f in enumerate(failures[:5]):
        q = f["query"]
        print(f"  #{i+1} [{q['type']}] Recall={f['recall']:.2f} F1={f['f1']:.2f} "
              f"Prec={f['precision']:.2f} Relevant={f['relevant']} Retrieved={f['retrieved']}")
        print(f"      Intent keys: {list(q['intent'].keys())}")
        print()

    # ─── OPTIMAL BUDGET ANALYSIS ───
    print("─" * 80)
    print("  OPTIMAL BUDGET: F1 plateau detection (60 min video)")
    print("─" * 80)
    r60 = all_results[60]
    print(f"  {'Budget':>8} {'VVM F1':>8} {'VVM Tokens':>12} {'Marginal F1':>14}")
    print(f"  {'─' * 50}")
    prev_f1 = 0
    for budget in BUDGETS:
        f1 = r60[budget]["vvm"]["f1"]
        tok = r60[budget]["vvm"]["tokens"]
        delta = f1 - prev_f1
        print(f"  {budget:>8} {f1:>8.3f} {tok:>12,.0f} {delta:>+14.4f}")
        prev_f1 = f1

    print("\n" + "=" * 80)
    print("  BENCHMARK COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_benchmark()
