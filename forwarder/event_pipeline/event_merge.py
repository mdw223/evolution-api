"""Merge partial event fields across Tier 1 → 2 → 3 extractions."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, fields
from datetime import date, timedelta
from typing import Any

from .models import EventData, EventStatus, IncomingMessage

logger = logging.getLogger(__name__)

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_LLM_FIELD_MAP = {
    "eventName": "event_name",
    "eventDate": "event_date",
    "eventHostOrganization": "event_host_organization",
    "eventDescription": "event_description",
    "eventLocation": "event_location",
    "eventStartTime": "event_start_time",
    "eventEndTime": "event_end_time",
}


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in ("null", "none", "n/a"):
            return None
        return text
    return str(value).strip() or None


def _normalize_time(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if re.match(r"^\d{2}:\d{2}:\d{2}$", value):
        return value
    if re.match(r"^\d{2}:\d{2}$", value):
        return f"{value}:00"
    return value


def infer_recurring_date(text: str, today: date | None = None) -> str | None:
    """Best-effort next occurrence for 'every Monday' style copy (admin can fix recurring later)."""
    today = today or date.today()
    lowered = text.lower()
    for day_name, weekday in _WEEKDAYS.items():
        if re.search(rf"\bevery\s+{day_name}\b", lowered) or re.search(
            rf"\bweekly\s+on\s+{day_name}\b", lowered
        ):
            days_ahead = (weekday - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (today + timedelta(days=days_ahead)).isoformat()
    return None


@dataclass
class PartialEvent:
    event_name: str | None = None
    event_date: str | None = None
    event_host_organization: str | None = None
    event_description: str | None = None
    event_location: str | None = None
    event_start_time: str | None = None
    event_end_time: str | None = None
    flyer_url: str | None = None
    status: EventStatus = "draft"
    whatsapp_message_id: str | None = None
    source_group_jid: str | None = None
    source_group_name: str | None = None
    confidence_score: float | None = None
    extraction_tier: str = "tier1"
    raw_message_text: str | None = None

    @classmethod
    def from_preview(
        cls,
        preview: dict[str, str | None],
        message: IncomingMessage,
        text: str,
        *,
        confidence: float,
        tier: str = "tier1",
    ) -> PartialEvent:
        return cls(
            event_name=preview.get("event_name"),
            event_date=preview.get("event_date"),
            event_location=preview.get("event_location"),
            event_start_time=preview.get("event_start_time"),
            event_host_organization=message.group_name,
            event_description=text[:4000] if text else None,
            whatsapp_message_id=message.message_id,
            source_group_jid=message.remote_jid,
            source_group_name=message.group_name,
            confidence_score=confidence,
            extraction_tier=tier,
            raw_message_text=text[:4000] if text else None,
        )

    @classmethod
    def from_event(cls, event: EventData) -> PartialEvent:
        return cls(
            event_name=event.event_name,
            event_date=event.event_date,
            event_host_organization=event.event_host_organization,
            event_description=event.event_description,
            event_location=event.event_location,
            event_start_time=event.event_start_time,
            event_end_time=event.event_end_time,
            flyer_url=event.flyer_url,
            status=event.status,
            whatsapp_message_id=event.whatsapp_message_id,
            source_group_jid=event.source_group_jid,
            source_group_name=event.source_group_name,
            confidence_score=event.confidence_score,
            extraction_tier=event.extraction_tier or "tier1",
            raw_message_text=event.raw_message_text,
        )

    def merge_llm_data(self, data: dict[str, Any], *, tier: str, confidence: float | None = None) -> None:
        """Apply non-empty LLM JSON fields; later tiers override earlier values."""
        for llm_key, attr in _LLM_FIELD_MAP.items():
            value = _clean_value(data.get(llm_key))
            if attr in ("event_start_time", "event_end_time"):
                value = _normalize_time(value)
            if value:
                setattr(self, attr, value[:200] if attr == "event_name" else value[:10] if attr == "event_date" else value)
        self.extraction_tier = tier
        if confidence is not None:
            self.confidence_score = confidence

    def merge_other(self, other: PartialEvent, *, tier: str) -> None:
        """Merge another partial snapshot; non-empty fields from other win."""
        for field in fields(PartialEvent):
            if field.name in ("status", "extraction_tier"):
                continue
            value = getattr(other, field.name)
            if value is not None and value != "":
                setattr(self, field.name, value)
        self.extraction_tier = tier

    def has_name(self) -> bool:
        return bool(self.event_name)

    def has_date(self) -> bool:
        return bool(self.event_date)

    def is_complete(self) -> bool:
        return self.has_name() and self.has_date()

    def can_ingest(self) -> bool:
        return self.has_name() and self.resolve_date() is not None

    def can_publish(self, min_confidence: float) -> bool:
        return self.is_complete() and (self.confidence_score or 0) >= min_confidence

    def resolve_date(self) -> str | None:
        if self.event_date:
            return self.event_date[:10]
        return infer_recurring_date(self.raw_message_text or "")

    def snapshot(self) -> dict[str, Any]:
        return {
            "event_name": self.event_name,
            "event_date": self.event_date,
            "event_host_organization": self.event_host_organization,
            "event_location": self.event_location,
            "event_start_time": self.event_start_time,
            "event_end_time": self.event_end_time,
            "extraction_tier": self.extraction_tier,
            "confidence_score": self.confidence_score,
        }

    def to_event_data(self, *, infer_date: bool = False) -> EventData | None:
        resolved_date = self.resolve_date() if infer_date else (self.event_date[:10] if self.event_date else None)
        if not self.event_name or not resolved_date:
            return None
        return EventData(
            event_name=self.event_name[:200],
            event_date=resolved_date,
            event_host_organization=self.event_host_organization,
            event_description=self.event_description,
            event_location=self.event_location,
            event_start_time=self.event_start_time,
            event_end_time=self.event_end_time,
            flyer_url=self.flyer_url,
            status=self.status,
            whatsapp_message_id=self.whatsapp_message_id,
            source_group_jid=self.source_group_jid,
            source_group_name=self.source_group_name,
            confidence_score=self.confidence_score,
            extraction_tier=self.extraction_tier,
            raw_message_text=self.raw_message_text,
        )

    def log_snapshot(self, tier: str, message_id: str) -> None:
        logger.info(
            "Pipeline %s accumulated id=%s %s",
            tier,
            message_id,
            self.snapshot(),
        )
