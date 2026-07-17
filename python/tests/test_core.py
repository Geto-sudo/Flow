"""
Sprint 0 + 1 — 30 tests for flow-core.

Covers: ProjectGraph (typed), observe(), query(), plan(), synthetic builder.

Run: python -m pytest tests/ -v
   or: python tests/test_core.py
"""

import sys, os, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flow_core import (
    observe, query, plan,
    ProjectGraph, Clip, Scene, TranscriptSegment, Person,
    DetectedObject, Asset, Timeline, Track, Project,
    GraphEdge,  # <-- needed for test_35
    build_graph_synthetic, SCENARIO_SPECS,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1–8: ProjectGraph unit tests
# ═══════════════════════════════════════════════════════════════════════════

def test_1_graph_creation():
    """Empty graph has no typed nodes (only project root)."""
    g = ProjectGraph("test")
    assert g.name == "test"
    assert len(g.nodes) == 0  # no auto-root anymore
    assert len(g.clips) == 0


def test_2_add_typed_node():
    """Adding a typed node stores it with its fields."""
    g = ProjectGraph("test")
    c = Clip(start=10.0, end=20.0, duration=10.0, source="test.mp4")
    g.add(c)
    assert c.id in g.nodes
    assert g.clips[0].start == 10.0
    assert g.clips[0].source == "test.mp4"


def test_3_add_edge_and_traverse():
    """Edges connect typed nodes and are traversable."""
    g = ProjectGraph("test")
    track = Track(name="V1", index=0)
    g.add(track)
    clip = Clip(start=0, end=60, duration=60, source="a.mp4")
    g.add(clip)
    g.add_edge(track.id, clip.id, "contains")
    children = g.children(track.id)
    assert len(children) == 1
    assert children[0].id == clip.id
    parents = g.parents(clip.id)
    assert parents[0].id == track.id


def test_4_remove_node():
    """Removing a node cleans up edges."""
    g = ProjectGraph("test")
    c = Clip(start=0, end=10, duration=10, source="t.mp4")
    g.add(c)
    g.remove_node(c.id)
    assert c.id not in g.nodes


def test_5_typed_properties():
    """graph.clips, graph.scenes, etc. return typed lists."""
    g = ProjectGraph("test")
    for i in range(3):
        g.add(Clip(start=i*10, end=i*10+10, duration=10, source=f"c{i}.mp4"))
    g.add(Scene(start=0, end=10, duration=10, topic="Intro"))
    assert len(g.clips) == 3
    assert len(g.scenes) == 1
    assert isinstance(g.clips[0], Clip)
    assert isinstance(g.scenes[0], Scene)


def test_6_search():
    """search(query) finds nodes by string content."""
    g = ProjectGraph("test")
    g.add(Clip(start=0, end=10, duration=10, source="revenue_clip.mp4"))
    g.add(Scene(start=0, end=10, duration=10, topic="Revenue Growth"))
    results = g.search("revenu")
    assert len(results) == 2


def test_7_at_time():
    """at_time(t) returns nodes active at time t."""
    g = ProjectGraph("test")
    g.add(Clip(start=0, end=30, duration=30, source="c.mp4"))
    g.add(Scene(start=10, end=20, duration=10, topic="Mid"))
    nodes = g.at_time(15)
    assert len(nodes) == 2


def test_8_serialization_roundtrip():
    """to_dict/from_dict preserves typed graph structure."""
    g = ProjectGraph("test")
    proj = Project(name="test")
    g.add(proj)
    tl = Timeline()
    g.add(tl)
    g.add_edge(proj.id, tl.id)
    track = Track(name="V1", index=0)
    g.add(track)
    g.add_edge(tl.id, track.id)
    clip = Clip(start=0, end=60, duration=60, source="s.mp4")
    g.add(clip)
    g.add_edge(track.id, clip.id)
    scene = Scene(start=0, end=30, duration=30, topic="Intro",
                  people=["Alice"])
    g.add(scene)
    g.add_edge(clip.id, scene.id, "contains_scene")

    d = g.to_dict()
    g2 = ProjectGraph.from_dict(d)
    assert g2.name == g.name
    assert len(g2.nodes) == len(g.nodes)
    assert len(g2.scenes) == 1
    assert g2.scenes[0].topic == "Intro"


# ═══════════════════════════════════════════════════════════════════════════
# 9–12: Synthetic builder tests
# ═══════════════════════════════════════════════════════════════════════════

def test_9_build_podcast_graph():
    """Synthetic podcast has expected typed structure."""
    g = build_graph_synthetic("podcast")
    s = g.stats()
    assert s["total_nodes"] > 10
    assert "clip" in s["by_type"]
    assert "scene" in s["by_type"]
    assert "transcript" in s["by_type"]
    assert "person" in s["by_type"]


def test_10_all_scenarios_valid():
    """All four scenario types build without errors."""
    for name in SCENARIO_SPECS:
        g = build_graph_synthetic(name)
        assert g.stats()["total_nodes"] > 0, f"{name} graph is empty"


def test_11_timeline_has_tracks():
    """Every synthetic graph has a timeline with at least one track."""
    for name in SCENARIO_SPECS:
        g = build_graph_synthetic(name)
        timelines = g.find_by_type(Timeline)
        assert len(timelines) == 1, f"{name}: expected 1 timeline"
        tracks = g.find_by_type(Track)
        assert len(tracks) >= 1, f"{name}: expected >=1 tracks"


def test_12_scenes_have_transcripts():
    """Scenes contain transcript segments."""
    g = build_graph_synthetic("podcast")
    tx_count = 0
    for scene in g.scenes:
        tx_count += len(g.children(scene.id, "has_transcript"))
    assert tx_count > 0, "Expected transcript segments"


# ═══════════════════════════════════════════════════════════════════════════
# 13–20: observe() and query() tests
# ═══════════════════════════════════════════════════════════════════════════

def test_13_observe_synthetic():
    """observe('podcast') returns a ProjectGraph."""
    g = observe("podcast")
    assert isinstance(g, ProjectGraph)
    assert "podcast" in g.name


def test_14_observe_invalid():
    """observe with invalid source raises FileNotFoundError."""
    try:
        observe("/nonexistent/path/video.mp4")
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_15_query_clips():
    """query(graph, 'clips') returns Clip nodes."""
    g = observe("interview")
    result = query(g, "clips")
    assert result["count"] > 0
    assert all(isinstance(n, Clip) for n in result["nodes"])


def test_16_query_scenes():
    """query(graph, 'scenes') returns Scene nodes."""
    g = observe("podcast")
    result = query(g, "scenes")
    assert result["count"] >= 3
    assert all(isinstance(n, Scene) for n in result["nodes"])


def test_17_query_find():
    """query(graph, 'find(text)') searches the graph."""
    g = observe("tutorial")
    result = query(g, "find(step)")
    assert result["count"] > 0, "Expected to find nodes mentioning 'step'"


def test_18_query_scene_by_index():
    """query(graph, 'scene(N)') returns the Nth scene with children."""
    g = observe("podcast")
    result = query(g, "scene(0)")
    assert "error" not in result
    assert result["count"] >= 1


def test_19_query_stats():
    """query(graph, 'stats') returns statistics."""
    g = observe("vlog")
    stats = query(g, "stats")
    assert stats["total_nodes"] > 0


def test_20_query_node_by_id():
    """query(graph, '<node_id>') returns that node with children."""
    g = observe("podcast")
    clip = g.clips[0]
    result = query(g, clip.id)
    assert result["count"] >= 1


# ═══════════════════════════════════════════════════════════════════════════
# 21–30: plan() tests — Sprint 1
# ═══════════════════════════════════════════════════════════════════════════

def test_21_plan_tighten():
    """plan(graph, 'tighten') returns trim actions on a podcast."""
    g = observe("podcast")
    result = plan(g, "tighten")
    assert result["intent"] == "tighten"
    assert result["count"] > 0, "Should find filler words to trim"
    for a in result["actions"]:
        assert a["action"] == "trim"
        assert "clip" in a
        assert "reason" in a


def test_22_plan_remove_ums():
    """plan(graph, 'remove_ums') finds hesitation markers."""
    g = observe("interview")
    result = plan(g, "remove_ums")
    for a in result["actions"]:
        assert a["action"] == "trim"


def test_23_plan_jump_cuts():
    """plan(graph, 'jump_cuts') splits long clips."""
    g = observe("vlog")
    result = plan(g, "jump_cuts")
    for a in result["actions"]:
        assert a["action"] == "split"
        assert "at" in a


def test_24_plan_dead_air():
    """plan(graph, 'remove_dead_air') finds non-content segments."""
    g = observe("tutorial")
    result = plan(g, "remove_dead_air")
    for a in result["actions"]:
        assert a["action"] == "trim"


def test_25_plan_unknown_intent():
    """plan() with unknown intent returns error."""
    g = observe("podcast")
    result = plan(g, "make_it_epic")
    assert "error" in result
    assert result["count"] == 0


def test_26_plan_all_scenarios():
    """Every scenario produces valid plan results for every intent."""
    intents = ["tighten", "remove_ums", "jump_cuts", "remove_dead_air"]
    for scenario in SCENARIO_SPECS:
        g = observe(scenario)
        for intent in intents:
            result = plan(g, intent)
            assert "actions" in result
            assert isinstance(result["count"], int)


def test_27_plan_actions_are_serializable():
    """All plan actions can be serialized to JSON."""
    g = observe("podcast")
    result = plan(g, "tighten")
    dumped = json.dumps(result["actions"])
    assert len(dumped) > 0


def test_28_plan_clip_references_exist():
    """Every action references a clip that exists in the graph."""
    g = observe("interview")
    result = plan(g, "remove_ums")
    clip_ids = {c.id for c in g.clips}
    for a in result["actions"]:
        if "clip" in a:
            assert a["clip"] in clip_ids, f"Clip {a['clip']} not in graph"


def test_29_plan_timestamps_in_range():
    """Trim action timestamps fall within their clip's range."""
    g = observe("podcast")
    result = plan(g, "tighten")
    for a in result["actions"]:
        if a["action"] == "trim" and "clip" in a:
            clip = g.get(a["clip"])
            if clip and isinstance(clip, Clip):
                assert clip.start <= a["start"] < clip.end, \
                    f"Trim start {a['start']} outside [{clip.start}, {clip.end}]"


def test_30_plan_consistent_with_observe_query():
    """Plan outputs integrate with observe->query->plan pipeline."""
    g = observe("tutorial")
    clips = query(g, "clips")
    scenes = query(g, "scenes")
    result = plan(g, "remove_dead_air")
    assert result["planner"] is not None
    assert clips["count"] > 0
    assert scenes["count"] > 0


# ═══════════════════════════════════════════════════════════════════════════
# New: Observable interface, window(), relationships
# ═══════════════════════════════════════════════════════════════════════════

def test_31_window_returns_grouped_nodes():
    """window() returns nodes grouped by type, overlapping the time range."""
    g = observe("podcast")
    w = g.window(0, 300)  # first 5 minutes
    assert "clip" in w
    assert "scene" in w
    assert "transcript" in w
    assert len(w["clip"]) >= 1
    assert len(w["scene"]) >= 1


def test_32_window_respects_boundaries():
    """window() only returns nodes that overlap [start, end]."""
    g = observe("interview")
    mid = g.nodes[g.scenes[0].id].end  # type: ignore
    w = g.window(mid - 1, mid + 1)  # narrow window
    total = sum(len(v) for v in w.values())
    assert total < len(g.nodes)  # should be fewer than all nodes


def test_33_observe_window_returns_rich_text():
    """observe_window() returns a formatted string for an AI agent."""
    g = observe("podcast")
    text = g.observe_window(0, 120)
    assert "Window 00:00" in text
    assert "scene" in text.lower() or "clip" in text.lower()


def test_34_neighbors_returns_connected_nodes():
    """neighbors() returns nodes connected by edges."""
    g = observe("podcast")
    scene = g.scenes[0]
    neigh = g.neighbors(scene.id)
    assert len(neigh) >= 1


def test_35_relationships_returns_typed_edges():
    """relationships() returns GraphEdge objects."""
    g = observe("podcast")
    scene = g.scenes[0]
    rels = g.relationships(scene.id)
    assert len(rels) >= 1
    assert all(isinstance(r, GraphEdge) for r in rels)


def test_36_children_parents_filter_by_relation():
    """children() and parents() filter by relation type."""
    g = observe("podcast")
    scene = g.scenes[0]
    # scene -> transcript via "has_transcript"
    kids = g.children(scene.id, "has_transcript")
    assert len(kids) >= 1
    assert all(isinstance(k, TranscriptSegment) for k in kids)


def test_37_get_and_getitem():
    """get() and __getitem__ work for node lookup."""
    g = observe("vlog")
    clip = g.clips[0]
    assert g.get(clip.id) is clip
    assert g[clip.id] is clip
    assert g.get("nonexistent") is None


def test_38_observe_on_every_node_type():
    """Every node type returns a non-empty observe() string."""
    g = observe("podcast")
    for node in g.nodes.values():
        obs = node.observe()
        assert isinstance(obs, str)
        assert len(obs) >= 5, f"observe() too short for {node.type}"


def test_39_summary_on_every_node_type():
    """Every node type returns a summary() <= 80 chars."""
    g = observe("podcast")
    for node in g.nodes.values():
        s = node.summary()
        assert isinstance(s, str)
        assert len(s) <= 81  # 80 chars + possible newline


def test_40_synthetic_has_audio_segments():
    """Synthetic graph includes AudioSegment nodes."""
    g = observe("podcast")
    audio_nodes = g.audio
    assert len(audio_nodes) > 0
    for a in audio_nodes:
        assert hasattr(a, "rms")
        assert hasattr(a, "beat")
        assert hasattr(a, "emotion")


def test_41_synthetic_has_objects():
    """Synthetic graph includes DetectedObject nodes."""
    g = observe("podcast")
    objects = g.objects
    assert len(objects) > 0


def test_42_edge_observe():
    """GraphEdge has an observe() method."""
    g = observe("podcast")
    scene = g.scenes[0]
    rels = g.relationships(scene.id)
    for r in rels:
        assert "[" in r.observe() or "--" in r.observe()


# ═══════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    tests = [v for k, v in list(locals().items())
             if k.startswith("test_") and callable(v)]
    tests.sort(key=lambda f: f.__name__)

    passed = 0
    for test in tests:
        try:
            test()
            print(f"  OK  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL {test.__name__}: {e}")

    print(f"\n  {passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
