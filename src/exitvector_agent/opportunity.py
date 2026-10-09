"""Post opportunity scoring, classification, and presentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable


class ContentAngle(str, Enum):
    MOMENTUM_CONVERGENCE = "MOMENTUM_CONVERGENCE"
    VALUATION_DISLOCATION = "VALUATION_DISLOCATION"
    PSC_RANK_JUMP = "PSC_RANK_JUMP"
    NEW_TOP20_ENTRY = "NEW_TOP20_ENTRY"
    INSIDER_BUY = "INSIDER_BUY"
    POLITICIAN_BUY = "POLITICIAN_BUY"
    EARNINGS_ACCELERATION = "EARNINGS_ACCELERATION"
    REVENUE_GROWTH_DISLOCATION = "REVENUE_GROWTH_DISLOCATION"
    TECHNICAL_BREAKOUT = "TECHNICAL_BREAKOUT"
    SOCIAL_SPIKE = "SOCIAL_SPIKE"
    MULTI_SIGNAL_CONVERGENCE = "MULTI_SIGNAL_CONVERGENCE"


@dataclass(frozen=True, slots=True)
class PostOpportunity:
    symbol: str
    total_score: float
    confidence: str
    social_trend_score: float
    regivion_score: float
    market_score: float | None
    freshness_score: float
    novelty_score: float
    engagement_potential_score: float
    trigger_reasons: list[str] = field(default_factory=list)
    social_summary: str = ""
    regivion_summary: str = ""
    strongest_fact: str = ""
    supporting_facts: list[str] = field(default_factory=list)
    urgency: str = "low"
    suggested_content_angle: str = ContentAngle.MOMENTUM_CONVERGENCE.value
    suggested_visual_type: str = ""
    content_angles: list[str] = field(default_factory=list)
    history_confidence: float = 1.0
    notification_eligible: bool = True
    re_notification_reason: str | None = None


class OpportunityScorer:
    """Compute a configurable 0-100 opportunity score with context-aware normalization."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = {
            "social": 0.45,
            "regivion": 0.20,
            "market": 0.15,
            "freshness": 0.05,
            "novelty": 0.10,
            "engagement": 0.05,
            **(weights or {}),
        }

    def history_confidence(self, *, baseline_mentions: int, current_mentions: int, min_observations: int = 3) -> float:
        """Reduce confidence when a social trend is based on a zero or very small baseline."""

        if current_mentions <= 0:
            return 0.0
        if baseline_mentions <= 0:
            baseline_component = min(current_mentions / max(min_observations * 2, 1), 1.0)
            return min(1.0, max(0.15, baseline_component)) if current_mentions < min_observations * 2 else 0.75
        return min(1.0, max(0.25, current_mentions / max(baseline_mentions * 2, 1)))

    def score(
        self,
        *,
        social_score: float,
        regivion_score: float | None,
        market_score: float | None,
        freshness_score: float,
        novelty_score: float,
        engagement_potential_score: float,
        history_confidence: float = 1.0,
    ) -> float:
        """Score available components while renormalizing when a component is unavailable."""

        components: dict[str, float] = {
            "social": max(0.0, min(100.0, float(social_score))),
            "regivion": max(0.0, min(100.0, float(regivion_score))) if regivion_score is not None else None,
            "market": max(0.0, min(100.0, float(market_score))) if market_score is not None else None,
            "freshness": max(0.0, min(100.0, float(freshness_score))),
            "novelty": max(0.0, min(100.0, float(novelty_score))),
            "engagement": max(0.0, min(100.0, float(engagement_potential_score))),
        }
        total_weight = sum(
            weight for name, weight in self.weights.items() if components.get(name) is not None
        )
        if total_weight <= 0:
            return 0.0
        weighted_total = sum(
            component * self.weights[name]
            for name, component in components.items()
            if component is not None
        )
        return min(100.0, max(0.0, weighted_total / total_weight))

    def confidence(
        self,
        *,
        total_score: float,
        history_confidence: float = 1.0,
        data_coverage: float = 1.0,
        signal_agreement: float = 1.0,
    ) -> str:
        """Return confidence from evidence quality rather than total opportunity score alone."""

        evidence_score = (
            0.40 * max(0.0, min(1.0, history_confidence))
            + 0.35 * max(0.0, min(1.0, data_coverage))
            + 0.25 * max(0.0, min(1.0, signal_agreement))
        )
        if total_score >= 75.0 and evidence_score >= 0.75:
            return "HIGH"
        if total_score >= 70.0 and evidence_score >= 0.55:
            return "MEDIUM"
        if total_score >= 55.0 and evidence_score >= 0.35:
            return "LOW"
        return "VERY_LOW"


def classify_content_angle(
    *,
    psc_rank_jump: bool = False,
    fresh_bullish_alert: bool = False,
    revenue_growth: bool = False,
    insider_buy: bool = False,
    politician_trade: bool = False,
    valuation_dislocation: bool = False,
    technical_breakout: bool = False,
    social_spike: bool = False,
    earnings_acceleration: bool = False,
    multi_signal: bool = False,
) -> ContentAngle:
    """Choose the primary rule-based content angle for an opportunity."""

    if multi_signal:
        return ContentAngle.MULTI_SIGNAL_CONVERGENCE
    if psc_rank_jump and fresh_bullish_alert:
        return ContentAngle.PSC_RANK_JUMP
    if insider_buy:
        return ContentAngle.INSIDER_BUY
    if politician_trade:
        return ContentAngle.POLITICIAN_BUY
    if valuation_dislocation:
        return ContentAngle.VALUATION_DISLOCATION
    if technical_breakout:
        return ContentAngle.TECHNICAL_BREAKOUT
    if fresh_bullish_alert:
        return ContentAngle.MOMENTUM_CONVERGENCE
    if psc_rank_jump:
        return ContentAngle.PSC_RANK_JUMP
    if revenue_growth:
        return ContentAngle.REVENUE_GROWTH_DISLOCATION
    if earnings_acceleration:
        return ContentAngle.EARNINGS_ACCELERATION
    if social_spike:
        return ContentAngle.SOCIAL_SPIKE
    return ContentAngle.MOMENTUM_CONVERGENCE


