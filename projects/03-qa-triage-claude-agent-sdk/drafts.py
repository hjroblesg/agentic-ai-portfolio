"""
Bug drafts waiting for a human decision in Slack, stored in the QA table:

  PK = DRAFT#<id>   SK = META
  status: PENDING -> APPROVED -> CREATED   (or PENDING -> SKIPPED, or APPROVED -> FAILED)
  expiresAt: epoch seconds; enable DynamoDB TTL on 'expiresAt' to delete old drafts.

claim() is a conditional write, so two clicks on the same button can never both win.
The draft stores the proposal as the agent produced it; on Approve, code files THAT text.
"""
import os
import time
import uuid

import boto3
from botocore.exceptions import ClientError

from qa_shared import BugProposal

TTL_HOURS = 24
_table = None


def table():
    """Created lazily (config read at first use) so tests can set up mocks and env first."""
    global _table
    if _table is None:
        kwargs = {"region_name": os.getenv("AWS_REGION", "us-east-1")}
        endpoint = os.getenv("DDB_ENDPOINT", "http://localhost:8000")
        if endpoint != "aws":
            kwargs["endpoint_url"] = endpoint
        _table = boto3.resource("dynamodb", **kwargs).Table(os.getenv("QA_TABLE", "crash-qa"))
    return _table


def save(bug: BugProposal, *, channel: str, thread_ts: str, requested_by: str) -> str:
    draft_id = uuid.uuid4().hex[:8]
    now = int(time.time())
    table().put_item(Item={
        "PK": f"DRAFT#{draft_id}", "SK": "META", "type": "Draft", "draftId": draft_id, "status": "PENDING",
        "summary": bug.summary[:255],                       # Jira summary limit
        "description": bug.description[:5000],
        "runIds": bug.run_ids, "kbIds": bug.kb_ids,
        "channel": channel, "threadTs": thread_ts, "requestedBy": requested_by,
        "createdAt": now, "expiresAt": now + TTL_HOURS * 3600,
    })
    return draft_id


def to_proposal(item: dict) -> BugProposal:
    return BugProposal(summary=item["summary"], description=item["description"],
                       run_ids=list(item.get("runIds", [])), kb_ids=list(item.get("kbIds", [])))


def load(draft_id: str) -> dict | None:
    return table().get_item(Key={"PK": f"DRAFT#{draft_id}", "SK": "META"}).get("Item")


def claim(draft_id: str, new_status: str, user: str) -> dict | None:
    """PENDING -> new_status (APPROVED or SKIPPED). None if already handled, expired or missing."""
    try:
        return table().update_item(
            Key={"PK": f"DRAFT#{draft_id}", "SK": "META"},
            UpdateExpression="SET #s = :new, decidedBy = :u, decidedAt = :t",
            ConditionExpression="#s = :pending AND expiresAt > :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":new": new_status, ":pending": "PENDING", ":u": user,
                                       ":t": int(time.time())},
            ReturnValues="ALL_NEW")["Attributes"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise


def record_result(draft_id: str, *, issue_key: str | None = None, error: str | None = None) -> None:
    table().update_item(
        Key={"PK": f"DRAFT#{draft_id}", "SK": "META"},
        UpdateExpression="SET #s = :s, issueKey = :k, #e = :e",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={":s": "CREATED" if issue_key else "FAILED", ":k": issue_key or "",
                                   ":e": error or ""})
