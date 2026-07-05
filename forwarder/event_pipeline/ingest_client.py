from __future__ import annotations

import logging

import requests

from .models import EventData

logger = logging.getLogger(__name__)


class IngestClient:
    def __init__(self, ingest_url: str, api_key: str, timeout: int = 30):
        self.ingest_url = ingest_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    def create_event(self, event: EventData) -> dict:
        payload = event.to_ingest_payload()
        logger.info(
            "Ingesting event name=%r date=%s status=%s tier=%s",
            event.event_name,
            event.event_date,
            event.status,
            event.extraction_tier,
        )
        resp = self.session.post(self.ingest_url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        body = resp.json()
        logger.info("Ingest response: %s", body.get("status", body))
        return body
