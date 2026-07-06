"""Upload event flyer images to Cloudflare R2 (S3-compatible API)."""

from __future__ import annotations

import base64
import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class FlyerUploader(Protocol):
    def available(self) -> bool: ...

    def upload_image(
        self,
        image_base64: str,
        filename: str,
        mimetype: str = "image/jpeg",
    ) -> str | None: ...


class R2FlyerUploader:
    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        public_url_base: str,
        *,
        key_prefix: str = "flyers",
    ):
        self.account_id = account_id.strip()
        self.access_key_id = access_key_id.strip()
        self.secret_access_key = secret_access_key.strip()
        self.bucket_name = bucket_name.strip()
        self.public_url_base = public_url_base.rstrip("/")
        self.key_prefix = key_prefix.strip("/")
        self._client = None

    def available(self) -> bool:
        if not all(
            [
                self.account_id,
                self.access_key_id,
                self.secret_access_key,
                self.bucket_name,
                self.public_url_base,
            ]
        ):
            return False
        try:
            import boto3

            endpoint = f"https://{self.account_id}.r2.cloudflarestorage.com"
            self._client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
            )
            return True
        except Exception as exc:
            logger.warning("R2 uploader unavailable: %s", exc)
            return False

    def _object_key(self, filename: str) -> str:
        safe_name = filename.lstrip("/")
        if self.key_prefix:
            return f"{self.key_prefix}/{safe_name}"
        return safe_name

    def upload_image(
        self,
        image_base64: str,
        filename: str,
        mimetype: str = "image/jpeg",
    ) -> str | None:
        if not image_base64:
            return None
        if not self.available():
            logger.warning("Skipping R2 upload — credentials or config missing")
            return None

        try:
            raw = base64.b64decode(image_base64)
            key = self._object_key(filename)
            assert self._client is not None
            self._client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=raw,
                ContentType=mimetype,
            )
            url = f"{self.public_url_base}/{key}"
            logger.info("Uploaded flyer to R2: %s", url)
            return url
        except Exception as exc:
            logger.error("R2 upload failed: %s", exc)
            return None
