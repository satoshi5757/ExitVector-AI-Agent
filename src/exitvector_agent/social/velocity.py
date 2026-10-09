"""Mention velocity and acceleration calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from exitvector_agent.social.models import SocialObservation


@dataclass(frozen=True, slots=True)
class RollingTickerStats:
    """Rolling statistics for one ticker and one time window."""

    window_minutes: int
    mentions: int
    unique_authors: int
    engagement_weighted: float
    baseline_mentions: int
    velocity_ratio: float
    acceleration: float
    confirming_sources: int


@dataclass(frozen=True, slots=True)
class VelocitySummary:
    """Point-in-time velocity summary for one ticker."""

    window_minutes: int
    mentions: int
    unique_authors: int
    engagement_weighted: float
    baseline_mentions: int
    velocity_ratio: float
    acceleration: float
    confirming_sources: int


class MentionVelocityEngine:
    """Compute rolling mention statistics with bounded ratios."""

    def __init__(
        self,
        window_minutes: tuple[int, ...] = (10, 30, 60),
        baseline_window_minutes: int = 60,
    ) -> None:
        self.window_minutes = tuple(sorted(window_minutes))
        self.baseline_window_minutes = baseline_window_minutes

    def calculate(
        self,
        ticker: str,
        observations: list[SocialObservation],
        now: datetime,
    ) -> dict[int, VelocitySummary]:
        """Calculate windowed metrics for one ticker."""

        ticker_observations = [
            observation
            for observation in observations
            if ticker in observation.tickers
            and observation.timestamp <= now
        ]
        summary: dict[int, VelocitySummary] = {}
        for window in self.window_minutes:
            start = now - timedelta(minutes=window)
            current = [
                observation
                for observation in ticker_observations
                if observation.timestamp >= start
            ]
            baseline_start = now - timedelta(minutes=window + self.baseline_window_minutes)
            baseline_end = now - timedelta(minutes=window)
            baseline = [
                observation
                for observation in ticker_observations
                if baseline_start <= observation.timestamp < baseline_end
            ]
            current_mentions = len(current)
            baseline_mentions = len(baseline)
            velocity_ratio = self._safe_ratio(current_mentions, baseline_mentions)
            acceleration = max(0.0, velocity_ratio - self._safe_ratio(len(baseline), max(len(baseline), 1)))
            unique_authors = len({observation.author for observation in current if observation.author})
            engagement_weighted = sum(
                observation.likes + observation.replies * 2 + observation.reposts * 3 + observation.views / 1000
                for observation in current
            )
            confirming_sources = len({observation.source for observation in current})
            summary[window] = VelocitySummary(
                window_minutes=window,
                mentions=current_mentions,
                unique_authors=unique_authors,
                engagement_weighted=engagement_weighted,
                baseline_mentions=baseline_mentions,
                velocity_ratio=velocity_ratio,
                acceleration=acceleration,
                confirming_sources=confirming_sources,
            )
        return summary

    @staticmethod
    def _safe_ratio(numerator: float, denominator: float) -> float:
        """Return a bounded ratio, avoiding divide-by-zero and huge values."""

        if denominator <= 0:
            return float(numerator) if numerator > 0 else 0.0
        ratio = float(numerator) / float(denominator)
        return min(10.0, max(0.0, ratio))
