#!/usr/bin/env python3
"""
Replay event pipeline against real Sheets/API data (Tier 1 + OCR + optional Tier 2).

Downloads flyer images from flyerURL when present, runs easyocr before scoring,
and optionally escalates to Ollama Tier 2 on reject or incomplete Tier 1 extraction.
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

import requests
import yaml

FORWARDER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FORWARDER_DIR))

from event_pipeline.classifier import EventClassifier
from event_pipeline.extractor import Tier1Extractor
from event_pipeline.ingest_client import IngestClient
from event_pipeline.ingest_resolver import resolve_ingest_url
from event_pipeline.local_llm import LocalLlmExtractor
from event_pipeline.models import EventData, IncomingMessage
from event_pipeline.ocr import FlyerOcr

DEFAULT_SHEETS_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRRLfgooQ_mjspJLBGAnexTkhk1TzfEEaZCXDwbPIzjhUrgx53TKKdN3Xxe9wjJ0bbPmxpTjYx1udpC/pub?gid=125079037&single=true&output=csv"
)

_flyer_cache: dict[str, str | None] = {}


@dataclass
class ReplayRow:
    row_id: str
    name: str
    host: str
    date: str
    description: str
    location: str
    flyer_url: str = ""


@dataclass
class ReplayResult:
    row: ReplayRow
    score: float
    action: str
    matched_keywords: list[str]
    extracted: bool
    would_publish: bool
    extraction_tier: str = "none"
    ocr_chars: int = 0
    had_flyer: bool = False
    tier2_ran: bool = False
    extracted_name: str | None = None
    extracted_date: str | None = None
    event: EventData | None = None
    ingest_status: str | None = None


def load_pipeline_config() -> dict:
    with open(FORWARDER_DIR / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("event_pipeline") or {}


def load_env_value(key: str) -> str:
    env_path = FORWARDER_DIR.parent / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def build_message_text(row: ReplayRow) -> str:
    parts = [row.name]
    if row.description and row.description.strip() != row.name.strip():
        parts.append(row.description)
    if row.location:
        parts.append(f"Location: {row.location}")
    if row.date:
        parts.append(row.date)
    return "\n".join(p for p in parts if p).strip()


def download_flyer_base64(url: str) -> str | None:
    if not url or not url.startswith("http"):
        return None
    if url in _flyer_cache:
        return _flyer_cache[url]
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        encoded = base64.b64encode(resp.content).decode("ascii")
        _flyer_cache[url] = encoded
        return encoded
    except Exception as exc:
        print(f"  WARN: flyer download failed ({url[:60]}…): {exc}", file=sys.stderr)
        _flyer_cache[url] = None
        return None


def load_rows_from_csv(csv_url: str, limit: int | None) -> list[ReplayRow]:
    with urlopen(csv_url, timeout=60) as resp:
        text = resp.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[ReplayRow] = []
    for raw in reader:
        name = (raw.get("name") or "").strip()
        date = (raw.get("date") or "").strip()
        if not name or not date:
            continue
        rows.append(
            ReplayRow(
                row_id=(raw.get("rowId") or raw.get("row_id") or str(len(rows) + 1)).strip(),
                name=name,
                host=(raw.get("host") or "").strip(),
                date=date,
                description=(raw.get("description") or "").strip(),
                location=(raw.get("location") or "").strip(),
                flyer_url=(raw.get("flyerURL") or raw.get("flyer_url") or "").strip(),
            )
        )
        if limit and len(rows) >= limit:
            break
    return rows


def load_rows_from_api(events_url: str, limit: int | None) -> list[ReplayRow]:
    resp = requests.get(events_url, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    rows: list[ReplayRow] = []
    for event in body.get("events") or []:
        rows.append(
            ReplayRow(
                row_id=str(event.get("rowId") or event.get("id") or len(rows) + 1),
                name=(event.get("name") or "").strip(),
                host=(event.get("host") or "").strip(),
                date=(event.get("date") or "").strip(),
                description=(event.get("description") or "").strip(),
                location=(event.get("location") or "").strip(),
                flyer_url=(event.get("flyerURL") or event.get("flyerUrl") or "").strip(),
            )
        )
        if limit and len(rows) >= limit:
            break
    return rows


def make_message(row: ReplayRow, text: str, has_image: bool) -> IncomingMessage:
    return IncomingMessage(
        message_id=f"replay-{row.row_id}",
        remote_jid="replay@g.us",
        group_name=row.host or "Replay",
        sender_name="Sheets Replay",
        text=text,
        has_image=has_image,
        raw_data={},
    )


def run_tier2(
    tier2: LocalLlmExtractor,
    message: IncomingMessage,
    text: str,
    tier2_publish_min: float,
) -> tuple[EventData | None, bool]:
    if not tier2.available():
        return None, False
    result = tier2.classify_and_extract(text, message)
    if not result.is_event or not result.event:
        return None, True
    event = result.event
    event.confidence_score = result.confidence
    event.extraction_tier = "tier2"
    event.status = "published" if result.confidence >= tier2_publish_min else "draft"
    return event, True


def replay_row(
    row: ReplayRow,
    classifier: EventClassifier,
    extractor: Tier1Extractor,
    tier2: LocalLlmExtractor | None,
    *,
    auto_publish_min_score: float,
    tier2_publish_min: float,
    use_tier2: bool,
    skip_ocr: bool,
) -> ReplayResult:
    text = build_message_text(row)
    image_b64: str | None = None
    has_image = False

    if row.flyer_url and not skip_ocr:
        image_b64 = download_flyer_base64(row.flyer_url)
        has_image = image_b64 is not None

    classification = classifier.classify(
        text,
        has_image=has_image,
        image_base64=image_b64,
    )
    combined_text = classification.combined_text or text
    message = make_message(row, combined_text, has_image)

    event = extractor.extract(message, confidence=classification.score)
    extraction_tier = "tier1"
    tier2_ran = False

    needs_tier2 = use_tier2 and tier2 and (
        classification.action == "reject"
        or (classification.action != "reject" and event is None)
    )

    if needs_tier2:
        event, tier2_ran = run_tier2(tier2, message, combined_text, tier2_publish_min)
        if event:
            extraction_tier = "tier2"
            classification.action = "pass" if event else classification.action

    would_publish = False
    if event and classification.action != "reject":
        if extraction_tier == "tier2":
            would_publish = event.status == "published"
        else:
            would_publish = classification.score >= auto_publish_min_score

    if event:
        event.extraction_tier = extraction_tier
        if extraction_tier == "tier1":
            event.confidence_score = classification.score
            if classification.action != "reject":
                event.status = "published" if would_publish else "draft"

    return ReplayResult(
        row=row,
        score=classification.score,
        action=classification.action,
        matched_keywords=classification.matched_keywords,
        extracted=event is not None,
        would_publish=would_publish,
        extraction_tier=extraction_tier if event else "none",
        ocr_chars=len(classification.ocr_text),
        had_flyer=bool(row.flyer_url),
        tier2_ran=tier2_ran,
        extracted_name=event.event_name if event else None,
        extracted_date=event.event_date if event else None,
        event=event,
    )


def _truncate(text: str | None, max_len: int = 120) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def format_extracted_event(event: EventData, *, verbose: bool = False) -> str:
    payload = event.to_ingest_payload()
    lines = [
        f"  name:       {payload['eventName']}",
        f"  date:       {payload['eventDate']}",
        f"  host:       {payload.get('eventHostOrganization') or '—'}",
        f"  location:   {payload.get('eventLocation') or '—'}",
        f"  start:      {payload.get('eventStartTime') or '—'}",
        f"  end:        {payload.get('eventEndTime') or '—'}",
        f"  status:     {payload.get('status')}",
        f"  tier:       {payload.get('extractionTier') or event.extraction_tier or '—'}",
        f"  confidence: {payload.get('confidenceScore')}",
    ]
    if verbose:
        desc = payload.get("eventDescription") or ""
        lines.append(f"  description: {_truncate(desc, 200) or '—'}")
        if payload.get("flyerUrl"):
            lines.append(f"  flyer:      {payload['flyerUrl']}")
    return "\n".join(lines)


def print_extracted_events(results: list[ReplayResult], *, verbose: bool = False) -> None:
    extracted = [r for r in results if r.event]
    if not extracted:
        return
    print("\n=== Extracted events ===")
    for result in extracted:
        event = result.event
        assert event is not None
        if verbose:
            print(f"\n--- {result.row.name[:60]} ---")
            print(format_extracted_event(event, verbose=True))
        else:
            host = event.event_host_organization or "—"
            loc = event.event_location or "—"
            print(
                f"  • {event.event_name} | {event.event_date} | {host} | {loc} "
                f"| {event.status} | {result.extraction_tier} "
                f"(conf={event.confidence_score})"
            )


def print_summary(results: list[ReplayResult]) -> None:
    total = len(results)
    rejected = sum(1 for r in results if r.action == "reject")
    extracted = sum(1 for r in results if r.extracted)
    would_publish = sum(1 for r in results if r.would_publish)
    with_flyer = sum(1 for r in results if r.had_flyer)
    with_ocr = sum(1 for r in results if r.ocr_chars > 0)
    tier2_used = sum(1 for r in results if r.tier2_ran)
    tier2_ok = sum(1 for r in results if r.extraction_tier == "tier2")
    needs_tier2 = sum(
        1 for r in results if r.action != "reject" and not r.extracted and not r.tier2_ran
    )

    print("\n=== Summary ===")
    print(f"Total rows:     {total}")
    print(f"Had flyer URL:  {with_flyer}")
    print(f"OCR text > 0:   {with_ocr}")
    print(f"Rejected:       {rejected}")
    print(f"Extracted:      {extracted}")
    print(f"  via Tier 1:   {sum(1 for r in results if r.extraction_tier == 'tier1')}")
    print(f"  via Tier 2:   {tier2_ok}")
    print(f"Tier 2 ran:     {tier2_used}")
    print(f"Would publish:  {would_publish}")
    print(f"Still stuck:    {needs_tier2}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay pipeline (Tier 1 + OCR + optional Tier 2) on Sheets/API data"
    )
    parser.add_argument("--source", choices=("csv", "api"), default="csv")
    parser.add_argument("--csv-url", default=DEFAULT_SHEETS_CSV_URL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ingest", action="store_true")
    parser.add_argument("--status", choices=("draft", "published"), default="draft")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--no-tier2",
        action="store_true",
        help="Skip Ollama Tier 2 even on reject / failed Tier 1 extraction",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Skip flyer download and OCR (text-only, old behavior)",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Only replay rows whose name contains this substring",
    )
    args = parser.parse_args()

    pipeline_cfg = load_pipeline_config()
    keywords_path = FORWARDER_DIR / "event_pipeline" / (
        pipeline_cfg.get("keywords_file") or "event_keywords.yaml"
    )
    auto_publish_min = float(pipeline_cfg.get("auto_publish_min_score", 0.5))
    tier2_publish_min = float(pipeline_cfg.get("tier2_publish_min_confidence", 0.75))

    ocr = FlyerOcr(
        languages=pipeline_cfg.get("easyocr_languages") or ["en"],
        gpu=bool(pipeline_cfg.get("easyocr_gpu", False)),
    )
    classifier = EventClassifier(
        keywords_path=keywords_path,
        min_score_pass=float(pipeline_cfg.get("min_score_pass", 0.3)),
        min_score_reject=float(pipeline_cfg.get("min_score_reject", 0.1)),
        ocr=None if args.no_ocr else ocr,
    )
    extractor = Tier1Extractor()

    tier2: LocalLlmExtractor | None = None
    use_tier2 = not args.no_tier2
    if use_tier2:
        tier2 = LocalLlmExtractor(
            base_url=pipeline_cfg.get("ollama_url", "http://localhost:11434"),
            model=pipeline_cfg.get("ollama_model", "llama3.1:8b"),
            timeout=int(pipeline_cfg.get("ollama_timeout", 120)),
        )
        if not tier2.available():
            print("WARN: Ollama not available — Tier 2 disabled for this run", file=sys.stderr)
            tier2 = None

    ingest_client: IngestClient | None = None
    if args.ingest:
        api_key = pipeline_cfg.get("pipeline_api_key") or load_env_value("PIPELINE_API_KEY")
        if not api_key:
            print("ERROR: PIPELINE_API_KEY required for --ingest", file=sys.stderr)
            sys.exit(1)
        ingest_url, backend_label = resolve_ingest_url(pipeline_cfg)
        ingest_client = IngestClient(ingest_url, api_key)
        print(f"Ingest backend: {backend_label} ({ingest_url})")

    if args.source == "csv":
        print("Loading rows from Sheets CSV…")
        rows = load_rows_from_csv(args.csv_url, args.limit)
    else:
        from event_pipeline.ingest_resolver import _ingest_to_events_url

        ingest_url, _ = resolve_ingest_url(pipeline_cfg)
        events_url = _ingest_to_events_url(ingest_url)
        print(f"Loading rows from API: {events_url}")
        rows = load_rows_from_api(events_url, args.limit)

    if args.name:
        needle = args.name.lower()
        rows = [r for r in rows if needle in r.name.lower()]

    print(f"Processing {len(rows)} rows (ocr={'on' if not args.no_ocr else 'off'}, tier2={'on' if tier2 else 'off'})…\n")

    results: list[ReplayResult] = []
    for row in rows:
        result = replay_row(
            row,
            classifier,
            extractor,
            tier2,
            auto_publish_min_score=auto_publish_min,
            tier2_publish_min=tier2_publish_min,
            use_tier2=use_tier2,
            skip_ocr=args.no_ocr,
        )

        if args.ingest and ingest_client and result.event:
            event = result.event
            event.status = args.status
            event.whatsapp_message_id = f"replay-{row.row_id}"
            try:
                resp = ingest_client.create_event(event)
                result.ingest_status = resp.get("status", "ok")
            except Exception as exc:
                result.ingest_status = f"error: {exc}"

        results.append(result)

        if args.verbose:
            line = (
                f"[{result.action:10}] score={result.score:.2f} "
                f"tier={result.extraction_tier:5} extracted={result.extracted} "
                f"publish={result.would_publish} ocr={result.ocr_chars} "
                f"| {row.name[:50]}"
            )
            if result.matched_keywords:
                line += f" | kw={','.join(result.matched_keywords[:4])}"
            if result.tier2_ran:
                line += " | tier2=ran"
            if result.ingest_status:
                line += f" | ingest={result.ingest_status}"
            print(line)
            if result.event:
                print(format_extracted_event(result.event, verbose=True))

    print_summary(results)
    if not args.verbose:
        print_extracted_events(results, verbose=False)

    if args.ingest:
        ingested = sum(
            1 for r in results if r.ingest_status and not str(r.ingest_status).startswith("error")
        )
        print(f"Ingested:       {ingested}")


if __name__ == "__main__":
    main()
