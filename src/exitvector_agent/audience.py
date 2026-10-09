"""Offline audience intelligence for X-compatible relationship analysis."""

from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from exitvector_agent.database import Database, ensure_schema


class SourceType(str, Enum):
    X_ARCHIVE = "X_ARCHIVE"
    MOCK = "MOCK"
    FUTURE_X_API = "FUTURE_X_API"
    FUTURE_BROWSER = "FUTURE_BROWSER"


class InteractionType(str, Enum):
    REPLY = "REPLY"
    MENTION = "MENTION"
    LIKE = "LIKE"
    REPOST = "REPOST"
    QUOTE = "QUOTE"
    USER_REPLY_TO_ACCOUNT = "USER_REPLY_TO_ACCOUNT"
    ACCOUNT_REPLY_TO_USER = "ACCOUNT_REPLY_TO_USER"
    USER_MENTION_OF_ACCOUNT = "USER_MENTION_OF_ACCOUNT"
    ACCOUNT_MENTION_OF_USER = "ACCOUNT_MENTION_OF_USER"


@dataclass(frozen=True, slots=True)
class AudienceDataCoverage:
    following_available: bool = False
    followers_available: bool = False
    replies_available: bool = False
    mentions_available: bool = False
    likes_received_available: bool = False
    reposts_available: bool = False
    replies_outbound_available: bool = False
    mentions_outbound_available: bool = False
    likes_performed_available: bool = False
    quotes_available: bool = False
    observation_window_start: datetime | None = None
    observation_window_end: datetime | None = None
    completeness: float = 0.0
    confidence: str = "AUTO"

    def __post_init__(self) -> None:
        if self.confidence == "AUTO":
            object.__setattr__(self, "confidence", "HIGH" if self.completeness >= .8 else "MEDIUM" if self.completeness >= .6 else "LOW")

    @property
    def window_days(self) -> int:
        if self.observation_window_start is None or self.observation_window_end is None:
            return 0
        return max(0, (self.observation_window_end - self.observation_window_start).days)

    @property
    def requires_confidence(self) -> bool:
        return self.completeness < 0.6 or self.confidence == "LOW" or not self.replies_available


@dataclass(frozen=True, slots=True)
class AudienceAccount:
    account_id: str
    username: str
    display_name: str = ""
    follows_user: bool = False
    user_follows: bool = False
    mutual_follow: bool = False
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    source: str = SourceType.MOCK.value
    source_confidence: float = 0.0
    bio: str = ""
    follower_count: int | None = None
    following_count: int | None = None
    verified: bool | None = None
    account_created_at: datetime | None = None
    data_coverage: AudienceDataCoverage = field(default_factory=AudienceDataCoverage)
    relationship_class: str = "UNKNOWN_INSUFFICIENT_DATA"
    unfollow_candidate: "UnfollowCandidate | None" = None


@dataclass(frozen=True, slots=True)
class AudienceRelationship:
    account_id: str
    username: str
    user_follows: bool
    account_follows_user: bool
    mutual_follow: bool
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    source: str = SourceType.MOCK.value
    source_confidence: float = 0.0
    follower_count: int | None = None
    following_count: int | None = None


