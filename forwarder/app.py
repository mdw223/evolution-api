import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

import yaml

from event_pipeline import EventPipeline
from forwarder import Forwarder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

forwarder = Forwarder()

try:
    event_pipeline = EventPipeline()
except Exception as exc:
    logger.error("Event pipeline failed to initialize: %s", exc)
    event_pipeline = None


class WebhookHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            body = {
                "status": "ok",
                "instance": forwarder.instance,
                "event_pipeline": bool(event_pipeline and event_pipeline.enabled),
            }
            self._send_json(200, body)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/webhook":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return

        event = payload.get("event", "unknown")
        logger.info("Webhook received: event=%s", event)
        result = forwarder.handle_webhook(payload)

        if event_pipeline and event_pipeline.enabled:
            threading.Thread(
                target=event_pipeline.handle_webhook,
                args=(payload,),
                daemon=True,
                name="event-pipeline",
            ).start()

        self._send_json(200, result)


if __name__ == "__main__":
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    host = cfg.get("host", "0.0.0.0")
    port = cfg.get("port", 5000)
    server = HTTPServer((host, port), WebhookHandler)
    logger.info("Starting forwarder on %s:%s", host, port)
    server.serve_forever()
