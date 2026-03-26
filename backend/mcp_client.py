import subprocess
import json
import uuid

MCP_CMD = ["python", "../MCP/server.py"]

def call_tool(tool: str, args: dict):
    proc = subprocess.Popen(
        MCP_CMD,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    request = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": f"tools/{tool}",   # 🔥 CRITICAL FIX
        "params": args
    }

    # Send JSON-RPC request
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()

    # Read until we get the matching response
    while True:
        line = proc.stdout.readline()

        if not line:
            raise RuntimeError("MCP returned empty response")

        try:
            data = json.loads(line.strip())
        except json.JSONDecodeError:
            continue  # skip logs / non-JSON lines

        if data.get("id") == request["id"]:
            if "result" in data:
                return data["result"]
            if "error" in data:
                return {"error": data["error"]}