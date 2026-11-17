"""
Talk to the server with NO MCP library: start it, write JSON-RPC lines to its stdin, read lines from
its stdout. This is everything an MCP host does under the hood over stdio.

  1. initialize                 -> server name, protocol version, capabilities
  2. notifications/initialized  (a notification: no id, no response)
  3. tools/list                 -> name, description, inputSchema of every tool
  4. tools/call                 -> content (text for the model), structuredContent, isError

  python raw_client.py            # prints every message in both directions
"""
import json
import subprocess
import sys
from pathlib import Path

import mcp.types

HERE = Path(__file__).resolve().parent


class RawStdioClient:
    def __init__(self, cmd: list[str], show=print):
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        self.next_id, self.show = 1, show

    def _send(self, msg: dict) -> None:
        self.show("→", msg)
        self.proc.stdin.write(json.dumps(msg) + "\n")      # one JSON object per line
        self.proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method, **({"params": params} if params else {})}
        self.next_id += 1
        self._send(msg)
        while True:                                       # skip server notifications (e.g. logs) until our id
            reply = json.loads(self.proc.stdout.readline())
            self.show("←", reply)
            if reply.get("id") == msg["id"]:
                return reply

    def notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.wait(timeout=10)


def session(show=print) -> dict:
    """Run the four steps; returns the replies (tests use them)."""
    c = RawStdioClient([sys.executable, str(HERE / "server.py")], show)
    try:
        init = c.request("initialize", {"protocolVersion": mcp.types.LATEST_PROTOCOL_VERSION, "capabilities": {},
                                        "clientInfo": {"name": "raw-client", "version": "0.1"}})
        c.notify("notifications/initialized")
        tools = c.request("tools/list")
        ok = c.request("tools/call", {"name": "failed_cases", "arguments": {"run_id": "r50"}})
        bad = c.request("tools/call", {"name": "failed_cases", "arguments": {"run_id": "r99"}})
        return {"initialize": init, "tools/list": tools, "call_ok": ok, "call_error": bad}
    finally:
        c.close()


def show_message(direction: str, msg: dict) -> None:
    print(f"\n{direction} " + json.dumps(msg, indent=2)[:2000])


if __name__ == "__main__":
    session(show_message)
