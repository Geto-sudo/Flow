"""Test plan() output schema on the real video pipeline."""
import sys
sys.path.insert(0, r"C:\Users\Administrator.BF-202506211914\Desktop\flow\python")
import flow_core as flow
import json

g = flow.observe(r"C:\Users\Administrator.BF-202506211914\Desktop\flow\test_fixtures\spoken.mp4", depth="full")

print("=" * 60)
print("Test 1: plan('cut_silences')")
print("=" * 60)
r = flow.plan(g, "cut_silences", min_silence=0.3)
print(f"  intent:   {r['intent']}")
print(f"  planner:  {r['planner']}")
print(f"  count:    {r['count']}")
for a in r['actions'][:3]:
    print(f"  action:   {json.dumps(a)}")

print()
print("=" * 60)
print("Test 2: plan('keep_only:person')")
print("=" * 60)
r2 = flow.plan(g, "keep_only:person")
print(f"  count:    {r2['count']}")
for a in r2['actions'][:3]:
    print(f"  action:   {json.dumps(a)}")

print()
print("=" * 60)
print("Test 3: plan('tighten_pauses') on a transcript with fillers")
print("=" * 60)
r3 = flow.plan(g, "tighten_pauses")
print(f"  count:    {r3['count']}")

print()
print("=" * 60)
print("Test 4: plan('unknown_intent')")
print("=" * 60)
r4 = flow.plan(g, "nope")
print(f"  error:    {r4.get('error')}")
print(f"  actions:  {r4['actions']}")
