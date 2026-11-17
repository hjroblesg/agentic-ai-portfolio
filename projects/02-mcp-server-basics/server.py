"""
A minimal MCP server: the same two tools as project 01, now reusable by ANY MCP host
(Claude Code, Claude Desktop, the Agent SDK, LangGraph, Strands...) instead of living inside one app.

What changed from 01:
- No hand-written JSON Schema. The SDK builds `inputSchema` from the type hints and `description`
  from the docstring. Those still are prompt text: the model decides from them.
- Errors: raise ToolError. Its message reaches the model (result.isError = true). Any other exception
  reaches the model only as a generic error, so expected failures should always be ToolErrors.
- One resource (data the HOST can read and attach) and one prompt (a template the USER can pick).
  Tools are for the MODEL; resources and prompts are for the app and the user.

  python server.py                                 # stdio: a host starts it as a subprocess
  python server.py --transport streamable-http     # HTTP on 127.0.0.1:9001/mcp

The full server with DynamoDB, S3 and S3 Vectors is shared/mcp-server/server.py.
"""
import argparse
import json
import sys
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from qa_shared.fixtures import load_fixtures

mcp = MCPServer("qa-basics", instructions="Read-only access to nightly test runs (synthetic data).")


@mcp.tool()
def list_runs(project: Literal["checkout", "search", "payments"], limit: int = 5) -> list[dict]:
    """List recent nightly test runs for one project, newest first, with pass/fail counts.
    Use it to find which runs failed before asking for their failed cases."""
    runs = sorted((r for r in load_fixtures().runs if r.project == project),
                  key=lambda r: r.executed_at, reverse=True)
    return [{"run_id": r.run_id, "executed_at": r.executed_at, "total": len(r.cases), "failed": len(r.failed)}
            for r in runs[:max(1, min(limit, 10))]]


@mcp.tool()
def failed_cases(run_id: str) -> list[dict]:
    """Failed test cases of one run (e.g. r42), with the error message of each.
    An empty list means the run was clean."""
    fx = load_fixtures()
    try:
        run = fx.run(run_id)
    except StopIteration:
        raise ToolError(f"Unknown run {run_id!r}. Call list_runs to see valid run ids.") from None
    log(f"failed_cases {run_id}: {len(run.failed)} failed")
    return [{"test_name": c.test, "error_message": fx.failure(c.failure).error_message} for c in run.failed]


@mcp.resource("runs://{run_id}")
def run_summary(run_id: str) -> str:
    """Every case of one run, as JSON (for hosts that attach context instead of calling tools)."""
    try:
        run = load_fixtures().run(run_id)
    except StopIteration:
        raise ValueError(f"Unknown run {run_id}") from None
    return json.dumps(run.model_dump(), indent=2)


@mcp.prompt()
def triage_run(run_id: str) -> str:
    """Ask the model to explain one failed run."""
    return f"Explain why run {run_id} failed. Use failed_cases, cite the error messages, and keep it short."


def log(msg: str) -> None:
    """stderr only: with stdio, stdout IS the protocol channel; one stray print() breaks the client."""
    print(f"[qa-basics] {msg}", file=sys.stderr, flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    ap.add_argument("--port", type=int, default=9001)
    args = ap.parse_args()
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="streamable-http", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
