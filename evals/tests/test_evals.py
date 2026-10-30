"""
The scorer must give the oracle 100% and catch each kind of broken adapter.
Broken adapters are small scripts written to tmp_path that wrap the oracle and damage its output.
"""
import json
import sys
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVALS))
import generate_comparison  # noqa: E402
import run_evals  # noqa: E402

ORACLE = EVALS / "examples" / "oracle_adapter.py"


def run(tmp_path, adapter, target="oracle", *extra):
    out = tmp_path / "results"
    code = run_evals.main(["--target", target, "--adapter", str(adapter), "--python", sys.executable,
                           "--repeats", "1", "--out", str(out), *extra])
    files = sorted(out.glob("*.json"))
    return code, json.loads(files[-1].read_text())


def broken(tmp_path, body: str) -> Path:
    """An adapter that runs the oracle, then applies `body` to `result` before printing."""
    p = tmp_path / "broken_adapter.py"
    p.write_text(f"""
import json, subprocess, sys
out = subprocess.run([sys.executable, {str(ORACLE)!r}, *sys.argv[1:]], capture_output=True, text=True).stdout
result = json.loads(out)
{body}
print(json.dumps(result))
""")
    return p


def test_oracle_scores_100(tmp_path):
    code, report = run(tmp_path, ORACLE, "oracle", "--min-pass-rate", "1.0")
    s = report["summary"]
    assert code == 0 and s["pass_rate"] == 1.0 and s["cases_always_passing"] == s["cases"] == 6
    assert s["category_accuracy"] == 1.0 and s["kb_accuracy"] == 1.0 and s["adapter_errors"] == 0
    assert report["meta"]["contract_version"] == "1"


def test_wrong_kb_on_negative_case_is_caught(tmp_path):
    # the classic agent mistake: forcing a near-miss KB onto refund_partial instead of null
    adapter = broken(tmp_path, """
for f in result["findings"]:
    if f["test_name"] == "refund_partial":
        f["kb_id"] = "KB-105"
""")
    _, report = run(tmp_path, adapter, "broken", "--case", "why-r50-failed")
    checks = {c["name"]: c for c in report["cases"][0]["runs"][0]["checks"]}
    assert not checks["finding:refund_partial"]["passed"]
    assert "kb_id KB-105 != None" in checks["finding:refund_partial"]["detail"]
    assert checks["finding:process_payment_high_load"]["passed"]
    assert report["summary"]["kb_accuracy"] < 1.0


def test_trajectory_and_forbidden_tests_are_caught(tmp_path):
    adapter = broken(tmp_path, """
result["trace"]["tools_called"] = []
result["findings"].append({"test_name": "cart_badge_count", "run_ids": [], "category": "flaky",
                           "kb_id": None, "confidence": 0.5, "evidence": []})
""")
    _, report = run(tmp_path, adapter, "broken", "--case", "open-flaky-tests")
    failed = {c["name"] for c in report["cases"][0]["runs"][0]["checks"] if not c["passed"]}
    assert failed == {"tool_called:open_flaky_tests", "forbid:cart_badge_count"}


def test_extra_proposal_is_caught(tmp_path):
    adapter = broken(tmp_path, """
result["proposals"].append({"summary": "502 again", "description": "dup of KB-103", "run_ids": ["r50"]})
""")
    _, report = run(tmp_path, adapter, "broken", "--case", "file-bug-r50")
    failed = {c["name"] for c in report["cases"][0]["runs"][0]["checks"] if not c["passed"]}
    assert failed == {"max_proposals"}


@pytest.mark.parametrize("body,expect", [
    ("raise SystemExit(3)", "exit 3"),
    ("print('not json'); raise SystemExit(0)", "not a valid TriageResult"),
    ("result['findings'][0]['category'] = 'maybe'", "not a valid TriageResult"),
])
def test_adapter_failures_are_reported_not_raised(tmp_path, body, expect):
    adapter = tmp_path / "bad.py"
    adapter.write_text(body if "result" not in body else broken(tmp_path, body).read_text())
    code, report = run(tmp_path, adapter, "bad", "--case", "why-r50-failed", "--min-pass-rate", "1.0")
    r = report["cases"][0]["runs"][0]
    assert code == 1 and not r["passed"] and expect in r["error"]
    assert report["summary"]["adapter_errors"] == 1


def test_comparison_table(tmp_path):
    run(tmp_path, ORACLE, "03-demo")
    md = generate_comparison.render(generate_comparison.latest_per_target(tmp_path / "results"))
    assert "GENERATED" in md and "| 03-demo | 100% (6/6) | 6/6 |" in md and "| why-r50-failed | 100% |" in md


def test_comparison_skips_oracle_and_handles_empty(tmp_path):
    run(tmp_path, ORACLE, "oracle")
    assert "No eval results yet" in generate_comparison.render(
        generate_comparison.latest_per_target(tmp_path / "results"))
