"""
Reference adapter that answers from the fixtures' ANSWER KEY, with no model and no AWS.

Two jobs:
  1. Self-check for the scorer: `make eval-oracle` must score 100%. If it doesn't, the bug is in
     cases.yaml or run_evals.py, not in an agent.
  2. Template for real adapters: copy the protocol (argparse --request, print one TriageResult JSON to
     stdout, logs to stderr) and replace `answer()` with a call to your agent.

  python evals/examples/oracle_adapter.py --request request.json
"""
import argparse
import json
import sys
import time

from qa_shared import BugProposal, Category, Finding, Trace, TriageRequest, TriageResult
from qa_shared.fixtures import Fixtures, load_fixtures


def runs_for(req: TriageRequest, fx: Fixtures) -> list[str]:
    if req.run_id:
        return [req.run_id]
    project = req.project or next((r.project for r in fx.runs if r.project in req.question.lower()), None)
    return [r.run_id for r in fx.runs if r.project == project]


def answer(req: TriageRequest, fx: Fixtures) -> TriageResult:
    q = req.question.lower()
    tools: list[str] = []

    if "flaky" in q:
        tools.append("open_flaky_tests")
        open_ = [f for f in fx.flaky if f.status == "OPEN"]
        findings = [Finding(test_name=f.test, run_ids=[f.last_run_id] if f.last_run_id else [],
                            category=Category.FLAKY, kb_id=None, confidence=1.0, evidence=[f.note]) for f in open_]
        text = "Open flaky tests: " + ", ".join(f"`{f.test}` ({f.project}, {f.occurrences}x)" for f in open_)
        return TriageResult(answer=text, findings=findings, trace=Trace(tools_called=tools, model="oracle"))

    run_ids = runs_for(req, fx)
    if not req.run_id:
        tools.append("list_runs")
    tools += ["failed_cases", "semantic_search"]

    by_test: dict[str, Finding] = {}
    for run_id in run_ids:
        for case in fx.run(run_id).failed:
            f = fx.failure(case.failure)
            if f.test_name in by_test:
                by_test[f.test_name].run_ids.append(run_id)
            else:
                by_test[f.test_name] = Finding(test_name=f.test_name, run_ids=[run_id],
                                               category=f.expected.category, kb_id=f.expected.kb_id,
                                               confidence=1.0, evidence=[f.error_message])
    findings = list(by_test.values())
    lines = [f"• `{f.test_name}` in {', '.join(f.run_ids)}: {f.category.value}, "
             f"{f.kb_id or 'no known issue'}" for f in findings] or ["No failures in those runs."]

    if "report" in q:
        tools.append("report_link")
        lines += [f"Report: runs/{r}/summary.json (link valid 15 min)" for r in run_ids]

    proposals = []
    if "file a bug" in q or "file bugs" in q:
        proposals = [BugProposal(summary=f"{f.test_name} failing in {', '.join(f.run_ids)}",
                                 description=f.evidence[0], run_ids=f.run_ids)
                     for f in findings if f.kb_id is None]
    return TriageResult(answer="\n".join(lines), findings=findings, proposals=proposals,
                        trace=Trace(tools_called=tools, model="oracle"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True, help="path to a TriageRequest JSON file")
    args = ap.parse_args()
    with open(args.request, encoding="utf-8") as fh:
        req = TriageRequest.model_validate(json.load(fh))
    start = time.perf_counter()
    result = answer(req, load_fixtures())
    result.trace.latency_ms = int((time.perf_counter() - start) * 1000)
    print(f"oracle: {len(result.findings)} findings", file=sys.stderr)      # logs -> stderr
    print(result.model_dump_json())                                           # result -> stdout


if __name__ == "__main__":
    main()
