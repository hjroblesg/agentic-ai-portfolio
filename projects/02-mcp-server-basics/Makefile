# 02 · MCP server basics. Run from this folder. Nothing here needs API keys or AWS.
#   make test        SDK client in-process + raw JSON-RPC over a real stdio subprocess
#   make raw         print every JSON-RPC message of a session
#   make client      the same session with the SDK Client
#   make run-http    serve on http://127.0.0.1:9001/mcp  (then: make client URL=http://127.0.0.1:9001/mcp)
#   make inspect     MCP Inspector UI (Node 20.19+ / 22.12+)
#   make claude      register with Claude Code, then ask it "which payments runs failed?"
PY   ?= python3
VENV := .venv
BIN  := $(VENV)/bin
REPO := $(abspath ../..)
URL  ?=

.PHONY: setup test raw client run-http inspect claude clean

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e "$(REPO)/shared" -e ".[test]"

setup: $(BIN)/python

test: setup
	$(BIN)/pytest -q

raw: setup
	$(BIN)/python raw_client.py

client: setup
	$(BIN)/python sdk_client.py $(URL)

run-http: setup
	$(BIN)/python server.py --transport streamable-http --port 9001

inspect: setup
	npx -y @modelcontextprotocol/inspector@latest $(CURDIR)/$(BIN)/python $(CURDIR)/server.py

claude: setup
	claude mcp add qa-basics -- $(CURDIR)/$(BIN)/python $(CURDIR)/server.py

clean:
	rm -rf $(VENV) .pytest_cache __pycache__ tests/__pycache__ *.egg-info
