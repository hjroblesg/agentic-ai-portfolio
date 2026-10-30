# Eval runner. Uses its own venv with qa_shared only; each project's adapter runs in that project's venv.
#   make test                               scorer tests (oracle = 100%, broken adapters are caught)
#   make eval-oracle                        scorer self-check against the answer key
#   make eval TARGET=03-qa-triage-claude-agent-sdk [REPEATS=3]
#   make comparison                         regenerate docs/comparison.md
PY      ?= python3
VENV    := .venv
BIN     := $(VENV)/bin
REPEATS ?= 3
TARGET  ?=

.PHONY: setup test eval eval-oracle comparison clean

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e "../shared[test]"

setup: $(BIN)/python

test: setup
	$(BIN)/pytest -q tests

eval: setup
	@test -n "$(TARGET)" || (echo "usage: make eval TARGET=<folder under projects/>"; exit 2)
	$(BIN)/python run_evals.py --target $(TARGET) --repeats $(REPEATS)
	$(BIN)/python generate_comparison.py

eval-oracle: setup
	$(BIN)/python run_evals.py --target oracle --adapter examples/oracle_adapter.py --python $(CURDIR)/$(BIN)/python \
		--repeats 1 --out $(CURDIR)/.oracle-results --min-pass-rate 1.0

comparison: setup
	$(BIN)/python generate_comparison.py

clean:
	rm -rf $(VENV) .pytest_cache __pycache__ tests/__pycache__ .oracle-results
