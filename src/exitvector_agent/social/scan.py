"""Scan orchestration for source adapters and trend ranking."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from exitvector_agent.database import Database
from exitvector_agent.logging import setup_logging
from exitvector_agent.social.extractors import TickerExtractor
from exitvector_agent.social.models import SocialObservation
from exitvector_agent.social.sources import MockSourceAdapter, SourceAdapter, SourceRunner
from exitvector_agent.social.trends import SocialTrendScorer
from exitvector_agent.social.velocity import MentionVelocityEngine

logger = setup_logging("exitvector.social.scan")


@dataclass(frozen=True, slots=True)
class TrendResult:
    """A ranked ticker trend summary."""

    ticker: str
    score: float
    velocity_ratio: float
    acceleration: float
    baseline_mentions: int
    current_mentions: int
    unique_authors: int
    confirming_sources: int
    reasons: list[str]


class SocialScanService:
    """Collect observations, calculate trends, and persist summary snapshots."""

    def __init__(
        self,
        database: Database,
        adapters: Iterable[SourceAdapter] | None = None,
        extractor: TickerExtractor | None = None,
        velocity_engine: MentionVelocityEngine | None = None,
        scorer: SocialTrendScorer | None = None,
        runner: SourceRunner | None = None,
        on_source_result=None,
    ) -> None:
        self.database = database
        self.extractor = extractor or TickerExtractor()
        self.velocity_engine = velocity_engine or MentionVelocityEngine()
        self.scorer = scorer or SocialTrendScorer()
        self.runner = runner or SourceRunner()
        self.on_source_result = on_source_result
        self.adapters = list(adapters) if adapters is not None else [
            MockSourceAdapter("stocktwits"),
            MockSourceAdapter("reddit"),
        ]

    async def run(self) -> list[TrendResult]:
        """Collect all source observations and return ranked trend results."""

        observations: list[SocialObservation] = []
        self.source_results = []
        for adapter in self.adapters:
            result = await self.runner.run(adapter)
            self.source_results.append(result)
            if self.on_source_result:
                self.on_source_result(result)
            if result.error:
                logger.warning("source_failed", extra={"context": {"source": result.source, "error_type": result.error}})
                continue
            observations.extend(result.observations)
            for observation in result.observations:
                self._persist_observation(observation)

        if any(row.raw_metadata.get('is_live_data') for row in observations):
            # Repeated/incremental live reads must use a unique rolling evidence set,
            # including the preceding baseline, restricted to explicitly selected sources.
            sources = sorted({row.source for row in observations})
            current = {(row.source, row.external_id): row for row in observations}
            lower = (datetime.now(timezone.utc) - timedelta(minutes=120)).isoformat()
            placeholders = ','.join('?' for _ in sources)
            stored = self.database.execute(f'SELECT * FROM social_observations WHERE source IN ({placeholders}) AND observed_at>=?', (*sources, lower))
            for row in stored:
                key = row['source'], row['external_id']
                if key not in current:
                    current[key] = SocialObservation(source=row['source'], external_id=row['external_id'],
                        timestamp=datetime.fromisoformat(row['observed_at']), text=row['raw_text'], author='',
                        tickers=row['ticker'].split(','), likes=row['likes'], replies=row['replies'],
                        reposts=row['reposts'], views=row['views'], raw_metadata=json.loads(row['metadata']))
            observations = list(current.values())
        ranked: list[TrendResult] = []
        all_tickers: dict[str, list[SocialObservation]] = {}
        for observation in observations:
            for ticker in observation.tickers:
                all_tickers.setdefault(ticker, []).append(observation)

        for ticker, ticker_observations in sorted(all_tickers.items()):
            stats = self.velocity_engine.calculate(ticker, observations, datetime.now(timezone.utc))
            current = stats.get(60)
            if current is None or current.mentions < self.scorer.min_volume:
                continue
            score = self.scorer.score(
                velocity_ratio=current.velocity_ratio,
                acceleration=current.acceleration,
                absolute_volume=current.mentions,
                unique_authors=current.unique_authors,
                engagement_weighted=current.engagement_weighted,
                confirming_sources=current.confirming_sources,
            )
            if not self.scorer.qualifies(score):
                continue
            ranked.append(
                TrendResult(
                    ticker=ticker,
                    score=score,
                    velocity_ratio=current.velocity_ratio,
                    acceleration=current.acceleration,
                    baseline_mentions=current.baseline_mentions,
                    current_mentions=current.mentions,
                    unique_authors=current.unique_authors,
                    confirming_sources=current.confirming_sources,
                    reasons=[
                        f"{score:.1f}/100 social trend score",
                        f"+{current.velocity_ratio * 100:.0f}% mention acceleration",
                    ],
                )
            )
            self.database.insert_trend_snapshot(
                ticker=ticker,
                score=score,
                velocity_ratio=current.velocity_ratio,
                acceleration=current.acceleration,
                baseline_mentions=current.baseline_mentions,
                current_mentions=current.mentions,
                unique_authors=current.unique_authors,
                confirming_sources=current.confirming_sources,
            )

        return sorted(ranked, key=lambda item: item.score, reverse=True)

    def run_sync(self, *, limit: int | None = None) -> list[TrendResult]:
        """Run the async scan from synchronous CLI code."""

        return asyncio.run(self.run())[:limit]

    def _persist_observation(self, observation: SocialObservation) -> None:
        if not observation.tickers:
            observation.tickers = self.extractor.extract(observation.text)
        if not observation.tickers:
            return
        observation_id = self.database.insert_observation(
            source=observation.source,
            external_id=observation.external_id,
            timestamp=observation.timestamp.isoformat(),
            text=observation.text,
            author='' if observation.raw_metadata.get('is_live_data') else observation.author,
            url=observation.url,
            tickers=",".join(observation.tickers),
            likes=observation.likes,
            replies=observation.replies,
            reposts=observation.reposts,
            views=observation.views,
            raw_metadata=json.dumps(observation.raw_metadata, ensure_ascii=False),
        )
        for ticker in observation.tickers:
            engagement_score = (
                observation.likes
                + observation.replies * 2
                + observation.reposts * 3
                + observation.views / 1000
            )
            self.database.insert_ticker_mention(
                ticker=ticker,
                source=observation.source,
                observation_id=observation_id,
                engagement_score=engagement_score,
            )


def collect_mock_trends() -> list[TrendResult]:
    """Collect deterministic mock trends without live data or credentials."""

    with Database("./data/exitvector.db") as database:
        service = SocialScanService(database=database)
        return asyncio.run(service.run())
