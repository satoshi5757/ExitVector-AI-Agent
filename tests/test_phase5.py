from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from exitvector_agent.content import (
    ContentBrief,
    ContentCandidate,
    ContentGeneratorProtocol,
    ContentValidationResult,
    LLMContentGenerator,
    MockLLMProvider,
    RuleBasedContentGenerator,
    normalize_for_similarity,
    validate_content,
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
        social_trend_score=75.2,
        regivion_score=98.4,
        market_score=60.0,
        freshness_score=90.0,
        novelty_score=80.0,
        engagement_potential_score=80.0,
        trigger_reasons=["social acceleration", "PSC rank jump"],
        social_summary="Social attention is accelerating",
        regivion_summary="PSC rank moved from 28 to 10 and a bullish alert is fresh",
        strongest_fact="PSC rank moved from 28 to 10",
        supporting_facts=["Fresh bullish Regivion alert", "Social acceleration 3.33x"],
        urgency="high",
        suggested_content_angle=angle,
        suggested_visual_type="PSC screenshot + chart",
        content_angles=[angle],
        history_confidence=1.0,
        notification_eligible=True,
    )


def test_content_generator_protocol_accepts_llm_generator() -> None:
    generator = LLMContentGenerator(provider=MockLLMProvider())

    assert isinstance(generator, ContentGeneratorProtocol)


def test_mock_provider_returns_structured_llm_response() -> None:
    provider = MockLLMProvider()
    brief = ContentBrief.from_opportunity(make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0))

    response = provider.generate("prompt", brief)

    assert response.text
    assert response.raw_output
    assert response.provider == "mock"
    assert response.model == "mock-llm"
    assert response.prompt_version == "EXITVECTOR_CONTENT_PROMPT_V1"


def test_content_brief_extracts_only_allowed_facts() -> None:
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    brief = ContentBrief.from_opportunity(opportunity)

    assert brief.symbol == "MSFT"
    assert brief.primary_angle == ContentAngle.PSC_RANK_JUMP.value
    assert "PSC rank 28 -> 10" in brief.allowed_facts
    assert any("social acceleration" in fact.lower() for fact in brief.allowed_facts)
    assert any("fresh bullish" in fact.lower() for fact in brief.allowed_facts)
    assert any("3.33" in str(number) for number in brief.allowed_numbers)
    assert "Revenue grew 32%" not in brief.factuality_constraints


def test_numeric_validation_accepts_allowed_numbers_and_rejects_unsupported_ones() -> None:
    brief = ContentBrief.from_opportunity(make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0))
    valid = validate_content("$MSFT moved from #28 to #10 in PSC.", brief)
    invalid_number = validate_content("$MSFT moved from #28 to #5 in PSC.", brief)
    unsupported_price = validate_content("$MSFT is heading to $700.", brief)

    assert valid.valid is True
    assert invalid_number.valid is False
    assert invalid_number.unsupported_numbers == ["5"]
    assert unsupported_price.valid is False
    assert any("price target" in reason.lower() for reason in unsupported_price.rejection_reasons)


def test_unsupported_claims_are_rejected_when_not_in_brief() -> None:
    brief = ContentBrief.from_opportunity(make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0))

    result = validate_content("$MSFT revenue grew 32% and insiders are loading up.", brief)

    assert result.valid is False
    assert any("revenue" in claim.lower() for claim in result.unsupported_claims)
    assert any("insider" in claim.lower() for claim in result.unsupported_claims)


def test_wrong_ticker_and_malformed_output_are_rejected() -> None:
    brief = ContentBrief.from_opportunity(make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0))

    wrong_symbol = validate_content("$AAPL moved from #28 to #10 in PSC.", brief)
    malformed = validate_content("{not valid json", brief)

    assert wrong_symbol.valid is False
    assert wrong_symbol.symbol_mismatch is True
    assert malformed.valid is False
    assert malformed.formatting_issues


