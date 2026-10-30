# 0004: The model proposes, a human approves, code writes

**Status:** accepted

## Context
Filing a Jira issue is an external, hard-to-undo action. A model that misclassifies a flaky test as a product bug would spam the tracker, and a prompt-injected log line could ask it to file anything.

## Decision
- No agent has a Jira tool. Agents return `BugProposal` drafts in the contract.
- The interface (Slack) shows each draft with Approve / Skip buttons; only users in `APPROVER_IDS` can approve.
- On Approve, plain code (`qa_shared.jira_client.create_issue`) creates the issue from the stored draft, not from model output generated after the click.
- Jira runs in dry-run (`DRYRUN-xxxxxx` keys) until `JIRA_BASE_URL` and credentials are set; evals never create tickets.
- LangGraph implements the pause with `interrupt()` and a checkpointer; the Agent SDK version keeps drafts in a store keyed by Slack message.

## Consequences
- A wrong classification costs one Skip click, not a ticket.
- Approval latency is human; the agent's run ends at the proposal.
- Evals measure proposal quality (`min_proposals`, `max_proposals`, run ids) without side effects.