@dataclass(frozen=True, slots=True)
class Interaction:
    interaction_id: str
    actor_account_id: str
    target_account_id: str
    interaction_type: InteractionType
    timestamp: datetime
    post_id: str | None = None
    source: str = SourceType.MOCK.value
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class RelationshipMetrics:
    account_id: str
    username: str
    user_follows_account: bool
    account_follows_user: bool
    mutual_follow: bool
    replies_to_user: int | None = None
    mentions_of_user: int | None = None
    likes_of_user: int | None = None
    reposts_of_user: int | None = None
    quotes_of_user: int | None = None
    user_replies_to_them: int | None = None
    user_mentions_them: int | None = None
    user_likes_them: int | None = None
    user_reposts_them: int | None = None
    inbound_interactions: int = 0
    outbound_interactions: int = 0
    total_interactions: int = 0
    last_inbound_interaction_at: datetime | None = None
    last_outbound_interaction_at: datetime | None = None
    days_since_last_interaction: int | None = None
    reciprocity_ratio: float = 0.0
    coverage: AudienceDataCoverage = field(default_factory=AudienceDataCoverage)
    relationship_class: str = "UNKNOWN_INSUFFICIENT_DATA"

    @classmethod
    def from_account(
        cls,
        relationship: AudienceRelationship,
        *,
        inbound: int,
        outbound: int,
        last_inbound: datetime | None,
        last_outbound: datetime | None,
        coverage: AudienceDataCoverage,
        replies_to_user: int | None = None,
        mentions_of_user: int | None = None,
        likes_of_user: int | None = None,
        reposts_of_user: int | None = None,
        quotes_of_user: int | None = None,
        user_replies_to_them: int | None = None,
        user_mentions_them: int | None = None,
        user_likes_them: int | None = None,
        user_reposts_them: int | None = None,
        relationship_class: str | None = None,
        as_of: datetime | None = None,
    ) -> "RelationshipMetrics":
        last_inbound = last_inbound if inbound else None
        last_outbound = last_outbound if outbound else None
        total_interactions = inbound + outbound
        ratio = 0.0 if outbound == 0 else inbound / outbound
        last_seen = max(filter(None, [last_inbound, last_outbound]), default=None)
        days_since = None if last_seen is None else max(0, ((as_of or coverage.observation_window_end or datetime.now(timezone.utc)) - last_seen).days)
        derived_relationship_class = relationship_class or classify_relationship(
            relationship,
            coverage,
            inbound=inbound,
            outbound=outbound,
            last_inbound=last_inbound,
            last_outbound=last_outbound,
        )
        return cls(
            account_id=relationship.account_id,
            username=relationship.username,
            user_follows_account=relationship.user_follows,
            account_follows_user=relationship.account_follows_user,
            mutual_follow=relationship.mutual_follow,
            replies_to_user=replies_to_user,
            mentions_of_user=mentions_of_user,
            likes_of_user=likes_of_user,
            reposts_of_user=reposts_of_user,
            quotes_of_user=quotes_of_user,
            user_replies_to_them=user_replies_to_them,
            user_mentions_them=user_mentions_them,
            user_likes_them=user_likes_them,
            user_reposts_them=user_reposts_them,
            inbound_interactions=inbound,
            outbound_interactions=outbound,
            total_interactions=total_interactions,
            last_inbound_interaction_at=last_inbound,
            last_outbound_interaction_at=last_outbound,
            days_since_last_interaction=days_since,
            reciprocity_ratio=ratio,
            coverage=coverage,
            relationship_class=derived_relationship_class,
        )


@dataclass(frozen=True, slots=True)
class ReciprocityScore:
    score: float
    confidence: str
    unknown: bool = False
    reason_codes: tuple[str, ...] = ()

    @staticmethod
    def from_decay(age_days: int, baseline: float, recent_weight: float, moderate_weight: float) -> float:
        if age_days <= 30:
            return baseline * recent_weight
        if age_days <= 90:
            return baseline * moderate_weight
        return baseline * max(0.0, 1.0 - (age_days - 90) / 180.0)


def _normalize_datetime(value: Any) -> datetime | None:
    if value in (None, "", "null"):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class RelationshipValueScore:
    score: float
    confidence: str
    unknown: bool = False
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UnfollowCandidate:
    account_id: str
    username: str
    score: float
    confidence: str
    reason_codes: tuple[str, ...]
    relationship_class: str
    reciprocity_score: float
    relationship_value_score: float
    inbound_interactions: int
    outbound_interactions: int
    last_interaction_at: datetime | None
    mutual_follow: bool
    data_coverage: AudienceDataCoverage
    recommendation_text: str


@dataclass(frozen=True, slots=True)
class HighValueConnection:
    account_id: str
    username: str
    score: float
    confidence: str
    reason_codes: tuple[str, ...]
    relationship_class: str
    reciprocity_score: float
    relationship_value_score: float
    inbound_interactions: int
    outbound_interactions: int
    last_interaction_at: datetime | None
    mutual_follow: bool
    data_coverage: AudienceDataCoverage
    recommendation_text: str


@runtime_checkable
class XAudienceDataProvider(Protocol):
    def get_following(self) -> list[AudienceAccount]:
        ...

    def get_followers(self) -> list[AudienceAccount]:
        ...

    def get_posts(self) -> list[dict[str, Any]]:
        ...

    def get_replies(self) -> list[dict[str, Any]]:
        ...

    def get_mentions(self) -> list[dict[str, Any]]:
        ...

    def get_likes_received(self) -> list[dict[str, Any]]:
        ...

    def get_interactions(self) -> list[Interaction]:
        ...

    def get_account_metadata(self, account_id: str) -> dict[str, Any]:
        ...

    def get_account_detail(self, account_id: str) -> AudienceAccount:
        ...

    def get_relationships(self) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True, slots=True)
