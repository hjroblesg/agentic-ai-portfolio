"""Slack handlers + drafts against mocked DynamoDB and a fake Slack client. No network."""
import sys

import boto3
import pytest
from moto import mock_aws

import bot
import drafts
from qa_shared import BugProposal, Trace, TriageResult

BUG = BugProposal(summary="Refund ledger off by 0.01 MXN", description="refund 150.00 expected, 149.99",
                  run_ids=["r50"], kb_ids=[])


class FakeClient:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda **kw: self.calls.append((name, kw))

    def named(self, name):
        return [kw for n, kw in self.calls if n == name]


class Logger:
    def warning(self, *a): pass
    def exception(self, *a): pass


@pytest.fixture
def table(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x", "AWS_REGION": "us-east-1",
                 "DDB_ENDPOINT": "aws", "QA_TABLE": "test-qa"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("JIRA_BASE_URL", raising=False)                 # dry-run Jira
    monkeypatch.delenv("APPROVER_IDS", raising=False)
    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName="test-qa", BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"}])
        drafts._table = None
        yield drafts.table()
        drafts._table = None


def mention(client, triage, said):
    event = {"channel": "C1", "ts": "111.1", "user": "U_ASKER", "text": "<@U0BOT> why did r50 fail?"}
    bot.handle_mention(event, lambda **kw: said.append(kw), client, Logger(), triage=triage)


def click(handler, client, draft_id, user="U_APPROVER"):
    body = {"user": {"id": user}, "channel": {"id": "C1"}, "message": {"ts": "222.2"},
            "actions": [{"value": draft_id}]}
    handler(lambda: None, body, client, Logger())


def test_mention_posts_answer_then_one_approval_per_proposal(table):
    client, said, asked = FakeClient(), [], []

    def triage(req):
        asked.append(req.question)
        return TriageResult(answer="r50: KB-103 + one new bug", proposals=[BUG], trace=Trace())
    mention(client, triage, said)
    assert asked == ["why did r50 fail?"]
    assert said == [{"text": "r50: KB-103 + one new bug", "thread_ts": "111.1"}]
    [post] = client.named("chat_postMessage")
    draft_id = post["blocks"][-1]["elements"][0]["value"]
    assert drafts.load(draft_id)["status"] == "PENDING" and drafts.load(draft_id)["requestedBy"] == "U_ASKER"


def test_agent_failure_is_reported_in_thread(table):
    said = []

    def triage(req):
        raise RuntimeError("boom")
    mention(FakeClient(), triage, said)
    assert "RuntimeError" in said[0]["text"]


def test_approve_creates_once_in_dry_run(table):
    draft_id = drafts.save(BUG, channel="C1", thread_ts="111.1", requested_by="U_ASKER")
    client = FakeClient()
    click(bot.handle_approve, client, draft_id)
    click(bot.handle_approve, client, draft_id, user="U_OTHER")      # second click loses the race
    [update] = client.named("chat_update")
    assert "DRYRUN-" in update["text"] and "<@U_APPROVER>" in update["text"]
    assert client.named("chat_postEphemeral")[0]["text"] == bot.ALREADY_HANDLED
    item = drafts.load(draft_id)
    assert item["status"] == "CREATED" and item["issueKey"].startswith("DRYRUN-")


def test_only_listed_approvers(table, monkeypatch):
    monkeypatch.setenv("APPROVER_IDS", "U_LEAD")
    draft_id = drafts.save(BUG, channel="C1", thread_ts="111.1", requested_by="U_ASKER")
    client = FakeClient()
    click(bot.handle_approve, client, draft_id, user="U_RANDOM")
    assert "approvers list" in client.named("chat_postEphemeral")[0]["text"]
    assert drafts.load(draft_id)["status"] == "PENDING"


def test_jira_error_marks_draft_failed(table, monkeypatch):
    def fail(*a):
        raise RuntimeError("Jira 400: project QA not found")
    monkeypatch.setattr(bot.jira_client, "create_issue", fail)
    draft_id = drafts.save(BUG, channel="C1", thread_ts="111.1", requested_by="U_ASKER")
    client = FakeClient()
    click(bot.handle_approve, client, draft_id)
    assert "Couldn't create" in client.named("chat_update")[0]["text"]
    assert drafts.load(draft_id)["status"] == "FAILED"


def test_skip(table):
    draft_id = drafts.save(BUG, channel="C1", thread_ts="111.1", requested_by="U_ASKER")
    client = FakeClient()
    click(bot.handle_skip, client, draft_id)
    assert "Skipped by <@U_APPROVER>" in client.named("chat_update")[0]["text"]
    assert drafts.load(draft_id)["status"] == "SKIPPED"


def test_expired_draft_cannot_be_claimed(table):
    draft_id = drafts.save(BUG, channel="C1", thread_ts="111.1", requested_by="U_ASKER")
    table.update_item(Key={"PK": f"DRAFT#{draft_id}", "SK": "META"}, UpdateExpression="SET expiresAt = :e",
                      ExpressionAttributeValues={":e": 1})
    assert drafts.claim(draft_id, "APPROVED", "U1") is None


@pytest.mark.parametrize("text,q", [("<@U0BOT> why r50?", "why r50?"), ("plain question", "plain question")])
def test_question_from(text, q):
    assert bot.question_from(text) == q


def test_adapter_prints_only_the_result(monkeypatch, tmp_path, capsys):
    import adapter
    req = tmp_path / "req.json"
    req.write_text('{"question": "why r50?", "run_id": "r50"}')
    monkeypatch.setattr(adapter.agent, "triage", lambda r: TriageResult(answer=f"got {r.run_id}"))
    monkeypatch.setattr(sys, "argv", ["adapter.py", "--request", str(req)])
    adapter.main()
    assert TriageResult.model_validate_json(capsys.readouterr().out).answer == "got r50"
