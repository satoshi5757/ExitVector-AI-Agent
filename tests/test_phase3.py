from datetime import datetime, timezone
from pathlib import Path

import pytest

from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.regivion import MockRegivionClient, RegivionEnrichment
from exitvector_agent.opportunity import (
    ContentAngle,
    OpportunityScorer,
    PostOpportunity,
    classify_content_angle,
    recommend_visual,
)
from exitvector_agent.social.sources import MockSourceAdapter


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "exitvector.db")
    ensure_schema(db)
    return db


def test_zero_baseline_has_reduced_history_confidence() -> None:
    confidence = OpportunityScorer().history_confidence(baseline_mentions=0, current_mentions=8)

    assert 0.0 < confidence < 1.0
    assert confidence < OpportunityScorer().history_confidence(baseline_mentions=20, current_mentions=160)


def test_regivion_enrichment_normalizes_partial_payloads() -> None:
    enrichment = RegivionEnrichment.from_payload(
        {
            "symbol": "MSFT",
            "psc": {"score": 98.4, "rank": 10, "previous_rank": 28, "status": "bullish"},
            "fundamentals": {"revenue_growth_yoy": 0.12, "earnings_growth_yoy": 0.10},
            "alerts": [{"name": "Positive momentum", "category": "momentum", "direction": "bullish", "timestamp": "2026-10-07T09:00:00Z"}],
        }
    )

    assert enrichment.symbol == "MSFT"
    assert enrichment.psc_score == 98.4
    assert enrichment.psc_rank == 10
    assert enrichment.previous_psc_rank == 28
    assert enrichment.rank_change == -18
    assert enrichment.psc_status == "bullish"
    assert enrichment.fresh_revenue_growth is True
    assert enrichment.recent_alert_names == ["Positive momentum"]


def test_opportunity_score_renormalizes_missing_market_component() -> None:
    score = OpportunityScorer(weights={"social": 0.30, "regivion": 0.25, "market": 0.15, "freshness": 0.10, "novelty": 0.10, "engagement": 0.10}).score(
        social_score=75.2,
        regivion_score=98.0,
        market_score=None,
        freshness_score=90.0,
        novelty_score=70.0,
        engagement_potential_score=80.0,
        history_confidence=0.75,
    )

    assert 0.0 <= score <= 100.0
    assert score > 70.0


def test_confidence_is_independent_of_total_score() -> None:
    confidence = OpportunityScorer().confidence(
        total_score=75.5,
        history_confidence=1.0,
        data_coverage=1.0,
        signal_agreement=1.0,
    )

    assert confidence == "HIGH"


def test_content_classification_and_visual_recommendation() -> None:
    angle = classify_content_angle(
        psc_rank_jump=True,
        fresh_bullish_alert=True,
        revenue_growth=True,
        insider_buy=False,
        politician_trade=False,
    )
    visual = recommend_visual(angle)

    assert angle == ContentAngle.PSC_RANK_JUMP
    assert "PSC" in visual


def test_mock_regivion_client_tracks_expected_scenarios() -> None:
    client = MockRegivionClient()

    msft = client.get_ticker("MSFT")
    nvda = client.get_ticker("NVDA")
    uber = client.get_ticker("UBER")
    xyz = client.get_ticker("XYZ")

    assert msft.psc_rank == 10
    assert nvda.psc_rank == 1
    assert uber.psc_score >= 90
    assert xyz is None


def test_mock_social_scenario_includes_uber() -> None:
    observations = MockSourceAdapter("mock").mock_observations()
    tickers = {ticker for observation in observations for ticker in observation.tickers}

    assert "UBER" in tickers


