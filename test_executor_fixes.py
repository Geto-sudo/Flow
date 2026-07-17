"""Test executor.py bug fixes."""
import sys, os
sys.path.insert(0, r"C:\Users\Administrator.BF-202506211914\Desktop\flow\python")
import flow_core as flow

VIDEO = r"C:\Users\Administrator.BF-202506211914\Desktop\flow\test_fixtures\spoken.mp4"
OUTPUT = r"C:\Users\Administrator.BF-202506211914\Desktop\flow\test_fixtures\spoken_trimmed.mp4"

# Test 1: bad trim (s > e) should be reported in errors, not crash
g = flow.observe(VIDEO, depth="fast")
res0 = flow.execute(g, [{"action": "trim", "clip": g.clips[0].id,
                          "start": 5.0, "end": 1.0, "reason": "bad"}])
if res0["errors"]:
    print(f"OK: bad trim caught: {res0['errors']}")
else:
    print(f"FAIL: bad trim not caught, applied={res0['actions_applied']}")

# Test 2: split at valid time should not duplicate edges
g2 = flow.observe(VIDEO, depth="fast")
before_edges = sum(len(v) for v in g2._out.values())
res = flow.execute(g2, [{"action": "split", "clip": g2.clips[0].id,
                          "at": 2.5, "reason": "test"}])
after_edges = sum(len(v) for v in g2._out.values())
print(f"split: edges before={before_edges}, after={after_edges}, "
      f"applied={res['actions_applied']}, errors={res['errors']}")

# Test 3: render uses bundled ffmpeg
g3 = flow.observe(VIDEO, depth="fast")
res2 = flow.execute(g3, [{"action": "trim", "clip": g3.clips[0].id,
                           "start": 0.0, "end": 3.0}])
render = res2["render"]
print(f"render cmd: {render[0][:80]}...")
print(f"uses bundled ffmpeg: {'imageio_ffmpeg' in render[0]}")

# Test 4: full cycle still works
import subprocess
output = OUTPUT
cmd = [output if c == res2["output"] else c for c in render]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
print(f"full render: rc={r.returncode}, size={os.path.getsize(output)/1024:.1f}KB")

# Test 5: verify still works
v = flow.verify({"duration": 3.0, "has_audio": True}, output)
print(f"verify: {v['summary']}")