class ImportSummary:
    import_run_id: int
    accounts: int
    follows: int
    followers: int
    posts: int
    interactions: int
    coverage: AudienceDataCoverage


INTERACTION_WEIGHTS = {
    "REPLY": 1.0,
    "QUOTE": 0.8,
    "MENTION": 0.7,
    "REPOST": 0.6,
    "LIKE": 0.5,
}


class AudienceRelationshipAnalyzer:
    """Create deterministic relationship metrics and recommendations from normalized data."""

    def __init__(
        self,
        *,
        following_window_days: int | None = None,
        minimum_confidence: float = 0.5,
        interaction_weights: dict[str, float] | None = None,
    ) -> None:
        self.following_window_days = following_window_days
        self.minimum_confidence = minimum_confidence
        self.interaction_weights = {**INTERACTION_WEIGHTS, **(interaction_weights or {})}

    def analyze_relationship(
        self,
        relationship: AudienceRelationship,
        *,
        inbound: int,
        outbound: int,
        last_inbound: datetime | None,
        last_outbound: datetime | None,
        coverage: AudienceDataCoverage,
        user_replies_to_them: int | None = None,
        user_mentions_them: int | None = None,
        user_likes_them: int | None = None,
        user_reposts_them: int | None = None,
        replies_to_user: int | None = None,
        mentions_of_user: int | None = None,
        likes_of_user: int | None = None,
        reposts_of_user: int | None = None,
        quotes_of_user: int | None = None,
    ) -> RelationshipMetrics:
        metrics = RelationshipMetrics.from_account(
            relationship,
            inbound=inbound,
            outbound=outbound,
            last_inbound=last_inbound,
            last_outbound=last_outbound,
            coverage=coverage,
            replies_to_user=replies_to_user,
            mentions_of_user=mentions_of_user,
            likes_of_user=likes_of_user,
            reposts_of_user=reposts_of_user,
            quotes_of_user=quotes_of_user,
            user_replies_to_them=user_replies_to_them,
            user_mentions_them=user_mentions_them,
            user_likes_them=user_likes_them,
            user_reposts_them=user_reposts_them,
            relationship_class=classify_relationship(
                relationship,
                coverage,
                inbound=inbound,
                outbound=outbound,
                last_inbound=last_inbound,
                last_outbound=last_outbound,
            ),
        )
        return metrics


def classify_relationship(
    relationship: AudienceRelationship | RelationshipMetrics,
    coverage: AudienceDataCoverage,
    *,
    inbound: int | None = None,
    outbound: int | None = None,
    last_inbound: datetime | None = None,
    last_outbound: datetime | None = None,
) -> str:
    is_metrics = isinstance(relationship, RelationshipMetrics)
    if is_metrics:
        inbound = relationship.inbound_interactions if inbound is None else inbound
        outbound = relationship.outbound_interactions if outbound is None else outbound
    mutual = relationship.mutual_follow if is_metrics else relationship.mutual_follow
    user_follows = relationship.user_follows_account if is_metrics else relationship.user_follows
    account_follows_user = relationship.account_follows_user if is_metrics else relationship.account_follows_user

    if mutual:
        if (inbound or 0) + (outbound or 0) > 0:
            return "HIGH_VALUE_MUTUAL" if (inbound or 0) >= 5 else "ACTIVE_MUTUAL"
        return "ACTIVE_MUTUAL"
    if user_follows:
        if (inbound or 0) == 0 and (outbound or 0) > 0:
            return "ONE_SIDED_OUTBOUND"
        if (inbound or 0) > 0 and (outbound or 0) == 0:
            return "ONE_SIDED_INBOUND"
        if (inbound or 0) + (outbound or 0) > 0:
            return "ONE_SIDED_OUTBOUND"
        if coverage.requires_confidence:
            return "ONE_SIDED_OUTBOUND"
        return "ONE_SIDED_OUTBOUND"
    if account_follows_user:
        if (inbound or 0) > 0 and (outbound or 0) == 0:
            return "ONE_SIDED_INBOUND"
        return "ONE_SIDED_INBOUND"
    if (inbound or 0) == 0 and (outbound or 0) == 0:
        return "NO_OBSERVED_INTERACTION"
    if coverage.completeness < 0.6:
        return "UNKNOWN_INSUFFICIENT_DATA"
    return "NO_OBSERVED_INTERACTION"


