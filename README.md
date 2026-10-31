# Agentic AI Portfolio

Agents built from first principles up to production patterns. Several of them solve **the same problem with different frameworks**: they share one contract, one synthetic dataset and one eval suite, so you can compare them on accuracy, trajectory, latency and cost.

**Running use case: QA failure triage.** Nightly test runs fail. An agent reads the runs (DynamoDB), the logs (S3) and a knowledge base of known issues (S3 Vectors + Bedrock embeddings), classifies each failure, links it to a known issue or says there is none, and drafts bugs. A human approves the drafts in Slack before anything reaches Jira.

## Levels and patterns

| Level | Meaning |
|---|---|
| 🟢 **Foundations** | One concept at a time: a tool call, an MCP server, retrieval |
| 🟡 **Intermediate** | Complete agents: tool loops, structured output, human-in-the-loop |
| 🔴 **Production** | Multi-agent systems, managed runtimes, observability, CI evals |

Pattern tags: `tool-use` · `mcp` · `rag` · `react` · `workflow-graph` · `structured-output` · `human-in-the-loop` · `multi-agent` · `evals`

## Projects

| # | Project | Level | Patterns | Stack | Eval pass rate | Status |
|---|---|---|---|---|---|---|
| 01 | `01-tool-use-basics` | 🟢 | `tool-use` | Anthropic Messages API | – | planned |
| 02 | `02-mcp-server-basics` | 🟢 | `mcp` `rag` | MCP Python SDK, DynamoDB, S3 Vectors | – | planned |
| 03 | [`03-qa-triage-claude-agent-sdk`](projects/03-qa-triage-claude-agent-sdk) | 🟡 | `react` `mcp` `structured-output` `human-in-the-loop` | Claude Agent SDK, Slack Bolt, Jira | – | ready |
| 04 | `04-qa-triage-langgraph` | 🟡 | `workflow-graph` `mcp` `human-in-the-loop` | LangGraph, LangChain MCP adapters | – | planned |
| 05 | `05-qa-triage-strands-agentcore` | 🔴 | `multi-agent` `mcp` `evals` | Strands Agents, Amazon Bedrock AgentCore | – | planned |

Projects live in `projects/` and appear here when they land. Eval numbers come from [`docs/comparison.md`](docs/comparison.md), which is generated from the result files and never edited by hand.

## Layout

```
shared/                 qa_shared package: contract, fixture loader, Jira + Slack helpers
  data/fixtures/        synthetic runs, failures (+ answer key), flaky registry, knowledge base
  data/                 seed DynamoDB, upload S3 reports, load the S3 Vectors index
  mcp-server/           the QA data MCP server (its own environment: mcp 2.x)
  infra/                DynamoDB Local (docker compose), IAM policies
evals/                  cases.yaml, runner, comparison generator, oracle adapter
projects/NN-<use-case>-<framework>/   one folder per implementation (each with its own environment)
docs/                   decisions (ADRs), project README template, comparison
```

## Quick start

Needs Python 3.11+, Docker, and for the agents an Anthropic API key plus an AWS account (see [cost note](#cost)).

```bash
cp .env.example .env                      # fill in what you need; .env is git-ignored
set -a; source .env; set +a

docker compose -f shared/infra/docker-compose.yml up -d     # DynamoDB Local on :8000
make -C shared test seed-local            # unit tests, then load the synthetic runs
make -C shared/mcp-server test            # every MCP tool through a real MCP client
make -C evals test eval-oracle            # the scorer, checked against the answer key
```

## Conventions

- **One contract.** Every implementation answers a `TriageRequest` with a `TriageResult` (`shared/qa_shared/contracts.py`): findings with category and known-issue id, bug *proposals*, and a trace (tools called, tokens, cost, latency).
- **One dataset.** `shared/data/fixtures/` feeds the database seed, the S3 reports, the unit tests and the eval answer key. It is synthetic; no real company data.
- **Separate environments.** Each folder with a `pyproject.toml` has its own `.venv`. Frameworks pin conflicting versions of `mcp`, so there is no single lockfile ([ADR 0002](docs/decisions/0002-separate-environments.md)).
- **Adapter protocol.** Each triage project ships `adapter.py`: `python adapter.py --request req.json` prints one `TriageResult` as JSON. The eval runner calls it as a subprocess in the project's own environment.
- **Same targets everywhere.** `make setup`, `make test` (offline, no keys, no AWS), `make run`, `make eval`.
- **Humans approve writes.** Agents only *propose* bugs; code creates the Jira issue after a person clicks Approve. Jira stays in dry-run until configured.

## Cost

Unit tests and CI tests use mocks and cost nothing. Running agents calls the Anthropic API, and the knowledge-base search calls Bedrock embeddings and S3 Vectors; a full eval run (6 cases × 3 repeats) is typically cents, not dollars. Set an AWS budget alert anyway.

## License

See [LICENSE](LICENSE).
