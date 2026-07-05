from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_INGEST = "http://localhost:5177/api/events/ingest"
DEFAULT_LOCAL_API_PORT = 5177


def _ingest_to_events_url(ingest_url: str) -> str:
    base = ingest_url.rstrip("/")
    if base.endswith("/api/events/ingest"):
        return base[: -len("/ingest")]
    parsed = urlparse(base)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    host = parsed.hostname or "localhost"
    return f"{parsed.scheme}://{host}:{port}/api/events"


def probe_events_api(events_url: str, timeout: float = 2.0) -> bool:
    try:
        resp = requests.get(events_url, timeout=timeout)
        if resp.status_code != 200:
            return False
        body = resp.json()
        return isinstance(body, dict) and "events" in body
    except (requests.RequestException, ValueError):
        return False


def resolve_ingest_url(pipeline_cfg: dict) -> tuple[str, str]:
    """
    Pick ingest URL: local dev API if reachable, else Vercel fallback.

    Returns (ingest_url, label) where label is 'local' or 'vercel'.
    """
    local_ingest = (
        pipeline_cfg.get("ingest_url_local") or DEFAULT_LOCAL_INGEST
    ).strip().rstrip("/")
    remote_ingest = pipeline_cfg.get("ingest_url", "").strip().rstrip("/")
    prefer_local = pipeline_cfg.get("prefer_local_ingest", True)

    if prefer_local:
        local_events = _ingest_to_events_url(local_ingest)
        if probe_events_api(local_events):
            logger.info("Using local ingest API: %s", local_ingest)
            return local_ingest, "local"
        logger.info("Local API not reachable at %s — trying Vercel fallback", local_events)

    if remote_ingest:
        logger.info("Using Vercel ingest API: %s", remote_ingest)
        return remote_ingest, "vercel"

    if prefer_local:
        raise ValueError(
            "Local ingest API is not running and event_pipeline.ingest_url is not set. "
            "Start nctrianglemuslims-ui with `pnpm dev:api` or set ingest_url to Vercel."
        )
    raise ValueError("event_pipeline.ingest_url is required")


def resolve_events_api_url(pipeline_cfg: dict) -> tuple[str, str]:
    """Same resolution as ingest, but returns GET /api/events base URL."""
    ingest_url, label = resolve_ingest_url(pipeline_cfg)
    return _ingest_to_events_url(ingest_url), label
