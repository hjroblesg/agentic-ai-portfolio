"""The fixtures are the answer key for every eval, so they get tested like code."""
from collections import Counter

import pytest

from qa_shared import Category
from qa_shared.fixtures import Fixtures, load_fixtures, load_kb_search_eval, run_report, to_dynamodb_items


@pytest.fixture(scope="module")
def fx():
    return load_fixtures()


def test_counts(fx):
    assert len(fx.runs) == 10
    assert sum(len(r.cases) for r in fx.runs) == 85
    assert len(fx.failures) == 13
    assert len(fx.known_issues) == 18
    assert Counter(f.status for f in fx.flaky) == {"OPEN": 3, "CLOSED": 2}


def test_every_failure_is_referenced_once(fx):
    referenced = [c.failure for r in fx.runs for c in r.cases if c.failure]
    assert sorted(referenced) == sorted(f.id for f in fx.failures)


def test_failures_point_back_to_their_run(fx):
    for r in fx.runs:
        for c in r.failed:
            f = fx.failure(c.failure)
            assert (f.run_id, f.test_name) == (r.run_id, c.test)


def test_every_failure_has_a_log_with_its_error(fx):
    for f in fx.failures:
        assert f.log.count("\n") >= 2, f"{f.id}: log too short"
        assert f.error_message.split(":")[0] in f.log, f"{f.id}: log doesn't show the error type"


def test_answer_key_covers_all_categories_used_and_a_negative_case(fx):
    cats = {f.expected.category for f in fx.failures}
    assert {Category.PRODUCT_BUG, Category.INFRA, Category.TEST_BUG} <= cats
    assert any(f.expected.kb_id is None for f in fx.failures), "need at least one 'no known issue' case"


def test_every_match_kb_entry_explains_some_failure(fx):
    used = {f.expected.kb_id for f in fx.failures}
    for k in fx.known_issues:
        if k.kind == "match":
            assert k.id in used, f"{k.id} is marked 'match' but no failure expects it"
        else:
            assert k.id not in used, f"{k.id} is a {k.kind} but a failure expects it"


def test_kb_search_eval_targets_exist(fx):
    ids = {k.id for k in fx.known_issues}
    assert all(q["expected"] in ids for q in load_kb_search_eval())


def test_validation_rejects_unknown_kb_id(fx):
    data = fx.model_dump()
    data["failures"][0]["expected"]["kb_id"] = "KB-999"
    with pytest.raises(ValueError, match="KB-999"):
        Fixtures.model_validate(data)


def test_validation_rejects_failed_case_without_failure_id(fx):
    data = fx.model_dump()
    data["runs"][0]["cases"][0]["failure"] = None
    with pytest.raises(ValueError, match="need a failure id"):
        Fixtures.model_validate(data)


# --- facts the Day 3 smoke tests relied on --------------------------------------------------
def test_known_smoke_facts(fx):
    failed = {r.run_id: sorted(c.test for c in r.failed) for r in fx.runs}
    assert failed["r42"] == ["apply_coupon", "login_safari"]
    assert failed["r50"] == ["process_payment_high_load", "refund_partial"]
    assert failed["r46"] == []                                     # the clean run
    assert [r.run_id for r in fx.runs if "login_safari" in failed[r.run_id]] == ["r41", "r42", "r45"]
    refund = next(f for f in fx.failures if f.test_name == "refund_partial")
    assert refund.expected.kb_id is None                           # the negative case


def test_dynamodb_items(fx):
    items = to_dynamodb_items(fx)
    assert len(items) == 100
    assert Counter(i["type"] for i in items) == {"Run": 10, "Case": 85, "Flaky": 5}
    run50 = next(i for i in items if i["type"] == "Run" and i["runId"] == "r50")
    assert (run50["failed"], run50["passed"], run50["total"]) == (2, 6, 8)
    assert run50["errorMessage"] == "2 failed: process_payment_high_load; refund_partial"
    autocomplete = next(i for i in items if i["type"] == "Flaky" and i["testName"] == "search_autocomplete")
    assert autocomplete["durationMs"] == 120000 and autocomplete["lastRunId"] == "r43"   # the fixed seed bug
    failed_cases = [i for i in items if i["type"] == "Case" and i["status"] == "FAILED"]
    assert len(failed_cases) == 13 and all(i["retries"] == 1 and i["errorMessage"] for i in failed_cases)


def test_run_report_includes_logs(fx):
    report = run_report(fx, "r42")
    failed = [c for c in report["cases"] if c["status"] == "FAILED"]
    assert report["failed"] == 2 and all("Traceback" in c["log"] for c in failed)
    assert all("log" not in c for c in report["cases"] if c["status"] == "PASSED")
