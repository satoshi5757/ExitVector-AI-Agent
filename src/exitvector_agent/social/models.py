"""Normalized social observation models."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class SocialObservation:
    """Normalized observation returned by every social data adapter."""

    source: str
    external_id: str
    timestamp: datetime
    text: str
    author: str = ""
    url: str = ""
    tickers: list[str] = field(default_factory=list)
    likes: int = 0
    replies: int = 0
    reposts: int = 0
    views: int = 0
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.text = self.text.strip()
        self.author = self.author.strip()
        self.url = self.url.strip()
        self.tickers = [ticker.upper() for ticker in self.tickers]
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)

    def to_db_record(self) -> dict[str, Any]:
        """Convert the observation into the Phase 1 SQLite schema."""

        return {
            "source": self.source,
            "external_id": self.external_id,
            "timestamp": self.timestamp.isoformat(),
            "text": self.text,
            "author": self.author,
            "url": self.url,
            "ticker": self.tickers[0] if self.tickers else "",
            "likes": self.likes,
            "replies": self.replies,
            "reposts": self.reposts,
            "views": self.views,
            "metadata": json.dumps(self.raw_metadata, ensure_ascii=False),
        }
