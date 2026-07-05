#!/usr/bin/env python3
"""Manual test for Tier 1 event pipeline (no webhook server required)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from event_pipeline.classifier import EventClassifier
from event_pipeline.extractor import Tier1Extractor
from event_pipeline.models import IncomingMessage

SAMPLE = """
Youth Halaqa this Saturday, March 15 at 6:30 PM
Location: Islamic Association of Raleigh
All youth welcome — registration required.
"""


def main() -> None:
    forwarder_dir = Path(__file__).resolve().parent.parent
    classifier = EventClassifier(forwarder_dir / "event_pipeline" / "event_keywords.yaml")
    extractor = Tier1Extractor()

    classification = classifier.classify(SAMPLE)
    print("Classification:", json.dumps(classification.__dict__, indent=2))

    message = IncomingMessage(
        message_id="test-msg-1",
        remote_jid="120363151179725752@g.us",
        group_name="IAR",
        sender_name="Test User",
        text=SAMPLE.strip(),
        has_image=False,
        raw_data={},
    )

    event = extractor.extract(message, confidence=classification.score)
    if event:
        print("Extracted event:", json.dumps(event.to_ingest_payload(), indent=2))
    else:
        print("Tier 1 extraction incomplete — would escalate to Tier 2")


if __name__ == "__main__":
    main()
