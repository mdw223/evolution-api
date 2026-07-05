"""Flyer OCR via easyocr (lazy-loaded, CPU)."""

from __future__ import annotations

import base64
import io
import logging
import threading

logger = logging.getLogger(__name__)

_reader = None
_reader_lock = threading.Lock()


class FlyerOcr:
    def __init__(self, languages: list[str] | None = None, gpu: bool = False):
        self.languages = languages or ["en"]
        self.gpu = gpu

    def available(self) -> bool:
        try:
            import easyocr  # noqa: F401

            return True
        except ImportError:
            return False

    def _get_reader(self):
        global _reader
        if _reader is not None:
            return _reader
        with _reader_lock:
            if _reader is None:
                import easyocr

                logger.info("Loading easyocr Reader (languages=%s, gpu=%s)", self.languages, self.gpu)
                _reader = easyocr.Reader(self.languages, gpu=self.gpu)
            return _reader

    def extract_text(self, image_base64: str) -> str:
        if not image_base64:
            return ""
        if not self.available():
            logger.warning("easyocr not installed — skipping OCR")
            return ""

        try:
            from PIL import Image
        except ImportError:
            logger.warning("Pillow not installed — skipping OCR")
            return ""

        raw = base64.b64decode(image_base64)
        image = Image.open(io.BytesIO(raw)).convert("RGB")

        import numpy as np

        reader = self._get_reader()
        lines = reader.readtext(np.array(image), detail=0, paragraph=True)
        text = "\n".join(line.strip() for line in lines if line and str(line).strip())
        logger.info("OCR extracted %d chars from image", len(text))
        return text
