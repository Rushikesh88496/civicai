"""MinIO / S3-compatible object storage backend backed by ``boto3``.

Works with any S3-compatible service — including a locally run MinIO server
pointed at via ``S3_ENDPOINT_URL`` (e.g. http://localhost:9000).
"""

from __future__ import annotations

import boto3
from botocore.config import Config

from app.core.config import Settings
from app.storage.base import Storage


class S3Storage(Storage):
    """S3-compatible backend. The bucket must already exist."""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.STORAGE_BUCKET
        self._public_base = (settings.S3_PUBLIC_BASE_URL or "").rstrip("/")
        client_config = Config(
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 3, "mode": "standard"},
            s3={"addressing_style": "path"},
        )
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            use_ssl=settings.S3_SECURE,
            config=client_config,
        )
        self._ensure_bucket()

    @property
    def backend_name(self) -> str:
        return "s3"

    def _ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception:
            self._client.create_bucket(Bucket=self._bucket)

    def upload(self, key: str, data: bytes, content_type: str) -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return self.url(key)

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception:
            pass

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    def read(self, key: str) -> bytes:
        obj = self._client.get_object(Bucket=self._bucket, Key=key)
        return obj["Body"].read()

    def url(self, key: str) -> str:
        if self._public_base:
            return f"{self._public_base}/{key}"
        endpoint = "localhost:9000"
        try:
            endpoint = self._client.meta.endpoint_url.replace("http://", "").replace("https://", "")
        except Exception:
            pass
        return f"http://{endpoint}/{self._bucket}/{key}"
