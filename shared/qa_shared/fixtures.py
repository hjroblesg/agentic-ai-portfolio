"""
Load and validate the synthetic fixtures (shared/data/fixtures), the single source of truth for
seed data, unit tests and evals. Also builds the DynamoDB items and S3 reports from them.

Fixtures directory: $QA_FIXTURES_DIR, else shared/data/fixtures next to this package
(works with `pip install -e shared`).
"""
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, model_validator

from .contracts import Category


def fixtures_dir() -> Path:
    return Path(os.getenv("QA_FIXTURES_DIR") or Path(__file__).resolve().parents[1] / "data" / "fixtures")


# --- models -------------------------------------------------------------------
class Case(BaseModel):
    test: str
    status: Literal["PASSED", "FAILED"]
    executed_at: str
    duration_ms: int
    failure: Optional[str] = None


class Run(BaseModel):
    run_id: str
    project: str
    pipeline: str
    executed_at: str
    duration_ms: int
    cases: list[Case]

    @property
    def failed(self) -> list[Case]:
        return [c for c in self.cases if c.status == "FAILED"]


class Expected(BaseModel):
    category: Category
    kb_id: Optional[str]


class Failure(BaseModel):
    id: str
    run_id: str
    test_name: str
    error_message: str
    log: str
    expected: Expected


class Flaky(BaseModel):
    test: str
    project: str
    status: Literal["OPEN", "CLOSED"]
    last_seen: str
    last_run_id: Optional[str]
    occurrences: int
    duration_ms: int
    note: str


class KnownIssue(BaseModel):
    id: str
    team: str
    severity: int
    kind: Literal["match", "near_miss", "distractor"]
    text: str


class Fixtures(BaseModel):
    runs: list[Run]
    failures: list[Failure]
    flaky: list[Flaky]
    known_issues: list[KnownIssue]

    @model_validator(mode="after")
    def _consistent(self):
        fail_ids = {f.id for f in self.failures}
        kb_ids = {k.id for k in self.known_issues}
        for run in self.runs:
            for c in run.cases:
                if (c.status == "FAILED") != bool(c.failure):
                    raise ValueError(f"{run.run_id}/{c.test}: FAILED cases (and only those) need a failure id")
                if c.failure and c.failure not in fail_ids:
                    raise ValueError(f"{run.run_id}/{c.test}: unknown failure id {c.failure}")
        for f in self.failures:
            if f.expected.kb_id and f.expected.kb_id not in kb_ids:
                raise ValueError(f"{f.id}: expected kb_id {f.expected.kb_id} not in kb.yaml")
        return self

    # lookups
    def failure(self, failure_id: str) -> Failure:
        return next(f for f in self.failures if f.id == failure_id)

    def run(self, run_id: str) -> Run:
        return next(r for r in self.runs if r.run_id == run_id)


def _read(name: str, key: str) -> list:
    with open(fixtures_dir() / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)[key]


@lru_cache(maxsize=1)
def load_fixtures() -> Fixtures:
    return Fixtures(runs=_read("runs.yaml", "runs"), failures=_read("failures.yaml", "failures"),
                    flaky=_read("flaky.yaml", "flaky"), known_issues=_read("kb.yaml", "known_issues"))


def load_kb_search_eval() -> list[dict]:
    return _read("kb_search_eval.yaml", "queries")


# --- builders -----------------------------------------------------------------
def to_dynamodb_items(fx: Fixtures) -> list[dict]:
    """Single-table design (Day 2): Run, Case and Flaky items with PK/SK and GSI1."""
    items: list[dict] = []
    for run in fx.runs:
        failed = run.failed
        item = {"PK": f"PROJECT#{run.project}", "SK": f"RUN#{run.executed_at}#{run.run_id}",
                "GSI1PK": f"RUN#{run.run_id}", "GSI1SK": "META", "type": "Run", "runId": run.run_id,
                "project": run.project, "status": "FAILED" if failed else "PASSED",
                "executedAt": run.executed_at, "durationMs": run.duration_ms, "total": len(run.cases),
                "passed": len(run.cases) - len(failed), "failed": len(failed), "pipeline": run.pipeline,
                "reportS3Key": f"runs/{run.run_id}/summary.json"}
        if failed:
            item["errorMessage"] = f"{len(failed)} failed: " + "; ".join(c.test for c in failed)
        items.append(item)
        for c in run.cases:
            case = {"PK": f"RUN#{run.run_id}", "SK": f"CASE#{c.test}#{c.status}", "type": "Case",
                    "runId": run.run_id, "project": run.project, "testName": c.test, "status": c.status,
                    "executedAt": c.executed_at, "durationMs": c.duration_ms}
            if c.failure:
                case["errorMessage"] = fx.failure(c.failure).error_message
                case["retries"] = 1
            items.append(case)
    for f in fx.flaky:
        item = {"PK": f"PROJECT#{f.project}", "SK": f"FLAKY#{f.test}", "GSI1PK": f"FLAKY#{f.status}",
                "GSI1SK": f.last_seen, "type": "Flaky", "project": f.project, "testName": f.test,
                "status": f.status, "executedAt": f"{f.last_seen}T02:00:00Z", "durationMs": f.duration_ms,
                "errorMessage": f.note, "occurrences": f.occurrences, "version": 1}
        if f.last_run_id:
            item["lastRunId"] = f.last_run_id
        items.append(item)
    return items


def run_report(fx: Fixtures, run_id: str) -> dict:
    """The JSON report stored at runs/<run_id>/summary.json, including failure logs."""
    run = fx.run(run_id)
    failed = run.failed
    return {"runId": run.run_id, "project": run.project, "pipeline": run.pipeline,
            "status": "FAILED" if failed else "PASSED", "executedAt": run.executed_at,
            "durationMs": run.duration_ms, "total": len(run.cases), "passed": len(run.cases) - len(failed),
            "failed": len(failed),
            "cases": [{"testName": c.test, "status": c.status, "durationMs": c.duration_ms,
                       **({"errorMessage": fx.failure(c.failure).error_message,
                           "log": fx.failure(c.failure).log} if c.failure else {})}
                      for c in run.cases]}
