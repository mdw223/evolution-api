from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EventStatus = Literal["published", "draft", "hidden"]


@dataclass
class IncomingMessage:
    message_id: str
    remote_jid: str
    group_name: str
    sender_name: str
    text: str
    has_image: bool
    raw_data: dict[str, Any] = field(repr=False)


@dataclass
class ClassificationResult:
    score: float
    action: Literal["reject", "pass", "force_pass"]
    matched_keywords: list[str] = field(default_factory=list)
    matched_phrases: list[str] = field(default_factory=list)
    ocr_text: str = ""
    combined_text: str = ""


@dataclass
class ExtractionResult:
    is_event: bool
    confidence: float
    event: EventData | None = None
    raw_response: str = ""


@dataclass
class EventData:
    event_name: str
    event_date: str  # YYYY-MM-DD
    event_host_organization: str | None = None
    event_description: str | None = None
    event_location: str | None = None
    event_start_time: str | None = None  # HH:MM:SS
    event_end_time: str | None = None
    flyer_url: str | None = None
    status: EventStatus = "draft"
    whatsapp_message_id: str | None = None
    source_group_jid: str | None = None
    source_group_name: str | None = None
    confidence_score: float | None = None
    extraction_tier: str | None = None
    raw_message_text: str | None = None

    def to_ingest_payload(self) -> dict[str, Any]:
        return {
            "eventName": self.event_name,
            "eventDate": self.event_date,
            "eventHostOrganization": self.event_host_organization,
            "eventDescription": self.event_description,
            "eventLocation": self.event_location,
            "eventStartTime": self.event_start_time,
            "eventEndTime": self.event_end_time,
            "flyerUrl": self.flyer_url,
            "status": self.status,
            "whatsappMessageId": self.whatsapp_message_id,
            "sourceGroupJid": self.source_group_jid,
            "sourceGroupName": self.source_group_name,
            "confidenceScore": self.confidence_score,
            "extractionTier": self.extraction_tier,
            "rawMessageText": self.raw_message_text,
        }