def test_opportunity_service_keeps_non_eligible_opportunities_ranked(database: Database) -> None:
    database.insert_opportunity(
        ticker="MSFT",
        total_score=75.5,
        confidence="HIGH",
        social_trend_score=95.0,
        regivion_score=98.0,
        market_score=50.0,
        freshness_score=90.0,
        novelty_score=80.0,
        engagement_potential_score=80.0,
        trigger_reasons='["social acceleration"]',
        social_summary="High",
        regivion_summary="Strong",
        strongest_fact="Strong",
        supporting_facts='["Strong"]',
        urgency="high",
        suggested_content_angle="MOMENTUM_CONVERGENCE",
        suggested_visual_type="chart",
        content_angles='["MOMENTUM_CONVERGENCE"]',
        notification_eligible=0,
    )

    ranked = [
        {"symbol": "MSFT", "score": 75.5, "eligible": False},
        {"symbol": "NVDA", "score": 72.4, "eligible": True},
        {"symbol": "UBER", "score": 72.1, "eligible": False},
    ]

    assert ranked[0]["symbol"] == "MSFT"
    assert ranked[0]["score"] > ranked[1]["score"] > ranked[2]["score"]
    assert ranked[0]["eligible"] is False


def test_novelty_guard_blocks_material_duplicates(database: Database) -> None:
    database.insert_opportunity(
        ticker="MSFT",
        total_score=91.4,
        confidence="HIGH",
        social_trend_score=75.2,
        regivion_score=98.0,
        market_score=50.0,
        freshness_score=90.0,
        novelty_score=70.0,
        engagement_potential_score=80.0,
        trigger_reasons='["social acceleration", "PSC rank jump"]',
        social_summary="High social acceleration",
        regivion_summary="PSC rank jumped",
        strongest_fact="PSC rank 28 -> 10",
        supporting_facts='["fresh bullish alert"]',
        urgency="high",
        suggested_content_angle="MULTI_SIGNAL_CONVERGENCE",
        suggested_visual_type="PSCs and chart",
        content_angles='["MOMENTUM_CONVERGENCE", "PSC_RANK_JUMP"]',
        notification_eligible=1,
    )

    assert database.is_opportunity_eligible("MSFT", score=91.4, threshold=75, delta=10, now=datetime.now(timezone.utc)) is False
    assert database.is_opportunity_eligible("MSFT", score=101.0, threshold=75, delta=10, now=datetime.now(timezone.utc)) is False


def test_opportunity_cooldown_blocks_immediate_renotification(database: Database) -> None:
    now = datetime.now(timezone.utc)
    database.insert_opportunity(
        ticker="MSFT",
        total_score=90.0,
        confidence="HIGH",
        social_trend_score=80.0,
        regivion_score=95.0,
        market_score=50.0,
        freshness_score=90.0,
        novelty_score=80.0,
        engagement_potential_score=80.0,
        trigger_reasons='["social acceleration"]',
        social_summary="High",
        regivion_summary="Strong",
        strongest_fact="Strong",
        supporting_facts='["Strong"]',
        urgency="high",
        suggested_content_angle="MOMENTUM_CONVERGENCE",
        suggested_visual_type="chart",
        content_angles='["MOMENTUM_CONVERGENCE"]',
        notification_eligible=1,
        detected_at=now.isoformat(),
    )

    assert database.is_opportunity_eligible("MSFT", score=95.0, threshold=75, delta=10, now=now, cooldown_minutes=180) is False


def test_database_supports_regivion_snapshot_persistence(database: Database) -> None:
    database.insert_regivion_snapshot(
        ticker="MSFT",
        payload={
            "symbol": "MSFT",
            "psc": {"score": 98.4, "rank": 10, "previous_rank": 28, "status": "bullish"},
            "alerts": [{"name": "Positive momentum", "category": "momentum", "direction": "bullish"}],
        },
    )

    row = database.get_regivion_snapshot("MSFT")
    assert row["ticker"] == "MSFT"
    assert '"psc"' in row["payload"]


