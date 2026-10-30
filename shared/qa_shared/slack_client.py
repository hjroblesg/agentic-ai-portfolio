"""
Slack message FORMATTING shared by every bot (pure functions, no Slack SDK dependency).
The handlers themselves stay in each project: how approval works (drafts + claim, a paused graph,
an AgentCore session...) is part of what each implementation demonstrates.
"""
from .contracts import BugProposal


def link(url: str | None, label: str) -> str:
    """Slack mrkdwn link (Slack doesn't render Markdown [label](url))."""
    return f"<{url}|{label}>" if url else label


def approval_blocks(bug: BugProposal, *, value: str, approve_action: str = "approve_bug",
                    skip_action: str = "skip_bug", note: str = "Draft expires in 24 h") -> list[dict]:
    """Block Kit message proposing a bug, with Create / Skip buttons. `value` identifies the draft."""
    desc = bug.description if len(bug.description) < 600 else bug.description[:600] + "…"
    evidence = " · ".join(filter(None, [
        f"Runs: {', '.join(bug.run_ids)}" if bug.run_ids else "",
        f"Known issues: {', '.join(bug.kb_ids)}" if bug.kb_ids else "",
        note]))
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": f":memo: *Proposed bug:* {bug.summary}\n>{desc}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": evidence}]},
        {"type": "actions", "elements": [
            {"type": "button", "style": "primary", "action_id": approve_action, "value": value,
             "text": {"type": "plain_text", "text": "Create in Jira"}},
            {"type": "button", "action_id": skip_action, "value": value,
             "text": {"type": "plain_text", "text": "Skip"}}]},
    ]


def outcome_blocks(text: str) -> list[dict]:
    """Replaces the buttons once decided, so nobody can click twice."""
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def created_text(key: str, url: str | None, summary: str, user_id: str) -> str:
    label = link(url, key) if url else f"`{key}` (dry run, Jira not configured)"
    return f":white_check_mark: Created {label}: {summary}. Approved by <@{user_id}>"


def skipped_text(summary: str, user_id: str) -> str:
    return f":no_entry_sign: Skipped by <@{user_id}>: {summary}"
