"""
The only code that writes to Jira. Called after a human approves, never by the model.

DRY-RUN unless JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN are all set: nothing is sent and a fake
key like DRYRUN-1a2b3c is returned, so the whole flow can be demoed without a Jira site.
Configuration is read at call time, so tests and scripts can change the environment.
"""
import os
import uuid

import requests


def _config() -> tuple[str, tuple[str, str], str]:
    return (os.getenv("JIRA_BASE_URL", "").rstrip("/"),
            (os.getenv("JIRA_EMAIL", ""), os.getenv("JIRA_API_TOKEN", "")),
            os.getenv("JIRA_PROJECT", "QA"))


def is_dry_run() -> bool:
    base, auth, _ = _config()
    return not (base and all(auth))


def issue_url(key: str) -> str | None:
    base, _, _ = _config()
    return None if is_dry_run() else f"{base}/browse/{key}"


def adf(description: str, run_ids: list[str], kb_ids: list[str]) -> dict:
    """Atlassian Document Format: one paragraph per line, then an evidence list."""
    content = [{"type": "paragraph", "content": [{"type": "text", "text": line}]}
               for line in description.split("\n") if line.strip()]
    evidence = [f"Runs: {', '.join(run_ids)}" if run_ids else None,
                f"Known issues: {', '.join(kb_ids)}" if kb_ids else None,
                "Drafted by a QA-Triage agent, approved by a human"]
    content.append({"type": "bulletList", "content": [
        {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": e}]}]}
        for e in evidence if e]})
    return {"type": "doc", "version": 1, "content": content}


def create_issue(summary: str, description: str, run_ids: list[str], kb_ids: list[str]) -> str:
    if is_dry_run():
        return f"DRYRUN-{uuid.uuid4().hex[:6]}"
    base, auth, project = _config()
    body = {"fields": {"project": {"key": project}, "issuetype": {"name": "Bug"}, "summary": summary,
                       "description": adf(description, run_ids, kb_ids),
                       "labels": ["from-agent"] + [k.lower() for k in kb_ids]}}
    r = requests.post(f"{base}/rest/api/3/issue", json=body, auth=auth, timeout=20,
                      headers={"Accept": "application/json", "Content-Type": "application/json"})
    if r.status_code >= 400:
        raise RuntimeError(f"Jira {r.status_code}: {r.text[:300]}")
    return r.json()["key"]
