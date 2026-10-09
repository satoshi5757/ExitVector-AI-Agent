from datetime import datetime, timedelta, timezone
from pathlib import Path

from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.social.sources import MockSourceAdapter
from exitvector_agent.social.velocity import MentionVelocityEngine


def test_mock_scenario_has_multiple_sources_and_distinct_market_profiles() -> None:
    observations = MockSourceAdapter("stocktwits").mock_observations()
    observations.extend(MockSourceAdapter("reddit").mock_observations())

    tickers = {ticker for observation in observations for ticker in observation.tickers}
    counts = {ticker: sum(1 for observation in observations if ticker in observation.tickers) for ticker in tickers}

    assert "MSFT" in tickers and "NVDA" in tickers and "XYZ" in tickers
    assert counts["MSFT"] >= 10
    assert counts["NVDA"] >= 4
    assert counts["XYZ"] >= 2
    assert len({observation.source for observation in observations}) >= 2


def test_velocity_uses_previous_window_baseline() -> None:
    now = datetime.now(timezone.utc)
    observations = [
        type("Observation", (), {"timestamp": now - timedelta(minutes=120), "text": "$MSFT", "author": "a", "tickers": ["MSFT"], "likes": 0, "replies": 0, "reposts": 0, "views": 0, "source": "mock-a"})(),
        type("Observation", (), {"timestamp": now - timedelta(minutes=40), "text": "$MSFT", "author": "b", "tickers": ["MSFT"], "likes": 0, "replies": 0, "reposts": 0, "views": 0, "source": "mock-b"})(),
        type("Observation", (), {"timestamp": now - timedelta(minutes=30), "text": "$MSFT", "author": "c", "tickers": ["MSFT"], "likes": 0, "replies": 0, "reposts": 0, "views": 0, "source": "mock-c"})(),
        type("Observation", (), {"timestamp": now - timedelta(minutes=20), "text": "$MSFT", "author": "d", "tickers": ["MSFT"], "likes": 0, "replies": 0, "reposts": 0, "views": 0, "source": "mock-d"})(),
        type("Observation", (), {"timestamp": now - timedelta(minutes=10), "text": "$MSFT", "author": "e", "tickers": ["MSFT"], "likes": 0, "replies": 0, "reposts": 0, "views": 0, "source": "mock-e"})(),
    ]
    stats = MentionVelocityEngine().calculate("MSFT", observations, now)

    assert stats[60].baseline_mentions == 1
    assert stats[60].velocity_ratio == 4.0
    assert stats[60].acceleration == 3.0


def test_rerun_does_not_duplicate_observations(tmp_path: Path) -> None:
    db = Database(tmp_path / "exitvector.db")
    ensure_schema(db)
    db.insert_observation(source="mock", external_id="id-1", timestamp="2026-10-06T00:00:00Z", text="$MSFT", author="a", url="", tickers="MSFT")
    db.insert_observation(source="mock", external_id="id-1", timestamp="2026-10-06T00:00:00Z", text="$MSFT", author="a", url="", tickers="MSFT")
    db.insert_ticker_mention(ticker="MSFT", source="mock", observation_id=1, engagement_score=12.5)
    db.insert_ticker_mention(ticker="MSFT", source="mock", observation_id=1, engagement_score=12.5)
    db.insert_trend_snapshot(
        ticker="MSFT",
        score=75.2,
        velocity_ratio=3.3,
        acceleration=2.3,
        baseline_mentions=6,
        current_mentions=20,
        unique_authors=10,
        confirming_sources=2,
    )
    db.insert_trend_snapshot(
        ticker="MSFT",
        score=75.2,
        velocity_ratio=3.3,
        acceleration=2.3,
        baseline_mentions=6,
        current_mentions=20,
        unique_authors=10,
        confirming_sources=2,
    )

    assert db.execute("SELECT COUNT(*) FROM social_observations").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM ticker_mentions").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM trend_score_snapshots").fetchone()[0] == 1
