from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.review import (
    ReviewAction,
    ReviewDecision,
    ReviewFeedback,
    ReviewQueue,
    ReviewService,
)


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "exitvector-review.db")
    ensure_schema(db)
    return db


@pytest.fixture
def service(database: Database) -> ReviewService:
    return ReviewService(database)


@pytest.fixture
def candidate(database: Database) -> dict:
    candidate_id = database.insert_content_candidate(
        opportunity_id=1,
        symbol="MSFT",
        opportunity_score=85.0,
        primary_angle="PSC_RANK_JUMP",
        secondary_angles='["MOMENTUM"]',
        content_format="BREAKING_SIGNAL",
        hook="Hook",
        body="Body",
        call_to_action="Act",
        full_text="MSFT is rising.",
        confidence="MEDIUM",
        estimated_engagement_score=80,
        tone="natural",
        facts_used='["Strong social momentum"]',
        facts_omitted='[]',
        generated_at=datetime.now(timezone.utc).isoformat(),
        factuality_warnings='[]',
        missing_context='["Unverified price target"]',
        visual_recommendation="chart",
        review_status="PENDING",
        requires_human_review=1,
        content_hash="hash-1",
    )
    return database.execute("SELECT * FROM content_candidates WHERE id = ?", (candidate_id,)).fetchone()


def test_review_queue_orders_priority_and_ready_state(service: ReviewService, candidate: dict) -> None:
    ready = service.queue.ready_candidates(limit=10)

    assert ready[0]["id"] == candidate["id"]
    assert ready[0]["ready_to_post"] is True


def test_review_service_approves_candidate_and_records_audit(service: ReviewService, candidate: dict) -> None:
    approved = service.approve_candidate(candidate["id"], reviewer="analyst", notes="Looks aligned")

    assert approved.review_status == "APPROVED"
    assert approved.requires_human_review is False
    assert approved.ready_to_post is True
    assert approved.audit_entries[-1]["action"] == "APPROVE"


def test_review_service_rejects_candidate_with_reason(service: ReviewService, candidate: dict) -> None:
    rejected = service.reject_candidate(candidate["id"], reason="Unsupported claim", reviewer="analyst")

    assert rejected.review_status == "REJECTED"
    assert rejected.ready_to_post is False
    assert rejected.audit_entries[-1]["reason"] == "Unsupported claim"


def test_review_service_edit_preserves_validation_and_updates_text(service: ReviewService, candidate: dict) -> None:
    edited = service.edit_candidate(
        candidate["id"],
        reviewer="analyst",
        updates={
            "full_text": "MSFT is rising with strong social momentum.",
            "body": "Body revised",
            "call_to_action": "Consider the evidence",
        },
    )

    assert edited.full_text == "MSFT is rising with strong social momentum."
    assert edited.body == "Body revised"
    assert edited.active_review_state == "EDITED"
    assert edited.audit_entries[-1]["action"] == "EDIT"
    assert edited.final_machine_validation == 1


def test_review_service_marks_expired_candidate_stale(service: ReviewService, candidate: dict) -> None:
    database = service.database
    database.execute(
        "UPDATE content_candidates SET generated_at = ?, review_status = 'PENDING' WHERE id = ?",
        ((datetime.now(timezone.utc) - timedelta(days=8)).isoformat(), candidate["id"]),
    )
    database.commit()

    stale = service.queue.review_candidates(limit=10)
    assert stale[0]["stale"] == 1


def test_review_service_supersedes_previous_candidate(service: ReviewService, candidate: dict) -> None:
    candidate_id = service.create_candidate_snapshot(candidate["id"], "manual")
    superseded = service.supersede_candidate(candidate["id"], superseded_by=candidate_id, reviewer="analyst")

    assert superseded.review_status == "SUPERSEDED"
    assert superseded.ready_to_post is False
    assert superseded.superseded_by == candidate_id
    assert superseded.audit_entries[-1]["action"] == "SUPERSEDE"


def test_review_service_can_export_approved_candidate(service: ReviewService, candidate: dict) -> None:
    service.approve_candidate(candidate["id"], reviewer="analyst")
    exported = service.export_candidate(candidate["id"], format="json")

    assert exported["status"] == "APPROVED"
    assert exported["content"]["full_text"] == candidate["full_text"]


def test_review_queue_notifies_only_human_review_candidates(service: ReviewService, candidate: dict) -> None:
    candidate_row = service.database.get_row("content_candidates", candidate["id"])
    service.notify_candidate(candidate_row["id"], "email")

    assert service.database.execute(
        "SELECT COUNT(*) FROM notifications WHERE ticker = ? AND channel = ?",
        (candidate_row["ticker"], "email"),
    ).fetchone()[0] == 1


def test_review_service_rejects_duplicate_notifications(service: ReviewService, candidate: dict) -> None:
    candidate_row = service.database.get_row("content_candidates", candidate["id"])
    first = service.notify_candidate(candidate_row["id"], "email")
    second = service.notify_candidate(candidate_row["id"], "email")

    assert first.notification_id == second.notification_id
    assert first.notification_id is not None


def test_review_decision_is_structured_and_machine_readable() -> None:
    decision = ReviewDecision(
        status="APPROVED",
        reason="Approved for publishing",
        reviewer="analyst",
        ready_to_post=True,
    )

    assert decision.status == "APPROVED"
    assert decision.ready_to_post is True


def test_review_feedback_is_structured_and_machine_readable() -> None:
    feedback = ReviewFeedback(
        action=ReviewAction.EDIT,
        reviewer="analyst",
        notes="Refine headline",
    )

    assert feedback.action == ReviewAction.EDIT
    assert feedback.notes == "Refine headline"
