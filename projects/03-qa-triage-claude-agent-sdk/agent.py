"""
QA-triage agent on the Claude Agent SDK: a ReAct loop over the shared QA data MCP server.

    triage(TriageRequest) -> TriageResult

- Tools: the qa-data MCP server (shared/mcp-server), started over stdio with ITS OWN interpreter
  (SERVER_PYTHON), so this project never imports mcp 2.x. Read-only; anything else is denied.
- Output: structured output (`output_format`) with the TriageOutput JSON schema, so findings and bug
  proposals come back as data, not prose to parse.
- Bugs: the model only PROPOSES (TriageOutput.proposals). Nothing here writes to Jira; bot.py does that
  after a human click (docs/decisions/0004-human-in-the-loop.md).
- Trace: tools called, tokens, cost and latency come from the SDK messages, never from the model.
"""
import asyncio
import copy
import logging
import os
import time
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, ToolUseBlock, query
from dotenv import load_dotenv

from qa_shared import Trace, TriageOutput, TriageRequest, TriageResult

log = logging.getLogger("qa-agent")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SERVER_DIR = REPO / "shared" / "mcp-server"
load_dotenv(REPO / ".env")              # repo-root .env; variables already set in the shell win

MODEL = os.getenv("TRIAGE_MODEL", "claude-sonnet-5-5")
MAX_PROPOSALS = 3
QA_TOOLS = ["list_runs", "failed_cases", "failure_log", "open_flaky_tests", "semantic_search", "report_link"]
ALLOWED_TOOLS = [f"mcp__qa-data__{t}" for t in QA_TOOLS]
PASS_THROUGH_ENV = ["AWS_PROFILE", "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                    "DDB_ENDPOINT", "QA_TABLE", "QA_REPORTS_BUCKET", "QA_VECTOR_BUCKET", "QA_VECTOR_INDEX"]

SYSTEM_PROMPT = """You are QA-Triage. You explain why nightly test runs failed, using only the qa-data tools.

Procedure
1. Find the runs: use the run ID if given; otherwise list_runs for the project.
2. Call failed_cases for EVERY failed run you discuss. Use failure_log when the error message alone
   doesn't show the cause.
3. Each failed case comes with knownIssues (closest KB entries). Use the top one only when it describes
   the same symptom AND component. Otherwise kb_id is null and you say "no known issue". A similar-sounding
   entry about another browser, endpoint or amount is NOT a match.
4. For flaky-test questions, call open_flaky_tests.
5. For report requests, call report_link and include the returned link.

Categories (one per finding)
- product_bug: the product misbehaves (wrong totals, 5xx errors, login broken for a known product defect).
- test_bug: the test itself is fragile or wrong (stale elements, bad waits, wrong assertion).
- infra: CI runners, containers, image pulls, caches, registries, network.
- flaky: only for tests listed by open_flaky_tests when the user asks about flaky tests.
- unknown: not enough evidence.
A test can be in the flaky registry and still be a product_bug in a given run; mention both.

Findings: one per distinct failing test, with every run ID where it failed, the exact error line(s) as
evidence, and your confidence (0-1).

Bug proposals: ONLY when the user asks to file/create/open a bug, and only for failures with NO known
issue (kb_id null). At most 3. They are drafts that a human approves later; never say a bug was created.

answer: Slack mrkdwn (*bold*, bullets, <url|label> links), under 250 words, citing run IDs and KB IDs.
Never claim a cause that the data or a KB entry doesn't support."""


# --- configuration --------------------------------------------------------------
def server_config() -> dict:
    """stdio MCP server, started with the server's own venv (see docs/decisions/0002)."""
    python = os.getenv("SERVER_PYTHON") or str(SERVER_DIR / ".venv" / "bin" / "python")
    if not Path(python).is_absolute():
        python = str((REPO / python).absolute())
    return {"command": python, "args": [str(SERVER_DIR / "server.py")],
            "env": {k: os.environ[k] for k in PASS_THROUGH_ENV if os.getenv(k)}}   # an empty AWS_PROFILE breaks boto3


def output_schema() -> dict:
    """TriageOutput's JSON schema with $refs inlined and validation-only keywords removed;
    pydantic re-validates the result afterwards, so nothing is lost."""
    schema = TriageOutput.model_json_schema()
    defs = schema.pop("$defs", {})

    def clean(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return clean(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            return {k: clean(v) for k, v in node.items()
                    if k not in ("title", "default", "minimum", "maximum")}
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node
    return clean(schema)


def options() -> ClaudeAgentOptions:
    env = {"ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"]} if os.getenv("ANTHROPIC_API_KEY") else {}
    return ClaudeAgentOptions(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"qa-data": server_config()},
        allowed_tools=ALLOWED_TOOLS,
        permission_mode="dontAsk",           # anything not allowed is denied, never waits for a human
        setting_sources=[],                  # ignore local Claude Code settings, CLAUDE.md, plugins
        output_format={"type": "json_schema", "schema": output_schema()},
        max_turns=20,
        max_budget_usd=0.50,
        env=env,                             # empty = use the Claude Code login
    )


def render_prompt(req: TriageRequest) -> str:
    hints = [f"{k}: {v}" for k, v in (("project", req.project), ("run_id", req.run_id)) if v]
    return req.question + (f"\n\n(Context: {', '.join(hints)})" if hints else "")


# --- run --------------------------------------------------------------------------
def to_result(messages: list, wall_ms: int) -> TriageResult:
    """Build the contract result from the SDK message stream (pure: tested offline)."""
    tools, model, final = [], "", None
    for m in messages:
        if isinstance(m, AssistantMessage):
            model = model or m.model
            tools += [b.name for b in m.content if isinstance(b, ToolUseBlock) and b.name.startswith("mcp__")]
        elif isinstance(m, ResultMessage):
            final = m
    if final is None:
        raise RuntimeError("agent stream ended without a result")
    if final.is_error or final.structured_output is None:
        raise RuntimeError(f"agent finished without structured output ({final.subtype}): "
                           f"{(final.errors or [final.result or ''])[0][:300]}")
    out = TriageOutput.model_validate(final.structured_output)
    out.proposals = out.proposals[:MAX_PROPOSALS]                           # enforced in code, not trusted
    usage = final.usage or {}
    trace = Trace(tools_called=tools,
                  input_tokens=sum(int(usage.get(k) or 0) for k in
                                   ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
                  output_tokens=int(usage.get("output_tokens") or 0),
                  cost_usd=round(final.total_cost_usd or 0.0, 6),
                  latency_ms=final.duration_ms or wall_ms,
                  model=model or MODEL)
    return TriageResult(**out.model_dump(), trace=trace)


async def atriage(req: TriageRequest) -> TriageResult:
    start = time.perf_counter()
    messages = []
    async for m in query(prompt=render_prompt(req), options=options()):
        if isinstance(m, AssistantMessage):
            for b in m.content:
                if isinstance(b, ToolUseBlock):
                    log.info("-> %s %s", b.name, b.input)
        messages.append(m)
    result = to_result(messages, int((time.perf_counter() - start) * 1000))
    log.info("done: tools=%s cost=$%.4f latency=%sms", result.trace.tools_called, result.trace.cost_usd,
             result.trace.latency_ms)
    return result


def triage(req: TriageRequest) -> TriageResult:
    return asyncio.run(atriage(req))


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    question = " ".join(sys.argv[1:]) or "Why did run r50 fail?"
    print(triage(TriageRequest(question=question)).model_dump_json(indent=2))