def _insert_msft_opportunity(database: Database, *, score: float = 81.6, detected_at: datetime | None = None, eligible: int = 1) -> None:
    database.insert_opportunity(
        ticker="MSFT",
        total_score=score,
        confidence="HIGH",
        social_trend_score=75.2,
        regivion_score=100.0,
        market_score=50.0,
        freshness_score=90.0,
        novelty_score=80.0,
        engagement_potential_score=80.0,
        trigger_reasons='["social acceleration", "PSC score 98.4"]',
        social_summary="High",
        regivion_summary="Strong",
        strongest_fact="Strong",
        supporting_facts='["Strong"]',
        urgency="high",
        suggested_content_angle="MULTI_SIGNAL_CONVERGENCE",
        suggested_visual_type="chart",
        content_angles='["MULTI_SIGNAL_CONVERGENCE"]',
        notification_eligible=eligible,
        detected_at=(detected_at or datetime.now(timezone.utc)).isoformat(),
    )
    database.insert_regivion_snapshot(
        ticker="MSFT",
        payload={
            "symbol": "MSFT",
            "psc": {"score": 98.4, "rank": 10, "previous_rank": 28, "status": "bullish"},
            "alerts": [{"name": "positive_momentum", "category": "momentum", "direction": "bullish"}],
            "insiders": [],
            "politicians": [],
            "entered_top_20": True,
        },
    )


def test_repeated_enrichment_is_not_material(database: Database) -> None:
    _insert_msft_opportunity(database)
    payload = {
        "symbol": "MSFT",
        "psc": {"score": 98.4, "rank": 10, "previous_rank": 28, "status": "bullish"},
        "alerts": [{"name": "positive_momentum", "category": "momentum", "direction": "bullish"}],
        "insiders": [],
        "politicians": [],
        "entered_top_20": True,
    }

    eligible, reason = database.evaluate_re_notification(
        "MSFT",
        score=81.6,
        threshold=75.0,
        delta=10.0,
        now=datetime.now(timezone.utc),
        cooldown_minutes=180,
        current_enrichment=payload,
        current_primary_angle="MULTI_SIGNAL_CONVERGENCE",
    )

    assert eligible is False
    assert reason is None


def test_score_delta_triggers_renotification(database: Database) -> None:
    _insert_msft_opportunity(database)

    eligible, reason = database.evaluate_re_notification(
        "MSFT",
        score=91.6,
        threshold=75.0,
        delta=10.0,
        now=datetime.now(timezone.utc),
        cooldown_minutes=180,
        current_enrichment={"symbol": "MSFT", "psc": {"score": 98.4, "rank": 10, "previous_rank": 28}, "alerts": [], "insiders": [], "politicians": [], "entered_top_20": True},
        current_primary_angle="MULTI_SIGNAL_CONVERGENCE",
    )

    assert eligible is True
    assert reason == "SCORE_DELTA"


def test_new_alert_with_small_score_delta_triggers_renotification(database: Database) -> None:
    _insert_msft_opportunity(database)

    eligible, reason = database.evaluate_re_notification(
        "MSFT",
        score=81.6,
        threshold=75.0,
        delta=10.0,
        now=datetime.now(timezone.utc),
        cooldown_minutes=180,
        current_enrichment={
            "symbol": "MSFT",
            "psc": {"score": 98.4, "rank": 10, "previous_rank": 28},
            "alerts": [{"name": "positive_momentum"}, {"name": "earnings_acceleration"}],
            "insiders": [],
            "politicians": [],
            "entered_top_20": True,
        },
        current_primary_angle="MULTI_SIGNAL_CONVERGENCE",
    )

    assert eligible is True
    assert reason == "NEW_ALERT"


def test_rank_milestone_with_small_score_delta_triggers_renotification(database: Database) -> None:
    _insert_msft_opportunity(database)

    eligible, reason = database.evaluate_re_notification(
        "MSFT",
        score=81.6,
        threshold=75.0,
        delta=10.0,
        now=datetime.now(timezone.utc),
        cooldown_minutes=180,
        current_enrichment={
            "symbol": "MSFT",
            "psc": {"score": 98.4, "rank": 5, "previous_rank": 10},
            "alerts": [{"name": "positive_momentum"}],
            "insiders": [],
            "politicians": [],
            "entered_top_20": True,
        },
        current_primary_angle="MULTI_SIGNAL_CONVERGENCE",
    )

    assert eligible is True
    assert reason == "PSC_RANK_MILESTONE"


