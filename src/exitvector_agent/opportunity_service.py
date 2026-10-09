"""Convert social trends and Regivion data into ranked opportunities."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Iterable

from exitvector_agent.database import Database
from exitvector_agent.opportunity import (
    ContentAngle,
    OpportunityScorer,
    PostOpportunity,
    build_content_angle_list,
    classify_content_angle,
    recommend_visual,
    score_regivion,
)
from exitvector_agent.regivion import RegivionClient, RegivionEnrichment
from exitvector_agent.social.scan import TrendResult


@dataclass(frozen=True, slots=True)
class OpportunityCandidate:
    symbol: str
    social: TrendResult
    enrichment: RegivionEnrichment | None
    score: float
    regivion_score: float
    confidence: str
    primary_angle: str
    visual: str
    reasons: list[str]
    summary: PostOpportunity


class OpportunityService:
    """Rank social attention into review-ready content opportunities."""

    def __init__(
        self,
        database: Database,
        regivion_client: RegivionClient,
        scorer: OpportunityScorer | None = None,
        threshold: float = 75.0,
        re_notify_delta: float = 10.0,
        cooldown_minutes: int = 180,
        live_mode: bool = False,
    ) -> None:
        self.database = database
        self.regivion_client = regivion_client
        self.scorer = scorer or OpportunityScorer()
        self.threshold = float(threshold)
        self.re_notify_delta = float(re_notify_delta)
        self.cooldown_minutes = cooldown_minutes
        self.live_mode = live_mode

    def scan(self, *, limit: int = 20, trends: Iterable[TrendResult] | None = None) -> list[PostOpportunity]:
        """Build a ranked opportunity list while tracking notification eligibility separately."""

        rows = self.database.execute(
            "SELECT * FROM trend_score_snapshots WHERE id IN (SELECT MAX(id) FROM trend_score_snapshots GROUP BY ticker) ORDER BY score DESC"
        ).fetchall()
        if trends is not None:
            from dataclasses import asdict
            rows = [asdict(trend) for trend in trends]
        opportunities: list[PostOpportunity] = []
        for row in rows:
            ticker = row["ticker"]
            social = TrendResult(
                ticker=ticker,
                score=float(row["score"]),
                velocity_ratio=float(row["velocity_ratio"]),
                acceleration=float(row["acceleration"]),
                baseline_mentions=int(row["baseline_mentions"]),
                current_mentions=int(row["current_mentions"]),
                unique_authors=int(row["unique_authors"]),
                confirming_sources=int(row["confirming_sources"]),
                reasons=[],
            )
            enrichment = self.regivion_client.get_ticker(ticker)
            previous_enrichment = json.loads(self.database.get_regivion_snapshot(ticker)["payload"]) if self.database.get_regivion_snapshot(ticker) else {}
            if enrichment is not None:
                self.database.insert_regivion_snapshot(ticker=ticker, payload=enrichment.raw)
            opportunity = self._build_opportunity(social=social, enrichment=enrichment)
            if opportunity is None:
                continue
            eligible, reason = self.database.evaluate_re_notification(
                ticker,
                score=opportunity.total_score,
                threshold=self.threshold,
                delta=self.re_notify_delta,
                now=datetime.now(timezone.utc),
                cooldown_minutes=self.cooldown_minutes,
                current_enrichment=enrichment.raw if enrichment is not None else None,
                current_primary_angle=opportunity.suggested_content_angle,
                previous_enrichment=previous_enrichment,
            )
            opportunity = replace(opportunity, notification_eligible=eligible, re_notification_reason=reason)
            opportunities.append(opportunity)
            self._persist(opportunity)
        return sorted(opportunities, key=lambda item: item.total_score, reverse=True)[:limit]

    def _build_opportunity(self, *, social: TrendResult, enrichment: RegivionEnrichment | None) -> PostOpportunity | None:
        history_confidence = self.scorer.history_confidence(
            baseline_mentions=social.baseline_mentions,
            current_mentions=social.current_mentions,
        )
        market_score = None if self.live_mode else self._market_score(social)
        regivion_score = self._regivion_score(enrichment)
        freshness_score = self._freshness_score(enrichment, social)
        if enrichment and enrichment.raw.get('provenance', {}).get('stale'):
            freshness_score = 0
        novelty_score = self._novelty_score(social, enrichment)
        engagement = self._engagement_score(social)

        total_score = self.scorer.score(
            social_score=social.score,
            regivion_score=None if self.live_mode and (enrichment is None or not any([
                enrichment.psc_score is not None, enrichment.psc_rank is not None,
                enrichment.forward_pe is not None, enrichment.peg is not None,
                enrichment.revenue_growth_yoy is not None, enrichment.earnings_growth_yoy is not None,
                enrichment.free_cash_flow_growth is not None, enrichment.recent_alerts,
                enrichment.recent_insider_buys, enrichment.recent_insider_sells,
                enrichment.recent_politician_trades])) else regivion_score,
            market_score=market_score,
            freshness_score=freshness_score,
            novelty_score=novelty_score,
            engagement_potential_score=engagement,
            history_confidence=history_confidence,
        )
        primary_angle = self._primary_angle(social=social, enrichment=enrichment)
        trigger_reasons = self._trigger_reasons(social=social, enrichment=enrichment)
        supporting_facts = self._supporting_facts(social=social, enrichment=enrichment)
        strongest_fact = trigger_reasons[0] if trigger_reasons else "Social trend is above threshold"
        data_coverage = self._data_coverage(social, enrichment)
        signal_agreement = self._signal_agreement(social, enrichment)
        opportunity = PostOpportunity(
            symbol=social.ticker,
            total_score=round(total_score, 1),
            confidence=self.scorer.confidence(
                total_score=total_score,
                history_confidence=history_confidence,
                data_coverage=data_coverage,
                signal_agreement=signal_agreement,
            ),
            social_trend_score=social.score,
            regivion_score=round(regivion_score, 1),
            market_score=market_score,
            freshness_score=freshness_score,
            novelty_score=novelty_score,
            engagement_potential_score=engagement,
            trigger_reasons=trigger_reasons,
            social_summary=f"{social.current_mentions} mentions with a {social.velocity_ratio:.2f}x velocity ratio",
            regivion_summary=self._regivion_summary(enrichment),
            strongest_fact=strongest_fact,
            supporting_facts=supporting_facts,
            urgency=self._urgency(social, enrichment),
            suggested_content_angle=primary_angle.value,
            suggested_visual_type=recommend_visual(primary_angle),
            content_angles=self._content_angles(social=social, enrichment=enrichment),
            history_confidence=history_confidence,
        )
        if enrichment and enrichment.raw.get('provenance', {}).get('stale'):
            opportunity = replace(opportunity, confidence='LOW', freshness_score=0)
        return opportunity

    def _persist(self, opportunity: PostOpportunity) -> None:
        self.database.insert_opportunity(
            ticker=opportunity.symbol,
            total_score=opportunity.total_score,
            confidence=opportunity.confidence,
            social_trend_score=opportunity.social_trend_score,
            regivion_score=opportunity.regivion_score,
            market_score=opportunity.market_score,
            freshness_score=opportunity.freshness_score,
            novelty_score=opportunity.novelty_score,
            engagement_potential_score=opportunity.engagement_potential_score,
            trigger_reasons=json.dumps(opportunity.trigger_reasons, ensure_ascii=False),
            social_summary=opportunity.social_summary,
            regivion_summary=opportunity.regivion_summary,
            strongest_fact=opportunity.strongest_fact,
            supporting_facts=json.dumps(opportunity.supporting_facts, ensure_ascii=False),
            urgency=opportunity.urgency,
            suggested_content_angle=opportunity.suggested_content_angle,
            suggested_visual_type=opportunity.suggested_visual_type,
            content_angles=json.dumps(opportunity.content_angles, ensure_ascii=False),
            notification_eligible=1 if opportunity.notification_eligible else 0,
            detected_at=datetime.now(timezone.utc).isoformat(),
            re_notification_reason=opportunity.re_notification_reason,
        )

    def _market_score(self, social: TrendResult) -> float | None:
        if social.current_mentions <= 0:
            return None
        price_score = min(100.0, max(0.0, social.velocity_ratio * 20.0))
        return min(100.0, max(0.0, price_score))

    def _regivion_score(self, enrichment: RegivionEnrichment | None) -> float:
        if enrichment is None:
            return 0.0
        return score_regivion(
            psc_score=enrichment.psc_score,
            psc_rank=enrichment.psc_rank,
            previous_psc_rank=enrichment.previous_psc_rank,
            recent_alerts=enrichment.recent_alerts,
            revenue_growth_yoy=enrichment.revenue_growth_yoy,
            earnings_growth_yoy=enrichment.earnings_growth_yoy,
            free_cash_flow_growth=enrichment.free_cash_flow_growth,
            insider_buys=len(enrichment.recent_insider_buys),
            politician_trades=len(enrichment.recent_politician_trades),
            fresh_rank_jump=enrichment.rank_change is not None and enrichment.rank_change < -5,
            entered_top_20=enrichment.entered_top_20,
        )

    def _freshness_score(self, enrichment: RegivionEnrichment | None, social: TrendResult) -> float:
        if enrichment is None:
            return 0.0
        score = 0.0
        if enrichment.psc_score is not None:
            score += 25.0
        if enrichment.psc_rank is not None:
            score += max(0.0, min(20.0, 25.0 - enrichment.psc_rank))
        if enrichment.rank_change is not None:
            score += 20.0
        if enrichment.recent_alerts:
            score += 25.0
        if any(alert.timestamp and (datetime.now(timezone.utc) - alert.timestamp).total_seconds() <= 86400 for alert in enrichment.recent_alerts):
            score += 30.0
        if enrichment.entered_top_20:
            score += 5.0
        if social.velocity_ratio > 2.0:
            score += 5.0
        return min(100.0, score)

    def _novelty_score(self, social: TrendResult, enrichment: RegivionEnrichment | None) -> float:
        score = 0.0
        if enrichment is not None:
            if enrichment.psc_score is not None:
                score += min(25.0, max(0.0, (enrichment.psc_score - 75.0) / 1.0))
            if enrichment.rank_change is not None:
                score += min(20.0, max(0.0, abs(enrichment.rank_change) * 1.5))
            if enrichment.psc_rank is not None and enrichment.psc_rank <= 20:
                score += 10.0
            if enrichment.entered_top_20:
                score += 15.0
            if enrichment.recent_alerts:
                score += 15.0
            if enrichment.recent_insider_buys:
                score += 10.0
            if enrichment.recent_politician_trades:
                score += 5.0
        score += min(20.0, max(0.0, social.acceleration * 10.0))
        if enrichment is not None and enrichment.bullish_alerts and enrichment.psc_score is not None and enrichment.psc_score >= 90.0:
            score += 10.0
        return min(100.0, score)

    def _data_coverage(self, social: TrendResult, enrichment: RegivionEnrichment | None) -> float:
        available = 1.0 if social.current_mentions > 0 else 0.0
        available += 1.0 if enrichment is not None else 0.0
        available += 1.0 if social.velocity_ratio > 0 else 0.0
        return min(1.0, available / 3.0)

    def _signal_agreement(self, social: TrendResult, enrichment: RegivionEnrichment | None) -> float:
        if enrichment is None:
            return 0.5 if social.velocity_ratio >= 2.0 else 0.25
        agreement = 0.0
        if social.velocity_ratio >= 2.0:
            agreement += 0.4
        if enrichment.psc_score is not None and enrichment.psc_score >= 90.0:
            agreement += 0.35
        if enrichment.bullish_alerts:
            agreement += 0.25
        return min(1.0, agreement)

    def _engagement_score(self, social: TrendResult) -> float:
        return min(100.0, max(0.0, social.current_mentions * 2.0 + social.unique_authors * 1.5))

    def _fresh_bullish_alerts(self, enrichment):
        if not self.live_mode:
            return enrichment.bullish_alerts
        now = datetime.now(timezone.utc)
        return [alert for alert in enrichment.bullish_alerts if alert.timestamp is not None
                and 0 <= (now - alert.timestamp).total_seconds() <= 86400]

    def _primary_angle(self, *, social: TrendResult, enrichment: RegivionEnrichment | None) -> ContentAngle:
        if enrichment is None:
            return classify_content_angle(social_spike=social.velocity_ratio >= 2.0)
        return classify_content_angle(
            psc_rank_jump=enrichment.rank_change is not None and enrichment.rank_change < -5,
            fresh_bullish_alert=bool(self._fresh_bullish_alerts(enrichment)),
            revenue_growth=enrichment.fresh_revenue_growth,
            insider_buy=bool(enrichment.recent_insider_buys),
            politician_trade=bool(enrichment.recent_politician_trades),
            valuation_dislocation=enrichment.forward_pe is not None and enrichment.forward_pe > 40.0,
            technical_breakout=not self.live_mode and social.acceleration >= 2.0,
            social_spike=social.velocity_ratio >= 2.0,
            earnings_acceleration=enrichment.earnings_growth_yoy is not None and enrichment.earnings_growth_yoy > 0.10,
            multi_signal=bool(enrichment.bullish_alerts) and enrichment.psc_score is not None and enrichment.psc_score >= 90.0,
        )

    def _trigger_reasons(self, *, social: TrendResult, enrichment: RegivionEnrichment | None) -> list[str]:
        reasons: list[str] = []
        if social.velocity_ratio >= 2.0:
            reasons.append(f"social acceleration {social.velocity_ratio:.2f}x")
        if enrichment is not None and enrichment.psc_score is not None:
            reasons.append(f"PSC score {enrichment.psc_score:.1f}")
        if enrichment is not None and enrichment.rank_change is not None and enrichment.rank_change < 0:
            reasons.append(f"PSC rank {enrichment.previous_psc_rank} -> {enrichment.psc_rank}")
        if enrichment is not None and self._fresh_bullish_alerts(enrichment):
            reasons.append("fresh bullish Regivion alert")
        if enrichment is not None and enrichment.recent_insider_buys:
            reasons.append(f"{len(enrichment.recent_insider_buys)} insider buy")
        if enrichment is not None and enrichment.recent_politician_trades:
            reasons.append(f"{len(enrichment.recent_politician_trades)} politician trade")
        if not reasons:
            reasons.append("social attention exceeded the scoring threshold")
        return reasons

    def _supporting_facts(self, *, social: TrendResult, enrichment: RegivionEnrichment | None) -> list[str]:
        facts: list[str] = [f"{social.current_mentions} mentions in the latest window"]
        if enrichment is not None:
            if enrichment.psc_score is not None:
                facts.append(f"PSC score {enrichment.psc_score:.1f}")
                stamp = enrichment.raw.get('provenance', {}).get('components', {}).get('psc', {}).get('source_timestamp')
                if stamp:
                    facts.append(f"PSC source date {stamp[:10]}")
            if enrichment.forward_pe is not None:
                facts.append(f"Forward PE {enrichment.forward_pe:g}")
            if enrichment.peg is not None:
                facts.append(f"PEG {enrichment.peg:g}")
            if enrichment.revenue_growth_yoy is not None:
                facts.append(f"Revenue growth {enrichment.revenue_growth_yoy:.1%}")
            if enrichment.earnings_growth_yoy is not None:
                facts.append(f"Earnings growth {enrichment.earnings_growth_yoy:.1%}")
        return facts

    def _regivion_summary(self, enrichment: RegivionEnrichment | None) -> str:
        if enrichment is None:
            return "No Regivion coverage"
        parts: list[str] = []
        if enrichment.psc_score is not None:
            parts.append(f"PSC {enrichment.psc_score:.1f}")
            stamp = enrichment.raw.get('provenance', {}).get('components', {}).get('psc', {}).get('source_timestamp')
            if stamp:
                parts.append(f"PSC source date {stamp[:10]}")
        if enrichment.psc_rank is not None:
            parts.append(f"rank {enrichment.psc_rank}")
        if enrichment.recent_alerts:
            parts.append(f"{len(enrichment.recent_alerts)} alert(s)")
        if not parts:
            return "Limited Regivion coverage"
        return "; ".join(parts)

    def _content_angles(self, *, social: TrendResult, enrichment: RegivionEnrichment | None) -> list[str]:
        if enrichment is None:
            return [classify_content_angle(social_spike=social.velocity_ratio >= 2.0).value]
        return build_content_angle_list(
            psc_rank_jump=enrichment.rank_change is not None and enrichment.rank_change < -5,
            fresh_bullish_alert=bool(self._fresh_bullish_alerts(enrichment)),
            revenue_growth=enrichment.fresh_revenue_growth,
            insider_buy=bool(enrichment.recent_insider_buys),
            politician_trade=bool(enrichment.recent_politician_trades),
            valuation_dislocation=enrichment.forward_pe is not None and enrichment.forward_pe > 40.0,
            technical_breakout=not self.live_mode and social.acceleration >= 2.0,
            social_spike=social.velocity_ratio >= 2.0,
            earnings_acceleration=enrichment.earnings_growth_yoy is not None and enrichment.earnings_growth_yoy > 0.10,
            multi_signal=bool(enrichment.bullish_alerts) and enrichment.psc_score is not None and enrichment.psc_score >= 90.0,
        )

    def _urgency(self, social: TrendResult, enrichment: RegivionEnrichment | None) -> str:
        if enrichment is not None and enrichment.rank_change is not None and enrichment.rank_change < -10:
            return "high"
        if social.velocity_ratio >= 3.0:
            return "high"
        if social.velocity_ratio >= 2.0:
            return "medium"
        return "low"


def build_opportunity_scan(database: Database, regivion_client: RegivionClient) -> list[PostOpportunity]:
    return OpportunityService(database=database, regivion_client=regivion_client).scan()
