"""Ticker extraction and false-positive filtering."""

from __future__ import annotations

import re
from dataclasses import dataclass


DEFAULT_EXCLUSIONS = {
    "AI",
    "AND",
    "ARE",
    "ATH",
    "CEO",
    "ETF",
    "FED",
    "GDP",
    "IS",
    "SEC",
    "SAYS",
    "THE",
    "USA",
    "WITH",
}

MARKET_CONTEXT = {
    "EARNINGS",
    "MARKET",
    "MOMENTUM",
    "MOVING",
    "PRICE",
    "RALLY",
    "SHARES",
    "STOCK",
    "TICKER",
    "TRADING",
    "VOLUME",
}


@dataclass(frozen=True, slots=True)
class TickerExtractor:
    """Extract stock symbols from social text with configurable exclusions."""

    exclusions: set[str] | None = None
    minimum_length: int = 1
    maximum_length: int = 5

    def __post_init__(self) -> None:
        if self.exclusions is None:
            object.__setattr__(self, "exclusions", DEFAULT_EXCLUSIONS)
        else:
            object.__setattr__(self, "exclusions", {item.upper() for item in self.exclusions})

    def extract(self, text: str) -> list[str]:
        """Return uppercase tickers in order of appearance."""

        matches: list[str] = []
        seen: set[str] = set()
        tokens = self._candidate_tokens(text)
        for candidate in tokens:
            if candidate in self.exclusions:
                continue
            if len(candidate) < self.minimum_length or len(candidate) > self.maximum_length:
                continue
            if not candidate.isalpha() or not candidate.isupper():
                continue
            if not self._is_high_confidence_candidate(text, candidate):
                continue
            if candidate not in seen:
                seen.add(candidate)
                matches.append(candidate)
        return matches

    def _is_high_confidence_candidate(self, text: str, candidate: str) -> bool:
        if re.search(r"\$" + re.escape(candidate) + r"\b", text, flags=re.IGNORECASE):
            return True
        pattern = re.compile(r"\$" + re.escape(candidate) + r"\b|\b" + re.escape(candidate) + r"\b")
        for match in pattern.finditer(text):
            start, end = match.span()
            context = text[max(0, start - 20) : min(len(text), end + 20)].upper()
            if re.search(r"\$" + re.escape(candidate), context):
                return True
            if any(word in MARKET_CONTEXT for word in re.findall(r"[A-Z]+", context)):
                return True
        return False

    def _candidate_tokens(self, text: str) -> list[str]:
        return [
            match.group(1)
            for match in re.finditer(r"\$?([A-Z]{1,5})\b", text.upper())
        ]
