"""
Every tool through a real MCP client (in-memory transport), against mocked DynamoDB + S3 seeded from
the shared fixtures. Vector search is stubbed: moto doesn't emulate S3 Vectors or Bedrock.
"""
import asyncio
import importlib
import json
import runpy
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

SHARED = Path(__file__).resolve().parents[2]
SERVER_DIR = Path(__file__).resolve().parents[1]
KB_BY_WORD = {"Safari": "KB-101", "coupon": "KB-104", "Webhook retry": "KB-107"}   # error text -> KB


@pytest.fixture(scope="module")
def server():
    env = {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x", "AWS_DEFAULT_REGION": "us-east-1",
           "AWS_REGION": "us-east-1", "DDB_ENDPOINT": "aws", "QA_REPORTS_BUCKET": "test-reports"}
    mp = pytest.MonkeyPatch()
    for k, v in env.items():
        mp.setenv(k, v)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        runpy.run_path(str(SHARED / "data" / "seed_qa_table.py"))["seed"](ddb)
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-reports")
        runpy.run_path(str(SHARED / "data" / "upload_reports.py"))["upload"](s3, "test-reports")
        sys.path.insert(0, str(SERVER_DIR))
        srv = importlib.import_module("server")
        # stand-in for Bedrock + S3 Vectors: match on words in the searched text, else a near miss
        srv._search = lambda text, top_k=3, team=None: [
            {"id": next((kb for w, kb in KB_BY_WORD.items() if w in text), "KB-109"), "distance": 0.3, "text": "stub"}
        ][:top_k]
        yield srv
    mp.undo()


def call(srv, name, args=None):
    from mcp import Client

    async def go():
        async with Client(srv.mcp) as c:
            return await c.call_tool(name, args or {})
    return asyncio.run(go())


def data(result):
    assert not result.is_error, result.content[0].text
    return result.structured_content["result"]


def test_tool_list_and_descriptions(server):
    from mcp import Client

    async def go():
        async with Client(server.mcp) as c:
            return (await c.list_tools()).tools
    tools = {t.name: t for t in asyncio.run(go())}
    assert set(tools) == {"list_runs", "failed_cases", "failure_log", "open_flaky_tests", "semantic_search",
                          "report_link"}
    assert all(len(t.description) > 40 for t in tools.values())          # the model reads these
    assert tools["failed_cases"].input_schema["required"] == ["run_id"]


def test_list_runs_newest_first_with_numbers(server):
    runs = data(call(server, "list_runs", {"project": "checkout", "limit": 4}))
    assert [r["runId"] for r in runs] == ["r48", "r45", "r42", "r41"]
    assert isinstance(runs[0]["failed"], int)                           # not the string "1"


def test_failed_cases_attach_known_issues(server):
    cases = data(call(server, "failed_cases", {"run_id": "r42"}))
    assert sorted(c["testName"] for c in cases) == ["apply_coupon", "login_safari"]
    assert {c["testName"]: c["knownIssues"][0]["id"] for c in cases} == {"apply_coupon": "KB-104",
                                                                          "login_safari": "KB-101"}


def test_clean_run_returns_empty_list(server):
    assert data(call(server, "failed_cases", {"run_id": "r46"})) == []


def test_failure_log(server):
    r = call(server, "failure_log", {"run_id": "r50", "test_name": "refund_partial"})
    assert not r.is_error and "ledger shows 149.99 MXN" in r.content[0].text
    passed = call(server, "failure_log", {"run_id": "r50", "test_name": "process_payment_card"})
    assert passed.is_error and "there is no failure log" in passed.content[0].text


def test_open_flaky_tests(server):
    flaky = data(call(server, "open_flaky_tests"))
    assert [f["testName"] for f in flaky] == ["payment_webhook_retry", "login_safari", "search_autocomplete"]
    assert flaky[2]["durationMs"] == 120000 and flaky[2]["lastRunId"] == "r43"
    assert all("knownIssues" in f for f in flaky)


def test_report_link(server):
    ok = call(server, "report_link", {"s3_key": "runs/r44/summary.json"})
    assert not ok.is_error and "runs/r44/summary.json" in ok.content[0].text
    for bad in ("secrets/x", "runs/../secrets/x"):
        r = call(server, "report_link", {"s3_key": bad})
        assert r.is_error and "Only keys under runs/" in r.content[0].text   # ToolError text reaches the model


def test_resource_includes_logs(server):
    from mcp import Client

    async def go():
        async with Client(server.mcp) as c:
            return await c.read_resource("runs://r42/summary")
    text = asyncio.run(go()).contents[0].text
    assert json.loads(text)["failed"] == 2 and "Traceback" in text


def test_unreachable_dynamodb_is_reported_readably(server, monkeypatch):
    from botocore.exceptions import EndpointConnectionError

    def boom(**kw):
        raise EndpointConnectionError(endpoint_url="http://localhost:8000")
    monkeypatch.setattr(server.table, "query", boom)
    r = call(server, "list_runs", {"project": "checkout"})
    assert r.is_error and "is the dynamodb-local container running?" in r.content[0].text