def compute_reciprocity(
    metrics: RelationshipMetrics,
    coverage: AudienceDataCoverage,
    *,
    weights: dict[str, float] | None = None,
) -> ReciprocityScore:
    weights = {
        "inbound": 0.45,
        "outbound": 0.25,
        "mutual": 0.15,
        "recency": 0.15,
        **(weights or {}),
    }
    if coverage.completeness < 0.4 or coverage.confidence == "LOW":
        return ReciprocityScore(0.0, "LOW", unknown=True, reason_codes=("LOW_CONFIDENCE_DATA",))
    inbound = metrics.inbound_interactions
    outbound = metrics.outbound_interactions
    mutual = 1.0 if metrics.mutual_follow else 0.0
    recent = 0.0 if metrics.last_inbound_interaction_at is None else 1.0
    score = (
        weights["inbound"] * min(1.0, inbound / 10.0)
        + weights["outbound"] * min(1.0, outbound / 10.0)
        + weights["mutual"] * mutual
        + weights["recency"] * recent
    ) * 100.0
    score = max(0.0, min(100.0, score))
    if coverage.completeness < 0.6:
        return ReciprocityScore(min(score, 29.999), "LOW", unknown=True, reason_codes=("LOW_CONFIDENCE_DATA",))
    if outbound > 0 and inbound == 0:
        return ReciprocityScore(score, "HIGH" if coverage.confidence == "HIGH" else "MEDIUM", reason_codes=("HIGH_OUTBOUND_ZERO_INBOUND" if outbound >= 10 else "OUTBOUND_ZERO_INBOUND",))
    confidence = "HIGH" if coverage.completeness >= 0.8 and coverage.confidence == "HIGH" else "MEDIUM"
    return ReciprocityScore(score, confidence, reason_codes=("RECIPROCITY",))


def compute_relationship_value(
    metrics: RelationshipMetrics,
    *,
    coverage: AudienceDataCoverage,
    weights: dict[str, float] | None = None,
) -> RelationshipValueScore:
    weights = {
        "reply": 0.35,
        "mutual": 0.25,
        "recent": 0.25,
        "frequency": 0.15,
        **(weights or {}),
    }
    if coverage.completeness < 0.5 or coverage.confidence == "LOW":
        return RelationshipValueScore(0.0, "LOW", unknown=True, reason_codes=("LOW_CONFIDENCE_DATA",))
    inbound, outbound = metrics.inbound_interactions, metrics.outbound_interactions
    reply_strength = min(1.0, inbound / 10.0)
    mutual = float(metrics.mutual_follow)
    has_recent = (
        (inbound > 0 and metrics.last_inbound_interaction_at is not None)
        or (outbound > 0 and metrics.last_outbound_interaction_at is not None)
    ) and metrics.days_since_last_interaction is not None and metrics.days_since_last_interaction <= 90
    recent = float(has_recent and inbound > 0)
    frequency = min(1.0, min(inbound, outbound) / 8.0)
    score = (weights["reply"] * reply_strength + weights["mutual"] * mutual
             + weights["recent"] * recent + weights["frequency"] * frequency) * 100.0
    reasons = []
    if has_recent:
        reasons.append("RECENT_INTERACTION")
    if metrics.mutual_follow:
        reasons.append("MUTUAL_FOLLOW")
    if inbound >= 2 and outbound >= 2:
        reasons.append("SUSTAINED_CONVERSATION")
    if inbound:
        reasons.append("OBSERVED_INBOUND_INTERACTION")
    if outbound and not inbound:
        reasons.append("OUTBOUND_ONLY_EFFORT")
    if not inbound and not outbound:
        reasons.append("NO_OBSERVED_INTERACTION")
    return RelationshipValueScore(max(0.0, min(100.0, score)),
                                  "HIGH" if coverage.completeness >= 0.8 and coverage.confidence == "HIGH" else "MEDIUM",
                                  reason_codes=tuple(reasons))


