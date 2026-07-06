"""Tier 3 cloud LLM fallback via Google Gemini."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date

import requests

from .debug_log import log_llm_raw, parse_gemini_error, redact_secrets
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


def _parse_retry_seconds(error_details: dict) -> float | None:
    delay = error_details.get("retry_delay")
    if not delay:
        return None
    if isinstance(delay, str) and delay.endswith("s"):
        try:
            return float(delay[:-1])
        except ValueError:
            return None
    return None


class CloudLlmExtractor:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        timeout: int = 90,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def available(self) -> bool:
        return bool(self.api_key)

    def _generate(self, parts: list[dict], *, step: str = "response") -> str:
        url = f"{self.base_url}/models/{self.model}:generateContent"
        last_error: requests.HTTPError | None = None

        for attempt in range(2):
            resp = requests.post(
                url,
                params={"key": self.api_key},
                json={"contents": [{"parts": parts}]},
                timeout=self.timeout,
            )
            if resp.status_code == 429 and attempt == 0:
                details = parse_gemini_error(resp.text)
                wait = _parse_retry_seconds(details) or 30.0
                logger.warning(
                    "Tier 3 Gemini rate limited (429) on %s — retrying in %.0fs. Details: %s",
                    step,
                    wait,
                    details.get("message") or details,
                )
                time.sleep(min(wait, 60.0))
                continue

            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                last_error = exc
                details = parse_gemini_error(resp.text)
                logger.error(
                    "Tier 3 Gemini HTTP %s on %s: %s",
                    resp.status_code,
                    step,
                    details.get("message") or details,
                )
                if resp.status_code == 429:
                    logger.error(
                        "Gemini 429 likely cause: quota/rate limit exceeded for model=%s. "
                        "Check https://aistudio.google.com/usage — free tier may have 0 quota "
                        "for this model, or daily RPM/RPD limit hit. Enable billing or switch "
                        "gemini_model in config.yaml (e.g. gemini-2.5-flash).",
                        self.model,
                    )
                raise exc

            body = resp.json()
            candidates = body.get("candidates") or []
            if not candidates:
                raise ValueError("Gemini returned no candidates")
            content_parts = candidates[0].get("content", {}).get("parts") or []
            texts = [p.get("text", "") for p in content_parts if p.get("text")]
            raw = "".join(texts)
            log_llm_raw(logger, "Tier 3 Gemini", step, raw)
            return raw

        if last_error:
            raise last_error
        raise RuntimeError("Gemini request failed without response")

    def classify_and_extract(
        self,
        text: str,
        message: IncomingMessage,
        *,
        image_base64: str | None = None,
        ocr_text: str = "",
    ) -> ExtractionResult:
        if not self.available():
            return ExtractionResult(is_event=False, confidence=0.0, failure_reason="api_key_missing")

        classify_raw = ""
        extract_raw = ""

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
                extract_raw = self._generate(parts, step="vision_extract")
                data = _parse_json_block(extract_raw)

                if "is_event" in data and not data.get("is_event"):
                    return ExtractionResult(
                        is_event=False,
                        confidence=float(data.get("confidence", 0.0)),
                        extract_raw=extract_raw,
                        raw_response=extract_raw,
                        llm_fields=data,
                        failure_reason="classifier_said_not_event",
                    )
            else:
                classify_raw = self._generate(
                    [{"text": CLASSIFY_PROMPT.format(text=text[:8000])}],
                    step="classify",
                )
                classify_data = _parse_json_block(classify_raw)
                if not classify_data.get("is_event"):
                    return ExtractionResult(
                        is_event=False,
                        confidence=float(classify_data.get("confidence", 0.0)),
                        classify_raw=classify_raw,
                        raw_response=classify_raw,
                        failure_reason="classifier_said_not_event",
                    )
                prompt = EXTRACT_PROMPT.format(text=text[:8000], today=date.today().isoformat())
                extract_raw = self._generate([{"text": prompt}], step="extract")
                data = _parse_json_block(extract_raw)

            confidence = float(data.get("confidence", 0.7))
            name = (data.get("eventName") or "").strip()
            event_date = (data.get("eventDate") or "").strip()
            if not name or not event_date:
                missing = []
                if not name:
                    missing.append("eventName")
                if not event_date:
                    missing.append("eventDate")
                return ExtractionResult(
                    is_event=True,
                    confidence=confidence,
                    classify_raw=classify_raw,
                    extract_raw=extract_raw,
                    raw_response=extract_raw or classify_raw,
                    llm_fields=data,
                    failure_reason=f"missing_fields:{','.join(missing)}",
                )

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
            return ExtractionResult(
                is_event=True,
                confidence=confidence,
                event=event,
                classify_raw=classify_raw,
                extract_raw=extract_raw,
                raw_response=extract_raw or classify_raw,
                llm_fields=data,
            )
        except requests.HTTPError as exc:
            details = parse_gemini_error(exc.response.text if exc.response else "")
            reason = f"http_{exc.response.status_code if exc.response else 'error'}"
            if exc.response and exc.response.status_code == 429:
                reason = "rate_limit_429"
            logger.error(
                "Tier 3 Gemini failed: %s",
                redact_secrets(str(details.get("message") or exc)),
            )
            return ExtractionResult(
                is_event=False,
                confidence=0.0,
                classify_raw=classify_raw,
                extract_raw=extract_raw,
                failure_reason=reason,
            )
        except Exception as exc:
            logger.error("Tier 3 Gemini failed: %s", exc)
            return ExtractionResult(
                is_event=False,
                confidence=0.0,
                classify_raw=classify_raw,
                extract_raw=extract_raw,
                failure_reason=f"error:{exc}",
            )
