from __future__ import annotations

from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from src.application.ports.object_storage_port import (
    ObjectStoragePort,
    ObjectStorageRef,
)
from src.infrastructure.core.config import genai_config


class MinioObjectStorageAdapter(ObjectStoragePort):
    def __init__(self, bucket: str | None = None) -> None:
        self._bucket = bucket or genai_config.OBJECT_STORAGE_BUCKET
        self._client = boto3.client(
            "s3",
            endpoint_url=genai_config.OBJECT_STORAGE_ENDPOINT,
            region_name=genai_config.OBJECT_STORAGE_REGION,
            aws_access_key_id=genai_config.OBJECT_STORAGE_ACCESS_KEY,
            aws_secret_access_key=genai_config.OBJECT_STORAGE_SECRET_KEY,
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def put_text(
        self,
        key: str,
        content: str,
        content_type: str = "text/plain",
    ) -> ObjectStorageRef:
        return self.put_bytes(key, content.encode("utf-8"), content_type)

    def put_bytes(
        self,
        key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> ObjectStorageRef:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        return ObjectStorageRef(
            bucket=self._bucket,
            key=key,
            uri=f"s3://{self._bucket}/{key}",
        )

    def put_file(
        self,
        key: str,
        file: BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> ObjectStorageRef:
        # upload_fileobj uses S3 multipart uploads for large files, keeping
        # only a bounded transfer chunk in memory rather than the whole CSV.
        self._client.upload_fileobj(
            Fileobj=file,
            Bucket=self._bucket,
            Key=key,
            ExtraArgs={"ContentType": content_type},
        )
        return ObjectStorageRef(
            bucket=self._bucket,
            key=key,
            uri=f"s3://{self._bucket}/{key}",
        )

    def get_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def get_stream(self, key: str) -> BinaryIO:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"]

    def get_size(self, key: str) -> int:
        response = self._client.head_object(Bucket=self._bucket, Key=key)
        return int(response["ContentLength"])

    def list_keys(self, suffix: str = "") -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(suffix):
                    keys.append(obj["Key"])
        return keys

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)
