"""Tier 3 cloud LLM fallback via Google Gemini."""

from __future__ import annotations

import json
import logging
import re
from datetime import date

import requests

from .models import EventData, ExtractionResult, IncomingMessage
from .prompts import CLASSIFY_PROMPT, EXTRACT_PROMPT, GEMINI_VISION_EXTRACT_PROMPT

logger = logging.getLogger(__name__)


def _parse_json_block(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _normalize_time(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if re.match(r"^\d{2}:\d{2}:\d{2}$", value):
        return value
    if re.match(r"^\d{2}:\d{2}$", value):
        return f"{value}:00"
    return value


class CloudLlmExtractor:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        timeout: int = 90,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def available(self) -> bool:
        return bool(self.api_key)

    def _generate(self, parts: list[dict]) -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        resp = requests.post(
            url,
            params={"key": self.api_key},
            json={"contents": [{"parts": parts}]},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        body = resp.json()
        candidates = body.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini returned no candidates")
        content_parts = candidates[0].get("content", {}).get("parts") or []
        texts = [p.get("text", "") for p in content_parts if p.get("text")]
        return "".join(texts)

    def classify_and_extract(
        self,
        text: str,
        message: IncomingMessage,
        *,
        image_base64: str | None = None,
        ocr_text: str = "",
    ) -> ExtractionResult:
        if not self.available():
            return ExtractionResult(is_event=False, confidence=0.0)

        try:
            if image_base64:
                prompt = GEMINI_VISION_EXTRACT_PROMPT.format(
                    ocr_text=ocr_text or text,
                    today=date.today().isoformat(),
                )
                parts = [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_base64,
                        }
                    },
                ]
            else:
                classify_raw = self._generate([{"text": CLASSIFY_PROMPT.format(text=text[:8000])}])
                classify_data = _parse_json_block(classify_raw)
                if not classify_data.get("is_event"):
                    return ExtractionResult(
                        is_event=False,
                        confidence=float(classify_data.get("confidence", 0.0)),
                        raw_response=classify_raw,
                    )
                prompt = EXTRACT_PROMPT.format(text=text[:8000], today=date.today().isoformat())
                parts = [{"text": prompt}]

            raw = self._generate(parts)
            data = _parse_json_block(raw)

            if image_base64 and "is_event" in data and not data.get("is_event"):
                return ExtractionResult(
                    is_event=False,
                    confidence=float(data.get("confidence", 0.0)),
                    raw_response=raw,
                )

            confidence = float(data.get("confidence", 0.7))
            name = (data.get("eventName") or "").strip()
            event_date = (data.get("eventDate") or "").strip()
            if not name or not event_date:
                return ExtractionResult(is_event=True, confidence=confidence, raw_response=raw)

            event = EventData(
                event_name=name[:200],
                event_date=event_date[:10],
                event_host_organization=(data.get("eventHostOrganization") or message.group_name) or None,
                event_description=(data.get("eventDescription") or text[:4000]) or None,
                event_location=(data.get("eventLocation") or None),
                event_start_time=_normalize_time(data.get("eventStartTime")),
                event_end_time=_normalize_time(data.get("eventEndTime")),
                whatsapp_message_id=message.message_id,
                source_group_jid=message.remote_jid,
                source_group_name=message.group_name,
                confidence_score=confidence,
                extraction_tier="tier3",
                raw_message_text=text[:4000],
            )
            return ExtractionResult(is_event=True, confidence=confidence, event=event, raw_response=raw)
        except Exception as exc:
            logger.error("Tier 3 Gemini failed: %s", exc)
            return ExtractionResult(is_event=False, confidence=0.0)
