"""Seed and report scripts against mocked AWS (moto): no account or credentials needed."""
import json
import runpy
from pathlib import Path

import boto3
import pytest
from boto3.dynamodb.conditions import Key
from moto import mock_aws

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(autouse=True)
def fake_aws(monkeypatch):
    for k, v in {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(k, v)
    with mock_aws():
        yield


def test_seed_supports_every_access_pattern():
    seed = runpy.run_path(str(DATA / "seed_qa_table.py"))
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    assert len(seed["seed"](ddb)) == 100
    t = ddb.Table("crash-qa")
    runs = t.query(KeyConditionExpression=Key("PK").eq("PROJECT#checkout") & Key("SK").begins_with("RUN#"),
                   ScanIndexForward=False)["Items"]
    assert [r["runId"] for r in runs] == ["r48", "r45", "r42", "r41"]                  # newest first
    cases = t.query(KeyConditionExpression=Key("PK").eq("RUN#r42") & Key("SK").begins_with("CASE#"))["Items"]
    assert sorted(c["testName"] for c in cases if c["status"] == "FAILED") == ["apply_coupon", "login_safari"]
    flaky = t.query(IndexName="GSI1", KeyConditionExpression=Key("GSI1PK").eq("FLAKY#OPEN"))["Items"]
    assert sorted(f["testName"] for f in flaky) == ["login_safari", "payment_webhook_retry", "search_autocomplete"]
    assert t.query(IndexName="GSI1", KeyConditionExpression=Key("GSI1PK").eq("RUN#r50"))["Items"][0]["failed"] == 2


def test_seed_is_idempotent():
    seed = runpy.run_path(str(DATA / "seed_qa_table.py"))
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    seed["seed"](ddb)
    seed["seed"](ddb)
    assert ddb.Table("crash-qa").scan(Select="COUNT")["Count"] == 100


def test_upload_reports():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-reports")
    keys = runpy.run_path(str(DATA / "upload_reports.py"))["upload"](s3, "test-reports")
    assert len(keys) == 10
    report = json.loads(s3.get_object(Bucket="test-reports", Key="runs/r50/summary.json")["Body"].read())
    assert report["failed"] == 2 and any("149.99" in c.get("log", "") for c in report["cases"])
