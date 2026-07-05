#!/usr/bin/env python3
"""
Replay Tier 1 classifier/extractor against real event text from Sheets CSV or API.

Default: dry-run (no writes). Use --ingest to POST draft replays to ingest API
(localhost:5177 if running, else Vercel fallback from config.yaml).
"""

from __future__ import annotations

import argparse
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
from event_pipeline.models import IncomingMessage

DEFAULT_SHEETS_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRRLfgooQ_mjspJLBGAnexTkhk1TzfEEaZCXDwbPIzjhUrgx53TKKdN3Xxe9wjJ0bbPmxpTjYx1udpC/pub?gid=125079037&single=true&output=csv"
)


@dataclass
class ReplayRow:
    row_id: str
    name: str
    host: str
    date: str
    description: str
    location: str


@dataclass
class ReplayResult:
    row: ReplayRow
    score: float
    action: str
    matched_keywords: list[str]
    extracted: bool
    would_publish: bool
    extracted_name: str | None = None
    extracted_date: str | None = None
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
            )
        )
        if limit and len(rows) >= limit:
            break
    return rows


def replay_row(
    row: ReplayRow,
    classifier: EventClassifier,
    extractor: Tier1Extractor,
    auto_publish_min_score: float,
) -> ReplayResult:
    text = build_message_text(row)
    classification = classifier.classify(text)
    message = IncomingMessage(
        message_id=f"replay-{row.row_id}",
        remote_jid="replay@g.us",
        group_name=row.host or "Replay",
        sender_name="Sheets Replay",
        text=text,
        has_image=False,
        raw_data={},
    )
    event = extractor.extract(message, confidence=classification.score)
    would_publish = bool(
        event
        and classification.action != "reject"
        and classification.score >= auto_publish_min_score
    )
    return ReplayResult(
        row=row,
        score=classification.score,
        action=classification.action,
        matched_keywords=classification.matched_keywords,
        extracted=event is not None,
        would_publish=would_publish,
        extracted_name=event.event_name if event else None,
        extracted_date=event.event_date if event else None,
    )


def print_summary(results: list[ReplayResult]) -> None:
    total = len(results)
    rejected = sum(1 for r in results if r.action == "reject")
    extracted = sum(1 for r in results if r.extracted)
    would_publish = sum(1 for r in results if r.would_publish)
    needs_tier2 = sum(1 for r in results if r.action != "reject" and not r.extracted)

    print("\n=== Summary ===")
    print(f"Total rows:     {total}")
    print(f"Rejected:       {rejected}  (score < min_score_reject)")
    print(f"Extracted:      {extracted}  (Tier 1 got name + date)")
    print(f"Would publish:  {would_publish}  (extracted + score >= auto_publish_min_score)")
    print(f"Needs Tier 2:   {needs_tier2}  (passed keywords but extraction incomplete)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Tier 1 classifier on Sheets/API event text")
    parser.add_argument(
        "--source",
        choices=("csv", "api"),
        default="csv",
        help="csv = Google Sheets publish URL; api = GET /api/events (local or Vercel)",
    )
    parser.add_argument(
        "--csv-url",
        default=DEFAULT_SHEETS_CSV_URL,
        help="Sheets CSV URL when --source csv",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max rows to process")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="POST extracted events to ingest API (default: dry-run only)",
    )
    parser.add_argument(
        "--status",
        choices=("draft", "published"),
        default="draft",
        help="Ingest status when --ingest (default: draft)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print one line per row",
    )
    args = parser.parse_args()

    pipeline_cfg = load_pipeline_config()
    keywords_path = FORWARDER_DIR / "event_pipeline" / (
        pipeline_cfg.get("keywords_file") or "event_keywords.yaml"
    )
    auto_publish_min = float(pipeline_cfg.get("auto_publish_min_score", 0.5))

    classifier = EventClassifier(
        keywords_path=keywords_path,
        min_score_pass=float(pipeline_cfg.get("min_score_pass", 0.3)),
        min_score_reject=float(pipeline_cfg.get("min_score_reject", 0.1)),
    )
    extractor = Tier1Extractor()

    ingest_client: IngestClient | None = None
    backend_label = "dry-run"
    if args.ingest:
        api_key = pipeline_cfg.get("pipeline_api_key") or load_env_value("PIPELINE_API_KEY")
        if not api_key:
            print("ERROR: PIPELINE_API_KEY required for --ingest", file=sys.stderr)
            sys.exit(1)
        ingest_url, backend_label = resolve_ingest_url(pipeline_cfg)
        ingest_client = IngestClient(ingest_url, api_key)
        print(f"Ingest backend: {backend_label} ({ingest_url})")

    if args.source == "csv":
        print(f"Loading rows from Sheets CSV…")
        rows = load_rows_from_csv(args.csv_url, args.limit)
    else:
        from event_pipeline.ingest_resolver import _ingest_to_events_url

        ingest_url, backend_label = resolve_ingest_url(pipeline_cfg)
        events_url = _ingest_to_events_url(ingest_url)
        print(f"Loading rows from API ({backend_label}): {events_url}")
        rows = load_rows_from_api(events_url, args.limit)

    print(f"Processing {len(rows)} rows…\n")

    results: list[ReplayResult] = []
    for row in rows:
        result = replay_row(row, classifier, extractor, auto_publish_min)

        if args.ingest and ingest_client and result.extracted:
            text = build_message_text(row)
            message = IncomingMessage(
                message_id=f"replay-{row.row_id}",
                remote_jid="replay@g.us",
                group_name=row.host or "Replay",
                sender_name="Sheets Replay",
                text=text,
                has_image=False,
                raw_data={},
            )
            event = extractor.extract(message, confidence=result.score)
            if event:
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
                f"extracted={result.extracted} publish={result.would_publish} "
                f"| {row.name[:60]}"
            )
            if result.matched_keywords:
                line += f" | kw={','.join(result.matched_keywords[:4])}"
            if result.ingest_status:
                line += f" | ingest={result.ingest_status}"
            print(line)

    print_summary(results)

    if args.ingest:
        ingested = sum(1 for r in results if r.ingest_status and r.ingest_status not in ("error",))
        print(f"Ingested:       {ingested}")


if __name__ == "__main__":
    main()
