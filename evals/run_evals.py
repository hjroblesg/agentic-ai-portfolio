"""
Run the shared eval cases against one implementation and save a JSON result file.

  python evals/run_evals.py --target 03-qa-triage-claude-agent-sdk           # projects/<target>/adapter.py
  python evals/run_evals.py --target 03-qa-triage-claude-agent-sdk --repeats 3 --case why-r50-failed
  python evals/run_evals.py --adapter evals/examples/oracle_adapter.py --target oracle   # scorer self-check

Adapter protocol (each project, in its OWN environment):
  <python> adapter.py --request request.json   ->  prints one TriageResult as JSON on stdout
  (logs go to stderr). The runner calls it as a subprocess, so projects never share dependencies.

Run this file with the shared environment (needs qa_shared): shared/.venv/bin/python evals/run_evals.py ...
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from qa_shared import CONTRACT_VERSION, TriageRequest, TriageResult, tool_short_name
from qa_shared.fixtures import Fixtures, load_fixtures

REPO = Path(__file__).resolve().parents[1]


# --- expectations ---------------------------------------------------------------
def load_cases(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["cases"]


def expected_findings(expect: dict, fx: Fixtures) -> list[dict]:
    """Answer-key findings for `findings_from_runs`, grouped by test, plus explicit `findings`."""
    by_test: dict[str, dict] = {}
    for run_id in expect.get("findings_from_runs", []):
        for case in fx.run(run_id).failed:
            f = fx.failure(case.failure)
            e = by_test.setdefault(f.test_name, {"test_name": f.test_name, "category": f.expected.category.value,
                                                  "kb_id": f.expected.kb_id, "run_ids": []})
            e["run_ids"].append(run_id)
    for explicit in expect.get("findings", []):
        by_test.setdefault(explicit["test_name"], {}).update(explicit)
    return list(by_test.values())


def _check(name: str, passed: bool, detail: str = "") -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def score(result: TriageResult, expect: dict, fx: Fixtures) -> tuple[list[dict], dict]:
    """Returns (checks, label stats). A run passes when every check passes."""
    checks: list[dict] = []
    stats = {"category_total": 0, "category_ok": 0, "kb_total": 0, "kb_ok": 0}
    got = {f.test_name.lower(): f for f in result.findings}

    for e in expected_findings(expect, fx):
        f = got.get(e["test_name"].lower())
        if f is None:
            checks.append(_check(f"finding:{e['test_name']}", False, "missing"))
            stats["category_total"] += "category" in e
            stats["kb_total"] += "kb_id" in e
            continue
        problems = []
        if "category" in e:
            stats["category_total"] += 1
            ok = f.category.value == e["category"]
            stats["category_ok"] += ok
            if not ok:
                problems.append(f"category {f.category.value} != {e['category']}")
        if "kb_id" in e:
            stats["kb_total"] += 1
            ok = (f.kb_id or None) == e["kb_id"]
            stats["kb_ok"] += ok
            if not ok:
                problems.append(f"kb_id {f.kb_id} != {e['kb_id']}")
        missing_runs = sorted(set(e.get("run_ids", [])) - set(f.run_ids))
        if missing_runs:
            problems.append(f"run_ids missing {missing_runs}")
        checks.append(_check(f"finding:{e['test_name']}", not problems, "; ".join(problems)))

    for t in expect.get("forbid_tests", []):
        checks.append(_check(f"forbid:{t}", t.lower() not in got, "present" if t.lower() in got else ""))

    answer = result.answer.lower()
    for s in expect.get("answer_must_include", []):
        checks.append(_check(f"answer_includes:{s}", s.lower() in answer))
    for s in expect.get("answer_must_not_include", []):
        checks.append(_check(f"answer_excludes:{s}", s.lower() not in answer))

    tools = {tool_short_name(t) for t in result.trace.tools_called}
    for t in expect.get("tools_must_include", []):
        checks.append(_check(f"tool_called:{t}", t in tools, f"called {sorted(tools)}"))
    for t in expect.get("tools_must_not_include", []):
        checks.append(_check(f"tool_not_called:{t}", t not in tools))

    n = len(result.proposals)
    if "min_proposals" in expect:
        checks.append(_check("min_proposals", n >= expect["min_proposals"], f"got {n}"))
    if "max_proposals" in expect:
        checks.append(_check("max_proposals", n <= expect["max_proposals"], f"got {n}"))
    for run_id in expect.get("proposal_run_ids_include", []):
        checks.append(_check(f"proposal_run:{run_id}", any(run_id in p.run_ids for p in result.proposals)))
    return checks, stats


# --- running adapters ------------------------------------------------------------
def resolve_target(target: str, adapter: str | None, python: str | None) -> tuple[Path, Path, str]:
    project = Path(target) if Path(target).is_dir() else REPO / "projects" / target
    adapter_path = Path(adapter).resolve() if adapter else project / "adapter.py"
    if not adapter_path.exists():
        sys.exit(f"adapter not found: {adapter_path}")
    if python is None:
        venv = project / ".venv"
        candidates = [venv / "bin" / "python", venv / "Scripts" / "python.exe"]
        python = next((str(c) for c in candidates if c.exists()), sys.executable)
    elif os.sep in python or "/" in python:
        python = str(Path(python).absolute())         # cwd=project; absolute() keeps the venv symlink
    return (project if project.is_dir() else adapter_path.parent), adapter_path, python


def run_adapter(python: str, adapter: Path, cwd: Path, request: TriageRequest, timeout: int):
    """Returns (TriageResult | None, error | None, wall_ms)."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        fh.write(request.model_dump_json())
    start = time.perf_counter()
    try:
        proc = subprocess.run([python, str(adapter), "--request", fh.name], cwd=cwd, capture_output=True,
                              text=True, timeout=timeout, env=os.environ.copy())
    except subprocess.TimeoutExpired:
        return None, f"timeout after {timeout}s", int((time.perf_counter() - start) * 1000)
    finally:
        os.unlink(fh.name)
    wall = int((time.perf_counter() - start) * 1000)
    if proc.returncode != 0:
        return None, f"exit {proc.returncode}: {proc.stderr.strip()[-500:]}", wall
    out = proc.stdout.strip()
    try:
        return TriageResult.model_validate_json(out), None, wall
    except ValueError:
        last = out.splitlines()[-1] if out else ""
        try:
            return TriageResult.model_validate_json(last), None, wall
        except ValueError as e:
            return None, f"stdout is not a valid TriageResult: {str(e)[:300]}", wall


