from __future__ import annotations

import re
from calendar import month_abbr, month_name
from datetime import date, timedelta

from .models import EventData, IncomingMessage

MONTHS = {
    name.lower(): idx
    for idx, name in enumerate(month_name)
    if name
}
MONTHS.update({abbr.lower().rstrip("."): idx for idx, abbr in enumerate(month_abbr) if abbr})

DATE_NUMERIC = re.compile(
    r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b",
)
DATE_NAMED = re.compile(
    r"\b("
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:,?\s+\d{4})?"
    r"|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:\s+\d{4})?"
    r")\b",
    re.IGNORECASE,
)
TIME_12H = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)\b",
    re.IGNORECASE,
)
TIME_24H = re.compile(r"\b(\d{1,2}):(\d{2})\b")
LOCATION_LABEL = re.compile(
    r"(?i)(?:location|venue|address):?\s+(.+?)(?:\n|$)",
)


def _normalize_month_token(token: str) -> int | None:
    key = token.lower().rstrip(".")
    if key in MONTHS:
        return MONTHS[key]
    for month_key, idx in MONTHS.items():
        if month_key.startswith(key[:3]):
            return idx
    return None


def _parse_date_token(token: str, today: date | None = None) -> date | None:
    today = today or date.today()
    lowered = token.lower().strip()

    if lowered == "today":
        return today
    if lowered in {"tomorrow", "tonight"}:
        return today + timedelta(days=1)

    numeric = DATE_NUMERIC.search(token)
    if numeric:
        month = int(numeric.group(1))
        day = int(numeric.group(2))
        year = int(numeric.group(3)) if numeric.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None

    named = DATE_NAMED.search(token)
    if not named:
        return None

    fragment = named.group(1)
    parts = re.split(r"\s+", fragment.replace(",", " "))
    parts = [p for p in parts if p]

    if len(parts) >= 2 and _normalize_month_token(parts[0]):
        month = _normalize_month_token(parts[0])
        day = int(re.sub(r"\D", "", parts[1]))
        year = today.year
        if len(parts) >= 3 and parts[2].isdigit():
            year = int(parts[2])
        try:
            parsed = date(year, month, day)
            if parsed < today and year == today.year:
                parsed = date(year + 1, month, day)
            return parsed
        except (TypeError, ValueError):
            return None

    if len(parts) >= 2 and parts[0].isdigit() and _normalize_month_token(parts[1]):
        day = int(parts[0])
        month = _normalize_month_token(parts[1])
        year = today.year
        if len(parts) >= 3 and parts[2].isdigit():
            year = int(parts[2])
        try:
            parsed = date(year, month, day)
            if parsed < today and year == today.year:
                parsed = date(year + 1, month, day)
            return parsed
        except (TypeError, ValueError):
            return None

    return None


def _parse_time(text: str) -> str | None:
    match = TIME_12H.search(text)
    if match:
        hour = int(match.group(1)) % 12
        minute = int(match.group(2) or 0)
        meridiem = match.group(3).lower()
        if meridiem.startswith("p"):
            hour += 12
        return f"{hour:02d}:{minute:02d}:00"

    match = TIME_24H.search(text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour < 24 and minute < 60:
            return f"{hour:02d}:{minute:02d}:00"
    return None


def _guess_event_name(text: str) -> str | None:
    for line in text.splitlines():
        candidate = line.strip(" -*•\t")
        if len(candidate) < 8:
            continue
        if DATE_NUMERIC.search(candidate) and len(candidate) < 20:
            continue
        if candidate.lower().startswith(("location:", "address:", "time:", "date:")):
            continue
        return candidate[:200]
    return None


def _guess_location(text: str) -> str | None:
    match = LOCATION_LABEL.search(text)
    if match:
        value = match.group(1).strip()
        if value and len(value) >= 4:
            return value[:300]
    return None


class Tier1Extractor:
    def extract(self, message: IncomingMessage, *, confidence: float) -> EventData | None:
        text = (message.text or "").strip()
        if not text:
            return None

        event_date = None
        for token in re.split(r"[\n,;|]", text):
            parsed = _parse_date_token(token)
            if parsed:
                event_date = parsed.isoformat()
                break
        if not event_date:
            parsed = _parse_date_token(text)
            if parsed:
                event_date = parsed.isoformat()

        event_name = _guess_event_name(text)
        if not event_name or not event_date:
            return None

        return EventData(
            event_name=event_name,
            event_date=event_date,
            event_host_organization=message.group_name,
            event_description=text[:4000],
            event_location=_guess_location(text),
            event_start_time=_parse_time(text),
            whatsapp_message_id=message.message_id,
            source_group_jid=message.remote_jid,
            source_group_name=message.group_name,
            confidence_score=confidence,
            extraction_tier="tier1",
            raw_message_text=text,
        )

    def extract_preview(self, message: IncomingMessage) -> dict[str, str | None]:
        """Return Tier 1 field guesses even when extraction is incomplete."""
        text = (message.text or "").strip()
        if not text:
            return {"event_name": None, "event_date": None, "event_location": None, "event_start_time": None}

        event_date = None
        for token in re.split(r"[\n,;|]", text):
            parsed = _parse_date_token(token)
            if parsed:
                event_date = parsed.isoformat()
                break
        if not event_date:
            parsed = _parse_date_token(text)
            if parsed:
                event_date = parsed.isoformat()

        return {
            "event_name": _guess_event_name(text),
            "event_date": event_date,
            "event_location": _guess_location(text),
            "event_start_time": _parse_time(text),
        }
