from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

from src.application.ports.object_storage_port import (
    ObjectStoragePort,
    ObjectStorageRef,
)
from src.infrastructure.core.config import genai_config


class MinioObjectStorageAdapter(ObjectStoragePort):
    def __init__(self) -> None:
        self._bucket = genai_config.OBJECT_STORAGE_BUCKET
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
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType=content_type,
        )
        return ObjectStorageRef(
            bucket=self._bucket,
            key=key,
            uri=f"s3://{self._bucket}/{key}",
        )