def test_new_insider_transaction_with_small_score_delta_triggers_renotification(database: Database) -> None:
    _insert_msft_opportunity(database)

    eligible, reason = database.evaluate_re_notification(
        "MSFT",
        score=81.6,
        threshold=75.0,
        delta=10.0,
        now=datetime.now(timezone.utc),
        cooldown_minutes=180,
        current_enrichment={
            "symbol": "MSFT",
            "psc": {"score": 98.4, "rank": 10, "previous_rank": 28},
            "alerts": [{"name": "positive_momentum"}],
            "insiders": [{"buyer": "CEO", "action": "buy", "timestamp": "2026-10-07T12:00:00Z"}],
            "politicians": [],
            "entered_top_20": True,
        },
        current_primary_angle="INSIDER_BUY",
    )

    assert eligible is True
    assert reason == "NEW_INSIDER_TRANSACTION"


def test_new_politician_transaction_with_small_score_delta_triggers_renotification(database: Database) -> None:
    _insert_msft_opportunity(database)

    eligible, reason = database.evaluate_re_notification(
        "MSFT",
        score=81.6,
        threshold=75.0,
        delta=10.0,
        now=datetime.now(timezone.utc),
        cooldown_minutes=180,
        current_enrichment={
            "symbol": "MSFT",
            "psc": {"score": 98.4, "rank": 10, "previous_rank": 28},
            "alerts": [{"name": "positive_momentum"}],
            "insiders": [],
            "politicians": [{"actor": "Senator A", "action": "buy", "timestamp": "2026-10-07T12:00:00Z"}],
            "entered_top_20": True,
        },
        current_primary_angle="POLITICIAN_BUY",
    )

    assert eligible is True
    assert reason == "NEW_POLITICIAN_TRANSACTION"


def test_primary_angle_change_triggers_renotification(database: Database) -> None:
    _insert_msft_opportunity(database)

    eligible, reason = database.evaluate_re_notification(
        "MSFT",
        score=81.6,
        threshold=75.0,
        delta=10.0,
        now=datetime.now(timezone.utc),
        cooldown_minutes=180,
        current_enrichment={
            "symbol": "MSFT",
            "psc": {"score": 98.4, "rank": 10, "previous_rank": 28},
            "alerts": [{"name": "positive_momentum"}],
            "insiders": [],
            "politicians": [],
            "entered_top_20": True,
        },
        current_primary_angle="PSC_RANK_JUMP",
    )

    assert eligible is True
    assert reason == "ANGLE_CHANGE"


def test_cooldown_expiry_triggers_renotification(database: Database) -> None:
    _insert_msft_opportunity(database, detected_at=datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0))

    eligible, reason = database.evaluate_re_notification(
        "MSFT",
        score=81.6,
        threshold=75.0,
        delta=10.0,
        now=datetime.now(timezone.utc),
        cooldown_minutes=180,
        current_enrichment={
            "symbol": "MSFT",
            "psc": {"score": 98.4, "rank": 10, "previous_rank": 28},
            "alerts": [{"name": "positive_momentum"}],
            "insiders": [],
            "politicians": [],
            "entered_top_20": True,
        },
        current_primary_angle="MULTI_SIGNAL_CONVERGENCE",
    )

    assert eligible is True
    assert reason == "COOLDOWN_EXPIRED"


def test_non_material_renrichment_refresh_is_not_material(database: Database) -> None:
    _insert_msft_opportunity(database)

    eligible, reason = database.evaluate_re_notification(
        "MSFT",
        score=81.6,
        threshold=75.0,
        delta=10.0,
        now=datetime.now(timezone.utc),
        cooldown_minutes=180,
        current_enrichment={
            "symbol": "MSFT",
            "psc": {"score": 98.4, "rank": 10, "previous_rank": 28},
            "alerts": [{"name": "positive_momentum"}],
            "insiders": [],
            "politicians": [],
            "entered_top_20": True,
        },
        current_primary_angle="MULTI_SIGNAL_CONVERGENCE",
    )

    assert eligible is False
    assert reason is None
