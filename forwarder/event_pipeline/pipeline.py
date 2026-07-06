from __future__ import annotations

import logging
import re
from pathlib import Path

import requests
import yaml

from .classifier import EventClassifier
from .cloud_llm import CloudLlmExtractor
from .extractor import Tier1Extractor
from .debug_log import log_extraction_result, log_tier_outcome
from .event_merge import PartialEvent
from .google_drive import GoogleDriveUploader
from .ingest_client import IngestClient
from .ingest_resolver import resolve_ingest_url
from .local_llm import LocalLlmExtractor
from .models import ClassificationResult, EventData, IncomingMessage
from .ocr import FlyerOcr
from .r2_storage import FlyerUploader, R2FlyerUploader

logger = logging.getLogger(__name__)


class EventPipeline:
    def __init__(self, config_path: Path | None = None):
        base = Path(__file__).resolve().parent.parent
        path = Path(config_path) if config_path else base / "config.yaml"
        with open(path) as f:
            self.config = yaml.safe_load(f)

        pipeline_cfg = self.config.get("event_pipeline") or {}
        self.enabled = bool(pipeline_cfg.get("enabled", False))
        if pipeline_cfg.get("verbose_logging"):
            logging.getLogger("event_pipeline").setLevel(logging.DEBUG)
        self.auto_publish_min_score = float(pipeline_cfg.get("auto_publish_min_score", 0.5))
        self.tier2_publish_min = float(pipeline_cfg.get("tier2_publish_min_confidence", 0.75))
        self.tier3_publish_min = float(pipeline_cfg.get("tier3_publish_min_confidence", 0.65))

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

        self.ocr = FlyerOcr(
            languages=pipeline_cfg.get("easyocr_languages") or ["en"],
            gpu=bool(pipeline_cfg.get("easyocr_gpu", False)),
        )
        self.classifier = EventClassifier(
            keywords_path=keywords_path,
            min_score_pass=float(pipeline_cfg.get("min_score_pass", 0.3)),
            min_score_reject=float(pipeline_cfg.get("min_score_reject", 0.1)),
            ocr=self.ocr,
        )
        self.extractor = Tier1Extractor()

        self.tier2 = LocalLlmExtractor(
            base_url=pipeline_cfg.get("ollama_url", "http://localhost:11434"),
            model=pipeline_cfg.get("ollama_model", "llama3.1:8b"),
            timeout=int(pipeline_cfg.get("ollama_timeout", 120)),
        )
        gemini_key = pipeline_cfg.get("gemini_api_key") or self._load_env_value(
            base.parent / ".env", "GEMINI_API_KEY"
        )
        self.tier3 = CloudLlmExtractor(
            api_key=gemini_key,
            model=pipeline_cfg.get("gemini_model", "gemini-2.5-flash"),
            timeout=int(pipeline_cfg.get("gemini_timeout", 90)),
        )

        drive_creds = pipeline_cfg.get("google_service_account_json") or self._load_env_value(
            base.parent / ".env", "GOOGLE_SERVICE_ACCOUNT_JSON"
        )
        drive_folder = pipeline_cfg.get("google_drive_folder_id", "")
        flyer_storage = (pipeline_cfg.get("flyer_storage") or "r2").lower()
        r2_key_prefix = pipeline_cfg.get("r2_key_prefix") or "flyers"

        self.flyer_uploader: FlyerUploader | None = None
        self.flyer_storage_label = "none"

        if flyer_storage == "r2":
            r2_account = pipeline_cfg.get("r2_account_id") or self._load_env_value(
                base.parent / ".env", "R2_ACCOUNT_ID"
            )
            r2_access = pipeline_cfg.get("r2_access_key_id") or self._load_env_value(
                base.parent / ".env", "R2_ACCESS_KEY_ID"
            )
            r2_secret = pipeline_cfg.get("r2_secret_access_key") or self._load_env_value(
                base.parent / ".env", "R2_SECRET_ACCESS_KEY"
            )
            r2_bucket = pipeline_cfg.get("r2_bucket_name") or self._load_env_value(
                base.parent / ".env", "R2_BUCKET_NAME"
            )
            r2_public = pipeline_cfg.get("r2_public_url_base") or self._load_env_value(
                base.parent / ".env", "R2_PUBLIC_URL_BASE"
            )
            r2 = R2FlyerUploader(
                account_id=r2_account,
                access_key_id=r2_access,
                secret_access_key=r2_secret,
                bucket_name=r2_bucket,
                public_url_base=r2_public,
                key_prefix=r2_key_prefix,
            )
            if r2.available():
                self.flyer_uploader = r2
                self.flyer_storage_label = "r2"
        elif flyer_storage == "drive" and drive_creds and drive_folder:
            drive = GoogleDriveUploader(drive_folder, drive_creds)
            if drive.available():
                self.flyer_uploader = drive
                self.flyer_storage_label = "drive"

        self.session = requests.Session()
        self.session.headers.update({"apikey": self.api_key, "Content-Type": "application/json"})

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

        if self.enabled:
            ingest_url = self.ingest.ingest_url if self.ingest else "none"
            logger.info(
                "Event pipeline ready: ingest_backend=%s url=%s source_groups=%d "
                "tier2=%s tier3=%s flyer_storage=%s",
                self.ingest_backend,
                ingest_url,
                len(self.source_jids),
                self.tier2.available(),
                self.tier3.available(),
                self.flyer_storage_label,
            )
        else:
            logger.info("Event pipeline disabled in config")

    @staticmethod
    def _load_env_value(env_path: Path, key: str) -> str:
        if not env_path.exists():
            return ""
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
        return ""

    def _url(self, path: str) -> str:
        return f"{self.evolution_url}/{path.lstrip('/')}"

    def _group_label(self, jid: str) -> str:
        return self.group_labels.get(jid, jid.split("@")[0])

    def _remember_id(self, msg_id: str) -> bool:
        if msg_id in self.seen_ids:
            return False
        if len(self.seen_ids) >= self.max_seen:
            self.seen_ids.clear()
        self.seen_ids.add(msg_id)
        return True

    def _get_media_base64(self, data: dict) -> tuple[str | None, str | None]:
        body = {"message": data}
        resp = self.session.post(
            self._url(f"chat/getBase64FromMediaMessage/{self.instance}"),
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("base64"), payload.get("mimetype")

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

    def _parse_message(self, payload: dict) -> tuple[IncomingMessage | None, str | None]:
        if payload.get("event") != "messages.upsert":
            return None, f"wrong_event_type:{payload.get('event', 'unknown')}"

        data = payload.get("data")
        if not data or not isinstance(data, dict):
            return None, "no_message_data"

        key = data.get("key") or {}
        remote_jid = key.get("remoteJid")
        if not remote_jid or remote_jid not in self.source_jids:
            return None, f"unknown_group:{remote_jid or 'missing'}"
        if key.get("fromMe") and not self.forward_own_messages:
            return None, "own_message_skipped"

        msg_id = key.get("id")
        if msg_id and not self._remember_id(msg_id):
            return None, f"duplicate_message:{msg_id}"

        text = self._extract_text(data) or ""
        if re.match(r"^\[.+\] .+", text):
            return None, "relay_prefixed_text"

        return (
            IncomingMessage(
                message_id=msg_id or "",
                remote_jid=remote_jid,
                group_name=self._group_label(remote_jid),
                sender_name=data.get("pushName") or "Unknown",
                text=text,
                has_image=self._is_image_message(data),
                raw_data=data,
            ),
            None,
        )

    @staticmethod
    def _text_preview(text: str, max_len: int = 80) -> str:
        preview = text.replace("\n", " ").strip()
        if len(preview) <= max_len:
            return preview
        return preview[: max_len - 1] + "…"

    def _log_message_received(self, message: IncomingMessage) -> None:
        logger.info(
            "Pipeline message id=%s group=%s sender=%s has_image=%s text=%r",
            message.message_id,
            message.group_name,
            message.sender_name,
            message.has_image,
            self._text_preview(message.text),
        )

    def _log_extracted_event(self, event: EventData) -> None:
        logger.info(
            "Pipeline extracted id=%s name=%r date=%s host=%s location=%s "
            "start=%s end=%s status=%s tier=%s confidence=%s",
            event.whatsapp_message_id,
            event.event_name,
            event.event_date,
            event.event_host_organization or "—",
            event.event_location or "—",
            event.event_start_time or "—",
            event.event_end_time or "—",
            event.status,
            event.extraction_tier,
            event.confidence_score,
        )

    def _message_for_extraction(
        self, message: IncomingMessage, classification: ClassificationResult
    ) -> IncomingMessage:
        if classification.combined_text and classification.combined_text != message.text:
            return IncomingMessage(
                message_id=message.message_id,
                remote_jid=message.remote_jid,
                group_name=message.group_name,
                sender_name=message.sender_name,
                text=classification.combined_text,
                has_image=message.has_image,
                raw_data=message.raw_data,
            )
        return message

    def _attach_flyer(
        self,
        event: EventData,
        image_base64: str | None,
        mimetype: str | None,
        message_id: str,
    ) -> None:
        if not image_base64 or not self.flyer_uploader:
            return
        ext = "jpg"
        if mimetype and "png" in mimetype:
            ext = "png"
        url = self.flyer_uploader.upload_image(
            image_base64, f"event-{message_id[:16]}.{ext}", mimetype or "image/jpeg"
        )
        if url:
            event.flyer_url = url

    def _ingest_event(self, event: EventData, classification_score: float) -> dict:
        assert self.ingest is not None
        self._log_extracted_event(event)
        result = self.ingest.create_event(event)
        return {
            "status": result.get("status", "created"),
            "score": classification_score,
            "event_status": event.status,
            "extraction_tier": event.extraction_tier,
            "confidence": event.confidence_score,
            "event_name": event.event_name,
            "event_date": event.event_date,
            "event_location": event.event_location,
            "group": event.source_group_name,
        }

    def _finalize_and_ingest(
        self,
        accumulated: PartialEvent,
        classification_score: float,
        *,
        publish_min_confidence: float | None,
        image_base64: str | None,
        mimetype: str | None,
        message_id: str,
    ) -> dict:
        if not accumulated.can_ingest():
            return {
                "status": "rejected",
                "reason": "missing_required_fields",
                "accumulated": accumulated.snapshot(),
                "score": classification_score,
            }

        event = accumulated.to_event_data(infer_date=True)
        assert event is not None

        if publish_min_confidence is not None and accumulated.can_publish(publish_min_confidence):
            event.status = "published"
        else:
            event.status = "draft"

        self._attach_flyer(event, image_base64, mimetype, message_id)
        try:
            return self._ingest_event(event, classification_score)
        except Exception as exc:
            logger.exception("Ingest failed for id=%s", message_id)
            return {"status": "error", "reason": str(exc), "extraction_tier": accumulated.extraction_tier}

    def _run_tier2(
        self,
        message: IncomingMessage,
        text: str,
        classification: ClassificationResult,
        image_base64: str | None,
        mimetype: str | None,
        accumulated: PartialEvent,
    ) -> dict:
        logger.info("Tier 2 Ollama for message id=%s", message.message_id)
        if not self.tier2.available():
            logger.warning("Ollama unavailable — skipping Tier 2")
            return self._run_tier3(
                message, text, classification, image_base64, mimetype,
                accumulated=accumulated, reason="ollama_unavailable",
            )

        result = self.tier2.classify_and_extract(text, message)
        if result.llm_fields:
            accumulated.merge_llm_data(result.llm_fields, tier="tier2", confidence=result.confidence)
        accumulated.log_snapshot("tier2", message.message_id)
        log_extraction_result(logger, "tier2", message.message_id, result)

        if not result.is_event:
            return self._run_tier3(
                message, text, classification, image_base64, mimetype,
                accumulated=accumulated, reason="tier2_not_event",
            )

        if accumulated.can_publish(self.tier2_publish_min):
            return self._finalize_and_ingest(
                accumulated,
                classification.score,
                publish_min_confidence=self.tier2_publish_min,
                image_base64=image_base64,
                mimetype=mimetype,
                message_id=message.message_id,
            )

        logger.info(
            "Tier 2 incomplete or low confidence id=%s — escalating to Tier 3",
            message.message_id,
        )
        return self._run_tier3(
            message, text, classification, image_base64, mimetype,
            accumulated=accumulated, reason="tier2_incomplete_or_low_confidence",
        )

    def _run_tier3(
        self,
        message: IncomingMessage,
        text: str,
        classification: ClassificationResult,
        image_base64: str | None,
        mimetype: str | None,
        *,
        accumulated: PartialEvent,
        reason: str = "tier2_escalation",
    ) -> dict:
        logger.info("Tier 3 Gemini for message id=%s (reason=%s)", message.message_id, reason)
        if not self.tier3.available():
            logger.warning("Gemini unavailable — saving accumulated draft if possible")
            accumulated.status = "draft"
            return self._finalize_and_ingest(
                accumulated,
                classification.score,
                publish_min_confidence=None,
                image_base64=image_base64,
                mimetype=mimetype,
                message_id=message.message_id,
            )

        result = self.tier3.classify_and_extract(
            text,
            message,
            image_base64=image_base64,
            ocr_text=classification.ocr_text,
        )
        if result.llm_fields:
            accumulated.merge_llm_data(
                result.llm_fields,
                tier="tier3",
                confidence=result.confidence if result.confidence > 0 else accumulated.confidence_score,
            )
        accumulated.log_snapshot("tier3", message.message_id)
        log_extraction_result(logger, "tier3", message.message_id, result)

        if result.failure_reason and not result.llm_fields:
            logger.warning(
                "Tier 3 failed id=%s reason=%s — using accumulated fields from prior tiers",
                message.message_id,
                result.failure_reason,
            )

        if not result.is_event and not accumulated.can_ingest():
            return {
                "status": "rejected",
                "reason": result.failure_reason or "tier3_not_event",
                "accumulated": accumulated.snapshot(),
                "score": classification.score,
            }

        return self._finalize_and_ingest(
            accumulated,
            classification.score,
            publish_min_confidence=self.tier3_publish_min,
            image_base64=image_base64,
            mimetype=mimetype,
            message_id=message.message_id,
        )

    def handle_webhook(self, payload: dict) -> dict:
        if not self.enabled:
            return {"status": "disabled"}

        message, ignore_reason = self._parse_message(payload)
        if not message:
            logger.info("Pipeline ignored: %s", ignore_reason)
            return {"status": "ignored", "reason": ignore_reason}

        self._log_message_received(message)

        image_base64: str | None = None
        mimetype: str | None = None
        if message.has_image:
            try:
                image_base64, mimetype = self._get_media_base64(message.raw_data)
            except Exception as exc:
                logger.warning("Failed to download image for id=%s: %s", message.message_id, exc)

        classification = self.classifier.classify(
            message.text,
            has_image=message.has_image,
            image_base64=image_base64,
        )
        logger.info(
            "Pipeline classify id=%s score=%.2f action=%s keywords=%s ocr_chars=%d",
            message.message_id,
            classification.score,
            classification.action,
            classification.matched_keywords[:5],
            len(classification.ocr_text),
        )

        if classification.action == "reject":
            logger.info(
                "Pipeline rejected id=%s score=%.2f reason=below_keyword_threshold",
                message.message_id,
                classification.score,
            )
            return {
                "status": "rejected",
                "score": classification.score,
                "reason": "below_keyword_threshold",
                "group": message.group_name,
            }

        extract_message = self._message_for_extraction(message, classification)
        event = self.extractor.extract(extract_message, confidence=classification.score)

        if event:
            event.extraction_tier = "tier1"
            event.confidence_score = classification.score
            if classification.score >= self.auto_publish_min_score:
                event.status = "published"
            else:
                event.status = "draft"
            log_tier_outcome(
                logger,
                "tier1",
                message.message_id,
                event=event,
                is_event=True,
                confidence=classification.score,
            )
            self._attach_flyer(event, image_base64, mimetype, message.message_id)
            try:
                return self._ingest_event(event, classification.score)
            except Exception as exc:
                logger.exception("Tier 1 ingest failed for id=%s", message.message_id)
                return {"status": "error", "reason": str(exc)}

        preview = self.extractor.extract_preview(extract_message)
        text = classification.combined_text or message.text
        accumulated = PartialEvent.from_preview(
            preview,
            extract_message,
            text,
            confidence=classification.score,
            tier="tier1",
        )
        accumulated.log_snapshot("tier1", message.message_id)
        log_tier_outcome(
            logger,
            "tier1",
            message.message_id,
            event=None,
            is_event=True,
            confidence=classification.score,
            failure_reason="incomplete_extraction",
            fields=accumulated.snapshot(),
        )
        logger.info(
            "Tier 1 extraction incomplete for id=%s — escalating to Tier 2",
            message.message_id,
        )
        return self._run_tier2(
            message, text, classification, image_base64, mimetype, accumulated
        )
