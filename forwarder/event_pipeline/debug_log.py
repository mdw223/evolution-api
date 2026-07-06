"""Structured logging helpers for pipeline tier debugging."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .models import EventData, ExtractionResult

MAX_RAW_LOG = 2000


def truncate_raw(text: str, max_len: int = MAX_RAW_LOG) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def event_snapshot(event: EventData | None) -> dict[str, Any]:
    if not event:
        return {"complete": False}
    return {
        "complete": True,
        "eventName": event.event_name,
        "eventDate": event.event_date,
        "eventHostOrganization": event.event_host_organization,
        "eventLocation": event.event_location,
        "eventStartTime": event.event_start_time,
        "eventEndTime": event.event_end_time,
        "status": event.status,
        "extractionTier": event.extraction_tier,
        "confidenceScore": event.confidence_score,
    }


def log_llm_raw(logger: logging.Logger, tier: str, step: str, raw: str) -> None:
    if not raw:
        logger.info("%s %s response: (empty)", tier, step)
        return
    logger.info(
        "%s %s response (%d chars): %s",
        tier,
        step,
        len(raw),
        truncate_raw(raw),
    )


def log_tier_outcome(
    logger: logging.Logger,
    tier: str,
    message_id: str,
    *,
    event: EventData | None = None,
    is_event: bool | None = None,
    confidence: float | None = None,
    failure_reason: str | None = None,
    fields: dict[str, Any] | None = None,
) -> None:
    parts: list[str] = []
    if is_event is not None:
        parts.append(f"is_event={is_event}")
    if confidence is not None:
        parts.append(f"confidence={confidence:.2f}")
    if failure_reason:
        parts.append(f"reason={failure_reason}")
    if event:
        parts.append(f"event={event_snapshot(event)}")
    elif fields:
        parts.append(f"fields={fields}")
    else:
        parts.append("event=none")
    logger.info("Pipeline %s outcome id=%s %s", tier, message_id, " ".join(parts))


def log_extraction_result(
    logger: logging.Logger,
    tier: str,
    message_id: str,
    result: ExtractionResult,
) -> None:
    if result.classify_raw:
        log_llm_raw(logger, tier, "classify", result.classify_raw)
    if result.extract_raw:
        log_llm_raw(logger, tier, "extract", result.extract_raw)
    if result.raw_response and not result.extract_raw and not result.classify_raw:
        log_llm_raw(logger, tier, "response", result.raw_response)
    log_tier_outcome(
        logger,
        tier,
        message_id,
        event=result.event,
        is_event=result.is_event,
        confidence=result.confidence,
        failure_reason=result.failure_reason or None,
    )


def redact_secrets(text: str) -> str:
    return re.sub(r"key=[A-Za-z0-9_-]+", "key=***REDACTED***", text)


def parse_gemini_error(response_text: str) -> dict[str, Any]:
    if not response_text:
        return {}
    try:
        body = json.loads(response_text)
    except json.JSONDecodeError:
        return {"message": truncate_raw(response_text, 500)}
    error = body.get("error") or {}
    details: dict[str, Any] = {
        "code": error.get("code"),
        "status": error.get("status"),
        "message": error.get("message"),
    }
    for item in error.get("details") or []:
        if item.get("@type", "").endswith("RetryInfo"):
            details["retry_delay"] = item.get("retryDelay")
        if item.get("@type", "").endswith("QuotaFailure"):
            details["quota_violations"] = item.get("violations")
    return details
