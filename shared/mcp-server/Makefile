# The MCP server lives in its own environment (mcp 2.x). Run from this folder.
PY      ?= python3
VENV    := .venv
BIN     := $(VENV)/bin

.PHONY: setup test run run-http inspect clean

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e ".[test]" -e ..        # tests seed mocked data with qa_shared

setup: $(BIN)/python                       ## create .venv (mcp 2.x, boto3, test deps)

test: setup                                ## every tool through a real MCP client, against mocked AWS
	$(BIN)/pytest -q

run: setup                                 ## stdio (normally the agent host starts it for you)
	$(BIN)/python server.py

run-http: setup                            ## shared HTTP service on 127.0.0.1:9000/mcp
	$(BIN)/python server.py --transport streamable-http --port 9000

inspect: setup                             ## MCP Inspector (needs Node 20.19+ / 22.12+)
	npx -y @modelcontextprotocol/inspector@latest -e AWS_PROFILE=$${AWS_PROFILE} -e AWS_REGION=$${AWS_REGION:-us-east-1} $(BIN)/python $(CURDIR)/server.py

clean:
	rm -rf $(VENV) .pytest_cache __pycache__ tests/__pycache__ *.egg-info
