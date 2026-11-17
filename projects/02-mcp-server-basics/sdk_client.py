"""
The same session as raw_client.py with the MCP SDK's Client: it handles the handshake, ids and parsing.
Pass a command (stdio), a URL (HTTP) or the server object itself (in-process, used by the tests).

  python sdk_client.py                                  # stdio: starts server.py
  python sdk_client.py http://127.0.0.1:9001/mcp        # HTTP: start `make run-http` first
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

HERE = Path(__file__).resolve().parent


async def demo(target) -> dict:
    async with Client(target) as client:
        tools = (await client.list_tools()).tools
        ok = await client.call_tool("failed_cases", {"run_id": "r50"})
        bad = await client.call_tool("failed_cases", {"run_id": "r99"})
        return {"server": client.server_info.name if client.server_info else "?",
                "tools": [t.name for t in tools],
                "ok": ok.structured_content, "error": (bad.is_error, bad.content[0].text)}


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else StdioServerParameters(
        command=sys.executable, args=[str(HERE / "server.py")])
    print(json.dumps(asyncio.run(demo(target)), indent=2))


if __name__ == "__main__":
    main()
