"""The server through the SDK client (in-process) and through raw JSON-RPC over a real stdio subprocess."""
import asyncio
import json

from mcp import Client

import raw_client
import sdk_client
import server


def call(fn):
    async def go():
        async with Client(server.mcp) as c:
            return await fn(c)
    return asyncio.run(go())


def test_schema_is_generated_from_type_hints_and_docstrings():
    tools = {t.name: t for t in call(lambda c: c.list_tools()).tools}
    assert set(tools) == {"list_runs", "failed_cases"}
    runs = tools["list_runs"].input_schema
    assert runs["required"] == ["project"]                               # limit has a default
    assert runs["properties"]["project"]["enum"] == ["checkout", "search", "payments"]   # from Literal
    assert tools["failed_cases"].description.startswith("Failed test cases of one run")  # from docstring


def test_structured_and_text_content():
    r = call(lambda c: c.call_tool("list_runs", {"project": "checkout", "limit": 2}))
    assert not r.is_error
    assert [x["run_id"] for x in r.structured_content["result"]] == ["r48", "r45"]
    assert "r48" in r.content[0].text                                  # what a text-only host shows the model


def test_tool_error_message_reaches_the_model():
    r = call(lambda c: c.call_tool("failed_cases", {"run_id": "r99"}))
    assert r.is_error and "Unknown run 'r99'" in r.content[0].text


def test_invalid_arguments_are_rejected_by_the_schema():
    r = call(lambda c: c.call_tool("list_runs", {"project": "billing"}))
    assert r.is_error


def test_resource_and_prompt():
    res = call(lambda c: c.read_resource("runs://r46"))
    assert json.loads(res.contents[0].text)["run_id"] == "r46"
    prompt = call(lambda c: c.get_prompt("triage_run", {"run_id": "r50"}))
    assert "run r50" in prompt.messages[0].content.text


def test_raw_json_rpc_over_stdio():
    seen = []
    replies = raw_client.session(show=lambda d, m: seen.append((d, m)))
    assert replies["initialize"]["result"]["serverInfo"]["name"] == "qa-basics"
    assert "protocolVersion" in replies["initialize"]["result"]            # negotiated by the server
    assert [t["name"] for t in replies["tools/list"]["result"]["tools"]] == ["list_runs", "failed_cases"]
    ok = replies["call_ok"]["result"]
    assert ok["isError"] is False and ok["structuredContent"]["result"][1]["test_name"] == "refund_partial"
    assert replies["call_error"]["result"]["isError"] is True
    # the notification was sent and got no reply: every reply id matches a request id
    sent_ids = {m["id"] for d, m in seen if d == "→" and "id" in m}
    assert {m["id"] for d, m in seen if d == "←" and "id" in m} <= sent_ids
    assert any(m.get("method") == "notifications/initialized" and "id" not in m for d, m in seen if d == "→")


def test_sdk_client_in_process():
    out = asyncio.run(sdk_client.demo(server.mcp))
    assert out["tools"] == ["list_runs", "failed_cases"] and out["error"][0] is True
