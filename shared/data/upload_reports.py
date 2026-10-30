"""
Upload one JSON report per run (with failure logs) to s3://$QA_REPORTS_BUCKET/runs/<run_id>/summary.json.
The bucket must exist: aws s3 mb s3://<your-unique-bucket-name>

  QA_REPORTS_BUCKET=crash-qa-reports-<suffix> python shared/data/upload_reports.py
"""
import json
import os

from qa_shared.fixtures import load_fixtures, run_report


def upload(s3, bucket: str) -> list[str]:
    fx = load_fixtures()
    keys = []
    for run in fx.runs:
        key = f"runs/{run.run_id}/summary.json"
        s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(run_report(fx, run.run_id), indent=2),
                      ContentType="application/json")
        keys.append(key)
    return keys


if __name__ == "__main__":
    import boto3
    bucket = os.environ["QA_REPORTS_BUCKET"]
    for key in upload(boto3.client("s3", region_name=os.getenv("AWS_REGION", "us-east-1")), bucket):
        print("uploaded", f"s3://{bucket}/{key}")