def score_unfollow_candidate(
    metrics: RelationshipMetrics,
    *,
    coverage: AudienceDataCoverage,
    weights: dict[str, float] | None = None,
    reciprocity_weights: dict[str, float] | None = None,
    value_weights: dict[str, float] | None = None,
) -> UnfollowCandidate:
    weights = {
        "user_follows": 0.15,
        "not_following_back": 0.20,
        "zero_inbound": 0.20,
        "repeated_outbound": 0.15,
        "old_contact": 0.10,
        "inactive": 0.10,
        "low_reciprocity": 0.05,
        "low_value": 0.05,
        **(weights or {}),
    }
    reasons: list[str] = []
    if metrics.user_follows_account:
        reasons.append("NOT_FOLLOWING_BACK") if not metrics.account_follows_user else None
    if metrics.mutual_follow:
        reasons.append("MUTUAL_FOLLOW")
    if metrics.inbound_interactions > 0:
        reasons.append("OBSERVED_INBOUND_INTERACTION")
    if metrics.inbound_interactions == 0 and metrics.outbound_interactions > 0:
        reasons.append("HIGH_OUTBOUND_ZERO_INBOUND" if metrics.outbound_interactions >= 10 else "OUTBOUND_ZERO_INBOUND")
    if metrics.days_since_last_interaction is not None and metrics.days_since_last_interaction >= 180:
        reasons.append("LONG_NO_CONTACT")
    if metrics.days_since_last_interaction is not None and metrics.days_since_last_interaction >= 365:
        reasons.append("INACTIVE")
    if coverage.completeness < 0.6 or coverage.confidence == "LOW":
        reasons.append("LOW_CONFIDENCE_DATA")
    if metrics.reciprocity_ratio < 0.25:
        reasons.append("LOW_RECIPROCITY")
    if metrics.user_follows_account and not metrics.account_follows_user and metrics.inbound_interactions == 0 and metrics.outbound_interactions > 0:
        reasons.append("NOT_FOLLOWING_BACK")
    if not metrics.user_follows_account and metrics.account_follows_user:
        reasons.append("ACCOUNT_FOLLOWS_USER")
    score = 0.0
    if metrics.user_follows_account:
        score += weights["user_follows"] * 100.0
    if metrics.user_follows_account and not metrics.account_follows_user:
        score += weights["not_following_back"] * 100.0
    if metrics.inbound_interactions == 0 and metrics.outbound_interactions > 0:
        score += weights["zero_inbound"] * min(1.0, metrics.outbound_interactions / 10.0) * 100.0
    if metrics.inbound_interactions > 0:
        score += 10.0
    if metrics.outbound_interactions >= 10:
        score += weights["repeated_outbound"] * 100.0
    if metrics.days_since_last_interaction is not None and metrics.days_since_last_interaction >= 180:
        score += weights["old_contact"] * 100.0
    if metrics.days_since_last_interaction is not None and metrics.days_since_last_interaction >= 365:
        score += weights["inactive"] * 100.0
    if metrics.reciprocity_ratio < 0.25:
        score += weights["low_reciprocity"] * 100.0
    if coverage.completeness < 0.6 or coverage.confidence == "LOW":
        score -= 10.0
    if metrics.mutual_follow:
        score = min(score, 60.0)
    if metrics.account_follows_user or metrics.inbound_interactions > 0:
        score = min(score, 60.0)
    if metrics.user_follows_account and metrics.account_follows_user:
        score = max(score, 30.0)
    score = max(0.0, min(100.0, score))
    if not metrics.user_follows_account:
        score = 0.0
    confidence = "LOW" if coverage.confidence == "LOW" else "HIGH" if coverage.completeness >= 0.8 and coverage.confidence == "HIGH" else "MEDIUM" if coverage.completeness >= 0.6 else "LOW"
    relationship_value = compute_relationship_value(metrics, coverage=coverage, weights=value_weights)
    reciprocity = compute_reciprocity(metrics, coverage, weights=reciprocity_weights)
    if relationship_value.score >= 70:
        score = 0.0
    return UnfollowCandidate(
        account_id=metrics.account_id,
        username=metrics.username,
        score=score,
        confidence=confidence,
        reason_codes=tuple(dict.fromkeys(reasons)),
        relationship_class=metrics.relationship_class,
        reciprocity_score=reciprocity.score,
        relationship_value_score=relationship_value.score,
        inbound_interactions=metrics.inbound_interactions,
        outbound_interactions=metrics.outbound_interactions,
        last_interaction_at=max(filter(None, [metrics.last_inbound_interaction_at, metrics.last_outbound_interaction_at]), default=None),
        mutual_follow=metrics.mutual_follow,
        data_coverage=coverage,
        recommendation_text=_unfollow_recommendation(score, metrics, coverage),
    )


