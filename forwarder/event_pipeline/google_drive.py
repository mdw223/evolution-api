"""Upload event flyer images to Google Drive (shared folder)."""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class GoogleDriveUploader:
    def __init__(self, folder_id: str, credentials_path: str | Path):
        self.folder_id = folder_id
        self.credentials_path = Path(credentials_path)
        self._service = None

    def available(self) -> bool:
        if not self.folder_id or not self.credentials_path.exists():
            return False
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds = service_account.Credentials.from_service_account_file(
                str(self.credentials_path),
                scopes=["https://www.googleapis.com/auth/drive.file"],
            )
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
            return True
        except Exception as exc:
            logger.warning("Google Drive uploader unavailable: %s", exc)
            return False

    def upload_image(
        self,
        image_base64: str,
        filename: str,
        mimetype: str = "image/jpeg",
    ) -> str | None:
        if not image_base64:
            return None
        if not self.available():
            logger.warning("Skipping Drive upload — credentials or folder not configured")
            return None

        try:
            from googleapiclient.http import MediaIoBaseUpload

            raw = base64.b64decode(image_base64)
            media = MediaIoBaseUpload(io.BytesIO(raw), mimetype=mimetype, resumable=False)
            metadata = {"name": filename, "parents": [self.folder_id]}

            file = (
                self._service.files()
                .create(body=metadata, media_body=media, fields="id")
                .execute()
            )
            file_id = file["id"]

            self._service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
            ).execute()

            url = f"https://drive.google.com/uc?id={file_id}"
            logger.info("Uploaded flyer to Drive: %s", url)
            return url
        except Exception as exc:
            logger.error("Drive upload failed: %s", exc)
            return None
