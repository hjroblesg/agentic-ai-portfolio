"""Agent wiring, offline: options, schema, and the SDK message stream -> TriageResult conversion."""
import asyncio
import json

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

import agent
from qa_shared import TriageRequest

GOOD = {
    "answer": "*r50*: `process_payment_high_load` matches KB-103; `refund_partial` has no known issue.",
    "findings": [
        {"test_name": "process_payment_high_load", "run_ids": ["r50"], "category": "product_bug",
         "kb_id": "KB-103", "confidence": 0.9, "evidence": ["HTTPError 502 Bad Gateway"]},
        {"test_name": "refund_partial", "run_ids": ["r50"], "category": "product_bug", "kb_id": None,
         "confidence": 0.8, "evidence": ["ledger shows 149.99 MXN"]}],
    "proposals": [{"summary": f"Refund off by 0.01 #{i}", "description": "d", "run_ids": ["r50"]} for i in range(5)],
}


def stream(structured=GOOD, **result_kw):
    return [
        AssistantMessage(content=[TextBlock("Checking."), ToolUseBlock("1", "mcp__qa-data__failed_cases",
                                                                       {"run_id": "r50"})], model="claude-test"),
        AssistantMessage(content=[ToolUseBlock("2", "mcp__qa-data__semantic_search", {"text": "502"}),
                                  ToolUseBlock("3", "StructuredOutput", {})], model="claude-test"),
        ResultMessage(**{"subtype": "success", "duration_ms": 4200, "duration_api_ms": 3000, "is_error": False,
                         "num_turns": 3, "session_id": "s", "total_cost_usd": 0.0123,
                         "usage": {"input_tokens": 100, "cache_read_input_tokens": 900,
                                   "cache_creation_input_tokens": 50, "output_tokens": 300},
                         "structured_output": structured, **result_kw}),
    ]


def test_to_result_builds_contract_and_trace():
    r = agent.to_result(stream(), wall_ms=9999)
    assert r.trace.tools_called == ["mcp__qa-data__failed_cases", "mcp__qa-data__semantic_search"]  # MCP only
    assert (r.trace.input_tokens, r.trace.output_tokens) == (1050, 300)
    assert r.trace.cost_usd == 0.0123 and r.trace.latency_ms == 4200 and r.trace.model == "claude-test"
    assert r.findings[1].kb_id is None
    assert len(r.proposals) == agent.MAX_PROPOSALS                     # capped in code


@pytest.mark.parametrize("kw,msg", [
    ({"structured": None}, "without structured output"),
    ({"is_error": True, "subtype": "error_max_budget_usd", "errors": ["budget"]}, "error_max_budget_usd"),
])
def test_to_result_errors(kw, msg):
    with pytest.raises(RuntimeError, match=msg):
        agent.to_result(stream(**kw), wall_ms=1)


def test_invalid_structured_output_is_rejected():
    bad = {**GOOD, "findings": [{**GOOD["findings"][0], "category": "probably_fine"}]}
    with pytest.raises(ValueError):
        agent.to_result(stream(bad), wall_ms=1)


def test_output_schema_is_self_contained():
    s = agent.output_schema()
    text = json.dumps(s)
    assert "$ref" not in text and "$defs" not in text and "minimum" not in text
    finding = s["properties"]["findings"]["items"]
    assert finding["properties"]["category"]["enum"][0] == "product_bug"
    assert "kb_id" in finding["required"]                              # explicit null, never omitted


def test_options_are_read_only_and_bounded(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    o = agent.options()
    assert o.allowed_tools == [f"mcp__qa-data__{t}" for t in agent.QA_TOOLS]
    assert not any("bug" in t or "jira" in t for t in o.allowed_tools)
    assert o.permission_mode == "dontAsk" and o.setting_sources == [] and o.env == {}
    assert o.max_budget_usd <= 1 and o.output_format["type"] == "json_schema"


def test_server_env_passes_only_set_values(monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "")                              # empty would break boto3
    monkeypatch.setenv("QA_TABLE", "t1")
    monkeypatch.setenv("SERVER_PYTHON", "shared/mcp-server/.venv/bin/python")
    cfg = agent.server_config()
    assert "AWS_PROFILE" not in cfg["env"] and cfg["env"]["QA_TABLE"] == "t1"
    assert cfg["command"].startswith(str(agent.REPO)) and cfg["args"][0].endswith("shared/mcp-server/server.py")


def test_atriage_uses_query_stream(monkeypatch):
    seen = {}

    async def fake_query(*, prompt, options):
        seen["prompt"] = prompt
        for m in stream():
            yield m
    monkeypatch.setattr(agent, "query", fake_query)
    r = asyncio.run(agent.atriage(TriageRequest(question="Why did r50 fail?", run_id="r50")))
    assert "run_id: r50" in seen["prompt"] and r.findings[0].kb_id == "KB-103"