def _unfollow_recommendation(score: float, metrics: RelationshipMetrics, coverage: AudienceDataCoverage) -> str:
    if coverage.completeness < 0.6 or coverage.confidence == "LOW":
        return "Insufficient data to determine whether this relationship should be considered for unfollowing."
    if metrics.mutual_follow:
        return ("Mutual follow and recent observed engagement support this relationship."
                if metrics.total_interactions and metrics.days_since_last_interaction is not None and metrics.days_since_last_interaction <= 90
                else "Mutual follow; assess observed engagement before considering changes.")
    if metrics.inbound_interactions > 0:
        return "This account has engaged with you; the relationship should receive additional context before any action."
    confidence = "high" if coverage.completeness >= 0.8 and coverage.confidence == "HIGH" else "medium"
    return (f"No observed inbound interaction in the covered period; {confidence}-confidence "
            "evidence of low reciprocity. Review context before considering unfollowing.")


def score_high_value_connection(
    metrics: RelationshipMetrics,
    *,
    coverage: AudienceDataCoverage,
    reciprocity_weights: dict[str, float] | None = None,
    value_weights: dict[str, float] | None = None,
) -> HighValueConnection:
    reciprocity = compute_reciprocity(metrics, coverage, weights=reciprocity_weights)
    relationship_value = compute_relationship_value(metrics, coverage=coverage, weights=value_weights)
    score = min(100.0, (relationship_value.score * 0.7) + (reciprocity.score * 0.3))
    reasons: list[str] = []
    if metrics.mutual_follow:
        reasons.append("MUTUAL_FOLLOW")
    if (metrics.replies_to_user or 0) >= 2 or (metrics.user_replies_to_them or 0) >= 2:
        reasons.append("FREQUENT_REPLIES")
    if metrics.total_interactions > 0 and metrics.days_since_last_interaction is not None and metrics.days_since_last_interaction <= 90:
        reasons.append("RECENT_ENGAGEMENT")
    return HighValueConnection(
        account_id=metrics.account_id,
        username=metrics.username,
        score=score,
        confidence="LOW" if coverage.confidence == "LOW" else "HIGH" if coverage.completeness >= 0.8 and coverage.confidence == "HIGH" else "MEDIUM" if coverage.completeness >= 0.6 else "LOW",
        reason_codes=tuple(reasons),
        relationship_class=metrics.relationship_class,
        reciprocity_score=reciprocity.score,
        relationship_value_score=relationship_value.score,
        inbound_interactions=metrics.inbound_interactions,
        outbound_interactions=metrics.outbound_interactions,
        last_interaction_at=max(filter(None, [metrics.last_inbound_interaction_at, metrics.last_outbound_interaction_at]), default=None),
        mutual_follow=metrics.mutual_follow,
        data_coverage=coverage,
        recommendation_text=("Insufficient data to assess connection value." if relationship_value.unknown else
                             "Observed inbound or mutual engagement supports this connection." if score >= 40 else
                             "Limited evidence of a high-value connection in this period."),
    )


def _timestamp_text(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat()


def _stable_id(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _coerce_bool(value: Any) -> bool:
    return bool(value) if value is not None else False


__all__ = [
    "AudienceAccount",
    "AudienceDataCoverage",
    "AudienceRelationship",
    "AudienceRelationshipAnalyzer",
    "AudienceQueryService",
    "DatabaseXAudienceDataProvider",
    "ArchiveXAudienceDataProvider",
    "HighValueConnection",
    "ImportSummary",
    "Interaction",
    "InteractionType",
    "MockXAudienceDataProvider",
    "RelationshipMetrics",
    "RelationshipValueScore",
    "ReciprocityScore",
    "SourceType",
    "UnfollowCandidate",
    "XArchiveImportService",
    "XAudienceDataProvider",
    "classify_relationship",
    "compute_reciprocity",
    "compute_relationship_value",
    "score_high_value_connection",
    "score_unfollow_candidate",
]

# Lazy compatibility exports also allow direct imports of audience_data.
def __getattr__(name: str):
    if name in {"ArchiveXAudienceDataProvider", "AudienceQueryService", "DatabaseXAudienceDataProvider",
                "MockXAudienceDataProvider", "XArchiveImportService"}:
        from exitvector_agent import audience_data
        return getattr(audience_data, name)
    raise AttributeError(name)
