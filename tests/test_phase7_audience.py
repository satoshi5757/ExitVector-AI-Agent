from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from exitvector_agent.audience import (
    AudienceDataCoverage,
    AudienceRelationship,
    HighValueConnection,
    Interaction,
    InteractionType,
    MockXAudienceDataProvider,
    RelationshipMetrics,
    RelationshipValueScore,
    ReciprocityScore,
    UnfollowCandidate,
    XArchiveImportService,
    XAudienceDataProvider,
    classify_relationship,
    compute_reciprocity,
    compute_relationship_value,
    score_unfollow_candidate,
)
from exitvector_agent.database import Database, ensure_schema


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "exitvector-audience.db")
    ensure_schema(db)
    return db


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 6, 30, tzinfo=timezone.utc)


def test_archive_normalization_handles_partial_archive(tmp_path: Path) -> None:
    archive = {
        "users": [{"id": "u1", "username": "ALPHA", "name": "Alpha", "created_at": "2024-01-01T00:00:00Z"}],
        "following": [{"id": "u2", "username": "BETA"}],
        "followers": [{"id": "u3", "username": "GAMMA"}],
        "posts": [{"id": "p1", "user_id": "u1", "created_at": "2026-05-01T00:00:00Z", "text": "hello"}],
        "replies": [{"id": "r1", "user_id": "u2", "created_at": "2026-05-15T00:00:00Z", "text": "reply"}],
    }
    path = tmp_path / "archive.json"
    path.write_text(json.dumps(archive), encoding="utf-8")

    service = XArchiveImportService(database=Database(tmp_path / "archive.db"))
    summary = service.import_archive(path)

    assert summary.accounts == 4
    assert summary.follows == 1
    assert summary.followers == 1
    assert summary.posts == 1
    assert summary.interactions == 1
    assert summary.coverage.following_available is True
    assert summary.coverage.replies_available is True
    assert summary.coverage.likes_received_available is False


def test_archive_import_is_idempotent(database: Database, tmp_path: Path) -> None:
    archive = {
        "following": [{"id": "u2", "username": "BETA"}],
        "followers": [{"id": "u3", "username": "GAMMA"}],
    }
    path = tmp_path / "archive.json"
    path.write_text(json.dumps(archive), encoding="utf-8")

    service = XArchiveImportService(database=database)
    first = service.import_archive(path)
    second = service.import_archive(path)

    assert first.accounts == second.accounts
    assert first.follows == second.follows
    assert database.execute("SELECT COUNT(*) FROM audience_accounts").fetchone()[0] == 3
    assert database.execute("SELECT COUNT(*) FROM audience_relationships").fetchone()[0] == 2


def test_missing_archive_categories_are_handled_gracefully(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    service = XArchiveImportService(database=Database(tmp_path / "empty.db"))

    coverage = service.import_archive(path).coverage

    assert coverage.following_available is False
    assert coverage.followers_available is False
    assert coverage.replies_available is False
    assert coverage.likes_received_available is False
    assert coverage.completeness == 0.0


def test_account_deduplication_uses_stable_identity() -> None:
    service = XArchiveImportService(database=Database(Path("tmp-audience.db")))
    first = service._normalize_account({"id": "u1", "username": "BETA", "name": "Beta"}, "X_ARCHIVE")
    second = service._normalize_account({"id": "u1", "username": "BETA", "name": "Beta"}, "X_ARCHIVE")

    assert first.account_id == second.account_id
    assert first.username == second.username


def test_relationship_metrics_and_mutual_follow_are_calculated() -> None:
    account = AudienceRelationship(
        account_id="u2",
        username="BETA",
        user_follows=True,
        account_follows_user=False,
        mutual_follow=False,
        first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        source="MOCK",
        source_confidence=0.9,
    )
    metrics = RelationshipMetrics.from_account(account, inbound=5, outbound=20, last_inbound=datetime(2026, 5, 1, tzinfo=timezone.utc), last_outbound=datetime(2026, 6, 20, tzinfo=timezone.utc), coverage=AudienceDataCoverage())

    assert metrics.user_follows_account is True
    assert metrics.account_follows_user is False
    assert metrics.mutual_follow is False
    assert metrics.inbound_interactions == 5
    assert metrics.outbound_interactions == 20
    assert metrics.total_interactions == 25
    assert metrics.reciprocity_ratio == pytest.approx(0.25)


def test_reciprocity_score_handles_unknown_coverage() -> None:
    coverage = AudienceDataCoverage(
        following_available=True,
        followers_available=True,
        replies_available=False,
        mentions_available=False,
        likes_received_available=False,
        reposts_available=False,
        observation_window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        observation_window_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
        completeness=0.4,
    )
    metrics = RelationshipMetrics.from_account(
        AudienceRelationship(account_id="u2", username="BETA", user_follows=True, account_follows_user=False, mutual_follow=False, first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc), last_seen_at=datetime(2026, 6, 30, tzinfo=timezone.utc), source="MOCK", source_confidence=0.7),
        inbound=0,
        outbound=20,
        last_inbound=None,
        last_outbound=datetime(2026, 6, 20, tzinfo=timezone.utc),
        coverage=coverage,
    )

    score = compute_reciprocity(metrics, coverage, weights={"inbound": 0.4, "outbound": 0.3, "mutual": 0.2, "recency": 0.1})

    assert score.score < 30
    assert score.confidence == "LOW"
    assert score.unknown is True