def test_content_length_and_empty_output_are_rejected() -> None:
    brief = ContentBrief.from_opportunity(make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0), maximum_length=40)

    long_result = validate_content("$MSFT moved from #28 to #10 in PSC with more unsupported details.", brief)
    empty_result = validate_content("   ", brief)

    assert long_result.valid is False
    assert long_result.length_violation is True
    assert empty_result.valid is False
    assert empty_result.rejection_reasons


def test_llm_generator_creates_three_distinct_variants() -> None:
    provider = MockLLMProvider()
    generator = LLMContentGenerator(provider=provider, variants_per_opportunity=3, max_repair_attempts=1)
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    candidates = generator.generate_for_opportunity(opportunity)

    assert len(candidates) == 3
    assert {candidate.variant_type for candidate in candidates} == {"PUNCHY", "DATA_DRIVEN", "QUESTION"}
    assert len({candidate.content_hash for candidate in candidates}) == 3
    assert all(candidate.review_status == "PENDING" for candidate in candidates)


def test_llm_generator_ranks_valid_candidates_by_score() -> None:
    generator = LLMContentGenerator(provider=MockLLMProvider())
    opportunities = [
        make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0),
        make_opportunity("NVDA", angle=ContentAngle.MULTI_SIGNAL_CONVERGENCE.value, score=76.0),
        make_opportunity("UBER", angle=ContentAngle.VALUATION_DISLOCATION.value, score=74.0),
    ]

    ranked = generator.rank_candidates(opportunities)

    assert [candidate.symbol for candidate in ranked] == ["MSFT", "NVDA", "UBER"]
    assert all(candidate.validation_result.valid for candidate in ranked)


def test_similarity_detection_rejects_nearly_identical_variants() -> None:
    first = "$MSFT moved from #28 to #10 in PSC. Social attention is accelerating."
    second = "$MSFT moved from #28 to #10 in PSC. Social attention is accelerating!"

    assert normalize_for_similarity(first) == normalize_for_similarity(second)
    assert len({normalize_for_similarity(first), normalize_for_similarity(second)}) == 1


def test_near_duplicate_candidates_are_suppressed_before_ranking() -> None:
    generator = LLMContentGenerator(provider=MockLLMProvider())
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)
    candidates = [
        generator.generate_candidate(opportunity, variant_index=0),
        replace(generator.generate_candidate(opportunity, variant_index=0), full_text="$MSFT moved from #28 to #10 in PSC. Social attention is accelerating!"),
        replace(generator.generate_candidate(opportunity, variant_index=0), full_text="$MSFT moved from #28 to #10 in PSC. Social attention is accelerating?"),
    ]

    ranked = generator._deduplicate_variants(candidates)

    assert len(ranked) == 1
    assert ranked[0].deduplication_status == "KEPT"
    assert ranked[0].validation_result.valid is True


def test_llm_repair_pass_uses_only_allowed_facts_and_removes_unsupported_numbers() -> None:
    provider = MockLLMProvider()
    generator = LLMContentGenerator(provider=provider, max_repair_attempts=1)
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    candidate = generator.generate_candidate(opportunity, invalid_text="$MSFT moved from #28 to #5 in PSC and is heading to $700.")

    assert candidate.original_validation_result.valid is False
    assert candidate.validation_result.valid is True
    assert candidate.repair_attempt_count == 1
    assert candidate.repaired_text
    assert candidate.repaired_validation_result.valid is True
    assert candidate.final_machine_validation is True


def test_failed_repair_is_rejected() -> None:
    provider = MockLLMProvider(fail_repair=True)
    generator = LLMContentGenerator(provider=provider, max_repair_attempts=1)
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    candidate = generator.generate_candidate(opportunity, invalid_text="$MSFT is heading to $700.")

    assert candidate.original_validation_result.valid is False
    assert candidate.validation_result.valid is False
    assert candidate.review_status == "REJECTED_BY_VALIDATOR"
    assert candidate.repair_attempt_count == 1
    assert candidate.repaired_text == ""
    assert candidate.final_machine_validation is False


