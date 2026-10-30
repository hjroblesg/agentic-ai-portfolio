# 0003: Deterministic work goes in tools, judgment goes to the model

**Status:** accepted

## Context
Early smoke tests failed in ways that weren't reasoning problems: DynamoDB numbers came back as strings, the model scanned when it should have queried, known issues were looked up inconsistently, and an S3 key with `..` would have been signed.

## Decision
Tools return finished, validated data; the model decides what it means.

- `failed_cases` and `open_flaky_tests` attach the top known-issue matches themselves, so every failure is checked against the KB on every call.
- Tools coerce types (`Decimal` → `int`), sort, and cap output (`failure_log` returns the last 60 lines).
- Tools validate input and fail with `ToolError` messages written for the model ("Only keys under runs/ …", "is the dynamodb-local container running?"); other exceptions are hidden from it.
- Access patterns are fixed in code (Query on PK/GSI1, never Scan).

## Consequences
- Fewer tool calls and steadier trajectories across frameworks, since all of them share the server.
- The model can still disagree with a suggested match (e.g. reject KB-105 for the refund mismatch); evals check that it does.
- Changing a tool's output is an MCP server change, covered by its own tests.
