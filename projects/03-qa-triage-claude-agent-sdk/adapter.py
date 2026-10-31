"""
Eval adapter (protocol in evals/run_evals.py): read a TriageRequest, print one TriageResult as JSON.
Logs go to stderr, so stdout carries only the result.

    .venv/bin/python adapter.py --request request.json
"""
import argparse
import json
import logging
import sys

from qa_shared import TriageRequest

import agent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", required=True)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    with open(args.request, encoding="utf-8") as fh:
        req = TriageRequest.model_validate(json.load(fh))
    print(agent.triage(req).model_dump_json())


if __name__ == "__main__":
    main()
