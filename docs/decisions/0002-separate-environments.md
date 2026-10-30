# 0002: Separate environments, no uv workspace

**Status:** accepted

## Context
The projects pin incompatible dependencies. The MCP server uses `mcp` 2.x; `langchain-mcp-adapters` requires `mcp<2`. Installing it into a shared environment silently downgraded `mcp` and broke the server. A uv workspace resolves all members into **one** lockfile, so it cannot hold both.

## Decision
- Every folder with a `pyproject.toml` has its own `.venv`, created by `make setup`.
- `shared/qa_shared` has **no** `mcp` dependency, so any project can install it (`pip install -e ../../shared`).
- The MCP server is never imported by agents. They start it as a process (stdio, via `SERVER_PYTHON`) or call it over HTTP.
- The eval runner calls each project's `adapter.py` as a subprocess with that project's interpreter.

## Consequences
- Version conflicts stay inside one project.
- More disk space and one `make setup` per folder.
- Process boundaries everywhere mean the contract is JSON on stdout and MCP on stdio/HTTP: the same boundaries as production.
