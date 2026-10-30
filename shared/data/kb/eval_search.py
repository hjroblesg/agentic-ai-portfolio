"""
Retrieval check for the known-issues index: every query in fixtures/kb_search_eval.yaml must
return its expected KB entry at rank 1. Exits non-zero on any failure (usable in CI with AWS).
"""
import sys

import boto3

from load_kb import IDX, REGION, VB, embed
from qa_shared.fixtures import load_kb_search_eval


def main() -> int:
    s3v = boto3.client("s3vectors", region_name=REGION)
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    cases = load_kb_search_eval()
    failures = 0
    for case in cases:
        hits = s3v.query_vectors(vectorBucketName=VB, indexName=IDX, topK=3, returnDistance=True,
                                 queryVector={"float32": embed(bedrock, case["query"])})["vectors"]
        top = hits[0]["key"] if hits else None
        distance = f"{hits[0]['distance']:.3f}" if hits else "-"
        ok = top == case["expected"]
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {case['query']!r} -> {top} ({distance}), expected {case['expected']}")
    print(f"{len(cases) - failures}/{len(cases)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
