from __future__ import annotations

import re
from pathlib import Path

import yaml

from .models import ClassificationResult

DATE_PATTERN = re.compile(
    r"\b("
    r"\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}"
    r"|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
    r"|today|tomorrow|tonight"
    r")\b",
    re.IGNORECASE,
)

TIME_PATTERN = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)\b|\b\d{1,2}:\d{2}\b",
    re.IGNORECASE,
)


class EventClassifier:
    def __init__(
        self,
        keywords_path: Path,
        min_score_pass: float = 0.3,
        min_score_reject: float = 0.1,
    ):
        self.min_score_pass = min_score_pass
        self.min_score_reject = min_score_reject

        with open(keywords_path) as f:
            data = yaml.safe_load(f) or {}

        self.keywords = [k.lower() for k in data.get("keywords", [])]
        self.phrases = [p.lower() for p in data.get("phrases", [])]

    def classify(self, text: str, *, has_image: bool = False) -> ClassificationResult:
        normalized = (text or "").lower()
        matched_keywords: list[str] = []
        matched_phrases: list[str] = []

        for keyword in self.keywords:
            if keyword and keyword in normalized:
                matched_keywords.append(keyword)

        for phrase in self.phrases:
            if phrase and phrase in normalized:
                matched_phrases.append(phrase)

        keyword_score = min(1.0, len(matched_keywords) * 0.12)
        phrase_score = min(0.4, len(matched_phrases) * 0.15)
        date_bonus = 0.15 if DATE_PATTERN.search(normalized) else 0.0
        time_bonus = 0.05 if TIME_PATTERN.search(normalized) else 0.0

        score = min(1.0, keyword_score + phrase_score + date_bonus + time_bonus)

        if has_image and (normalized.strip() or score >= self.min_score_reject):
            return ClassificationResult(
                score=max(score, self.min_score_pass),
                action="force_pass",
                matched_keywords=matched_keywords,
                matched_phrases=matched_phrases,
            )

        if score < self.min_score_reject:
            action = "reject"
        elif score >= self.min_score_pass:
            action = "pass"
        else:
            action = "reject"

        return ClassificationResult(
            score=score,
            action=action,
            matched_keywords=matched_keywords,
            matched_phrases=matched_phrases,
        )
