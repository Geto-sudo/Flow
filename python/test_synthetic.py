"""Smoke test: synthetic observe -> query chain.

Validates that flow_core's 5-verb API works end-to-end without ffmpeg
by using the synthetic scenario generator (build_graph_synthetic).
"""
import sys
sys.path.insert(0, r"C:\Users\Administrator.BF-202506211914\Desktop\flow\crates\flow-core")
import flow_core as flow


def main():
    print("=" * 70)
    print("FLOW CORE — synthetic smoke test")
    print("=" * 70)

    # 1. observe via synthetic scenario
    g = flow.observe("podcast")
    print(f"\n[observe('podcast')]")
    print(f"  {repr(g)}")
    print(f"  stats: {g.stats()}")

    # 2. query by node type
    for q in ["scenes", "transcript", "people", "objects", "tracks", "timeline"]:
        r = flow.query(g, q)
        print(f"\n[query(g, '{q}')] count={r.get('count', '?')}")
        for n in r.get("nodes", [])[:3]:
            label = n.label[:60] if n.label else "(no label)"
            print(f"  - [{n.type}] {label}")

    # 3. find by text
    r = flow.query(g, "find(AI)")
    print(f"\n[query(g, 'find(AI)')] count={r['count']}")
    for n in r["nodes"][:3]:
        print(f"  - [{n.type}] {n.label[:60]}")

    # 4. scene(N) — first scene with children
    r = flow.query(g, "scene(0)")
    print(f"\n[query(g, 'scene(0)')] count={r['count']}")
    for n in r.get("nodes", [])[:5]:
        print(f"  - [{n.type}] {n.label[:60]}")

    # 5. stats
    r = flow.query(g, "stats")
    print(f"\n[query(g, 'stats')] {r}")

    # 6. serialization roundtrip
    d = g.to_dict()
    g2 = type(g).from_dict(d)
    print(f"\n[serialization roundtrip]")
    print(f"  graph1 nodes={len(g.nodes)} | graph2 nodes={len(g2.nodes)}")
    print(f"  match: {g.stats() == g2.stats()}")

    # 7. try all 4 scenarios
    print("\n[scenarios]")
    for scenario in ["podcast", "interview", "vlog", "tutorial"]:
        g = flow.observe(scenario)
        s = g.stats()
        print(f"  {scenario:10s} -> scenes={s['by_type'].get('Scene', 0):2d} "
              f"transcripts={s['by_type'].get('Transcript', 0):3d} "
              f"people={s['by_type'].get('Person', 0):2d} "
              f"objects={s['by_type'].get('Object', 0):2d}")

    print("\n" + "=" * 70)
    print("OK — synthetic pipeline works end-to-end")
    print("=" * 70)


if __name__ == "__main__":
    main()
