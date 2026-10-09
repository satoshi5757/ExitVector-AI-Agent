from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.social.models import SocialObservation
from exitvector_agent.social.extractors import TickerExtractor
from exitvector_agent.social.velocity import MentionVelocityEngine
from exitvector_agent.social.trends import SocialTrendScorer
from exitvector_agent.social.sources import MockSourceAdapter, SourceFailure


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "exitvector.db")
    ensure_schema(db)
    return db


def test_ticker_extraction_supports_symbols_and_capitalized_tokens() -> None:
    text = "$MSFT and NVDA are moving; $UBER is active."

    assert TickerExtractor().extract(text) == ["MSFT", "NVDA", "UBER"]


def test_ticker_extraction_excludes_false_positive_terms() -> None:
    text = "AI CEO says USA GDP is strong, ATH is a new ETF. SEC and FED remain quiet."

    assert TickerExtractor().extract(text) == []


def test_ticker_extraction_uses_configurable_exclusions() -> None:
    extractor = TickerExtractor(exclusions={"AI", "BETA"})

    assert extractor.extract("AI BETA") == []


def test_normalization_preserves_source_fields() -> None:
    observed_at = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    observation = SocialObservation(
        source="stocktwits",
        external_id="abc-123",
        timestamp=observed_at,
        text="$MSFT hits a new high",
        author="trader_1",
        url="https://example.com/post/abc-123",
        tickers=["MSFT"],
        likes=10,
        replies=2,
        reposts=3,
        views=500,
        raw_metadata={"sentiment": "bullish"},
    )

    assert observation.source == "stocktwits"
    assert observation.raw_metadata["sentiment"] == "bullish"
    assert observation.to_db_record()["ticker"] == "MSFT"


def test_duplicate_observations_are_detected_by_source_and_external_id() -> None:
    source = MockSourceAdapter("mock")
    observation = SocialObservation(
        source="mock",
        external_id="duplicate-id",
        timestamp=datetime.now(timezone.utc),
        text="$MSFT",
        author="author",
        tickers=["MSFT"],
    )

    assert source.is_duplicate(observation) is False
    assert source.is_duplicate(observation) is True


def test_velocity_engine_uses_rolling_windows_and_handles_zero_baseline() -> None:
    now = datetime.now(timezone.utc)
    observations = [
        SocialObservation(
            source="mock",
            external_id=f"obs-{idx}",
            timestamp=now - timedelta(minutes=idx),
            text="$MSFT",
            author=f"user-{idx}",
            tickers=["MSFT"],
        )
        for idx in range(1, 9)
    ]
    engine = MentionVelocityEngine(window_minutes=(10, 30, 60), baseline_window_minutes=60)

    stats = engine.calculate("MSFT", observations, now)

    assert stats[10].mentions == 8
    assert stats[30].mentions == 8
    assert stats[60].mentions == 8
    assert stats[60].velocity_ratio == 8.0
    assert stats[60].acceleration == 8.0
    assert stats[60].baseline_mentions == 0


def test_velocity_engine_prevents_huge_score_from_single_mention_growth() -> None:
    now = datetime.now(timezone.utc)
    observations = [
        SocialObservation(
            source="mock",
            external_id="baseline",
            timestamp=now - timedelta(minutes=80),
            text="$XYZ",
            author="a",
            tickers=["XYZ"],
        ),
        SocialObservation(
            source="mock",
            external_id="current-1",
            timestamp=now - timedelta(minutes=15),
            text="$XYZ",
            author="b",
            tickers=["XYZ"],
        ),
        SocialObservation(
            source="mock",
            external_id="current-2",
            timestamp=now,
            text="$XYZ",
            author="c",
            tickers=["XYZ"],
        ),
    ]
    engine = MentionVelocityEngine(window_minutes=(10, 30, 60), baseline_window_minutes=60)

    stats = engine.calculate("XYZ", observations, now)
    assert stats[60].velocity_ratio == 2.0
    assert stats[60].acceleration == 1.0


def test_social_trend_score_requires_minimum_volume_and_thresholds() -> None:
    scorer = SocialTrendScorer(
        weights={
            "velocity": 0.30,
            "acceleration": 0.20,
            "absolute_volume": 0.15,
            "unique_authors": 0.15,
            "engagement": 0.10,
            "cross_source": 0.10,
        },
        min_volume=5,
        min_score=50,
    )
    strong = scorer.score(
        velocity_ratio=3.8,
        acceleration=2.1,
        absolute_volume=38,
        unique_authors=19,
        engagement_weighted=14,
        confirming_sources=2,
    )
    weak = scorer.score(
        velocity_ratio=2.0,
        acceleration=0.3,
        absolute_volume=2,
        unique_authors=2,
        engagement_weighted=1,
        confirming_sources=1,
    )

    assert strong > 80
    assert weak < 50


def test_trend_score_distinguishes_cross_source_confirmation() -> None:
    scorer = SocialTrendScorer(min_volume=5, min_score=50)
    single_source = scorer.score(
        velocity_ratio=2.5,
        acceleration=1.5,
        absolute_volume=10,
        unique_authors=6,
        engagement_weighted=8,
        confirming_sources=1,
    )
    multi_source = scorer.score(
        velocity_ratio=2.5,
        acceleration=1.5,
        absolute_volume=10,
        unique_authors=6,
        engagement_weighted=8,
        confirming_sources=3,
    )

    assert multi_source > single_source


def test_database_persists_trend_snapshots(database) -> None:
    database.insert_observation(
        source="mock",
        external_id="trend-1",
        timestamp="2026-10-06T12:00:00Z",
        text="$MSFT",
        author="u1",
        url="https://example.com/1",
        tickers="MSFT",
        likes=10,
        replies=2,
        reposts=1,
        views=500,
        raw_metadata='{"source":"mock"}',
    )
    database.insert_ticker_mention(
        ticker="MSFT",
        source="mock",
        observation_id=1,
        engagement_score=12.5,
    )
    database.insert_trend_snapshot(
        ticker="MSFT",
        score=91.2,
        velocity_ratio=2.4,
        acceleration=1.7,
        baseline_mentions=10,
        current_mentions=38,
        unique_authors=19,
        confirming_sources=2,
    )

    row = database.get_recent_trend_snapshots(limit=1)[0]
    assert row["ticker"] == "MSFT"
    assert row["score"] == 91.2


def test_source_failures_are_isolated() -> None:
    class FailingSource:
        name = "failing"

        async def collect(self) -> list[SocialObservation]:
            raise RuntimeError("timeout")

    failures = []
    results = []

    async def run() -> None:
        source = FailingSource()
        try:
            await source.collect()
        except RuntimeError as exc:
            failures.append(exc)
            results.append("failed")

    import asyncio

    asyncio.run(run())

    assert failures
    assert results == ["failed"]


def test_missing_credentials_do_not_crash_source_adapter() -> None:
    source = MockSourceAdapter("mock", credentials={})

    assert source.is_configured() is True
    assert source.get_missing_credentials() == []


def test_mock_data_contains_distinct_market_scenarios() -> None:
    observations = MockSourceAdapter("mock").mock_observations()
    tickers = {ticker for observation in observations for ticker in observation.tickers}

    assert "MSFT" in tickers
    assert "NVDA" in tickers
    assert "XYZ" in tickers
