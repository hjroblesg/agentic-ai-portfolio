"""
Two tools over the synthetic fixtures (no AWS, no database): what the model sees and what actually runs.

A tool is three things:
  1. a NAME the model calls it by,
  2. a DESCRIPTION the model reads to decide when to call it (this is prompt text: write it carefully),
  3. an INPUT SCHEMA (JSON Schema) the model's arguments must follow.
The model never runs anything. It returns a `tool_use` block; YOUR code runs the function and sends back
a `tool_result`.
"""
import json

from qa_shared.fixtures import load_fixtures

TOOLS = [
    {
        "name": "list_runs",
        "description": ("List recent nightly test runs for one project, newest first, with pass/fail counts. "
                        "Use it to find which runs failed before asking for their failed cases."),
        "input_schema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "enum": ["checkout", "search", "payments"]},
                "limit": {"type": "integer", "description": "Max runs to return (1-10)", "default": 5},
            },
            "required": ["project"],
        },
    },
    {
        "name": "failed_cases",
        "description": ("Failed test cases of one run, with the error message of each. "
                        "An empty list means the run was clean."),
        "input_schema": {
            "type": "object",
            "properties": {"run_id": {"type": "string", "description": "A run id such as r42"}},
            "required": ["run_id"],
        },
    },
]


class ToolInputError(ValueError):
    """Bad arguments from the model. Sent back as is_error=true so the model can correct itself."""


def list_runs(project: str, limit: int = 5) -> list[dict]:
    runs = [r for r in load_fixtures().runs if r.project == project]
    if not runs:
        raise ToolInputError(f"Unknown project {project!r}. Use checkout, search or payments.")
    runs.sort(key=lambda r: r.executed_at, reverse=True)
    return [{"run_id": r.run_id, "executed_at": r.executed_at, "total": len(r.cases), "failed": len(r.failed)}
            for r in runs[:max(1, min(int(limit), 10))]]


def failed_cases(run_id: str) -> list[dict]:
    fx = load_fixtures()
    try:
        run = fx.run(run_id)
    except StopIteration:
        raise ToolInputError(f"Unknown run {run_id!r}. Call list_runs to see valid run ids.") from None
    return [{"test_name": c.test, "error_message": fx.failure(c.failure).error_message} for c in run.failed]


IMPLEMENTATIONS = {"list_runs": list_runs, "failed_cases": failed_cases}


def run_tool(name: str, args: dict) -> tuple[str, bool]:
    """Execute one tool call. Returns (content for the tool_result, is_error)."""
    fn = IMPLEMENTATIONS.get(name)
    if fn is None:
        return f"Unknown tool {name!r}.", True
    try:
        return json.dumps(fn(**args)), False
    except (ToolInputError, TypeError) as e:          # TypeError: missing or unexpected arguments
        return str(e), True
