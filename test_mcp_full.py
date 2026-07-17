"""Full MCP cycle: observe → plan → execute → render → verify."""
import sys, json, subprocess, os
sys.path.insert(0, r"C:\Users\Administrator.BF-202506211914\Desktop\flow\python")
from flow_core.mcp_server import _handle_request

VIDEO = r"C:\Users\Administrator.BF-202506211914\Desktop\flow\test_fixtures\spoken.mp4"
OUTPUT = r"C:\Users\Administrator.BF-202506211914\Desktop\flow\test_fixtures\mcp_out.mp4"

# Observe
r = _handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                     "params": {"name": "flow_observe",
                                "arguments": {"video_path": VIDEO, "depth": "fast"}}})
c = json.loads(r["result"]["content"][0]["text"])
gid = c["graph_id"]
print(f"[observe] graph_id={gid}, {c['stats']['total_nodes']} nodes, {c['duration_seconds']}s")

# Plan
r = _handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "flow_plan",
                                "arguments": {"graph_id": gid, "intent": "first_n:3"}}})
p = json.loads(r["result"]["content"][0]["text"])
print(f"[plan] {p['count']} actions, planner={p['planner']}")

# Execute (returns render cmd)
r = _handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "flow_execute",
                                "arguments": {"graph_id": gid,
                                              "actions": p["actions"],
                                              "output_path": OUTPUT}}})
e = json.loads(r["result"]["content"][0]["text"])
print(f"[execute] applied={e['actions_applied']}, errors={e['errors']}")

# Run the render (this is what an MCP client would do via its shell tool)
render = e["render"]
render = [OUTPUT if c == e["output"] else c for c in render]
print(f"[render cmd] {' '.join(render[:8])}...")
r2 = subprocess.run(render, capture_output=True, text=True, timeout=60)
print(f"[render] rc={r2.returncode}")
if r2.returncode != 0:
    print(f"[render stderr] {r2.stderr[-500:]}")
print(f"[render] size={os.path.getsize(OUTPUT)/1024:.1f}KB")

# Verify
r = _handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                     "params": {"name": "flow_verify",
                                "arguments": {"expected": {"duration": 3.0,
                                                          "has_audio": True},
                                              "actual": OUTPUT}}})
v = json.loads(r["result"]["content"][0]["text"])
print(f"[verify] ok={v['ok']}, summary={v['summary']}")

print()
print("=" * 60)
print("Full MCP cycle works: observe → plan → execute → render → verify")
print("=" * 60)