def test_relationship_value_score_is_separate_from_reciprocity() -> None:
    metrics = RelationshipMetrics.from_account(
        AudienceRelationship(account_id="u2", username="BETA", user_follows=True, account_follows_user=False, mutual_follow=False, first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc), last_seen_at=datetime(2026, 6, 30, tzinfo=timezone.utc), source="MOCK", source_confidence=0.9),
        inbound=0,
        outbound=20,
        last_inbound=None,
        last_outbound=datetime(2026, 6, 20, tzinfo=timezone.utc),
        coverage=AudienceDataCoverage(completeness=1.0),
    )
    score = compute_relationship_value(metrics, coverage=AudienceDataCoverage(completeness=1.0), weights={"reply": 0.35, "mutual": 0.25, "recent": 0.25, "frequency": 0.15})

    assert isinstance(score, RelationshipValueScore)
    assert score.score < 100
    assert score.score >= 0
    assert score.unknown is False


def test_time_decay_is_configurable_and_preserves_history() -> None:
    now = datetime(2026, 6, 30, tzinfo=timezone.utc)
    age = now - datetime(2026, 5, 1, tzinfo=timezone.utc)
    result = ReciprocityScore.from_decay(age.days, 10.0, 0.6, 0.3)

    assert result > 0
    assert result < 10.0


def test_observation_window_limits_scores() -> None:
    now = datetime(2026, 6, 30, tzinfo=timezone.utc)
    coverage = AudienceDataCoverage(observation_window_start=now - timedelta(days=90), observation_window_end=now)
    assert coverage.window_days == 90


def test_relationship_classification_respects_coverage() -> None:
    coverage = AudienceDataCoverage(replies_available=True, mentions_available=True, completeness=0.8)
    relationship = AudienceRelationship(account_id="u2", username="BETA", user_follows=True, account_follows_user=False, mutual_follow=False, first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc), last_seen_at=datetime(2026, 6, 30, tzinfo=timezone.utc), source="MOCK", source_confidence=0.9)
    metrics = RelationshipMetrics.from_account(relationship, inbound=0, outbound=20, last_inbound=None, last_outbound=datetime(2026, 6, 20, tzinfo=timezone.utc), coverage=coverage)

    assert classify_relationship(metrics, coverage) == "ONE_SIDED_OUTBOUND"


def test_unfollow_candidate_score_is_not_driven_by_follow_back_alone() -> None:
    metrics = RelationshipMetrics.from_account(
        AudienceRelationship(account_id="u2", username="BETA", user_follows=True, account_follows_user=False, mutual_follow=False, first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc), last_seen_at=datetime(2026, 6, 30, tzinfo=timezone.utc), source="MOCK", source_confidence=0.9),
        inbound=0,
        outbound=20,
        last_inbound=None,
        last_outbound=datetime(2026, 6, 20, tzinfo=timezone.utc),
        coverage=AudienceDataCoverage(completeness=1.0),
    )
    score = score_unfollow_candidate(metrics, coverage=AudienceDataCoverage(completeness=1.0))

    assert score.score > 50
    assert score.reason_codes
    assert score.relationship_class == "ONE_SIDED_OUTBOUND"


