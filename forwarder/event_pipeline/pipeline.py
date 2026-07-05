from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from .classifier import EventClassifier
from .extractor import Tier1Extractor
from .ingest_client import IngestClient
from .ingest_resolver import resolve_ingest_url
from .models import IncomingMessage

logger = logging.getLogger(__name__)


class EventPipeline:
    def __init__(self, config_path: Path | None = None):
        base = Path(__file__).resolve().parent.parent
        path = Path(config_path) if config_path else base / "config.yaml"
        with open(path) as f:
            self.config = yaml.safe_load(f)

        pipeline_cfg = self.config.get("event_pipeline") or {}
        self.enabled = bool(pipeline_cfg.get("enabled", False))
        self.auto_publish_min_score = float(pipeline_cfg.get("auto_publish_min_score", 0.5))

        self.instance = self.config["instance"]
        self.evolution_url = self.config["evolution_url"].rstrip("/")
        self.source_jids = set(self.config["source_group_jids"])
        self.group_labels = self.config.get("group_labels", {})
        self.forward_own_messages = self.config.get("forward_own_messages", False)

        self.api_key = self.config.get("api_key") or self._load_env_value(
            base.parent / ".env", "AUTHENTICATION_API_KEY"
        )

        keywords_file = pipeline_cfg.get("keywords_file", "event_keywords.yaml")
        keywords_path = Path(__file__).parent / keywords_file

        self.classifier = EventClassifier(
            keywords_path=keywords_path,
            min_score_pass=float(pipeline_cfg.get("min_score_pass", 0.3)),
            min_score_reject=float(pipeline_cfg.get("min_score_reject", 0.1)),
        )
        self.extractor = Tier1Extractor()

        self.ingest: IngestClient | None = None
        self.ingest_backend: str | None = None
        if self.enabled:
            pipeline_api_key = pipeline_cfg.get("pipeline_api_key") or self._load_env_value(
                base.parent / ".env", "PIPELINE_API_KEY"
            )
            if not pipeline_api_key:
                raise ValueError("PIPELINE_API_KEY is required when event pipeline is enabled")
            ingest_url, backend = resolve_ingest_url(pipeline_cfg)
            self.ingest = IngestClient(ingest_url, pipeline_api_key)
            self.ingest_backend = backend

        self.seen_ids: set[str] = set()
        self.max_seen = 5000

    @staticmethod
    def _load_env_value(env_path: Path, key: str) -> str:
        if not env_path.exists():
            return ""
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
        return ""

    def _group_label(self, jid: str) -> str:
        return self.group_labels.get(jid, jid.split("@")[0])

    def _remember_id(self, msg_id: str) -> bool:
        if msg_id in self.seen_ids:
            return False
        if len(self.seen_ids) >= self.max_seen:
            self.seen_ids.clear()
        self.seen_ids.add(msg_id)
        return True

    @staticmethod
    def _extract_text(data: dict) -> str | None:
        message = data.get("message") or {}
        if message.get("conversation"):
            return message["conversation"]
        if message.get("extendedTextMessage", {}).get("text"):
            return message["extendedTextMessage"]["text"]
        for media_key in ("imageMessage", "videoMessage", "documentMessage"):
            if message.get(media_key, {}).get("caption"):
                return message[media_key]["caption"]
        return None

    @staticmethod
    def _is_image_message(data: dict) -> bool:
        message_type = data.get("messageType", "")
        message = data.get("message") or {}
        if message_type in ("imageMessage", "stickerMessage"):
            return True
        if message_type == "documentMessage":
            mimetype = message.get("documentMessage", {}).get("mimetype", "")
            return mimetype.startswith("image/")
        return False

    def _parse_message(self, payload: dict) -> IncomingMessage | None:
        if payload.get("event") != "messages.upsert":
            return None

        data = payload.get("data")
        if not data or not isinstance(data, dict):
            return None

        key = data.get("key") or {}
        remote_jid = key.get("remoteJid")
        if not remote_jid or remote_jid not in self.source_jids:
            return None
        if key.get("fromMe") and not self.forward_own_messages:
            return None

        msg_id = key.get("id")
        if msg_id and not self._remember_id(msg_id):
            logger.debug("Pipeline skipping duplicate message id=%s", msg_id)
            return None

        text = self._extract_text(data) or ""
        if re.match(r"^\[.+\] .+", text):
            return None

        return IncomingMessage(
            message_id=msg_id or "",
            remote_jid=remote_jid,
            group_name=self._group_label(remote_jid),
            sender_name=data.get("pushName") or "Unknown",
            text=text,
            has_image=self._is_image_message(data),
            raw_data=data,
        )

    def handle_webhook(self, payload: dict) -> dict:
        if not self.enabled:
            return {"status": "disabled"}

        message = self._parse_message(payload)
        if not message:
            return {"status": "ignored"}

        classification = self.classifier.classify(message.text, has_image=message.has_image)
        logger.info(
            "Pipeline classify id=%s score=%.2f action=%s keywords=%s",
            message.message_id,
            classification.score,
            classification.action,
            classification.matched_keywords[:5],
        )

        if classification.action == "reject":
            return {
                "status": "rejected",
                "score": classification.score,
                "reason": "below_keyword_threshold",
            }

        event = self.extractor.extract(message, confidence=classification.score)
        if not event:
            return {
                "status": "needs_tier2",
                "score": classification.score,
                "reason": "tier1_extraction_incomplete",
            }

        if classification.score >= self.auto_publish_min_score:
            event.status = "published"
        else:
            event.status = "draft"

        try:
            assert self.ingest is not None
            result = self.ingest.create_event(event)
            return {
                "status": result.get("status", "created"),
                "score": classification.score,
                "event_status": event.status,
                "extraction_tier": event.extraction_tier,
            }
        except Exception as exc:
            logger.exception("Pipeline ingest failed for id=%s", message.message_id)
            return {"status": "error", "reason": str(exc)}
