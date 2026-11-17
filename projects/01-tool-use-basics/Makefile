# 01 · Tool use basics. Run from this folder.
#   make test                                  offline (scripted fake client)
#   make run Q="Why did run r50 fail?"         live, prints every message block (needs ANTHROPIC_API_KEY)
PY   ?= python3
VENV := .venv
BIN  := $(VENV)/bin
REPO := $(abspath ../..)
Q    ?= Which checkout tests failed most recently, and why?

.PHONY: setup test run clean

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e "$(REPO)/shared" -e ".[test]"

setup: $(BIN)/python

test: setup
	$(BIN)/pytest -q

run: setup
	$(BIN)/python loop.py "$(Q)" --show-messages

clean:
	rm -rf $(VENV) .pytest_cache __pycache__ tests/__pycache__ *.egg-info