def test_high_value_connection_is_prioritized_by_replies_and_mutual_follow() -> None:
    relationship = AudienceRelationship(account_id="u1", username="ALPHA", user_follows=True, account_follows_user=True, mutual_follow=True, first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc), last_seen_at=datetime(2026, 6, 30, tzinfo=timezone.utc), source="MOCK", source_confidence=0.9)
    metrics = RelationshipMetrics.from_account(relationship, inbound=14, outbound=8, last_inbound=datetime(2026, 6, 20, tzinfo=timezone.utc), last_outbound=datetime(2026, 6, 25, tzinfo=timezone.utc), coverage=AudienceDataCoverage(completeness=1.0))
    score = compute_relationship_value(metrics, coverage=AudienceDataCoverage(completeness=1.0))

    assert score.score > 70
    assert score.unknown is False


def test_never_interact_query_requires_coverage() -> None:
    relationship = AudienceRelationship(account_id="u2", username="BETA", user_follows=True, account_follows_user=False, mutual_follow=False, first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc), last_seen_at=datetime(2026, 6, 30, tzinfo=timezone.utc), source="MOCK", source_confidence=0.9)
    metrics = RelationshipMetrics.from_account(relationship, inbound=0, outbound=20, last_inbound=None, last_outbound=datetime(2026, 6, 20, tzinfo=timezone.utc), coverage=AudienceDataCoverage(completeness=1.0))
    coverage = AudienceDataCoverage(replies_available=True, mentions_available=True, likes_received_available=False, completeness=0.5)

    classification = classify_relationship(metrics, coverage)
    assert classification == "ONE_SIDED_OUTBOUND"
    assert coverage.requires_confidence is True


def test_mock_dataset_ranks_beta_above_gamma_and_delta() -> None:
    provider = MockXAudienceDataProvider()
    relationships = provider.get_relationships()

    ranked = sorted(relationships, key=lambda item: item["unfollow_score"], reverse=True)
    assert [item["username"] for item in ranked[:3]] == ["BETA", "GAMMA", "DELTA"]
    assert "ALPHA" not in {item["username"] for item in ranked[:3]}
    assert "EPSILON" not in {item["username"] for item in ranked[:3]}


def test_import_failure_is_isolated_from_database() -> None:
    db = Database(Path("tmp-audience-failure.db"))
    service = XArchiveImportService(database=db)
    with pytest.raises(ValueError):
        service.import_archive(Path("missing-archive.json"))

    assert db.execute("SELECT COUNT(*) FROM audience_accounts").fetchone()[0] == 0


def test_provider_interface_is_implemented() -> None:
    assert isinstance(MockXAudienceDataProvider(), XAudienceDataProvider)


def test_interaction_normalization_uses_supported_types() -> None:
    interaction = Interaction(
        interaction_id="i1",
        actor_account_id="u1",
        target_account_id="u2",
        interaction_type=InteractionType.REPLY,
        timestamp=datetime(2026, 6, 1, tzinfo=timezone.utc),
        post_id="p1",
        source="X_ARCHIVE",
        confidence=0.9,
    )

    assert interaction.interaction_type == InteractionType.REPLY
    assert interaction.confidence == 0.9


def test_database_persists_audience_tables(database: Database) -> None:
    ensure_schema(database)

    tables = database.list_tables()
    assert {
        "audience_accounts",
        "audience_relationships",
        "audience_interactions",
        "audience_import_runs",
        "audience_data_coverage",
        "audience_reciprocity_scores",
        "audience_relationship_value_scores",
        "audience_unfollow_candidates",
        "audience_high_value_connections",
    }.issubset(tables)


def test_account_detail_contains_recommendation_and_coverage() -> None:
    provider = MockXAudienceDataProvider()
    account = provider.get_account_detail("BETA")

    assert account.username == "BETA"
    assert account.relationship_class == "ONE_SIDED_OUTBOUND"
    assert account.data_coverage.replies_available is True
    assert account.unfollow_candidate.score > 50
