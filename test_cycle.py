"""End-to-end test: observe → plan → execute → verify.

This is the full mission-critical cycle. The video gets trimmed to 3s
via the agent's plan, rendered by execute, and verified by verify."""
import sys
sys.path.insert(0, r"C:\Users\Administrator.BF-202506211914\Desktop\flow\python")
import flow_core as flow

video = r"C:\Users\Administrator.BF-202506211914\Desktop\flow\test_fixtures\spoken.mp4"
output = r"C:\Users\Administrator.BF-202506211914\Desktop\flow\test_fixtures\spoken_trimmed.mp4"

print("=" * 60)
print("Cycle: observe → plan → execute → ffmpeg render → verify")
print("=" * 60)

# 1. observe
g = flow.observe(video, depth="fast")
print(f"\n[1] observe: {len(g.nodes)} nodes, {len(g.scenes)} scenes")

# 2. plan
plan = flow.plan(g, "first_n:3")
print(f"\n[2] plan('first_n:3'): {plan['count']} actions")
for a in plan['actions']:
    print(f"    {a}")

# 3. execute (apply + render)
result = flow.execute(g, plan['actions'])
print(f"\n[3] execute: {result['actions_applied']} applied, {len(result['errors'])} errors")

# 4. Run the ffmpeg render
import subprocess, os
from flow_core import _ffmpeg as _ff
cmd = [_ff.ffmpeg_path() if c == 'ffmpeg' else c for c in result['render']]
cmd = [output if c == result['output'] else c for c in cmd]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
print(f"\n[4] ffmpeg render: rc={r.returncode}, size={os.path.getsize(output)/1024:.1f}KB")

# 5. verify
expected = {
    "duration": 3.0,           # ±0.5s tolerance
    "has_audio": True,
    "min_duration": 2.5,
    "max_duration": 3.5,
}
verdict = flow.verify(expected, output)
print(f"\n[5] verify: {verdict['summary']}")
print(f"    ok: {verdict['ok']}")
print(f"    checks:")
for c in verdict['checks']:
    status = "✓" if c['ok'] else "✗"
    print(f"      {status} {c['name']:15s} expected={c['expected']!r:10s} actual={c['actual']!r}")
if verdict['errors']:
    print(f"    errors: {verdict['errors']}")
if verdict['warnings']:
    print(f"    warnings: {verdict['warnings']}")
print(f"    diff: {verdict['diff']}")

# 6. Now test with a FAILING expectation
print("\n" + "=" * 60)
print("Failure case: expected 10s duration but actual is ~3s")
print("=" * 60)
expected_fail = {"duration": 10.0}
v2 = flow.verify(expected_fail, output)
print(f"  ok: {v2['ok']}")
print(f"  summary: {v2['summary']}")
print(f"  errors: {v2['errors']}")

# 7. Verify with a ProjectGraph directly (no path needed)
print("\n" + "=" * 60)
print("Verify from ProjectGraph (no render needed)")
print("=" * 60)
g_after = flow.observe(video, depth="fast")
# Apply the same plan in-memory
flow.execute(g_after, plan['actions'])
g_verdict = flow.verify(expected, g_after)
print(f"  ok: {g_verdict['ok']}")
print(f"  summary: {g_verdict['summary']}")