def git_sha() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True).stdout
        return sha + ("-dirty" if dirty.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def summarize(case_results: list[dict]) -> dict:
    runs = [r for c in case_results for r in c["runs"]]
    ok = [r for r in runs if r["trace"]]
    stat = lambda k: sum(r["label_stats"][k] for r in runs)
    lat = [r["latency_ms"] for r in ok]
    return {
        "runs": len(runs), "runs_passed": sum(r["passed"] for r in runs),
        "pass_rate": round(sum(r["passed"] for r in runs) / len(runs), 3) if runs else 0.0,
        "cases_always_passing": sum(all(r["passed"] for r in c["runs"]) for c in case_results),
        "cases": len(case_results),
        "category_accuracy": round(stat("category_ok") / stat("category_total"), 3) if stat("category_total") else None,
        "kb_accuracy": round(stat("kb_ok") / stat("kb_total"), 3) if stat("kb_total") else None,
        "adapter_errors": sum(1 for r in runs if r["error"]),
        "latency_ms_median": int(statistics.median(lat)) if lat else None,
        "latency_ms_max": max(lat) if lat else None,
        "cost_usd_total": round(sum(r["trace"]["cost_usd"] for r in ok), 4),
        "cost_usd_per_run": round(sum(r["trace"]["cost_usd"] for r in ok) / len(ok), 4) if ok else None,
        "tokens_per_run": int(sum(r["trace"]["input_tokens"] + r["trace"]["output_tokens"] for r in ok) / len(ok))
        if ok else None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="folder name under projects/, or a path")
    ap.add_argument("--adapter", help="override adapter path (default <target>/adapter.py)")
    ap.add_argument("--python", help="interpreter for the adapter (default <target>/.venv python)")
    ap.add_argument("--cases", default=str(REPO / "evals" / "cases.yaml"))
    ap.add_argument("--case", action="append", help="run only these case ids (repeatable)")
    ap.add_argument("--repeats", type=int, default=3, help="runs per case; agents are non-deterministic")
    ap.add_argument("--timeout", type=int, default=300, help="seconds per adapter call")
    ap.add_argument("--out", default=str(REPO / "evals" / "results"))
    ap.add_argument("--min-pass-rate", type=float, default=0.0, help="exit 1 below this (for CI gates)")
    args = ap.parse_args(argv)

    fx = load_fixtures()
    cases = [c for c in load_cases(Path(args.cases)) if not args.case or c["id"] in args.case]
    if not cases:
        sys.exit("no matching cases")
    cwd, adapter, python = resolve_target(args.target, args.adapter, args.python)
    started = datetime.now(timezone.utc)
    print(f"target={args.target} adapter={adapter} python={python} cases={len(cases)} repeats={args.repeats}",
          file=sys.stderr)

    case_results, models = [], set()
    for case in cases:
        request = TriageRequest(**case["request"])
        runs = []
        for i in range(args.repeats):
            result, error, wall = run_adapter(python, adapter, cwd, request, args.timeout)
            if result is None:
                checks, stats = [_check("adapter", False, error)], {"category_total": 0, "category_ok": 0,
                                                                    "kb_total": 0, "kb_ok": 0}
            else:
                checks, stats = score(result, case.get("expect", {}), fx)
                models.add(result.trace.model)
            passed = all(c["passed"] for c in checks)
            runs.append({"repeat": i + 1, "passed": passed, "error": error, "checks": checks, "label_stats": stats,
                         "latency_ms": (result.trace.latency_ms or wall) if result else wall,
                         "trace": result.trace.model_dump() if result else None,
                         "output": result.model_dump(exclude={"trace"}) if result else None})
            failed = [c["name"] + (f" ({c['detail']})" if c["detail"] else "") for c in checks if not c["passed"]]
            print(f"{'PASS' if passed else 'FAIL'}  {case['id']} #{i + 1}" + (f"  -> {'; '.join(failed)}" if failed else ""),
                  file=sys.stderr)
        case_results.append({"id": case["id"], "request": case["request"],
                             "pass_rate": round(sum(r["passed"] for r in runs) / len(runs), 3), "runs": runs})

    summary = summarize(case_results)
    report = {"meta": {"target": args.target, "started_at": started.isoformat(timespec="seconds"),
                       "git_sha": git_sha(), "contract_version": CONTRACT_VERSION,
                       "models": sorted(m for m in models if m), "repeats": args.repeats,
                       "cases_file": os.path.relpath(args.cases, REPO)},
              "summary": summary, "cases": case_results}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{Path(args.target).name}-{started.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"saved {path}", file=sys.stderr)
    return 1 if summary["pass_rate"] < args.min_pass_rate else 0


if __name__ == "__main__":
    sys.exit(main())
