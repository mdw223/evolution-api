"""Tier 3 cloud LLM fallback (Groq/Gemini) — not implemented yet."""

from __future__ import annotations


class CloudLlmExtractor:
    def available(self) -> bool:
        return False

    def classify_and_extract(self, text: str, image_base64: str | None = None) -> None:
        raise NotImplementedError("Tier 3 cloud LLM extraction is planned for a later Phase 2 step")
