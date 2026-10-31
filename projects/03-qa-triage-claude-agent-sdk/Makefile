# 03 · QA triage with the Claude Agent SDK. Run from this folder.
#   make test     offline: no API key, no AWS, no Slack
#   make ask Q="Why did run r50 fail?"   one live question (needs the MCP server venv + data)
#   make run      Slack bot
#   make eval     shared eval cases through adapter.py
PY      ?= python3
VENV    := .venv
BIN     := $(VENV)/bin
REPO    := $(abspath ../..)
REPEATS ?= 3
Q       ?= Why did run r50 fail?

.PHONY: setup server test ask run eval clean

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e "$(REPO)/shared" -e ".[test]"

setup: $(BIN)/python

server:                                    ## the MCP server's own venv (agent starts it over stdio)
	$(MAKE) -C $(REPO)/shared/mcp-server setup

test: setup
	$(BIN)/pytest -q

ask: setup server
	$(BIN)/python agent.py "$(Q)"

run: setup server
	$(BIN)/python bot.py

eval: setup server
	$(MAKE) -C $(REPO)/evals eval TARGET=$(notdir $(CURDIR)) REPEATS=$(REPEATS)

clean:
	rm -rf $(VENV) .pytest_cache __pycache__ tests/__pycache__ *.egg-info
