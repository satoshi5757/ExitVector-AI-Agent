"""Preliminary social trend scoring."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrendScore:
    """Social trend score with threshold and metadata."""

    ticker: str
    score: float
    velocity_ratio: float
    acceleration: float
    absolute_volume: int
    unique_authors: int
    engagement_weighted: float
    confirming_sources: int
    reason: str


class SocialTrendScorer:
    """Compute a 0-100 social trend score from rolling mention signals."""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        min_volume: int = 5,
        min_score: float = 50.0,
        max_ratio: float = 10.0,
    ) -> None:
        self.weights = {
            "velocity": 0.30,
            "acceleration": 0.20,
            "absolute_volume": 0.15,
            "unique_authors": 0.15,
            "engagement": 0.10,
            "cross_source": 0.10,
            **(weights or {}),
        }
        self.min_volume = min_volume
        self.min_score = min_score
        self.max_ratio = max_ratio

    def score(
        self,
        *,
        velocity_ratio: float,
        acceleration: float,
        absolute_volume: int,
        unique_authors: int,
        engagement_weighted: float,
        confirming_sources: int,
    ) -> float:
        """Return a bounded score, honoring minimum-volume and score thresholds."""

        capped_ratio = min(max(velocity_ratio, 0.0), self.max_ratio)
        capped_acceleration = min(max(acceleration, 0.0), self.max_ratio)
        capped_volume = min(max(absolute_volume, 0.0), 100.0)
        capped_authors = min(max(unique_authors, 0.0), 100.0)
        capped_engagement = min(max(engagement_weighted, 0.0), 100.0)
        capped_sources = min(max(confirming_sources, 0.0), 5.0)

        if absolute_volume < self.min_volume:
            return 0.0

        velocity_score = min(1.0, capped_ratio / 4.0) * self.weights["velocity"]
        acceleration_score = min(1.0, capped_acceleration / 2.0) * self.weights["acceleration"]
        volume_score = min(1.0, capped_volume / 40.0) * self.weights["absolute_volume"]
        author_score = min(1.0, capped_authors / 25.0) * self.weights["unique_authors"]
        engagement_score = min(1.0, capped_engagement / 30.0) * self.weights["engagement"]
        source_score = min(1.0, capped_sources / 3.0) * self.weights["cross_source"]

        score = (velocity_score + acceleration_score + volume_score + author_score + engagement_score + source_score) * 100.0
        return min(100.0, max(0.0, score))

    def qualifies(self, score: float) -> bool:
        """Report whether a score clears the minimum required threshold."""

        return score >= self.min_score
