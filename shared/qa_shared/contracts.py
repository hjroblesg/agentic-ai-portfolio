"""
The shared contract every implementation honours, so evals compare like for like.

    adapter.run(TriageRequest) -> TriageResult

- TriageOutput is what the MODEL produces (use its JSON schema for structured output).
- TriageResult = TriageOutput + Trace, which the ADAPTER fills (tools called, tokens, cost, latency).
Bump CONTRACT_VERSION on any breaking change; eval results record it.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1"


class Category(str, Enum):
    PRODUCT_BUG = "product_bug"     # the product misbehaves
    TEST_BUG = "test_bug"           # the test itself is wrong or fragile
    FLAKY = "flaky"                 # intermittent, no stable cause yet
    INFRA = "infra"                 # CI, runners, network, registries
    UNKNOWN = "unknown"             # not enough evidence to say


class TriageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(description="What the user asked, e.g. 'why did run r50 fail?'")
    project: Optional[str] = Field(None, description="checkout | search | payments, when known")
    run_id: Optional[str] = Field(None, description="A run id like r42, when known")


class Finding(BaseModel):
    test_name: str
    run_ids: list[str] = Field(description="Runs where this failure was seen")
    category: Category
    kb_id: Optional[str] = Field(description="Matching known issue, or null when none fits")
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list,
                                description="Quoted error lines or tool outputs the conclusion rests on")


class BugProposal(BaseModel):
    """A DRAFT. Implementations must never create the ticket without human approval."""
    summary: str
    description: str
    run_ids: list[str]
    kb_ids: list[str] = Field(default_factory=list)


class TriageOutput(BaseModel):
    """What the model is asked to return (structured output)."""
    answer: str = Field(description="Human-readable answer (Slack mrkdwn), citing run IDs and KB IDs")
    findings: list[Finding] = Field(default_factory=list)
    proposals: list[BugProposal] = Field(default_factory=list)


class Trace(BaseModel):
    """Filled by the adapter, never by the model."""
    tools_called: list[str] = Field(default_factory=list, description="In call order, as the framework names them")
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    model: str = ""


class TriageResult(TriageOutput):
    contract_version: str = CONTRACT_VERSION
    trace: Trace = Field(default_factory=Trace)


def tool_short_name(name: str) -> str:
    """'mcp__qa-data__failed_cases' (Agent SDK) and 'failed_cases' (LangGraph) -> 'failed_cases'."""
    return name.rsplit("__", 1)[-1]