def test_invalid_repair_after_valid_initial_text_is_rejected() -> None:
    provider = MockLLMProvider(fail_repair=True)
    generator = LLMContentGenerator(provider=provider, max_repair_attempts=1)
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    candidate = generator.generate_candidate(opportunity, invalid_text="$MSFT is heading to $700.")

    assert candidate.original_validation_result.valid is False
    assert candidate.validation_result.valid is False
    assert candidate.review_status == "REJECTED_BY_VALIDATOR"
    assert candidate.repair_attempt_count == 1
    assert candidate.final_machine_validation is False
    assert candidate.repaired_text == ""


def test_repair_succeeds_and_marks_candidate_valid() -> None:
    provider = MockLLMProvider()
    generator = LLMContentGenerator(provider=provider, max_repair_attempts=1)
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    candidate = generator.generate_candidate(opportunity, invalid_text="$MSFT moved from #28 to #5 in PSC.")

    assert candidate.original_validation_result.valid is False
    assert candidate.validation_result.valid is True
    assert candidate.review_status == "PENDING"
    assert candidate.repaired_text
    assert candidate.final_machine_validation is True


def test_question_variant_must_be_a_question_and_not_punchy_duplicate() -> None:
    provider = MockLLMProvider()
    generator = LLMContentGenerator(provider=provider, variants_per_opportunity=3, max_repair_attempts=1)
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    candidates = generator.generate_for_opportunity(opportunity)
    question = next(candidate for candidate in candidates if candidate.variant_type == "QUESTION")

    assert "?" in question.full_text
    assert question.validation_result.valid is True
    assert question.deduplication_status == "KEPT"


def test_llm_provider_failure_does_not_break_other_opportunities() -> None:
    provider = MockLLMProvider(fail_for_symbols={"MSFT"})
    generator = LLMContentGenerator(provider=provider)
    opportunities = [
        make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0),
        make_opportunity("NVDA", angle=ContentAngle.MULTI_SIGNAL_CONVERGENCE.value, score=76.0),
    ]

    results = generator.generate_for_opportunities(opportunities)

    assert results["MSFT"] is None
    assert results["NVDA"] is not None
    assert len(results["NVDA"]) == 3


def test_missing_llm_provider_configuration_is_reported_cleanly() -> None:
    generator = LLMContentGenerator(provider=None)

    candidates = generator.generate_for_opportunity(make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0))

    assert candidates == []


def test_database_persists_llm_candidate_metadata(database: Database) -> None:
    generator = LLMContentGenerator(database=database, provider=MockLLMProvider())
    opportunity = make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0)

    candidates = generator.generate_for_opportunity(opportunity)
    row = database.get_recent_candidate("MSFT")

    assert row is not None
    assert row["generator_type"] == "LLM"
    assert row["provider"] == "mock"
    assert row["prompt_version"] == "EXITVECTOR_CONTENT_PROMPT_V1"
    assert row["review_status"] == "PENDING"
    assert len(candidates) == 3


def test_xyz_is_excluded_from_llm_generation() -> None:
    generator = LLMContentGenerator(provider=MockLLMProvider())

    assert generator.generate_for_opportunity(make_opportunity("XYZ", angle=ContentAngle.SOCIAL_SPIKE.value, score=10.0)) == []


def test_provider_response_malformed_is_rejected() -> None:
    provider = MockLLMProvider(malformed_response=True)
    generator = LLMContentGenerator(provider=provider)

    result = generator.generate_candidate(make_opportunity("MSFT", angle=ContentAngle.PSC_RANK_JUMP.value, score=83.0))

    assert result.validation_result.valid is False
    assert result.review_status == "REJECTED_BY_VALIDATOR"
    assert "malformed" in " ".join(result.validation_result.rejection_reasons).lower()
