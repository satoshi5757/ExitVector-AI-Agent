from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from dataclasses import replace

from exitvector_agent.content import (
    ContentCandidate,
    ContentFormat,
    ContentGeneratorProtocol,
    RuleBasedContentGenerator,
    select_content_format,
)
from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.opportunity import ContentAngle, PostOpportunity


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "exitvector.db")
    ensure_schema(db)
    return db


def make_opportunity(symbol: str, *, angle: str, score: float, confidence: str = "HIGH") -> PostOpportunity:
    return PostOpportunity(
        symbol=symbol,
        total_score=score,
        confidence=confidence,
        social_trend_score=80.0,
        regivion_score=95.0,
        market_score=60.0,
        freshness_score=90.0,
        novelty_score=80.0,
        engagement_potential_score=60.0,
        trigger_reasons=["social acceleration", "PSC rank jump"],
        social_summary="Social attention is accelerating",
        regivion_summary="Strong Regivion signal",
        strongest_fact="PSC rank moved sharply",
        supporting_facts=["Strong signal", "Fresh alert"],
        urgency="high",
        suggested_content_angle=angle,
        suggested_visual_type="PSC screenshot + chart",
        content_angles=[angle],
        history_confidence=1.0,
        notification_eligible=True,
    )


def test_format_selection_uses_angle_and_opportunity() -> None:
    assert select_content_format(ContentAngle.PSC_RANK_JUMP) == ContentFormat.BREAKING_SIGNAL
    assert select_content_format(ContentAngle.MULTI_SIGNAL_CONVERGENCE) == ContentFormat.DATA_POINT
    assert select_content_format(ContentAngle.VALUATION_DISLOCATION) == ContentFormat.CONTRARIAN_TAKE


def test_hook_generation_returns_multiple_families() -> None:
    generator = RuleBasedContentGenerator()
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    hooks = generator.generate_hooks(opportunity)

    assert len(hooks) >= 3
    assert all(len(hook) > 0 for hook in hooks)
    assert any("$MSFT" in hook for hook in hooks)


def test_strongest_fact_selection_prioritizes_timely_and_large_changes() -> None:
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)
    generator = RuleBasedContentGenerator()

    facts = generator.select_facts(opportunity)

    assert len(facts) >= 1
    assert any("PSC" in fact or "rank" in fact.lower() for fact in facts)


def test_factuality_guard_blocks_unverified_claims() -> None:
    generator = RuleBasedContentGenerator()
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    candidate = generator.generate_candidate(opportunity)

    assert candidate.factuality_warnings == []
    assert candidate.requires_human_review is True
    assert candidate.full_text
    assert "will explode" not in candidate.full_text.lower()


def test_missing_facts_are_excluded_from_copy() -> None:
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)
    opportunity = replace(opportunity, trigger_reasons=[])
    generator = RuleBasedContentGenerator()

    candidate = generator.generate_candidate(opportunity)

    assert candidate.facts_used
    assert candidate.missing_context
    assert candidate.missing_context[0].startswith("Missing")


def test_deterministic_draft_generation_is_repeatable() -> None:
    generator = RuleBasedContentGenerator()
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    first = generator.generate_candidate(opportunity)
    second = generator.generate_candidate(opportunity)

    assert first.full_text == second.full_text
    assert first.hook == second.hook


def test_candidate_ranking_prioritizes_score_and_signal_strength() -> None:
    generator = RuleBasedContentGenerator()
    msft = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)
    nvda = make_opportunity("NVDA", angle=ContentAngle.MULTI_SIGNAL_CONVERGENCE.value, score=76.0)
    uber = make_opportunity("UBER", angle=ContentAngle.VALUATION_DISLOCATION.value, score=74.0)

    ranked = generator.rank_candidates([nvda, msft, uber])

    assert [candidate.symbol for candidate in ranked] == ["MSFT", "NVDA", "UBER"]


def test_engagement_heuristic_is_configurable() -> None:
    generator = RuleBasedContentGenerator()
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    candidate = generator.generate_candidate(opportunity)

    assert 0 <= candidate.estimated_engagement_score <= 100
    assert candidate.estimated_engagement_score > 0


def test_duplicate_content_is_suppressed_by_hash_and_cooldown(database: Database) -> None:
    generator = RuleBasedContentGenerator(database=database, content_cooldown_minutes=180)
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    first = generator.generate_candidate(opportunity)
    second = generator.generate_candidate(opportunity)

    assert first.content_hash == second.content_hash
    assert generator.is_duplicate(first) is True
    assert generator.is_duplicate(first, force_generate=True) is True


def test_content_cooldown_allows_material_change_regeneration(database: Database) -> None:
    generator = RuleBasedContentGenerator(database=database, content_cooldown_minutes=180)
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)
    first = generator.generate_candidate(opportunity)
    opportunity = replace(
        opportunity,
        trigger_reasons=[*opportunity.trigger_reasons, "new bullish fracture"],
        total_score=90.0,
    )
    second = generator.generate_candidate(opportunity)

    assert second.full_text != first.full_text
    assert second.format != first.format


def test_database_persists_content_candidate(database: Database) -> None:
    generator = RuleBasedContentGenerator(database=database)
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    candidate = generator.generate_candidate(opportunity)
    row = database.get_recent_candidate("MSFT")

    assert row is not None
    assert row["format"] == candidate.format.value
    assert row["review_status"] == "PENDING"
    assert row["requires_human_review"] == 1


def test_content_review_status_is_explicit() -> None:
    generator = RuleBasedContentGenerator()
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)
    candidate = generator.generate_candidate(opportunity)

    assert candidate.review_status == "PENDING"
    assert candidate.requires_human_review is True


def test_xyz_generates_nothing() -> None:
    generator = RuleBasedContentGenerator()
    opportunity = make_opportunity("XYZ", angle=ContentAngle.SOCIAL_SPIKE.value, score=10.0)

    candidates = generator.generate_for_opportunity(opportunity)

    assert candidates == []


def test_phase4_deterministic_behavior_for_msft_nvda_uber() -> None:
    generator = RuleBasedContentGenerator()
    opportunities = [
        make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0),
        make_opportunity("NVDA", angle=ContentAngle.MULTI_SIGNAL_CONVERGENCE.value, score=76.0),
        make_opportunity("UBER", angle=ContentAngle.VALUATION_DISLOCATION.value, score=74.0),
    ]

    candidates = [candidate for opportunity in opportunities for candidate in generator.generate_for_opportunity(opportunity)]

    symbols = [candidate.symbol for candidate in candidates]
    assert symbols.count("MSFT") >= 3
    assert symbols.count("NVDA") >= 3
    assert symbols.count("UBER") >= 3
    assert all("$" in candidate.full_text for candidate in candidates if candidate.symbol != "XYZ")


def test_content_generator_protocol_is_implemented() -> None:
    generator = RuleBasedContentGenerator()
    assert isinstance(generator, ContentGeneratorProtocol)
