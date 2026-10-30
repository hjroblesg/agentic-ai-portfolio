"""
Create the DynamoDB table and load it from the fixtures (10 runs, 85 cases, 5 flaky = 100 items).

  python shared/data/seed_qa_table.py --local          # DynamoDB Local (shared/infra/docker-compose.yml)
  python shared/data/seed_qa_table.py                  # real DynamoDB (AWS_PROFILE / AWS_REGION)
  python shared/data/seed_qa_table.py --local --reset  # drop and recreate first
  python shared/data/seed_qa_table.py --dry-run        # print item counts, no AWS calls
"""
import argparse
import os
from collections import Counter

from qa_shared.fixtures import load_fixtures, to_dynamodb_items

TABLE = os.getenv("QA_TABLE", "crash-qa")
REGION = os.getenv("AWS_REGION", "us-east-1")


def create_table(client) -> None:
    client.create_table(
        TableName=TABLE,
        AttributeDefinitions=[{"AttributeName": a, "AttributeType": "S"} for a in ("PK", "SK", "GSI1PK", "GSI1SK")],
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        GlobalSecondaryIndexes=[{"IndexName": "GSI1",
                                 "KeySchema": [{"AttributeName": "GSI1PK", "KeyType": "HASH"},
                                               {"AttributeName": "GSI1SK", "KeyType": "RANGE"}],
                                 "Projection": {"ProjectionType": "ALL"}}],
        BillingMode="PAY_PER_REQUEST")
    client.get_waiter("table_exists").wait(TableName=TABLE)


def seed(ddb) -> list[dict]:
    """Create the table if needed and write every item. `ddb` is a boto3 DynamoDB resource."""
    client = ddb.meta.client
    if TABLE not in client.list_tables()["TableNames"]:
        create_table(client)
    items = to_dynamodb_items(load_fixtures())
    with ddb.Table(TABLE).batch_writer() as bw:
        for item in items:
            bw.put_item(Item=item)
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", action="store_true", help="use DynamoDB Local on $DDB_ENDPOINT or localhost:8000")
    ap.add_argument("--reset", action="store_true", help="delete the table first if it exists")
    ap.add_argument("--dry-run", action="store_true", help="only build the items and print counts")
    args = ap.parse_args()

    if args.dry_run:
        items = to_dynamodb_items(load_fixtures())
        print(f"{len(items)} items: {dict(Counter(i['type'] for i in items))}")
        return

    import boto3
    kwargs = {"region_name": REGION}
    if args.local:
        kwargs["endpoint_url"] = os.getenv("DDB_ENDPOINT", "http://localhost:8000")
        kwargs.update(aws_access_key_id="local", aws_secret_access_key="local")   # DynamoDB Local accepts any
    ddb = boto3.resource("dynamodb", **kwargs)
    if args.reset and TABLE in ddb.meta.client.list_tables()["TableNames"]:
        ddb.meta.client.delete_table(TableName=TABLE)
        ddb.meta.client.get_waiter("table_not_exists").wait(TableName=TABLE)
    items = seed(ddb)
    print(f"Loaded {len(items)} items into {TABLE}: {dict(Counter(i['type'] for i in items))}")


if __name__ == "__main__":
    main()
