"""Test the full plan() API surface on the real video pipeline."""
import sys, json
sys.path.insert(0, r"C:\Users\Administrator.BF-202506211914\Desktop\flow\python")
import flow_core as flow

g = flow.observe(r"C:\Users\Administrator.BF-202506211914\Desktop\flow\test_fixtures\spoken.mp4", depth="full")

# Try every pattern intent
tests = [
    "cut_silences",
    "first_n:3",
    "last_n:2",
    "trim:1-4",
    "keep_only:person",
    "remove_label:sheep",
    "tagged_scenes:animated",
    "tighten_pauses",
    "unknown_thing",
    "first_n:notanumber",
    "trim:bad",
]

for intent in tests:
    r = flow.plan(g, intent)
    status = "OK " if "error" not in r else "ERR"
    print(f"[{status}] {intent:30s} -> count={r['count']:3d} planner={r.get('planner')}")
    if "error" in r:
        print(f"        error: {r['error']}")
    elif r['actions']:
        # Show one action sample
        a = r['actions'][0]
        print(f"        sample: {json.dumps(a)}")
