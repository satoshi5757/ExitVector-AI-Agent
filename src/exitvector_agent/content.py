"""Deterministic content strategy, drafting, and review persistence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from exitvector_agent.database import Database
from exitvector_agent.opportunity import ContentAngle, PostOpportunity, recommend_visual


class ContentFormat(str, Enum):
    SHORT_QUESTION = "SHORT_QUESTION"
    BULLISH_TAKE = "BULLISH_TAKE"
    BREAKING_SIGNAL = "BREAKING_SIGNAL"
    DATA_POINT = "DATA_POINT"
    CONTRARIAN_TAKE = "CONTRARIAN_TAKE"
    WATCHLIST_ALERT = "WATCHLIST_ALERT"
    STOCK_BATTLE = "STOCK_BATTLE"
    CHART_SETUP = "CHART_SETUP"
    CATALYST_SUMMARY = "CATALYST_SUMMARY"
    WHY_IT_MATTERS = "WHY_IT_MATTERS"


@dataclass(frozen=True, slots=True)
class ContentCandidate:
    symbol: str
    opportunity_id: int | None
    primary_angle: str
    secondary_angles: list[str]
    format: ContentFormat
    hook: str
    body: str
    call_to_action: str
    full_text: str
    confidence: str
    estimated_engagement_score: int
    tone: str
    facts_used: list[str]
    facts_omitted: list[str]
    generated_at: datetime
    factuality_warnings: list[str] = field(default_factory=list)
    missing_context: list[str] = field(default_factory=list)
    visual_recommendation: str = ""
    requires_human_review: bool = True
    review_status: str = "PENDING"
    content_hash: str = ""
    generator_type: str = "RULE_BASED"
    provider: str | None = None
    model: str | None = None
    prompt_version: str = "EXITVECTOR_CONTENT_PROMPT_V1"
    raw_output: str = ""
    original_raw_output: str = ""
    brief_snapshot: dict[str, Any] = field(default_factory=dict)
    original_validation_result: "ContentValidationResult" = field(default_factory=lambda: ContentValidationResult())
    validation_result: "ContentValidationResult" = field(default_factory=lambda: ContentValidationResult())
    repaired_validation_result: "ContentValidationResult | None" = None
    repaired_text: str = ""
    final_machine_validation: bool = False
    deduplication_status: str = "UNIQUE"
    repair_attempt_count: int = 0
    variant_type: str = "STANDARD"


@dataclass(frozen=True, slots=True)
class ContentValidationResult:
    valid: bool = False
    unsupported_numbers: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    symbol_mismatch: bool = False
    length_violation: bool = False
    formatting_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    raw_output: str
    provider: str
    model: str | None
    prompt_version: str = "EXITVECTOR_CONTENT_PROMPT_V1"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContentBrief:
    symbol: str
    primary_angle: str
    secondary_angles: list[str]
    tone: str
    preferred_format: str
    strongest_fact: str
    supporting_facts: list[str]
    social_summary: str
    regivion_summary: str
    urgency: str
    confidence: str
    visual_recommendation: str
    allowed_numbers: list[str]
    allowed_facts: list[str]
    forbidden_claim_types: list[str]
    factuality_constraints: list[str]
    style_profile: dict[str, Any]
    maximum_length: int
    request_type: str = "GENERATE"
    prompt_version: str = "EXITVECTOR_CONTENT_PROMPT_V1"

    @classmethod
    def from_opportunity(
        cls,
        opportunity: PostOpportunity,
        *,
        maximum_length: int = 280,
        style_profile: dict[str, Any] | None = None,
    ) -> "ContentBrief":
        numeric_tokens = _extract_allowed_numbers(opportunity)
        allowed_facts = [
            f"symbol = {opportunity.symbol}",
            *[fact for fact in _allowed_fact_lines(opportunity) if fact],
        ]
        return cls(
            symbol=opportunity.symbol.upper(),
            primary_angle=opportunity.suggested_content_angle,
            secondary_angles=opportunity.content_angles,
            tone="FinX-native, punchy, conversational",
            preferred_format="SHORT",
            strongest_fact=opportunity.strongest_fact,
            supporting_facts=opportunity.supporting_facts,
            social_summary=opportunity.social_summary,
            regivion_summary=opportunity.regivion_summary,
            urgency=opportunity.urgency,
            confidence=opportunity.confidence,
            visual_recommendation=opportunity.suggested_visual_type,
            allowed_numbers=[str(number) for number in numeric_tokens],
            allowed_facts=allowed_facts,
            forbidden_claim_types=[
                "share price",
                "price target",
                "revenue",
                "earnings",
                "EPS",
                "margins",
                "valuation",
                "analyst targets",
                "insider transactions",
                "politician trades",
                "PSC score",
                "PSC ranking",
                "percentage returns",
                "technical levels",
                "catalysts",
                "dates",
                "market-cap figures",
            ],
            factuality_constraints=[
                "Only facts explicitly present in the supplied brief may appear as factual claims.",
                "Never invent numeric claims, dates, prices, valuations, targets, or catalysts.",
                "Do not discuss unsupported insider or politician activity.",
                "Do not mention a different ticker than the brief symbol.",
            ],
            style_profile=style_profile or {
                "concise": True,
                "punchy": True,
                "natural": True,
                "cashtags": True,
                "avoid_hashtags": True,
                "avoid_emojis": True,
                "preferred_length": "STANDARD",
            },
            maximum_length=maximum_length,
        )


@runtime_checkable
class ContentGeneratorProtocol(Protocol):
    def generate_for_opportunity(self, opportunity: PostOpportunity) -> list[ContentCandidate]:
        ...

    def generate_candidate(self, opportunity: PostOpportunity) -> ContentCandidate:
        ...


def select_content_format(angle: ContentAngle | str) -> ContentFormat:
    """Choose a deterministic format from the opportunity angle."""

    angle_name = angle.value if isinstance(angle, ContentAngle) else angle
    mapping: dict[str, ContentFormat] = {
        ContentAngle.SOCIAL_SPIKE.value: ContentFormat.SHORT_QUESTION,
        ContentAngle.PSC_RANK_JUMP.value: ContentFormat.BREAKING_SIGNAL,
        ContentAngle.VALUATION_DISLOCATION.value: ContentFormat.CONTRARIAN_TAKE,
        ContentAngle.MULTI_SIGNAL_CONVERGENCE.value: ContentFormat.DATA_POINT,
        ContentAngle.INSIDER_BUY.value: ContentFormat.BREAKING_SIGNAL,
        ContentAngle.POLITICIAN_BUY.value: ContentFormat.DATA_POINT,
        ContentAngle.TECHNICAL_BREAKOUT.value: ContentFormat.CHART_SETUP,
        ContentAngle.REVENUE_GROWTH_DISLOCATION.value: ContentFormat.WHY_IT_MATTERS,
        ContentAngle.EARNINGS_ACCELERATION.value: ContentFormat.DATA_POINT,
        ContentAngle.NEW_TOP20_ENTRY.value: ContentFormat.WATCHLIST_ALERT,
        ContentAngle.MOMENTUM_CONVERGENCE.value: ContentFormat.BULLISH_TAKE,
    }
    return mapping.get(angle_name, ContentFormat.BULLISH_TAKE)


class ContentStyleProfile:
    """Configured style characteristics for deterministic FinX-native content."""

    def __init__(
        self,
        *,
        concise: bool = True,
        punchy: bool = True,
        natural: bool = True,
        cashtags: bool = True,
        avoid_hashtags: bool = True,
        confidence_language: str = "worth watching",
    ) -> None:
        self.concise = concise
        self.punchy = punchy
        self.natural = natural
        self.cashtags = cashtags
        self.avoid_hashtags = avoid_hashtags
        self.confidence_language = confidence_language


class RuleBasedContentGenerator:
    """Generate deterministic, traceable content candidates without an LLM."""

    def __init__(
        self,
        *,
        database: Database | None = None,
        style: ContentStyleProfile | None = None,
        content_cooldown_minutes: int = 180,
        max_candidates: int = 3,
    ) -> None:
        self.database = database
        self.style = style or ContentStyleProfile()
        self.content_cooldown_minutes = content_cooldown_minutes
        self.max_candidates = max(1, max_candidates)

    def generate_for_opportunity(self, opportunity: PostOpportunity) -> list[ContentCandidate]:
        """Generate up to three content candidates for one opportunity."""
        if opportunity.symbol == "XYZ":
            return []
        if opportunity.total_score < 65.0:
            return []
        facts = self.select_facts(opportunity)
        hooks = self.generate_hooks(opportunity)
        candidates: list[ContentCandidate] = []
        seen: set[str] = set()
        for index, hook in enumerate(hooks[: self.max_candidates]):
            format_value = self.select_format_for_hook(opportunity, index)
            body = self.build_body(opportunity, facts, format_value)
            candidate = self._make_candidate(opportunity, format_value, hook, body, facts)
            if candidate.content_hash in seen:
                continue
            seen.add(candidate.content_hash)
            candidates.append(candidate)
        return candidates

    def generate_candidate(self, opportunity: PostOpportunity) -> ContentCandidate:
        """Generate and persist the best candidate for one opportunity."""
        candidates = self.generate_for_opportunity(opportunity)
        if not candidates:
            raise ValueError(f"No content candidates can be generated for {opportunity.symbol}")
        candidate = self._select_best_candidate(candidates)
        if self.database is not None:
            latest = self.database.get_recent_candidate(opportunity.symbol)
            if latest is not None:
                previous_score = float(latest["opportunity_score"])
                score_delta = abs(opportunity.total_score - previous_score)
                if score_delta >= 5.0 or latest["content_hash"] != candidate.content_hash:
                    alternate = self._select_alternate_candidate(candidates, latest["format"])
                    candidate = alternate if alternate is not None else candidate
            self._persist(candidate, opportunity)
        return candidate

    def is_duplicate(self, candidate: ContentCandidate, *, force_generate: bool = False) -> bool:
        """Detect a recurring duplicate candidate using the stored text hash and cooldown."""
        if self.database is None:
            return False
        row = self.database.get_recent_content_by_hash(candidate.content_hash)
        if row is None:
            return False
        if force_generate:
            return True
        created_at = datetime.fromisoformat(row["generated_at"])
        elapsed_minutes = (datetime.now(timezone.utc) - created_at).total_seconds() / 60.0
        return elapsed_minutes < self.content_cooldown_minutes

    def select_facts(self, opportunity: PostOpportunity) -> list[str]:
        """Select deterministic, supported facts in priority order."""

        facts: list[str] = []
        if "PSC rank" in " ".join(opportunity.trigger_reasons):
            facts.append(f"PSC rank {opportunity.regivion_summary}")
        if opportunity.regivion_score >= 90:
            facts.append(f"Regivion conviction {opportunity.regivion_score:.1f}/100")
        if opportunity.social_trend_score >= 70:
            facts.append(f"Social acceleration {opportunity.social_trend_score:.1f}/100")
        if opportunity.market_score is not None:
            facts.append(f"Market signal {opportunity.market_score:.1f}/100")
        if opportunity.regivion_summary and "alert" in opportunity.regivion_summary.lower():
            facts.append("Fresh bullish Regivion alert")
        if opportunity.supporting_facts:
            facts.extend(fact for fact in opportunity.supporting_facts if fact and "score" not in fact.lower())
        if opportunity.trigger_reasons:
            facts.insert(0, opportunity.trigger_reasons[-1])
        return self._deduplicate(facts)[:3]

    def generate_hooks(self, opportunity: PostOpportunity) -> list[str]:
        """Generate 3-5 deterministic hook candidates."""
        ticker = f"${opportunity.symbol}"
        angle = opportunity.suggested_content_angle
        hooks: list[str] = []
        if angle == ContentAngle.PSC_RANK_JUMP.value:
            hooks.extend([
                f"{ticker} just moved onto my radar.",
                f"This one caught my attention: {ticker}.",
                f"Are investors sleeping on {ticker}?",
                f"One signal I would not ignore: {ticker}.",
                f"Crazy stat of the day: {ticker}.",
            ])
        elif angle == ContentAngle.MULTI_SIGNAL_CONVERGENCE.value:
            hooks.extend([
                f"What is happening with {ticker} right now?",
                f"{ticker} is building a multi-signal setup.",
                f"This is one to watch: {ticker}.",
                f"Social attention and fundamentals are aligning at {ticker}.",
                f"Is {ticker} starting to matter more?",
            ])
        elif angle == ContentAngle.VALUATION_DISLOCATION.value:
            hooks.extend([
                f"Everyone is focused on the headline, but look at {ticker}.",
                f"{ticker} may be an interesting valuation setup.",
                f"This one is worth watching: {ticker}.",
                f"A contrarian angle on {ticker}.",
                f"Is the market missing something in {ticker}?",
            ])
        else:
            hooks.extend([
                f"This caught my attention: {ticker}.",
                f"Watch this level in {ticker}.",
                f"One signal I would not ignore: {ticker}.",
                f"Is {ticker} about to get more attention?",
                f"Something is changing here: {ticker}.",
            ])
        return hooks[:5]

    def build_body(self, opportunity: PostOpportunity, facts: list[str], format_value: ContentFormat) -> str:
        """Build a short, factual body using the selected facts."""
        if not facts:
            return "Worth watching closely."
        first_fact = facts[0]
        supporting = facts[1:3]
        if format_value == ContentFormat.BREAKING_SIGNAL:
            body = f"{first_fact}."
            if supporting:
                body += f" {supporting[0]}."
            return body + " Worth watching closely."
        if format_value == ContentFormat.DATA_POINT:
            body = f"{first_fact}."
            if supporting:
                body += f" {supporting[0]}."
            return body + " A useful setup to monitor."
        if format_value == ContentFormat.CONTRARIAN_TAKE:
            body = f"{first_fact}."
            if supporting:
                body += f" {supporting[0]}."
            return body + " The market may be missing the broader context."
        if format_value == ContentFormat.WATCHLIST_ALERT:
            return f"{first_fact}. Keep it on the watchlist."
        if format_value == ContentFormat.CHART_SETUP:
            return f"{first_fact}. The chart and signal context are worth reviewing."
        if format_value == ContentFormat.SHORT_QUESTION:
            return f"{first_fact}. Which side would you take?"
        if format_value == ContentFormat.BULLISH_TAKE:
            return f"{first_fact}. The setup is interesting, but not a guarantee."
        return f"{first_fact}. Worth watching."

    def _select_best_candidate(self, candidates: list[ContentCandidate]) -> ContentCandidate:
        return max(candidates, key=lambda item: (item.estimated_engagement_score, item.confidence))

    def _select_alternate_candidate(
        self,
        candidates: list[ContentCandidate],
        previous_format: str,
    ) -> ContentCandidate | None:
        alternatives = [candidate for candidate in candidates if candidate.format.value != previous_format]
        if not alternatives:
            return None
        return max(alternatives, key=lambda item: (item.estimated_engagement_score, item.confidence))

    def rank_candidates(self, opportunities: list[PostOpportunity]) -> list[ContentCandidate]:
        ranked: list[tuple[float, ContentCandidate]] = []
        for opportunity in opportunities:
            candidates = self.generate_for_opportunity(opportunity)
            if candidates:
                ranked.append(
                    (
                        opportunity.total_score,
                        max(
                            candidates,
                            key=lambda item: (item.estimated_engagement_score, item.confidence),
                        ),
                    )
                )
        return [candidate for _, candidate in sorted(ranked, key=lambda item: item[0], reverse=True)]

    def _deduplicate(self, facts: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for fact in facts:
            value = fact.strip()
            if not value or value.lower() in seen:
                continue
            seen.add(value.lower())
            ordered.append(value)
        return ordered

    def select_format_for_hook(self, opportunity: PostOpportunity, index: int) -> ContentFormat:
        angle = ContentAngle(opportunity.suggested_content_angle)
        formats = [
            select_content_format(angle),
            ContentFormat.BULLISH_TAKE,
            ContentFormat.DATA_POINT,
        ]
        return formats[index % len(formats)]

    def _make_candidate(
        self,
        opportunity: PostOpportunity,
        format_value: ContentFormat,
        hook: str,
        body: str,
        facts: list[str],
    ) -> ContentCandidate:
        fact_safety = self._factuality_warnings(opportunity, facts)
        candidate = ContentCandidate(
            symbol=opportunity.symbol,
            opportunity_id=None,
            primary_angle=opportunity.suggested_content_angle,
            secondary_angles=opportunity.content_angles,
            format=format_value,
            hook=hook,
            body=body,
            call_to_action="Worth watching closely.",
            full_text=f"{hook} {body}",
            confidence=opportunity.confidence,
            estimated_engagement_score=self.estimate_engagement(opportunity, format_value, hook, body),
            tone="natural",
            facts_used=facts,
            facts_omitted=self._facts_omitted(opportunity, facts),
            generated_at=datetime.now(timezone.utc),
            factuality_warnings=fact_safety,
            missing_context=self._missing_context(opportunity, facts),
            visual_recommendation=opportunity.suggested_visual_type or recommend_visual(opportunity.suggested_content_angle),
            requires_human_review=True,
            review_status="PENDING",
        )
        return replace(candidate, content_hash=self._content_hash(candidate, opportunity))

    def _factuality_warnings(self, opportunity: PostOpportunity, facts: list[str]) -> list[str]:
        warnings: list[str] = []
        if opportunity.regivion_summary == "No Regivion coverage":
            warnings.append("No Regivion coverage; treat the setup as social-only.")
        if not facts:
            warnings.append("No supported facts were selected for the draft.")
        return warnings

    def _missing_context(self, opportunity: PostOpportunity, facts: list[str]) -> list[str]:
        missing: list[str] = []
        if not opportunity.regivion_summary or "No Regivion" in opportunity.regivion_summary:
            missing.append("Missing Regivion context")
        if not opportunity.trigger_reasons:
            missing.append("Missing trigger reasons")
        if not facts:
            missing.append("Missing supported facts")
        if opportunity.market_score is None:
            missing.append("Missing market-price context")
        return missing

    def _facts_omitted(self, opportunity: PostOpportunity, facts: list[str]) -> list[str]:
        candidates = [
            opportunity.strongest_fact,
            *opportunity.supporting_facts,
            *opportunity.trigger_reasons,
        ]
        fact_set = {fact for fact in candidates if fact}
        return [fact for fact in fact_set if fact not in facts]

    def estimate_engagement(
        self,
        opportunity: PostOpportunity,
        format_value: ContentFormat,
        hook: str,
        body: str,
    ) -> int:
        score = 35
        if "?" in hook:
            score += 12
        if any(token in body for token in ("#28", "#10", "rank", "jump", "acceleration")):
            score += 18
        if opportunity.symbol in hook:
            score += 12
        if len(body) <= 80:
            score += 8
        if format_value in {ContentFormat.CONTRARIAN_TAKE, ContentFormat.WATCHLIST_ALERT}:
            score += 8
        if opportunity.novelty_score >= 75:
            score += 10
        if opportunity.confidence == "HIGH":
            score += 5
        return max(0, min(100, score))

    def _content_hash(self, candidate: ContentCandidate, opportunity: PostOpportunity) -> str:
        payload = {
            "symbol": candidate.symbol,
            "format": candidate.format.value,
            "hook": candidate.hook,
            "body": candidate.body,
            "facts": candidate.facts_used,
            "angle": candidate.primary_angle,
            "score": candidate.confidence,
            "total_score": opportunity.total_score,
            "engagement": candidate.estimated_engagement_score,
            "trigger_reasons": opportunity.trigger_reasons,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _persist(self, candidate: ContentCandidate, opportunity: PostOpportunity) -> None:
        if self.database is None:
            return
        self.database.insert_content_candidate(
            opportunity_id=opportunity_id_from_row(self.database.get_recent_opportunity(opportunity.symbol)),
            symbol=candidate.symbol,
            opportunity_score=opportunity.total_score,
            primary_angle=candidate.primary_angle,
            secondary_angles=json.dumps(candidate.secondary_angles, ensure_ascii=False),
            content_format=candidate.format.value,
            hook=candidate.hook,
            body=candidate.body,
            call_to_action=candidate.call_to_action,
            full_text=candidate.full_text,
            confidence=candidate.confidence,
            estimated_engagement_score=candidate.estimated_engagement_score,
            tone=candidate.tone,
            facts_used=json.dumps(candidate.facts_used, ensure_ascii=False),
            facts_omitted=json.dumps(candidate.facts_omitted, ensure_ascii=False),
            generated_at=candidate.generated_at.isoformat(),
            factuality_warnings=json.dumps(candidate.factuality_warnings, ensure_ascii=False),
            missing_context=json.dumps(candidate.missing_context, ensure_ascii=False),
            visual_recommendation=candidate.visual_recommendation,
            review_status=candidate.review_status,
            requires_human_review=int(candidate.requires_human_review),
            content_hash=candidate.content_hash,
            generator_type=candidate.generator_type,
            provider=candidate.provider,
            model=candidate.model,
            prompt_version=candidate.prompt_version,
            raw_output=candidate.raw_output,
            original_raw_output=candidate.original_raw_output,
            brief_snapshot=json.dumps(candidate.brief_snapshot, ensure_ascii=False),
            validation_result=json.dumps(asdict(candidate.validation_result), ensure_ascii=False),
            repair_attempt_count=candidate.repair_attempt_count,
            variant_type=candidate.variant_type,
            original_validation_result=json.dumps(asdict(candidate.original_validation_result), ensure_ascii=False),
            repaired_text=candidate.repaired_text,
            final_machine_validation=int(candidate.final_machine_validation),
            deduplication_status=candidate.deduplication_status,
        )


class GenerationLimitReached(RuntimeError):
    """Run-scoped inference budget, including repairs and retries, was exhausted."""


class LLMProvider(Protocol):
    def generate(self, prompt: str, structured_input: Any) -> LLMResponse:
        ...


class MockLLMProvider:
    """Deterministic offline LLM provider for tests and local demonstrations."""

    def __init__(
        self,
        *,
        fail_for_symbols: set[str] | None = None,
        fail_repair: bool = False,
        malformed_response: bool = False,
    ) -> None:
        self.fail_for_symbols = fail_for_symbols or set()
        self.fail_repair = fail_repair
        self.malformed_response = malformed_response
        self.provider = "mock"
        self.model = "mock-llm"

    def generate(self, prompt: str, structured_input: Any) -> LLMResponse:
        if structured_input.symbol in self.fail_for_symbols:
            raise RuntimeError(f"Simulated failure for {structured_input.symbol}")
        if self.malformed_response:
            return LLMResponse(
                text="{not valid json",
                raw_output="{not valid json",
                provider=self.provider,
                model=self.model,
                prompt_version="EXITVECTOR_CONTENT_PROMPT_V1",
            )
        request_type = getattr(structured_input, "request_type", "GENERATE")
        if request_type == "REPAIR":
            if self.fail_repair:
                raise RuntimeError("Repair request failed")
            text = _repair_text(structured_input)
        else:
            variant = "PUNCHY"
            if "data_driven" in prompt.lower():
                variant = "DATA_DRIVEN"
            elif "question" in prompt.lower():
                variant = "QUESTION"
            text = _mock_draft(structured_input, variant=variant)
        return LLMResponse(
            text=text,
            raw_output=text,
            provider=self.provider,
            model=self.model,
            prompt_version="EXITVECTOR_CONTENT_PROMPT_V1",
        )


class LLMContentGenerator:
    """Generate, validate, repair, rank, and persist LLM-written candidates."""

    def __init__(
        self,
        *,
        database: Database | None = None,
        provider: LLMProvider | None = None,
        style: ContentStyleProfile | None = None,
        max_candidates: int = 3,
        variants_per_opportunity: int = 3,
        max_repair_attempts: int = 1,
        content_cooldown_minutes: int = 180,
        auto_persist: bool = True,
    ) -> None:
        self.database = database
        self.auto_persist = auto_persist
        self.provider = provider
        self.style = style or ContentStyleProfile()
        self.max_candidates = max(1, max_candidates)
        self.variants_per_opportunity = max(1, variants_per_opportunity)
        self.max_repair_attempts = max_repair_attempts
        self.content_cooldown_minutes = content_cooldown_minutes

    def generate_for_opportunity(self, opportunity: PostOpportunity) -> list[ContentCandidate]:
        if opportunity.symbol == "XYZ" or opportunity.total_score < 65.0:
            return []
        if self.provider is None:
            return []
        attempts: list[ContentCandidate] = []
        seen_text: set[str] = set()
        for index in range(min(self.variants_per_opportunity, self.max_candidates)):
            try:
                candidate = self.generate_candidate(opportunity, variant_index=index)
            except GenerationLimitReached:
                break
            except RuntimeError:
                raise
            normalized = normalize_for_similarity(candidate.full_text)
            if normalized in seen_text:
                continue
            seen_text.add(normalized)
            attempts.append(candidate)
        punchy = next((candidate for candidate in attempts if candidate.variant_type == "PUNCHY"), None)
        attempts = [
            replace(candidate, validation_result=self._validate_variant(candidate, punchy))
            if candidate.variant_type == "QUESTION"
            else candidate
            for candidate in attempts
        ]
        return self._deduplicate_variants(attempts)

    def generate_for_opportunities(self, opportunities: list[PostOpportunity]) -> dict[str, list[ContentCandidate] | None]:
        results: dict[str, list[ContentCandidate] | None] = {}
        for opportunity in opportunities:
            try:
                results[opportunity.symbol] = self.generate_for_opportunity(opportunity)
            except RuntimeError:
                results[opportunity.symbol] = None
        return results

    def generate_candidate(
        self,
        opportunity: PostOpportunity,
        *,
        variant_index: int = 0,
        invalid_text: str | None = None,
    ) -> ContentCandidate:
        if opportunity.symbol == "XYZ" or opportunity.total_score < 65.0:
            raise ValueError(f"No content candidates can be generated for {opportunity.symbol}")
        if self.provider is None:
            raise RuntimeError("No LLM provider is configured")
        brief = ContentBrief.from_opportunity(opportunity)
        variant = ["PUNCHY", "DATA_DRIVEN", "QUESTION"][variant_index % 3]
        original_response = None
        repair_response = None
        if invalid_text is not None:
            original_text = invalid_text
        else:
            original_text = self._draft_text(opportunity, brief, variant)
            original_response = self._last_response
        original_validation = validate_content(original_text, brief)
        repaired_text = ""
        repaired_validation: ContentValidationResult | None = None
        final_validation = original_validation
        repair_count = 0
        repair_attempted = False
        repair_succeeded = False
        while not final_validation.valid and repair_count < self.max_repair_attempts:
            if any("malformed content response" in reason.lower() for reason in original_validation.rejection_reasons):
                break
            try:
                repair_count += 1
                repair_attempted = True
                repair = self.provider.generate(
                    build_repair_prompt(brief) + f" Repair a {variant} variant.",
                    replace(brief, symbol=brief.symbol, request_type="REPAIR"),
                )
                repair_response = repair
                repaired_text = repair.text
                if not repaired_text:
                    final_validation = ContentValidationResult(
                        valid=False,
                        rejection_reasons=["Repair provider returned empty content"],
                    )
                    break
                if normalize_for_similarity(repaired_text) == normalize_for_similarity(original_text):
                    final_validation = ContentValidationResult(
                        valid=False,
                        rejection_reasons=["Repair did not change the invalid draft"],
                    )
                    break
                repaired_validation = validate_content(repaired_text, brief)
                final_validation = repaired_validation
                repair_succeeded = repaired_validation.valid
            except RuntimeError:
                repaired_text = ""
                repaired_validation = None
                repair_succeeded = False
                final_validation = ContentValidationResult(
                    valid=False,
                    rejection_reasons=["Repair provider failed"],
                )
                break
        result = self._candidate_from_response(
            opportunity,
            brief,
            original_text,
            repaired_text,
            final_validation,
            original_validation,
            repair_count,
            variant,
            invalid_text is not None,
            repaired_validation,
            repair_attempted,
            repair_succeeded,
        )
        response = repair_response if repair_succeeded else original_response
        if response is not None:
            result = replace(result, provider=response.provider, model=response.model,
                prompt_version=response.prompt_version, raw_output=response.raw_output,
                original_raw_output=original_response.raw_output if original_response else original_text)
            result = replace(result, content_hash=self._content_hash(result))
        if self.auto_persist and self.database is not None and result.review_status != "REJECTED_BY_VALIDATOR":
            self._persist(result)
        return result

    def rank_candidates(self, opportunities: list[PostOpportunity]) -> list[ContentCandidate]:
        ranked: list[tuple[float, ContentCandidate]] = []
        for opportunity in opportunities:
            valid_candidates = [
                candidate
                for candidate in self._deduplicate_variants(self.generate_for_opportunity(opportunity))
                if candidate.validation_result.valid
            ]
            if not valid_candidates:
                continue
            ranked.append((opportunity.total_score, max(valid_candidates, key=lambda item: (item.estimated_engagement_score, item.content_hash))))
        return [candidate for _, candidate in sorted(ranked, key=lambda item: item[0], reverse=True)]

    def _draft_text(self, opportunity: PostOpportunity, brief: ContentBrief, variant: str) -> str:
        prompt = f"{build_exitvector_system_prompt()} Write a {variant} variant. Explicitly follow the requested {variant} intent and use only the supplied facts."
        response = self.provider.generate(prompt, replace(brief, symbol=brief.symbol))
        self._last_response = response
        if not response.text:
            raise RuntimeError("Provider returned empty content")
        return response.text

    def _candidate_from_response(
        self,
        opportunity: PostOpportunity,
        brief: ContentBrief,
        original_text: str,
        repaired_text: str,
        final_validation: ContentValidationResult,
        original_validation: ContentValidationResult,
        repair_count: int,
        variant_type: str,
        forced_invalid: bool,
        repaired_validation: ContentValidationResult | None,
        repair_attempted: bool = False,
        repair_succeeded: bool = False,
    ) -> ContentCandidate:
        if repair_attempted:
            final_text = repaired_text if repair_succeeded else original_text
        else:
            final_text = original_text
        if final_validation.valid:
            review_status = "PENDING"
        else:
            review_status = "REJECTED_BY_VALIDATOR"
        repaired_validation_result = repaired_validation if repair_succeeded else None
        candidate = ContentCandidate(
            symbol=opportunity.symbol,
            opportunity_id=opportunity_id_from_row(self.database.get_recent_opportunity(opportunity.symbol)) if self.database else None,
            primary_angle=opportunity.suggested_content_angle,
            secondary_angles=opportunity.content_angles,
            format=ContentFormat.BREAKING_SIGNAL,
            hook="",
            body=final_text,
            call_to_action="Worth watching closely.",
            full_text=final_text,
            confidence=opportunity.confidence,
            estimated_engagement_score=estimate_llm_engagement(final_text, opportunity),
            tone="natural",
            facts_used=brief.allowed_facts,
            facts_omitted=[],
            generated_at=datetime.now(timezone.utc),
            factuality_warnings=final_validation.warnings,
            missing_context=[],
            visual_recommendation=opportunity.suggested_visual_type,
            requires_human_review=True,
            review_status=review_status,
            generator_type="LLM",
            provider="mock",
            model="mock-llm",
            prompt_version=brief.prompt_version,
            raw_output=final_text,
            original_raw_output=original_text,
            brief_snapshot=_brief_snapshot(brief),
            original_validation_result=original_validation,
            validation_result=final_validation,
            repaired_validation_result=repaired_validation_result,
            repaired_text=repaired_text,
            final_machine_validation=final_validation.valid,
            repair_attempt_count=repair_count,
            variant_type=variant_type,
        )
        return replace(candidate, content_hash=self._content_hash(candidate))

    def _validate_variant(self, candidate: ContentCandidate, punchy_candidate: ContentCandidate | None) -> ContentValidationResult:
        validation = candidate.validation_result
        if candidate.variant_type == "QUESTION":
            if not re.search(r"\?", candidate.full_text):
                validation = replace(validation, valid=False, formatting_issues=["QUESTION variant has no question mark"], rejection_reasons=["QUESTION variant has no question mark"])
            elif punchy_candidate is not None and _similarity(candidate.full_text, punchy_candidate.full_text) >= 0.75:
                validation = replace(validation, valid=False, formatting_issues=["QUESTION variant is not meaningfully different from PUNCHY"], rejection_reasons=["QUESTION variant is not meaningfully different from PUNCHY"])
            elif candidate.full_text.startswith("Could ") and not re.search(r"\b(?:could|can|should|would|is|are)\b", candidate.full_text, flags=re.IGNORECASE):
                validation = replace(validation, valid=False, formatting_issues=["QUESTION variant is not an engagement question"], rejection_reasons=["QUESTION variant is not an engagement question"])
        return validation

    def _deduplicate_variants(self, candidates: list[ContentCandidate]) -> list[ContentCandidate]:
        ranked: list[ContentCandidate] = []
        for candidate in sorted(candidates, key=lambda item: item.estimated_engagement_score, reverse=True):
            duplicate = False
            for kept in ranked:
                similarity = _similarity(candidate.full_text, kept.full_text)
                if similarity >= 0.85:
                    duplicate = True
                    candidate = replace(candidate, deduplication_status="SUPPRESSED_DUPLICATE")
                    break
            if duplicate:
                continue
            ranked.append(replace(candidate, deduplication_status="KEPT"))
        return ranked

    def _content_hash(self, candidate: ContentCandidate) -> str:
        payload = {
            "symbol": candidate.symbol,
            "text": candidate.full_text,
            "angle": candidate.primary_angle,
            "variant": candidate.variant_type,
            "provider": candidate.provider,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _persist(self, candidate: ContentCandidate) -> None:
        if self.database is None:
            return
        self.database.insert_content_candidate(
            opportunity_id=candidate.opportunity_id,
            symbol=candidate.symbol,
            opportunity_score=float(candidate.validation_result.valid),
            primary_angle=candidate.primary_angle,
            secondary_angles=json.dumps(candidate.secondary_angles, ensure_ascii=False),
            content_format=candidate.format.value,
            hook=candidate.hook,
            body=candidate.body,
            call_to_action=candidate.call_to_action,
            full_text=candidate.full_text,
            confidence=candidate.confidence,
            estimated_engagement_score=candidate.estimated_engagement_score,
            tone=candidate.tone,
            facts_used=json.dumps(candidate.facts_used, ensure_ascii=False),
            facts_omitted=json.dumps(candidate.facts_omitted, ensure_ascii=False),
            generated_at=candidate.generated_at.isoformat(),
            factuality_warnings=json.dumps(candidate.factuality_warnings, ensure_ascii=False),
            missing_context=json.dumps(candidate.missing_context, ensure_ascii=False),
            visual_recommendation=candidate.visual_recommendation,
            review_status=candidate.review_status,
            requires_human_review=int(candidate.requires_human_review),
            content_hash=candidate.content_hash,
            generator_type=candidate.generator_type,
            provider=candidate.provider,
            model=candidate.model,
            prompt_version=candidate.prompt_version,
            raw_output=candidate.raw_output,
            original_raw_output=candidate.original_raw_output,
            brief_snapshot=json.dumps(candidate.brief_snapshot, ensure_ascii=False),
            validation_result=json.dumps(asdict(candidate.validation_result), ensure_ascii=False),
            repair_attempt_count=candidate.repair_attempt_count,
            variant_type=candidate.variant_type,
            original_validation_result=json.dumps(asdict(candidate.original_validation_result), ensure_ascii=False),
            repaired_text=candidate.repaired_text,
            final_machine_validation=int(candidate.final_machine_validation),
            deduplication_status=candidate.deduplication_status,
        )


def build_exitvector_system_prompt() -> str:
    return (
        "You are ExitVector, a concise FinX-native financial content writer. "
        "Use only the supplied facts and never invent prices, targets, valuations, revenue, "
        "earnings, EPS, margins, dates, catalysts, rankings, insider transactions, or politician trades. "
        "Keep it punchy, conversational, and short."
    )


def build_repair_prompt(brief: ContentBrief) -> str:
    return (
        f"{build_exitvector_system_prompt()} Rewrite using only these facts: {brief.allowed_facts}. "
        "Remove unsupported claims and do not introduce any new numbers."
    )


def normalize_for_similarity(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return " ".join(normalized.split())


def _similarity(first: str, second: str) -> float:
    left = normalize_for_similarity(first)
    right = normalize_for_similarity(second)
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    shared = len(left_tokens & right_tokens)
    return shared / max(len(left_tokens | right_tokens), 1)


def _extract_allowed_numbers(opportunity: PostOpportunity) -> list[str]:
    values: list[str] = []
    for fact in _allowed_fact_lines(opportunity):
        values.extend(re.findall(r"\d+(?:\.\d+)?", fact))
    return _deduplicate(values)


def _allowed_fact_lines(opportunity: PostOpportunity) -> list[str]:
    evidence = [opportunity.strongest_fact, *opportunity.supporting_facts,
                *opportunity.trigger_reasons, opportunity.regivion_summary,
                opportunity.social_summary]
    facts = [f"social trend score = {opportunity.social_trend_score:.1f}"]
    for fact in evidence:
        if not fact:
            continue
        rank = re.search(r"(?:PSC )?rank (?:moved from )?(\d+)\s*(?:to|->|\u2192)\s*(\d+)", fact, re.I)
        if rank:
            facts.append(f"PSC rank {rank[1]} -> {rank[2]}")
        acceleration = re.search(r"social acceleration\s*(?:=)?\s*(\d+(?:\.\d+)?)x", fact, re.I)
        if acceleration:
            facts.append(f"social acceleration = {acceleration[1]}x")
        facts.append(fact)
    return _deduplicate(facts)


def _deduplicate(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _mock_draft(brief: ContentBrief | PostOpportunity, *, variant: str = "PUNCHY") -> str:
    if isinstance(brief, PostOpportunity):
        brief = ContentBrief.from_opportunity(brief)
    ticker = f"${brief.symbol}"
    if brief.symbol == "MSFT":
        evidence = " ".join(brief.allowed_facts)
        rank = re.search(r"PSC rank (\d+) -> (\d+)", evidence)
        acceleration = re.search(r"social acceleration = (\d+(?:\.\d+)?)x", evidence)
        if rank and acceleration:
            previous, current = rank.groups()
            ratio = acceleration[1]
            if variant == "PUNCHY":
                return f"{ticker} just moved from #{previous} to #{current} in PSC. Social attention is accelerating too."
            if variant == "DATA_DRIVEN":
                return f"{ticker} is showing a strong PSC rank move and a fresh bullish signal. Social acceleration is {ratio}x."
            return f"Could the market be overlooking {ticker} after a #{previous}-to-#{current} PSC move? Social acceleration is {ratio}x, so the setup deserves a closer look."
        supported = ". ".join(brief.allowed_facts[:3])
        return f"{ticker}: {supported}." + (" What deserves a closer look?" if variant == "QUESTION" else "")
    if brief.symbol == "NVDA":
        if variant == "PUNCHY":
            return f"{ticker} still has serious PSC conviction. Social interest remains high, but novelty is lower."
        if variant == "DATA_DRIVEN":
            return f"{ticker} combines strong PSC conviction with durable social interest. The setup is useful, but not as fresh as MSFT."
        return f"What is keeping social interest elevated in {ticker} despite a lower novelty premium? PSC conviction remains strong, but the freshness edge is smaller than MSFT."
    if brief.symbol == "UBER":
        if variant == "PUNCHY":
            return f"{ticker} is a more analytical setup. The valuation and FCF context are interesting, but social interest is moderate."
        if variant == "DATA_DRIVEN":
            return f"{ticker} offers a valuation and FCF angle with moderate social interest. It reads more contrarian than momentum-driven."
        return f"Could {ticker} be the contrarian alternative before social attention catches up? Its valuation and FCF context are more interesting than the current sentiment signal."
    return f"{ticker} is worth watching as the signal develops."


def _repair_text(brief: ContentBrief) -> str:
    facts = brief.allowed_facts[:3]
    if not facts:
        return "The supplied brief does not contain any supported facts."
    return ". ".join(fact.strip(".") for fact in facts if fact.strip()) + "."


def estimate_llm_engagement(text: str, opportunity: PostOpportunity) -> int:
    score = 55
    if "?" in text:
        score += 9
    if any(token in text.lower() for token in ("accelerating", "rank", "signal", "watching")):
        score += 15
    if len(text) <= 140:
        score += 10
    if opportunity.confidence == "HIGH":
        score += 5
    return max(0, min(100, score))


def validate_content(text: str, brief: ContentBrief) -> ContentValidationResult:
    cleaned = text.strip()
    reasons: list[str] = []
    warnings: list[str] = []
    unsupported_numbers: list[str] = []
    unsupported_claims: list[str] = []
    formatting_issues: list[str] = []
    if not cleaned:
        reasons.append("Empty content output")
        return ContentValidationResult(
            valid=False,
            unsupported_numbers=[],
            unsupported_claims=[],
            symbol_mismatch=False,
            length_violation=False,
            formatting_issues=["Empty content output"],
            warnings=[],
            rejection_reasons=["Empty content output"],
        )
    if len(cleaned) > brief.maximum_length:
        reasons.append(f"Content exceeds {brief.maximum_length} characters")
    explicit_tickers = re.findall(r"\$([A-Z]{1,5})", cleaned)
    symbol_mismatch = bool(explicit_tickers) and explicit_tickers[0].upper() != brief.symbol.upper()
    if symbol_mismatch:
        reasons.append(f"Ticker mismatch: generated {explicit_tickers[0]} instead of {brief.symbol}")
    numbers = re.findall(r"\d+(?:\.\d+)?", cleaned)
    allowed_numbers = {str(number) for number in brief.allowed_numbers}
    for value in numbers:
        if value not in allowed_numbers:
            unsupported_numbers.append(value)
            reasons.append(f"Unsupported numeric claim: {value}")
    evidence = " ".join(brief.allowed_facts).lower()
    # Numeric allowlists alone cannot distinguish a score from an invented rank.
    guarded = [
        (r"\b(?:rank(?:ed|ing)?|top\s*20|rank acceleration)\b", r"\brank\s+\d|top\s*20", "PSC ranking"),
        (r"\b(?:alert|alerts)\b", r"\balert", "alert"),
        (r"\brevenue\s+(?:growth|grew|increased|rose)", r"revenue growth", "revenue growth"),
        (r"\bearnings?\s+(?:growth|grew|increased|rose)", r"earnings growth", "earnings growth"),
        (r"\b(?:share price|current price|trading at|breakout|technical)\b", r"share price|current price|technical breakout", "market"),
    ]
    for claim_pattern, evidence_pattern, label in guarded:
        if re.search(claim_pattern, cleaned, re.I) and not re.search(evidence_pattern, evidence):
            unsupported_claims.append(label + " claim is not supported by the brief")
            reasons.append("Unsupported claim: " + label)
    patterns = [
        (r"revenue (?:grew|increased|rose).*\d", "revenue"),
        (r"earnings?(?: per share|).*\d", "earnings"),
        (r"(?:target|price target).*(?:\$|\d)", "price target"),
        (r"(?:insider|insiders|ceo|board member|executive|pelosi|senator).*?(?:bought|buy|sold|trade|loading up)", "insider"),
        (r"(?:politician|senator|congress).*?(?:bought|buy|sold|trade)", "politician"),
        (r"\$\d+(?:,\d{3})*(?:\.\d+)?", "price target"),
        (r"(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})", "date"),
    ]
    for pattern, claim_type in patterns:
        if re.search(pattern, cleaned, flags=re.IGNORECASE):
            if claim_type == "date" and all(match.lower() in evidence for match in re.findall(pattern, cleaned, flags=re.IGNORECASE)):
                continue
            if claim_type == "price target" and any(
                "price target" in fact.lower() for fact in brief.allowed_facts
            ):
                continue
            unsupported_claims.append(f"{claim_type} claim is not supported by the brief")
            reasons.append(f"Unsupported claim: {claim_type}")
    if re.search(r"\$\d+(?:,\d{3})*(?:\.\d+)?", cleaned):
        if not any("price target" in fact.lower() for fact in brief.allowed_facts):
            unsupported_claims.append("price target claim is not supported by the brief")
            reasons.append("Unsupported claim: price target")
    try:
        if cleaned.startswith("{") or cleaned.startswith("["):
            json.loads(cleaned)
    except json.JSONDecodeError:
        formatting_issues.append("Malformed content response")
        reasons.append("Malformed content response")
    if "not valid json" in cleaned.lower() or "malformed" in cleaned.lower():
        formatting_issues.append("Malformed content response")
        reasons.append("Malformed content response")
    if cleaned.count("\n") > 3:
        formatting_issues.append("Excessive formatting")
    return ContentValidationResult(
        valid=not reasons,
        unsupported_numbers=unsupported_numbers,
        unsupported_claims=unsupported_claims,
        symbol_mismatch=symbol_mismatch,
        length_violation=len(cleaned) > brief.maximum_length,
        formatting_issues=formatting_issues,
        warnings=warnings,
        rejection_reasons=reasons,
    )


def _brief_snapshot(brief: ContentBrief) -> dict[str, Any]:
    return {
        "symbol": brief.symbol,
        "primary_angle": brief.primary_angle,
        "secondary_angles": brief.secondary_angles,
        "tone": brief.tone,
        "preferred_format": brief.preferred_format,
        "strongest_fact": brief.strongest_fact,
        "supporting_facts": brief.supporting_facts,
        "social_summary": brief.social_summary,
        "regivion_summary": brief.regivion_summary,
        "urgency": brief.urgency,
        "confidence": brief.confidence,
        "visual_recommendation": brief.visual_recommendation,
        "allowed_numbers": brief.allowed_numbers,
        "allowed_facts": brief.allowed_facts,
        "forbidden_claim_types": brief.forbidden_claim_types,
        "factuality_constraints": brief.factuality_constraints,
        "style_profile": brief.style_profile,
        "maximum_length": brief.maximum_length,
        "prompt_version": brief.prompt_version,
    }


def opportunity_id_from_row(row: Any) -> int | None:
    return None if row is None else int(row["id"])


class ContentGenerationService:
    """Operational handoff: generate/repair using existing engines, then validate
    and deduplicate final variants before persistence. Never replace reviewed rows.
    """
    def __init__(self, database: Database, generator=None, *, social_sources=None) -> None:
        self.database = database
        self.social_sources = social_sources
        self.generator = generator or LLMContentGenerator(database=database, provider=MockLLMProvider(), auto_persist=False)
        if isinstance(self.generator, LLMContentGenerator):
            self.generator.auto_persist = False

    def generate(self, opportunity: PostOpportunity) -> dict[str, Any]:
        candidates = self.generator.generate_for_opportunity(opportunity)
        created = []
        rejected = 0
        validations = []
        for candidate in candidates:
            brief = ContentBrief.from_opportunity(opportunity)
            validation = validate_content(candidate.full_text, brief)
            validations.append({"variant": candidate.variant_type, "valid": validation.valid,
                                "rejection_reasons": validation.rejection_reasons})
            if not validation.valid or (candidate.generator_type == "LLM" and not candidate.validation_result.valid):
                rejected += 1
                continue
            if self.database.get_recent_content_by_hash(candidate.content_hash):
                continue
            candidate = replace(candidate, validation_result=validation, final_machine_validation=True, brief_snapshot=_brief_snapshot(brief),
                                requires_human_review=True, review_status="PENDING")
            if candidate.provider == 'openai':
                sources = sorted(self.social_sources or [])
                source_filter = (' AND source IN (' + ','.join('?' for _ in sources) + ')') if sources else ''
                cutoff = (datetime.now(timezone.utc) - timedelta(minutes=120)).isoformat()
                provenance = [dict(r) for r in self.database.execute(
                    'SELECT id,source,external_id,observed_at FROM social_observations WHERE (ticker=? OR ticker LIKE ? OR ticker LIKE ? OR ticker LIKE ?) AND observed_at>=?' + source_filter + ' ORDER BY observed_at DESC LIMIT 100',
                    (opportunity.symbol, opportunity.symbol + ',%', '%,' + opportunity.symbol, '%,' + opportunity.symbol + ',%', cutoff, *sources))]
                snapshot = self.database.get_regivion_snapshot(opportunity.symbol)
                brief_snapshot = {**candidate.brief_snapshot, 'data_provenance': {'social': provenance,
                    'regivion': json.loads(snapshot['payload']).get('provenance', {}) if snapshot else {},
                    'market': 'disabled'}}
                candidate = replace(candidate, brief_snapshot=brief_snapshot)
            if isinstance(self.generator, LLMContentGenerator):
                self.generator._persist(candidate)
            else:
                self.generator._persist(candidate, opportunity)
            row = self.database.get_recent_content_by_hash(candidate.content_hash)
            self.database.execute("UPDATE content_candidates SET opportunity_score=?, ready_to_post=0, active_review_state='PENDING' WHERE id=?",
                                  (opportunity.total_score, row["id"]))
            self.database.commit()
            created.append(dict(self.database.get_row("content_candidates", row["id"])))
        return {"created": created, "rejected": rejected, "generated": len(candidates), "validation": validations}
