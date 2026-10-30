import pytest

from qa_shared import BugProposal, jira_client, slack_client


@pytest.fixture
def no_jira(monkeypatch):
    for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def jira(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net/")
    monkeypatch.setenv("JIRA_EMAIL", "bot@example.test")
    monkeypatch.setenv("JIRA_API_TOKEN", "t")


def test_dry_run_by_default(no_jira):
    assert jira_client.is_dry_run()
    assert jira_client.create_issue("s", "d", ["r50"], []).startswith("DRYRUN-")
    assert jira_client.issue_url("QA-1") is None


def test_real_mode_sends_adf_and_labels(jira, monkeypatch):
    sent = {}

    class Resp:
        status_code = 201
        text = ""
        @staticmethod
        def json(): return {"key": "QA-7"}

    monkeypatch.setattr(jira_client.requests, "post", lambda url, **kw: sent.update(url=url, **kw) or Resp())
    assert jira_client.create_issue("Sum", "line1\nline2", ["r50"], ["KB-103"]) == "QA-7"
    fields = sent["json"]["fields"]
    assert sent["url"] == "https://example.atlassian.net/rest/api/3/issue"
    assert fields["description"]["type"] == "doc" and len(fields["description"]["content"]) == 3
    assert fields["labels"] == ["from-agent", "kb-103"]
    assert jira_client.issue_url("QA-7") == "https://example.atlassian.net/browse/QA-7"


def test_real_mode_raises_readable_error(jira, monkeypatch):
    class Resp:
        status_code = 401
        text = "Unauthorized"
    monkeypatch.setattr(jira_client.requests, "post", lambda url, **kw: Resp())
    with pytest.raises(RuntimeError, match="Jira 401"):
        jira_client.create_issue("s", "d", [], [])


def test_approval_blocks_and_outcomes():
    bug = BugProposal(summary="Refund off by 0.01", description="x" * 700, run_ids=["r50"], kb_ids=[])
    blocks = slack_client.approval_blocks(bug, value="draft-1")
    buttons = blocks[-1]["elements"]
    assert [b["action_id"] for b in buttons] == ["approve_bug", "skip_bug"]
    assert all(b["value"] == "draft-1" for b in buttons)
    assert blocks[0]["text"]["text"].endswith("…")                         # long descriptions truncated
    assert "dry run" in slack_client.created_text("DRYRUN-1", None, "s", "U1")
    assert "<https://x/QA-1|QA-1>" in slack_client.created_text("QA-1", "https://x/QA-1", "s", "U1")
    assert slack_client.link("https://x", "label") == "<https://x|label>"
