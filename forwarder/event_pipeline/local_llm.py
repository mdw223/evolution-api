"""Tier 2 local LLM extraction via Ollama."""

from __future__ import annotations

import json
import logging
import re
from datetime import date

import requests

from .debug_log import log_llm_raw
from .models import EventData, ExtractionResult, IncomingMessage
from .prompts import CLASSIFY_PROMPT, EXTRACT_PROMPT

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


class LocalLlmExtractor:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1:8b",
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            return any(self.model in name for name in models)
        except requests.RequestException:
            return False

    def _chat(self, prompt: str) -> str:
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def classify(self, text: str) -> tuple[bool, float, str]:
        prompt = CLASSIFY_PROMPT.format(text=text[:8000])
        try:
            raw = self._chat(prompt)
            log_llm_raw(logger, "Tier 2 Ollama", "classify", raw)
            data = _parse_json_block(raw)
            return bool(data.get("is_event")), float(data.get("confidence", 0.0)), raw
        except Exception as exc:
            logger.error("Tier 2 classify failed: %s", exc)
            return False, 0.0, ""

    def extract(self, text: str, message: IncomingMessage) -> tuple[EventData | None, str, str]:
        prompt = EXTRACT_PROMPT.format(text=text[:8000], today=date.today().isoformat())
        try:
            raw = self._chat(prompt)
            log_llm_raw(logger, "Tier 2 Ollama", "extract", raw)
            data = _parse_json_block(raw)
            name = (data.get("eventName") or "").strip()
            event_date = (data.get("eventDate") or "").strip()
            if not name or not event_date:
                missing = []
                if not name:
                    missing.append("eventName")
                if not event_date:
                    missing.append("eventDate")
                return None, raw, f"missing_fields:{','.join(missing)}"
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
                raw_message_text=text[:4000],
                extraction_tier="tier2",
            )
            return event, raw, ""
        except Exception as exc:
            logger.error("Tier 2 extract failed: %s", exc)
            return None, "", f"parse_error:{exc}"

    def classify_and_extract(self, text: str, message: IncomingMessage) -> ExtractionResult:
        is_event, confidence, classify_raw = self.classify(text)
        if not is_event:
            return ExtractionResult(
                is_event=False,
                confidence=confidence,
                classify_raw=classify_raw,
                failure_reason="classifier_said_not_event",
            )

        event, extract_raw, failure = self.extract(text, message)
        if not event:
            return ExtractionResult(
                is_event=True,
                confidence=confidence,
                classify_raw=classify_raw,
                extract_raw=extract_raw,
                failure_reason=failure or "extract_incomplete",
            )

        event.confidence_score = confidence
        return ExtractionResult(
            is_event=True,
            confidence=confidence,
            event=event,
            classify_raw=classify_raw,
            extract_raw=extract_raw,
        )
