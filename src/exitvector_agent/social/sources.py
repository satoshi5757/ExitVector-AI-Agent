"""Source adapters and failure-isolation utilities."""

from __future__ import annotations

import asyncio
import logging
import httpx
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from exitvector_agent.social.extractors import TickerExtractor
from exitvector_agent.social.models import SocialObservation

logger = logging.getLogger("exitvector.social")


class SourceFailure(RuntimeError):
    """Raised when a source cannot return observations safely."""


class SourceAdapter(ABC):
    """Base interface for feed adapters returning normalized observations."""

    name: str

    @abstractmethod
    async def collect(self) -> list[SocialObservation]:
        """Collect normalized observations. Implementations must never crash the caller."""

    def is_configured(self) -> bool:
        """Return whether required credentials, endpoints, or configuration exist."""

        return True

    def get_missing_credentials(self) -> list[str]:
        """Return required credential names that are missing."""

        return []


@dataclass(slots=True)
class SourceResult:
    """Result returned by an adapter runner."""

    source: str
    observations: list[SocialObservation] = field(default_factory=list)
    error: str | None = None


class SourceRunner:
    """Execute source adapters with per-source isolation and timeout handling."""

    def __init__(self, timeout_seconds: float = 10.0, retries: int = 1, backoff_seconds: float = .1) -> None:
        self.timeout_seconds = timeout_seconds
        self.retries = max(0, retries)
        self.backoff_seconds = backoff_seconds

    async def run(self, adapter: SourceAdapter) -> SourceResult:
        """Collect observations while isolating source failures."""

        try:
            observations = await self._collect_with_retry(adapter)
            return SourceResult(source=adapter.name, observations=observations)
        except Exception as exc:  # pragma: no cover - exercised by integration tests
            logger.warning("source_failure", extra={"event": "source_failure", "context": {"source": adapter.name, "error_type": type(exc).__name__}})
            return SourceResult(source=adapter.name, error=type(exc).__name__)

    async def _collect_with_retry(self, adapter: SourceAdapter) -> list[SocialObservation]:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return await asyncio.wait_for(adapter.collect(), timeout=self.timeout_seconds)
            except Exception as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                transient = isinstance(exc, (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError)) or (isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code == 429 or exc.response.status_code >= 500))
                if not transient:
                    raise
                if getattr(adapter, 'health', None):
                    adapter.health.metrics['retries'] += 1
                await asyncio.sleep(self.backoff_seconds * (attempt + 1))
        raise SourceFailure(f"{adapter.name} failed after {self.retries + 1} attempts") from last_error


class StocktwitsAdapter(SourceAdapter):
    """Stocktwits adapter placeholder. Uses a public endpoint only when configured."""

    name = "stocktwits"

    def __init__(self, endpoint: str = "https://api.stocktwits.com/api/2/streams/symbol/", credentials: dict[str, str] | None = None) -> None:
        self.endpoint = endpoint.rstrip("/") + "/"
        self.credentials = credentials or {}
        self.extractor = TickerExtractor()

    def is_configured(self) -> bool:
        return bool(self.credentials.get("api_key"))

    def get_missing_credentials(self) -> list[str]:
        return ["api_key"] if not self.is_configured() else []

    async def collect(self) -> list[SocialObservation]:
        if not self.is_configured():
            raise SourceFailure("Stocktwits API credentials are not configured")
        raise SourceFailure("Stocktwits live integration is not implemented in Phase 2")


class RedditAdapter(SourceAdapter):
    """Reddit adapter placeholder. No browser scraping or authentication is used."""

    name = "reddit"

    def __init__(self, credentials: dict[str, str] | None = None) -> None:
        self.credentials = credentials or {}

    def is_configured(self) -> bool:
        return bool(self.credentials.get("client_id") and self.credentials.get("client_secret"))

    def get_missing_credentials(self) -> list[str]:
        missing = []
        for name in ("client_id", "client_secret"):
            if not self.credentials.get(name):
                missing.append(name)
        return missing

    async def collect(self) -> list[SocialObservation]:
        if not self.is_configured():
            raise SourceFailure("Reddit API credentials are not configured")
        raise SourceFailure("Reddit live integration is not implemented in Phase 2")


class RSSFeedAdapter(SourceAdapter):
    """RSS/Atom feed adapter using standard-library XML parsing."""

    name = "rss"

    def __init__(self, endpoints: list[str], timeout_seconds: float = 10.0) -> None:
        self.endpoints = list(endpoints)
        self.timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.endpoints)

    def get_missing_credentials(self) -> list[str]:
        return []

    async def collect(self) -> list[SocialObservation]:
        if not self.endpoints:
            raise SourceFailure("No RSS endpoints are configured")
        raise SourceFailure("RSS live integration is not implemented in Phase 2")


