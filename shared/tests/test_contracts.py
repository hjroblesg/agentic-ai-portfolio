import pytest
from pydantic import ValidationError

from qa_shared import (CONTRACT_VERSION, BugProposal, Category, Finding, Trace, TriageOutput, TriageRequest,
                       TriageResult, tool_short_name)


def test_result_round_trips_as_json():
    r = TriageResult(answer="r50: 502 → KB-103; refund: no known issue",
                     findings=[Finding(test_name="refund_partial", run_ids=["r50"], category=Category.PRODUCT_BUG,
                                       kb_id=None, confidence=0.8, evidence=["ledger shows 149.99 MXN"])],
                     proposals=[BugProposal(summary="Refund ledger off by 0.01", description="d", run_ids=["r50"])],
                     trace=Trace(tools_called=["mcp__qa-data__failed_cases"], latency_ms=1200, model="m"))
    again = TriageResult.model_validate_json(r.model_dump_json())
    assert again == r and again.contract_version == CONTRACT_VERSION


def test_kb_id_null_is_explicit_and_required():
    with pytest.raises(ValidationError):
        Finding(test_name="t", run_ids=[], category="product_bug", confidence=0.5)   # kb_id missing
    assert Finding(test_name="t", run_ids=[], category="product_bug", kb_id=None, confidence=0.5).kb_id is None


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_confidence_bounds(bad):
    with pytest.raises(ValidationError):
        Finding(test_name="t", run_ids=[], category="infra", kb_id=None, confidence=bad)


def test_unknown_category_rejected():
    with pytest.raises(ValidationError):
        Finding(test_name="t", run_ids=[], category="cosmic_rays", kb_id=None, confidence=0.5)


def test_request_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        TriageRequest(question="q", build="b42")


def test_model_facing_schema_excludes_trace():
    props = TriageOutput.model_json_schema()["properties"]
    assert set(props) == {"answer", "findings", "proposals"}


@pytest.mark.parametrize("name", ["mcp__qa-data__failed_cases", "failed_cases"])
def test_tool_short_name(name):
    assert tool_short_name(name) == "failed_cases"