def recommend_visual(angle: ContentAngle | str) -> str:
    """Return a rule-based visual recommendation without generating an image."""

    angle_name = angle.value if isinstance(angle, ContentAngle) else angle
    mapping: dict[str, str] = {
        ContentAngle.PSC_RANK_JUMP.value: "PSC score/rank screenshot + price chart",
        ContentAngle.INSIDER_BUY.value: "insider transaction screenshot/card",
        ContentAngle.POLITICIAN_BUY.value: "politician disclosure graphic",
        ContentAngle.VALUATION_DISLOCATION.value: "price drawdown + valuation chart",
        ContentAngle.MOMENTUM_CONVERGENCE.value: "TradingView chart + PSC score",
        ContentAngle.REVENUE_GROWTH_DISLOCATION.value: "revenue and earnings trend chart",
        ContentAngle.EARNINGS_ACCELERATION.value: "earnings revision snapshot",
        ContentAngle.TECHNICAL_BREAKOUT.value: "price breakout chart with volume",
        ContentAngle.SOCIAL_SPIKE.value: "social volume chart + timestamped mentions",
        ContentAngle.MULTI_SIGNAL_CONVERGENCE.value: "multi-signal dashboard screenshot",
        ContentAngle.NEW_TOP20_ENTRY.value: "Top 20 rank badges + price chart",
    }
    return mapping.get(angle_name, "price chart + supporting market snapshot")


def build_supporting_facts(items: Iterable[Any]) -> list[str]:
    """Create readable supporting facts while preserving non-string values."""

    facts: list[str] = []
    for item in items:
        value = str(item).strip()
        if value:
            facts.append(value)
    return facts


def score_regivion(
    *,
    psc_score: float | None,
    psc_rank: int | None,
    previous_psc_rank: int | None,
    recent_alerts: list[Any],
    revenue_growth_yoy: float | None,
    earnings_growth_yoy: float | None,
    free_cash_flow_growth: float | None,
    insider_buys: int,
    politician_trades: int,
    fresh_rank_jump: bool = False,
    entered_top_20: bool | None = False,
) -> float:
    """Compute a 0-100 conviction score from Regivion signals."""

    score = 0.0
    if psc_score is not None:
        score += min(50.0, psc_score * 0.5)
    if psc_rank is not None:
        score += max(0.0, min(22.0, 26.0 - psc_rank))
    if previous_psc_rank is not None and psc_rank is not None:
        improvement = previous_psc_rank - psc_rank
        score += min(12.0, max(0.0, improvement * 0.5))
    if fresh_rank_jump:
        score += 10.0
    if any(alert.direction == "bullish" for alert in recent_alerts):
        score += 8.0
    if revenue_growth_yoy is not None and revenue_growth_yoy > 0:
        score += min(8.0, revenue_growth_yoy * 100.0 / 2.0)
    if earnings_growth_yoy is not None and earnings_growth_yoy > 0:
        score += min(8.0, earnings_growth_yoy * 100.0 / 2.0)
    if free_cash_flow_growth is not None and free_cash_flow_growth > 0:
        score += min(6.0, free_cash_flow_growth * 100.0 / 3.0)
    if insider_buys > 0:
        score += min(8.0, insider_buys * 2.0)
    if politician_trades > 0:
        score += min(6.0, politician_trades * 2.0)
    if entered_top_20:
        score += 5.0
    return min(100.0, max(0.0, score))


def build_content_angle_list(*, psc_rank_jump: bool, fresh_bullish_alert: bool, revenue_growth: bool, insider_buy: bool, politician_trade: bool, valuation_dislocation: bool = False, technical_breakout: bool = False, social_spike: bool = False, earnings_acceleration: bool = False, multi_signal: bool = False) -> list[str]:
    angle = classify_content_angle(
        psc_rank_jump=psc_rank_jump,
        fresh_bullish_alert=fresh_bullish_alert,
        revenue_growth=revenue_growth,
        insider_buy=insider_buy,
        politician_trade=politician_trade,
        valuation_dislocation=valuation_dislocation,
        technical_breakout=technical_breakout,
        social_spike=social_spike,
        earnings_acceleration=earnings_acceleration,
        multi_signal=multi_signal,
    )
    angles: list[str] = [angle.value]
    if psc_rank_jump:
        angles.append(ContentAngle.PSC_RANK_JUMP.value)
    if fresh_bullish_alert:
        angles.append(ContentAngle.MOMENTUM_CONVERGENCE.value)
    if revenue_growth:
        angles.append(ContentAngle.REVENUE_GROWTH_DISLOCATION.value)
    if insider_buy:
        angles.append(ContentAngle.INSIDER_BUY.value)
    if politician_trade:
        angles.append(ContentAngle.POLITICIAN_BUY.value)
    if valuation_dislocation:
        angles.append(ContentAngle.VALUATION_DISLOCATION.value)
    if technical_breakout:
        angles.append(ContentAngle.TECHNICAL_BREAKOUT.value)
    if social_spike:
        angles.append(ContentAngle.SOCIAL_SPIKE.value)
    if earnings_acceleration:
        angles.append(ContentAngle.EARNINGS_ACCELERATION.value)
    if multi_signal:
        angles.append(ContentAngle.MULTI_SIGNAL_CONVERGENCE.value)
    return list(dict.fromkeys(angles))
