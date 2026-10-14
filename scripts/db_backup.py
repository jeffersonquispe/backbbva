#!/usr/bin/env python3
"""Back up and manage the local DynamoDB, OpenSearch, and MinIO data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

# Imports below require the repository root when this file is run directly.
# ruff: noqa: E402
import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError
from opensearchpy import OpenSearch, RequestsHttpConnection, helpers

from src.infrastructure.persistence.database.dynamodb import schemas

BACKUP_ROOT = Path("backups")
META_FILE = "manifest.json"
_SERIALIZER = TypeSerializer()
_DESERIALIZER = TypeDeserializer()


def _dynamodb():
    kwargs: dict[str, Any] = {"region_name": os.getenv("DYNAMO_REGION_NAME", "us-east-1")}
    kwargs.update(
        endpoint_url=os.getenv("DYNAMO_ENDPOINT", "http://dynamodb:8000"),
        aws_access_key_id=os.getenv("DYNAMO_ACCESS_KEY", "dummy"),
        aws_secret_access_key=os.getenv("DYNAMO_SECRET_KEY", "dummy"),
    )
    return boto3.resource("dynamodb", **kwargs)


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("OBJECT_STORAGE_ENDPOINT", "http://minio:9000"),
        region_name=os.getenv("OBJECT_STORAGE_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("OBJECT_STORAGE_ACCESS_KEY", "dummy"),
        aws_secret_access_key=os.getenv("OBJECT_STORAGE_SECRET_KEY", "dummy123"),
    )


def _opensearch() -> OpenSearch:
    parsed = urlparse(os.getenv("OPENSEARCH_ENDPOINT", "http://opensearch:9200"))
    auth_mode = os.getenv("OPENSEARCH_AUTH_MODE", "basic")
    if auth_mode == "basic":
        auth = (os.getenv("OPENSEARCH_USERNAME", "admin"), os.getenv("OPENSEARCH_PASSWORD", "dummy"))
    elif auth_mode == "aws_sigv4":
        from opensearchpy import AWSV4SignerAuth

        auth = AWSV4SignerAuth(
            boto3.Session().get_credentials(), os.getenv("OPENSEARCH_REGION", "eu-west-1"), "es"
        )
    else:
        raise ValueError(f"Unknown OPENSEARCH_AUTH_MODE: {auth_mode}")
    return OpenSearch(
        hosts=[{"host": parsed.hostname, "port": parsed.port or (443 if parsed.scheme == "https" else 80)}],
        http_auth=auth,
        use_ssl=parsed.scheme == "https",
        verify_certs=os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true",
        connection_class=RequestsHttpConnection,
    )


def _configured_table_names() -> set[str]:
    return {
        value["TableName"]
        for value in vars(schemas).values()
        if isinstance(value, dict) and "TableName" in value
    }


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _write_jsonl(path: Path, rows) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def backup(directory: Path | None, skip_object_storage: bool) -> None:
    target = directory or BACKUP_ROOT / _timestamp()
    target.mkdir(parents=True, exist_ok=False)
    working = target.with_name(f".{target.name}.incomplete")
    if working.exists():
        shutil.rmtree(working)
    working.mkdir(parents=True)
    try:
        _write_backup_contents(working, skip_object_storage)
        for path in working.iterdir():
            path.replace(target / path.name)
        working.rmdir()
    except Exception:
        shutil.rmtree(working, ignore_errors=True)
        raise
    print(f"Backup complete: {target}")


def _write_backup_contents(target: Path, skip_object_storage: bool) -> None:
    db_dir = target / "dynamodb"
    db_dir.mkdir()
    dynamodb = _dynamodb()
    client = dynamodb.meta.client
    table_names: list[str] = []
    response = client.list_tables()
    table_names.extend(response.get("TableNames", []))
    while response.get("LastEvaluatedTableName"):
        response = client.list_tables(ExclusiveStartTableName=response["LastEvaluatedTableName"])
        table_names.extend(response.get("TableNames", []))

    manifest: dict[str, Any] = {"created_at": datetime.now(UTC).isoformat(), "dynamodb": {}, "object_storage": None, "opensearch": None}
    for table_name in table_names:
        description = client.describe_table(TableName=table_name)["Table"]
        schema_path = db_dir / f"{table_name}.schema.json"
        schema_path.write_text(json.dumps(description, indent=2, default=str) + "\n", encoding="utf-8")
        table = dynamodb.Table(table_name)

        def scan_items():
            page = table.scan()
            yield from page.get("Items", [])
            while page.get("LastEvaluatedKey"):
                page = table.scan(ExclusiveStartKey=page["LastEvaluatedKey"])
                yield from page.get("Items", [])

        count = _write_jsonl(
            db_dir / f"{table_name}.items.jsonl",
            ({key: _SERIALIZER.serialize(value) for key, value in item.items()} for item in scan_items()),
        )
        manifest["dynamodb"][table_name] = {"items": count, "schema": schema_path.name}
        print(f"Backed up DynamoDB {table_name}: {count} items")

    if not skip_object_storage:
        s3 = _s3()
        bucket = os.getenv("OBJECT_STORAGE_BUCKET", "aria-reports")
        objects_dir = target / "object_storage" / bucket
        objects_dir.mkdir(parents=True)
        records = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                local_path = objects_dir / hashlib.sha256(key.encode("utf-8")).hexdigest()
                local_path.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(bucket, key, str(local_path))
                records.append({"key": key, "path": str(local_path.relative_to(target))})
        manifest["object_storage"] = {"bucket": bucket, "objects": records}
        print(f"Backed up object storage {bucket}: {len(records)} objects")

    os_client = _opensearch()
    index = os.getenv("OPENSEARCH_INDEX", "fraud_knowledge")
    if os_client.indices.exists(index=index):
        index_dir = target / "opensearch"
        index_dir.mkdir()
        settings = os_client.indices.get_settings(index=index)
        mappings = os_client.indices.get_mapping(index=index)
        index_settings = settings[index]["settings"].get("index", settings[index]["settings"])
        (index_dir / "settings.json").write_text(json.dumps(index_settings, indent=2) + "\n", encoding="utf-8")
        (index_dir / "mapping.json").write_text(json.dumps(mappings[index]["mappings"], indent=2) + "\n", encoding="utf-8")
        count = _write_jsonl(
            index_dir / "documents.jsonl",
            ({"id": hit["_id"], "source": hit["_source"]} for hit in helpers.scan(os_client, index=index)),
        )
        manifest["opensearch"] = {"index": index, "documents": count}
        print(f"Backed up OpenSearch {index}: {count} documents")
    (target / META_FILE).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _load_manifest(directory: Path) -> dict[str, Any]:
    if not directory.is_absolute():
        directory = REPO_ROOT / directory
    manifest_path = directory / META_FILE
    if not manifest_path.is_file():
        raise SystemExit(f"Invalid backup: missing {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("dynamodb"), dict):
        raise SystemExit(f"Invalid backup: {manifest_path} has no DynamoDB table catalog")
    for table_name, info in manifest["dynamodb"].items():
        if not isinstance(info, dict) or not isinstance(info.get("schema"), str):
            raise SystemExit(f"Invalid backup: malformed table entry for {table_name}")
        table_dir = directory / "dynamodb"
        if not (table_dir / info["schema"]).is_file() or not (table_dir / f"{table_name}.items.jsonl").is_file():
            raise SystemExit(f"Invalid backup: missing DynamoDB files for {table_name}")
    return manifest


def _validate_table_schema(table_name: str, expected: dict[str, Any], actual: dict[str, Any]) -> None:
    for field in ("KeySchema", "AttributeDefinitions"):
        expected_value = expected.get(field, [])
        actual_value = actual.get(field, [])
        if sorted(expected_value, key=lambda item: item.get("AttributeName", "")) != sorted(
            actual_value, key=lambda item: item.get("AttributeName", "")
        ):
            raise ValueError(f"Cannot restore {table_name}: existing table has incompatible {field}")


def restore(directory: Path, skip_object_storage: bool, os_bulk_size: int, checkpoint: Path | None, resume: bool) -> None:
    if not directory.is_absolute():
        directory = REPO_ROOT / directory
    manifest = _load_manifest(directory)
    if os_bulk_size < 1:
        raise ValueError("--os-bulk-size must be at least 1")
    dynamodb = _dynamodb()
    client = dynamodb.meta.client
    for table_name, info in manifest["dynamodb"].items():
        schema = json.loads((directory / "dynamodb" / info["schema"]).read_text(encoding="utf-8"))
        try:
            existing_schema = client.describe_table(TableName=table_name)["Table"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
            global_indexes = [
                {
                    "IndexName": index["IndexName"],
                    "KeySchema": index["KeySchema"],
                    "Projection": index["Projection"],
                }
                for index in schema.get("GlobalSecondaryIndexes", [])
            ]
            client.create_table(
                TableName=table_name,
                KeySchema=schema["KeySchema"],
                AttributeDefinitions=schema["AttributeDefinitions"],
                BillingMode=schema.get("BillingModeSummary", {}).get("BillingMode", "PAY_PER_REQUEST"),
                **({"GlobalSecondaryIndexes": global_indexes} if global_indexes else {}),
            )
            dynamodb.Table(table_name).wait_until_exists()
        else:
            _validate_table_schema(table_name, schema, existing_schema)
        table = dynamodb.Table(table_name)
        with (directory / "dynamodb" / f"{table_name}.items.jsonl").open(encoding="utf-8") as stream:
            with table.batch_writer() as batch:
                for line in stream:
                    item = json.loads(line)
                    batch.put_item(Item={key: _DESERIALIZER.deserialize(value) for key, value in item.items()})
        print(f"Restored DynamoDB {table_name}: {info['items']} items")

    if not skip_object_storage and manifest.get("object_storage"):
        s3 = _s3()
        for obj in manifest["object_storage"]["objects"]:
            s3.upload_file(str(directory / obj["path"]), manifest["object_storage"]["bucket"], obj["key"])
        print(f"Restored object storage: {len(manifest['object_storage']['objects'])} objects")

    snapshot = manifest.get("opensearch")
    if snapshot:
        os_client = _opensearch()
        index = snapshot["index"]
        if os_client.indices.exists(index=index):
            os_client.indices.delete(index=index)
        index_dir = directory / "opensearch"
        mapping = json.loads((index_dir / "mapping.json").read_text(encoding="utf-8"))
        settings = json.loads((index_dir / "settings.json").read_text(encoding="utf-8"))
        if set(settings) == {"settings"}:
            settings = settings["settings"]
        settings = {
            key: value
            for key, value in settings.items()
            if key not in {"provided_name", "creation_date", "uuid", "version", "routing"}
        }
        os_client.indices.create(index=index, body={"settings": settings, "mappings": mapping})
        actions = []
        checkpoint_path = checkpoint or directory / "opensearch.restore.checkpoint"
        start_at = int(checkpoint_path.read_text(encoding="utf-8").strip() or "0") if resume and checkpoint_path.is_file() else 0
        processed = 0
        with (index_dir / "documents.jsonl").open(encoding="utf-8") as document_stream:
            for line in document_stream:
                if processed < start_at:
                    processed += 1
                    continue
                document = json.loads(line)
                actions.append({"_op_type": "index", "_index": index, "_id": document["id"], "_source": document["source"]})
                processed += 1
                if len(actions) >= os_bulk_size:
                    helpers.bulk(os_client, actions, chunk_size=os_bulk_size, raise_on_error=True)
                    actions.clear()
                    checkpoint_path.write_text(f"{processed}\n", encoding="utf-8")
        if actions:
            helpers.bulk(os_client, actions, chunk_size=os_bulk_size, raise_on_error=True)
        checkpoint_path.write_text(f"{processed}\n", encoding="utf-8")
        print(f"Restored OpenSearch {index}: {snapshot['documents']} documents")


def list_backups() -> None:
    backup_root = REPO_ROOT / BACKUP_ROOT
    if not backup_root.is_dir():
        print(f"No backups found in {BACKUP_ROOT}")
        return
    for directory in sorted((path for path in backup_root.iterdir() if path.is_dir()), reverse=True):
        manifest_path = directory / META_FILE
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        items = sum(table["items"] for table in manifest["dynamodb"].values())
        print(f"{directory}  DynamoDB items={items}; OpenSearch docs={manifest.get('opensearch', {}).get('documents', 0)}")


def prune(skip_object_storage: bool) -> None:
    dynamodb = _dynamodb()
    names = sorted(_configured_table_names() & set(dynamodb.meta.client.list_tables()["TableNames"]))
    for name in names:
        table = dynamodb.Table(name)
        schema = dynamodb.meta.client.describe_table(TableName=name)["Table"]
        key_names = [key["AttributeName"] for key in schema["KeySchema"]]
        page = table.scan(ProjectionExpression=", ".join(f"#{key}" for key in key_names), ExpressionAttributeNames={f"#{key}": key for key in key_names})
        while True:
            with table.batch_writer() as batch:
                for item in page["Items"]:
                    batch.delete_item(Key={key: item[key] for key in key_names})
            if not page.get("LastEvaluatedKey"):
                break
            page = table.scan(ExclusiveStartKey=page["LastEvaluatedKey"], ProjectionExpression=", ".join(f"#{key}" for key in key_names), ExpressionAttributeNames={f"#{key}": key for key in key_names})
        print(f"Pruned DynamoDB {name}")
    os_client = _opensearch()
    index = os.getenv("OPENSEARCH_INDEX", "fraud_knowledge")
    if os_client.indices.exists(index=index):
        os_client.delete_by_query(index=index, body={"query": {"match_all": {}}}, conflicts="proceed", refresh=True)
        print(f"Pruned OpenSearch {index}")
    if not skip_object_storage:
        s3 = _s3()
        bucket = os.getenv("OBJECT_STORAGE_BUCKET", "aria-reports")
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objects})
        print(f"Pruned object storage {bucket}")


def drop(skip_object_storage: bool) -> None:
    dynamodb = _dynamodb()
    names = sorted(_configured_table_names() & set(dynamodb.meta.client.list_tables()["TableNames"]), reverse=True)
    for name in names:
        table = dynamodb.Table(name)
        table.delete()
        table.wait_until_not_exists()
        print(f"Dropped DynamoDB {name}")
    os_client = _opensearch()
    index = os.getenv("OPENSEARCH_INDEX", "fraud_knowledge")
    if os_client.indices.exists(index=index):
        os_client.indices.delete(index=index)
        print(f"Dropped OpenSearch {index}")
    if not skip_object_storage:
        s3 = _s3()
        bucket = os.getenv("OBJECT_STORAGE_BUCKET", "aria-reports")
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": objects})
        s3.delete_bucket(Bucket=bucket)
        print(f"Dropped object storage bucket {bucket}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backup_parser = commands.add_parser("backup")
    backup_parser.add_argument("--dir", type=Path)
    backup_parser.add_argument("--skip-object-storage", action="store_true")
    restore_parser = commands.add_parser("restore")
    restore_parser.add_argument("--dir", type=Path, required=True)
    restore_parser.add_argument("--skip-object-storage", action="store_true")
    restore_parser.add_argument("--os-bulk-size", type=int, default=20)
    restore_parser.add_argument("--os-checkpoint-file", type=Path)
    restore_parser.add_argument("--resume-opensearch", action="store_true")
    commands.add_parser("list")
    for name in ("drop", "prune"):
        command_parser = commands.add_parser(name)
        command_parser.add_argument("--skip-object-storage", action="store_true")
    args = parser.parse_args()
    if args.command == "backup":
        backup(args.dir, args.skip_object_storage)
    elif args.command == "restore":
        restore(args.dir, args.skip_object_storage, args.os_bulk_size, args.os_checkpoint_file, args.resume_opensearch)
    elif args.command == "list":
        list_backups()
    elif args.command == "prune":
        prune(args.skip_object_storage)
    elif args.command == "drop":
        drop(args.skip_object_storage)


if __name__ == "__main__":
    try:
        main()
    except (ClientError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
