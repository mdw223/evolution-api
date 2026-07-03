import logging
import re
from pathlib import Path

import requests
import yaml

logger = logging.getLogger(__name__)

MEDIA_MESSAGE_TYPES = {
    "imageMessage": "image",
    "stickerMessage": "image",
    "videoMessage": "video",
}


class Forwarder:
    def __init__(self, config_path=None):
        base = Path(__file__).resolve().parent
        path = Path(config_path) if config_path else base / "config.yaml"
        with open(path) as f:
            self.config = yaml.safe_load(f)

        self.api_key = self.config.get("api_key") or self._load_api_key_from_env(base.parent / ".env")
        self.instance = self.config["instance"]
        self.evolution_url = self.config["evolution_url"].rstrip("/")
        self.target_jid = self.config["target_group_jid"]
        self.source_jids = set(self.config["source_group_jids"])
        self.group_labels = self.config.get("group_labels", {})
        self.seen_ids = set()
        self.max_seen = 5000
        self.forward_own_messages = self.config.get("forward_own_messages", False)

        self.session = requests.Session()
        self.session.headers.update({"apikey": self.api_key, "Content-Type": "application/json"})

    @staticmethod
    def _load_api_key_from_env(env_path):
        if not env_path.exists():
            raise FileNotFoundError(f"Missing api_key in config and no .env at {env_path}")
        for line in env_path.read_text().splitlines():
            if line.startswith("AUTHENTICATION_API_KEY="):
                return line.split("=", 1)[1].strip()
        raise ValueError("AUTHENTICATION_API_KEY not found in .env")

    def _url(self, path):
        return f"{self.evolution_url}/{path.lstrip('/')}"

    def _group_label(self, jid):
        return self.group_labels.get(jid, jid.split("@")[0])

    def _remember_id(self, msg_id):
        if msg_id in self.seen_ids:
            return False
        if len(self.seen_ids) >= self.max_seen:
            self.seen_ids.clear()
        self.seen_ids.add(msg_id)
        return True

    def should_forward(self, payload):
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
        if remote_jid == self.target_jid:
            return None

        msg_id = key.get("id")
        if msg_id and not self._remember_id(msg_id):
            logger.debug("Skipping duplicate message id=%s", msg_id)
            return None

        return data

    def _extract_text(self, data):
        message = data.get("message") or {}
        if message.get("conversation"):
            return message["conversation"]
        if message.get("extendedTextMessage", {}).get("text"):
            return message["extendedTextMessage"]["text"]
        for media_key in ("imageMessage", "videoMessage", "documentMessage"):
            if message.get(media_key, {}).get("caption"):
                return message[media_key]["caption"]
        return None

    def _is_image_message(self, data):
        message_type = data.get("messageType", "")
        message = data.get("message") or {}

        if message_type in ("imageMessage", "stickerMessage"):
            return True
        if message_type == "documentMessage":
            mimetype = message.get("documentMessage", {}).get("mimetype", "")
            return mimetype.startswith("image/")
        return False

    def _format_prefix(self, data):
        jid = data["key"]["remoteJid"]
        group = self._group_label(jid)
        sender = data.get("pushName") or "Unknown"
        return f"[{group}] {sender}"

    def _send_text(self, text):
        body = {"number": self.target_jid, "text": text}
        resp = self.session.post(self._url(f"message/sendText/{self.instance}"), json=body, timeout=30)
        resp.raise_for_status()
        logger.info("Forwarded text to %s", self.target_jid)

    def _get_media_base64(self, data):
        body = {"message": data}
        resp = self.session.post(
            self._url(f"chat/getBase64FromMediaMessage/{self.instance}"),
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def _send_media(self, mediatype, base64_data, caption, mimetype=None):
        body = {
            "number": self.target_jid,
            "mediatype": mediatype,
            "media": base64_data,
            "caption": caption,
        }
        if mimetype:
            body["mimetype"] = mimetype
        resp = self.session.post(self._url(f"message/sendMedia/{self.instance}"), json=body, timeout=60)
        resp.raise_for_status()
        logger.info("Forwarded %s to %s", mediatype, self.target_jid)

    def handle_webhook(self, payload):
        data = self.should_forward(payload)
        if not data:
            return {"status": "ignored"}

        prefix = self._format_prefix(data)
        message_type = data.get("messageType", "")

        try:
            if self._is_image_message(data):
                media = self._get_media_base64(data)
                base64_data = media.get("base64")
                if not base64_data:
                    logger.warning("No base64 in media response for %s", message_type)
                    return {"status": "error", "reason": "no_base64"}

                text = self._extract_text(data)
                caption = f"{prefix}: {text}" if text else str(prefix)
                mediatype = MEDIA_MESSAGE_TYPES.get(message_type, "image")
                mimetype = media.get("mimetype")
                self._send_media(mediatype, base64_data, caption, mimetype)
                return {"status": "forwarded", "type": "media"}

            text = self._extract_text(data)
            if not text:
                logger.debug("No text content in message type=%s", message_type)
                return {"status": "ignored", "reason": "no_text"}

            if re.match(r"^\[.+\] .+", text):
                return {"status": "ignored", "reason": "forward_prefix"}

            self._send_text(f"{prefix}: {text}")
            return {"status": "forwarded", "type": "text"}

        except requests.HTTPError as exc:
            logger.error("Evolution API error: %s %s", exc.response.status_code, exc.response.text)
            return {"status": "error", "reason": str(exc)}
        except Exception as exc:
            logger.error("Forward failed: %s", exc)
            return {"status": "error", "reason": str(exc)}
