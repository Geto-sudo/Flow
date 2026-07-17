"""Test MCP server end-to-end via direct handler call."""
import sys, json
sys.path.insert(0, r"C:\Users\Administrator.BF-202506211914\Desktop\flow\python")
from flow_core.mcp_server import _handle_request

VIDEO = r"C:\Users\Administrator.BF-202506211914\Desktop\flow\test_fixtures\spoken.mp4"
OUTPUT = r"C:\Users\Administrator.BF-202506211914\Desktop\flow\test_fixtures\mcp_out.mp4"

# 1. initialize
r = _handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
print(f"[1] initialize: server={r['result']['serverInfo']}")

# 2. tools/list
r = _handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
tools = r["result"]["tools"]
print(f"[2] tools/list: {len(tools)} tools")
for t in tools:
    print(f"    - {t['name']}")

# 3. flow_observe
r = _handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "flow_observe",
                                "arguments": {"video_path": VIDEO, "depth": "fast"}}})
content = json.loads(r["result"]["content"][0]["text"])
gid = content["graph_id"]
print(f"[3] flow_observe: graph_id={gid}, dur={content['duration_seconds']}s, "
      f"nodes={content['stats']['total_nodes']}")

# 4. flow_query
r = _handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                     "params": {"name": "flow_query",
                                "arguments": {"graph_id": gid, "query": "scenes"}}})
q = json.loads(r["result"]["content"][0]["text"])
print(f"[4] flow_query scenes: count={q['count']}")

# 5. flow_plan
r = _handle_request({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                     "params": {"name": "flow_plan",
                                "arguments": {"graph_id": gid, "intent": "first_n:3"}}})
p = json.loads(r["result"]["content"][0]["text"])
print(f"[5] flow_plan first_n:3: {p['count']} actions, planner={p['planner']}")

# 6. flow_execute
r = _handle_request({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                     "params": {"name": "flow_execute",
                                "arguments": {"graph_id": gid,
                                              "actions": p["actions"],
                                              "output_path": OUTPUT}}})
e = json.loads(r["result"]["content"][0]["text"])
print(f"[6] flow_execute: applied={e['actions_applied']}, errors={e['errors']}, "
      f"render cmd starts: {e['render'][0][:60]}...")

# 7. flow_verify
r = _handle_request({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                     "params": {"name": "flow_verify",
                                "arguments": {"expected": {"duration": 3.0,
                                                          "has_audio": True},
                                              "actual": OUTPUT}}})
v = json.loads(r["result"]["content"][0]["text"])
print(f"[7] flow_verify: ok={v['ok']}, summary={v['summary']}")
