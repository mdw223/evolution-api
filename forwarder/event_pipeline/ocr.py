"""Flyer OCR (easyocr) — not implemented yet."""

from __future__ import annotations


class FlyerOcr:
    def available(self) -> bool:
        return False

    def extract_text(self, image_base64: str) -> str:
        raise NotImplementedError("OCR is planned for a later Phase 2 step")
