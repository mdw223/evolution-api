"""Tier 2 local LLM extraction (Ollama) — not implemented yet."""

from __future__ import annotations


class LocalLlmExtractor:
    def available(self) -> bool:
        return False

    def classify_and_extract(self, text: str) -> None:
        raise NotImplementedError("Tier 2 Ollama extraction is planned for a later Phase 2 step")
