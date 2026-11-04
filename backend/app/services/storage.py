"""File storage for uploaded briefs and exports: local disk (dev) or Amazon S3 (prod)."""
from __future__ import annotations

import os
import uuid

from ..config import get_settings


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:120]


def save(prefix: str, filename: str, content: bytes, content_type: str = "application/octet-stream") -> str:
    s = get_settings()
    key = f"{prefix}/{uuid.uuid4().hex[:12]}-{_safe(filename)}"
    if s.storage_backend == "s3":
        import boto3

        boto3.client("s3", region_name=s.aws_region).put_object(
            Bucket=s.s3_bucket, Key=key, Body=content, ContentType=content_type, ServerSideEncryption="AES256")
    else:
        path = os.path.join(s.storage_local_dir, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(content)
    return key


def check() -> bool:
    s = get_settings()
    if s.storage_backend == "s3":
        import boto3

        boto3.client("s3", region_name=s.aws_region).head_bucket(Bucket=s.s3_bucket)
        return True
    os.makedirs(s.storage_local_dir, exist_ok=True)
    return os.access(s.storage_local_dir, os.W_OK)
