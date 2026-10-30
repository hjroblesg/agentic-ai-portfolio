# 0001: One contract for every triage implementation

**Status:** accepted

## Context
Several projects solve the same QA-triage problem with different frameworks (Claude Agent SDK, LangGraph, Strands + AgentCore). Without a common shape, comparing them means comparing prose answers by eye.

## Decision
Every implementation takes a `TriageRequest` and returns a `TriageResult` (`shared/qa_shared/contracts.py`):

- `TriageOutput` (answer, findings, proposals) is what the **model** produces; its JSON schema is used for structured output.
- `Trace` (tools called, tokens, cost, latency, model) is filled by the **adapter**, never by the model.
- `Finding.kb_id` is required but nullable, so "no known issue" is an explicit answer, not an omission.
- `CONTRACT_VERSION` is bumped on breaking changes and recorded in every eval result.

## Consequences
- Evals score fields, not wording: labels, known-issue matches, trajectory, proposals.
- Each project needs a thin `adapter.py` that maps its framework's output and telemetry to the contract.
- The contract constrains answers; a new capability (e.g. severity) means a contract change in one place.
