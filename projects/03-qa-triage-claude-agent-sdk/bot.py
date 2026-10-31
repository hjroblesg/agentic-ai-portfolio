"""
Slack interface for the QA-triage agent, with human-in-the-loop bug filing.

  @mention -> agent.triage() -> answer posted in the thread
           -> each BugProposal saved as a DRAFT (drafts.py) and shown with [Create in Jira] [Skip]
  click    -> claim the draft atomically -> qa_shared.jira_client.create_issue() -> outcome replaces buttons

The agent has no write tools. Jira is written here, from the stored draft, after a person clicks.

Run:  make run   (needs SLACK_BOT_TOKEN, SLACK_APP_TOKEN; optional JIRA_*, APPROVER_IDS=U123,U456)
Slack scopes: app_mentions:read, chat:write, reactions:write. Socket Mode on (enables interactivity).
"""
import logging
import os

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from qa_shared import TriageRequest, jira_client
from qa_shared.slack_client import approval_blocks, created_text, outcome_blocks, skipped_text

import agent
import drafts

log = logging.getLogger("qa-bot")
ALREADY_HANDLED = "This draft was already handled or has expired."


def approvers() -> set[str]:
    return {u.strip() for u in os.getenv("APPROVER_IDS", "").split(",") if u.strip()}


def question_from(text: str) -> str:
    """'<@U0BOT> why did r50 fail?' -> 'why did r50 fail?'"""
    return text.split(">", 1)[-1].strip() if text.lstrip().startswith("<@") else text.strip()


# --- handlers (plain functions: tests call them with fake Slack clients) ---------------
def handle_mention(event, say, client, logger, triage=agent.triage):
    thread = event.get("thread_ts", event["ts"])
    try:
        client.reactions_add(channel=event["channel"], timestamp=event["ts"], name="eyes")
    except Exception as e:                                       # missing reactions:write is not fatal
        logger.warning(f"reaction failed: {e}")
    try:
        result = triage(TriageRequest(question=question_from(event["text"])))
    except Exception as e:
        logger.exception("agent failed")
        say(text=f":warning: Something went wrong while answering: `{type(e).__name__}`", thread_ts=thread)
        return
    say(text=result.answer, thread_ts=thread)
    for bug in result.proposals:
        draft_id = drafts.save(bug, channel=event["channel"], thread_ts=thread, requested_by=event.get("user", ""))
        client.chat_postMessage(channel=event["channel"], thread_ts=thread,
                                text=f"Proposed bug: {bug.summary} (needs approval)",
                                blocks=approval_blocks(bug, value=draft_id))


def _replace_buttons(client, body, text: str) -> None:
    client.chat_update(channel=body["channel"]["id"], ts=body["message"]["ts"], text=text,
                       blocks=outcome_blocks(text))


def _ephemeral(client, body, text: str) -> None:
    client.chat_postEphemeral(channel=body["channel"]["id"], user=body["user"]["id"], text=text)


def handle_approve(ack, body, client, logger):
    ack()                                                        # Slack needs this within 3 s
    user, draft_id = body["user"]["id"], body["actions"][0]["value"]
    allowed = approvers()
    if allowed and user not in allowed:
        _ephemeral(client, body, "You're not on the approvers list for bug creation.")
        return
    item = drafts.claim(draft_id, "APPROVED", user)
    if item is None:                                             # double click, other approver, or expired
        _ephemeral(client, body, ALREADY_HANDLED)
        return
    bug = drafts.to_proposal(item)
    try:
        key = jira_client.create_issue(bug.summary, bug.description, bug.run_ids, bug.kb_ids)
    except Exception as e:
        logger.exception("jira create failed")
        drafts.record_result(draft_id, error=str(e))
        _replace_buttons(client, body, f":x: Couldn't create the issue: {str(e)[:200]}")
        return
    drafts.record_result(draft_id, issue_key=key)
    _replace_buttons(client, body, created_text(key, jira_client.issue_url(key), bug.summary, user))


def handle_skip(ack, body, client, logger):
    ack()
    user = body["user"]["id"]
    item = drafts.claim(body["actions"][0]["value"], "SKIPPED", user)
    if item is None:
        _ephemeral(client, body, ALREADY_HANDLED)
        return
    _replace_buttons(client, body, skipped_text(item["summary"], user))


def build_app() -> App:
    app = App(token=os.environ["SLACK_BOT_TOKEN"])
    app.event("app_mention")(handle_mention)
    app.action("approve_bug")(handle_approve)
    app.action("skip_bug")(handle_skip)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log.info("model=%s jira=%s approvers=%s", agent.MODEL,
             "DRY RUN" if jira_client.is_dry_run() else os.getenv("JIRA_BASE_URL"), approvers() or "anyone")
    SocketModeHandler(build_app(), os.environ["SLACK_APP_TOKEN"]).start()
