# shared/: the qa_shared package, fixtures and data scripts. Run from this folder.
PY      ?= python3
VENV    := .venv
BIN     := $(VENV)/bin

.PHONY: setup test seed-local seed reports kb kb-eval clean

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -e ".[test]"

setup: $(BIN)/python                      ## create .venv with qa_shared (editable) + test deps

test: setup                               ## unit tests: fixtures, contract, clients, data scripts (mocked AWS)
	$(BIN)/pytest -q

seed-local: setup                         ## load DynamoDB Local (start it with: docker compose -f infra/docker-compose.yml up -d)
	$(BIN)/python data/seed_qa_table.py --local --reset

seed: setup                               ## load real DynamoDB (uses AWS_PROFILE / AWS_REGION)
	$(BIN)/python data/seed_qa_table.py

reports: setup                            ## upload run reports to s3://$$QA_REPORTS_BUCKET
	$(BIN)/python data/upload_reports.py

kb: setup                                 ## create/load the S3 Vectors known-issues index
	$(BIN)/python data/kb/load_kb.py

kb-eval: setup                            ## retrieval check: every query must hit its KB entry at rank 1
	$(BIN)/python data/kb/eval_search.py

clean:
	rm -rf $(VENV) .pytest_cache */__pycache__ */*/__pycache__ *.egg-info