class MockSourceAdapter(SourceAdapter):
    """Deterministic source that works offline without credentials."""

    name = "mock"

    def __init__(self, name: str = "mock", credentials: dict[str, str] | None = None) -> None:
        self.name = name
        self.credentials = credentials or {}
        self._seen: set[str] = set()

    def is_configured(self) -> bool:
        return True

    def get_missing_credentials(self) -> list[str]:
        return []

    def is_duplicate(self, observation: SocialObservation) -> bool:
        key = f"{observation.source}:{observation.external_id}"
        if key in self._seen:
            return True
        self._seen.add(key)
        return False

    def mock_observations(self) -> list[SocialObservation]:
        """Return a deterministic multi-source market scenario."""

        now = datetime.now(timezone.utc)
        observations: list[SocialObservation] = []

        msft_authors = [
            "alpha_trader",
            "beta_trader",
            "gamma_trader",
            "delta_trader",
            "epsilon_trader",
            "zeta_trader",
            "eta_trader",
            "theta_trader",
            "iota_trader",
            "kappa_trader",
        ]
        for minute, author in enumerate(msft_authors, start=1):
            observations.append(
                SocialObservation(
                    source=self.name,
                    external_id=f"mock-{self.name}-msft-{minute}",
                    timestamp=now - timedelta(minutes=minute),
                    text="$MSFT is drawing AI/cloud attention as demand accelerates.",
                    author=author,
                    url=f"https://example.com/msft/{self.name}/{minute}",
                    tickers=["MSFT"],
                    likes=25,
                    replies=4,
                    reposts=5,
                    views=8000,
                    raw_metadata={"sentiment": "bullish", "source": self.name},
                )
            )
        for minute, author in enumerate(["msft_baseline_1", "msft_baseline_2", "msft_baseline_3"], start=1):
            observations.append(
                SocialObservation(
                    source=self.name,
                    external_id=f"mock-{self.name}-msft-baseline-{minute}",
                    timestamp=now - timedelta(minutes=90 + minute),
                    text="MSFT runs are attracting long-duration attention.",
                    author=author,
                    url=f"https://example.com/msft/{self.name}/baseline/{minute}",
                    tickers=["MSFT"],
                    likes=10,
                    replies=1,
                    reposts=2,
                    views=2000,
                    raw_metadata={"sentiment": "neutral", "source": self.name},
                )
            )

        nvda_authors = ["chip_analyst_1", "chip_analyst_2", "chip_analyst_3", "chip_analyst_4"]
        for minute, author in enumerate(nvda_authors, start=1):
            observations.append(
                SocialObservation(
                    source=self.name,
                    external_id=f"mock-{self.name}-nvda-{minute}",
                    timestamp=now - timedelta(minutes=15 + minute),
                    text="NVDA remains steady with consistent chip demand.",
                    author=author,
                    url=f"https://example.com/nvda/{self.name}/{minute}",
                    tickers=["NVDA"],
                    likes=15,
                    replies=2,
                    reposts=3,
                    views=3500,
                    raw_metadata={"sentiment": "neutral", "source": self.name},
                )
            )

        for minute, author in enumerate(["uber_analyst_1", "uber_analyst_2", "uber_analyst_3", "uber_analyst_4", "uber_analyst_5", "uber_analyst_6", "uber_analyst_7"], start=1):
            observations.append(
                SocialObservation(
                    source=self.name,
                    external_id=f"mock-{self.name}-uber-{minute}",
                    timestamp=now - timedelta(minutes=10 + minute),
                    text="UBER's valuation and cash flow profile remain compelling.",
                    author=author,
                    url=f"https://example.com/uber/{self.name}/{minute}",
                    tickers=["UBER"],
                    likes=18,
                    replies=2,
                    reposts=3,
                    views=4200,
                    raw_metadata={"sentiment": "bullish", "source": self.name},
                )
            )
        for minute, author in enumerate(["uber_baseline_1", "uber_baseline_2"], start=1):
            observations.append(
                SocialObservation(
                    source=self.name,
                    external_id=f"mock-{self.name}-uber-baseline-{minute}",
                    timestamp=now - timedelta(minutes=70 + minute),
                    text="UBER remains a steady cash-flow and mobility story.",
                    author=author,
                    url=f"https://example.com/uber/{self.name}/baseline/{minute}",
                    tickers=["UBER"],
                    likes=8,
                    replies=1,
                    reposts=1,
                    views=900,
                    raw_metadata={"sentiment": "neutral", "source": self.name},
                )
            )

        observations.append(
            SocialObservation(
                source=self.name,
                external_id=f"mock-{self.name}-xyz-1",
                timestamp=now - timedelta(minutes=45),
                text="XYZ buzz is only a single early comment.",
                author="delta_user",
                url=f"https://example.com/xyz/{self.name}/1",
                tickers=["XYZ"],
                likes=2,
                replies=0,
                reposts=0,
                views=120,
                raw_metadata={"sentiment": "speculative", "source": self.name},
            )
        )
        observations.append(
            SocialObservation(
                source=self.name,
                external_id=f"mock-{self.name}-xyz-2",
                timestamp=now - timedelta(minutes=5),
                text="XYZ appears again in a small conversation.",
                author="echo_user",
                url=f"https://example.com/xyz/{self.name}/2",
                tickers=["XYZ"],
                likes=1,
                replies=0,
                reposts=0,
                views=60,
                raw_metadata={"sentiment": "speculative", "source": self.name},
            )
        )
        return observations

    async def collect(self) -> list[SocialObservation]:
        return self.mock_observations()
