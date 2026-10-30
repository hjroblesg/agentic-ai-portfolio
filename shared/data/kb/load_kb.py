"""
Create the S3 Vectors bucket/index if needed and load every known issue from fixtures/kb.yaml
(embedded with Amazon Titan Text Embeddings V2, 1024 dimensions, cosine).
Re-running is safe: put_vectors overwrites by key.

  python shared/data/kb/load_kb.py
  python shared/data/kb/eval_search.py      # then check retrieval quality
"""
import json
import os

import boto3
from botocore.exceptions import ClientError

from qa_shared.fixtures import load_fixtures

REGION = os.getenv("AWS_REGION", "us-east-1")
VB = os.getenv("QA_VECTOR_BUCKET", "crash-kb-vectors")
IDX = os.getenv("QA_VECTOR_INDEX", "qa-docs")
EMBED_MODEL = "amazon.titan-embed-text-v2:0"


def embed(bedrock, text: str) -> list[float]:
    r = bedrock.invoke_model(modelId=EMBED_MODEL,
                             body=json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}))
    return json.loads(r["body"].read())["embedding"]


def ensure_index(s3v) -> None:
    try:
        s3v.create_vector_bucket(vectorBucketName=VB)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConflictException":
            raise
    try:
        s3v.create_index(vectorBucketName=VB, indexName=IDX, dataType="float32", dimension=1024,
                         distanceMetric="cosine",
                         metadataConfiguration={"nonFilterableMetadataKeys": ["source_text"]})
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConflictException":
            raise


def main() -> None:
    s3v = boto3.client("s3vectors", region_name=REGION)
    bedrock = boto3.client("bedrock-runtime", region_name=REGION)
    ensure_index(s3v)
    kb = load_fixtures().known_issues
    s3v.put_vectors(vectorBucketName=VB, indexName=IDX, vectors=[
        {"key": k.id, "data": {"float32": embed(bedrock, k.text)},
         "metadata": {"source_text": k.text, "team": k.team, "severity": k.severity, "kind": k.kind}}
        for k in kb])
    print(f"loaded {len(kb)} known issues into {VB}/{IDX}")


if __name__ == "__main__":
    main()
