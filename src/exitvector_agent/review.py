"""Human review lifecycle for ExitVector content candidates."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Sequence, Protocol

from exitvector_agent.database import Database


class ReviewAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    EDIT = "EDIT"
    ARCHIVE = "ARCHIVE"
    SUPERSEDE = "SUPERSEDE"
    EXPORT = "EXPORT"
    NOTIFY = "NOTIFY"


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    status: str
    reason: str = ""
    reviewer: str = "system"
    ready_to_post: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class ReviewFeedback:
    action: ReviewAction
    reviewer: str = "system"
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReviewCandidate:
    id: int
    opportunity_id: int | None
    ticker: str
    primary_angle: str
    full_text: str
    hook: str
    body: str
    call_to_action: str
    review_status: str
    requires_human_review: bool
    ready_to_post: bool
    final_machine_validation: bool
    active_review_state: str
    stale: bool
    superseded_by: int | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    audit_entries: list[dict[str, Any]]

    @classmethod
    def from_row(cls, row: Any, audit_entries: Sequence[dict[str, Any]] | None = None) -> "ReviewCandidate":
        audit = list(audit_entries or [])
        return cls(
            id=int(row["id"]),
            opportunity_id=row["opportunity_id"],
            ticker=row["ticker"],
            primary_angle=row["primary_angle"],
            full_text=row["full_text"],
            hook=row["hook"],
            body=row["body"],
            call_to_action=row["call_to_action"],
            review_status=row["review_status"],
            requires_human_review=_as_bool(row["requires_human_review"]),
            ready_to_post=_as_bool(row["ready_to_post"]) if "ready_to_post" in row.keys() else row["review_status"] in {"APPROVED", "EDITED", "PENDING"},
            final_machine_validation=_as_bool(row["final_machine_validation"]),
            active_review_state=row["active_review_state"],
            stale=_as_bool(row["stale"]),
            superseded_by=row["superseded_by"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=_parse_datetime(row["reviewed_at"]),
            audit_entries=audit,
        )


def _as_bool(value: Any) -> bool:
    return bool(int(value)) if value is not None else False


def _coerce_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, str, bool)):
        return bool(value) if value in {0, 1} else value
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value)).astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class NotificationDecision:
    notification_id: int | None
    channel: str
    candidate_id: int
    status: str


class ReviewQueue:
    """Query and rank content candidates for human review."""

    def __init__(self, database: Database, *, stale_after_days: int = 7) -> None:
        self.database = database
        self.stale_after_days = stale_after_days

    def review_candidates(self, *, limit: int = 20) -> list[sqlite3.Row]:
        return self.database.execute(
            """
            SELECT c.*,
                   CASE WHEN c.review_status IN ('APPROVED', 'PENDING', 'EDITED') THEN 1 ELSE 0 END AS ready_to_post,
                   CASE WHEN c.generated_at < ? THEN 1 ELSE 0 END AS stale
            FROM content_candidates c
            WHERE c.review_status NOT IN ('REJECTED', 'SUPERSEDED')
            ORDER BY c.review_status = 'PENDING' DESC,
                     c.review_status = 'EDITED' DESC,
                     c.review_status = 'APPROVED' DESC,
                     c.generated_at DESC
            LIMIT ?
            """,
            (self._stale_cutoff().isoformat(), limit),
        ).fetchall()

    def ready_candidates(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.database.execute(
            """
            SELECT c.*,
                   CASE WHEN c.review_status IN ('APPROVED', 'PENDING', 'EDITED') THEN 1 ELSE 0 END AS review_ready_to_post,
                   CASE WHEN c.generated_at < ? THEN 1 ELSE 0 END AS review_stale
            FROM content_candidates c
            WHERE c.review_status IN ('APPROVED', 'PENDING', 'EDITED')
              AND c.review_status != 'SUPERSEDED'
            ORDER BY c.reviewed_at DESC, c.id DESC
            LIMIT ?
            """,
            (self._stale_cutoff().isoformat(), limit),
        ).fetchall()
        return [
            {
                **{key: _coerce_value(row[key]) for key in row.keys() if key not in {"review_ready_to_post", "review_stale"}},
                "ready_to_post": _as_bool(row["review_ready_to_post"]),
                "stale": _as_bool(row["review_stale"]),
            }
            for row in rows
        ]

    def _stale_cutoff(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=self.stale_after_days)


class ReviewService:
    """Apply deterministic human review actions to persisted content candidates."""

    def __init__(self, database: Database, *, queue: ReviewQueue | None = None) -> None:
        self.database = database
        self.queue = queue or ReviewQueue(database)

    def approve_candidate(self, candidate_id: int, *, reviewer: str, notes: str = "") -> ReviewCandidate:
        return self._update_candidate(
            candidate_id,
            review_status="APPROVED",
            requires_human_review=0,
            ready_to_post=1,
            active_review_state="APPROVED",
            reviewer=reviewer,
            reason="Approved",
            notes=notes,
            action=ReviewAction.APPROVE,
        )

    def reject_candidate(self, candidate_id: int, *, reason: str, reviewer: str, notes: str = "") -> ReviewCandidate:
        return self._update_candidate(
            candidate_id,
            review_status="REJECTED",
            requires_human_review=0,
            ready_to_post=0,
            active_review_state="REJECTED",
            reviewer=reviewer,
            reason=reason,
            notes=notes,
            action=ReviewAction.REJECT,
        )

    def edit_candidate(
        self,
        candidate_id: int,
        *,
        reviewer: str,
        updates: dict[str, str],
        notes: str = "",
    ) -> ReviewCandidate:
        row = self._require_candidate(candidate_id)
        values: list[Any] = []
        assignments: list[str] = []
        for field_name, value in updates.items():
            if field_name not in {"hook", "body", "call_to_action", "full_text", "visual_recommendation"}:
                continue
            assignments.append(f"{field_name} = ?")
            values.append(value)
        if not assignments:
            raise ValueError("No editable fields supplied")
        values.extend([reviewer, datetime.now(timezone.utc).isoformat(), candidate_id])
        self.database.execute(
            f"UPDATE content_candidates SET {', '.join(assignments)}, review_status = 'EDITED', "
            "active_review_state = 'EDITED', requires_human_review = 1, ready_to_post = 1, "
            "reviewed_by = ?, reviewed_at = ?, final_machine_validation = 1 WHERE id = ?",
            tuple(values),
        )
        self.database.commit()
        return self._append_audit(
            candidate_id,
            action=ReviewAction.EDIT,
            reviewer=reviewer,
            reason="Edited",
            notes=notes,
            metadata={"updated_fields": list(updates)},
        )

    def archive_candidate(self, candidate_id: int, *, reviewer: str, notes: str = "") -> ReviewCandidate:
        return self._update_candidate(
            candidate_id,
            review_status="ARCHIVED",
            requires_human_review=0,
            ready_to_post=0,
            active_review_state="ARCHIVED",
            reviewer=reviewer,
            reason="Archived",
            notes=notes,
            action=ReviewAction.ARCHIVE,
        )

    def supersede_candidate(self, candidate_id: int, *, superseded_by: int, reviewer: str, reason: str = "Superseded") -> ReviewCandidate:
        return self._update_candidate(
            candidate_id,
            review_status="SUPERSEDED",
            requires_human_review=0,
            ready_to_post=0,
            active_review_state="SUPERSEDED",
            reviewer=reviewer,
            reason=reason,
            notes="",
            action=ReviewAction.SUPERSEDE,
            metadata={"superseded_by": superseded_by},
        )

    def create_candidate_snapshot(self, candidate_id: int, reviewer: str, notes: str = "") -> int:
        row = self._require_candidate(candidate_id)
        snapshot = {key: row[key] for key in row.keys()}
        cursor = self.database.execute(
            """
            INSERT INTO review_snapshots(candidate_id, reviewer, notes, snapshot)
            VALUES(?, ?, ?, ?)
            """,
            (candidate_id, reviewer, notes, json.dumps(snapshot, default=str)),
        )
        self.database.commit()
        return int(cursor.lastrowid)

    def export_candidate(self, candidate_id: int, *, format: str = "json") -> dict[str, Any]:
        row = self._require_candidate(candidate_id)
        payload = {
            "id": row["id"],
            "ticker": row["ticker"],
            "status": row["review_status"],
            "content": {
                "hook": row["hook"],
                "body": row["body"],
                "call_to_action": row["call_to_action"],
                "full_text": row["full_text"],
                "format": row["format"],
            },
        }
        self.database.execute(
            "UPDATE content_candidates SET export_status = ?, export_format = ?, exported_at = ? WHERE id = ?",
            ("EXPORTED", format, datetime.now(timezone.utc).isoformat(), candidate_id),
        )
        self.database.commit()
        self._append_audit(candidate_id, action=ReviewAction.EXPORT, reviewer="system", reason="Exported", notes="", metadata={"format": format})
        return payload

    def notify_candidate(self, candidate_id: int, channel: str, *, event_key: str | None = None) -> NotificationDecision:
        row = self._require_candidate(candidate_id)
        existing = self.database.execute(
            "SELECT id FROM notifications WHERE candidate_id = ? AND channel = ? AND review_action = ?",
            (candidate_id, channel, "NOTIFY"),
        ).fetchone()
        if existing is None and event_key is not None:
            existing = self.database.execute("SELECT id FROM notifications WHERE deduplication_key=?", (event_key,)).fetchone()
        if existing is not None:
            notification_id = int(existing["id"])
            return NotificationDecision(notification_id, channel, candidate_id, "ALREADY_NOTIFIED")
        notification_id = self.database.execute(
            """
            INSERT INTO notifications(ticker, score, channel, payload, candidate_id, review_action, created_at, deduplication_key, opportunity_id)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["ticker"],
                float(row["opportunity_score"]),
                channel,
                json.dumps({"candidate_id": candidate_id, "status": row["review_status"]}),
                candidate_id,
                "NOTIFY",
                datetime.now(timezone.utc).isoformat(),
                event_key, row["opportunity_id"],
            ),
        ).lastrowid
        self.database.commit()
        self._append_audit(candidate_id, action=ReviewAction.NOTIFY, reviewer="system", reason="Notification queued", notes="", metadata={"channel": channel, "notification_id": notification_id})
        return NotificationDecision(int(notification_id), channel, candidate_id, "QUEUED")

    def _update_candidate(
        self,
        candidate_id: int,
        *,
        review_status: str,
        requires_human_review: int,
        ready_to_post: int,
        active_review_state: str,
        reviewer: str,
        reason: str,
        notes: str,
        action: ReviewAction,
        metadata: dict[str, Any] | None = None,
    ) -> ReviewCandidate:
        timestamp = datetime.now(timezone.utc).isoformat()
        self.database.execute(
            """
            UPDATE content_candidates
            SET review_status = ?,
                requires_human_review = ?,
                ready_to_post = ?,
                active_review_state = ?,
                reviewed_by = ?,
                reviewed_at = ?,
                final_machine_validation = 1,
                superseded_by = COALESCE(superseded_by, superseded_by)
            WHERE id = ?
            """,
            (review_status, requires_human_review, ready_to_post, active_review_state, reviewer, timestamp, candidate_id),
        )
        self.database.commit()
        if action == ReviewAction.SUPERSEDE:
            self.database.execute(
                "UPDATE content_candidates SET superseded_by = ? WHERE id = ?",
                (metadata.get("superseded_by"), candidate_id),
            )
            self.database.commit()
        return self._append_audit(
            candidate_id,
            action=action,
            reviewer=reviewer,
            reason=reason,
            notes=notes,
            metadata=metadata or {},
        )

    def _append_audit(
        self,
        candidate_id: int,
        *,
        action: ReviewAction,
        reviewer: str,
        reason: str,
        notes: str,
        metadata: dict[str, Any],
    ) -> ReviewCandidate:
        row = self._require_candidate(candidate_id)
        audit = {
            "candidate_id": candidate_id,
            "action": action.value,
            "reviewer": reviewer,
            "reason": reason,
            "notes": notes,
            "metadata": metadata,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.database.execute(
            """
            INSERT INTO review_audit(candidate_id, action, reviewer, reason, notes, metadata, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                action.value,
                reviewer,
                reason,
                notes,
                json.dumps(metadata, default=str),
                audit["timestamp"],
            ),
        )
        self.database.commit()
        existing = self.database.execute(
            "SELECT * FROM review_audit WHERE candidate_id = ? ORDER BY created_at DESC",
            (candidate_id,),
        ).fetchall()
        return ReviewCandidate.from_row(row, [dict(record) for record in existing])

    def _require_candidate(self, candidate_id: int) -> sqlite3.Row:
        row = self.database.execute(
            """
            SELECT c.*,
                   CASE WHEN c.generated_at < ? THEN 1 ELSE 0 END AS stale,
                   c.ready_to_post,
                   c.active_review_state
            FROM content_candidates c
            WHERE id = ?
            """,
            (self.queue._stale_cutoff().isoformat(), candidate_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"Candidate {candidate_id} does not exist")
        return row


class ReviewNotifier(Protocol):
    def send(self, items: list[dict[str, Any]]) -> None: ...


class ConsoleReviewNotifier:
    def __init__(self, *, quiet: bool = False) -> None:
        self.quiet = quiet

    def send(self, items: list[dict[str, Any]]) -> None:
        if not self.quiet:
            print(f"{len(items)} new ExitVector review item(s): " + ", ".join(f"{i['ticker']} ({i['score']:.1f})" for i in items))


class MockReviewNotifier:
    def __init__(self) -> None:
        self.batches: list[list[dict[str, Any]]] = []

    def send(self, items: list[dict[str, Any]]) -> None:
        self.batches.append(items)


class ReviewHandoffService:
    """Operational views require actual machine validation; ready requires approval."""
    def __init__(self, database: Database) -> None:
        self.database = database
        self.review = ReviewService(database)

    def pending(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.database.execute("""
            SELECT * FROM content_candidates WHERE review_status IN ('PENDING','EDITED')
            AND requires_human_review=1 AND final_machine_validation=1
            ORDER BY opportunity_score DESC, estimated_engagement_score DESC, id
        """)]

    def ready(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.database.execute("""
            SELECT * FROM content_candidates WHERE review_status='APPROVED' AND ready_to_post=1
            AND requires_human_review=0 AND final_machine_validation=1 AND reviewed_by IS NOT NULL
            ORDER BY opportunity_score DESC, id
        """)]

    def recommended(self) -> list[dict[str, Any]]:
        result, seen = [], set()
        for row in self.pending():
            key = row['opportunity_id'] or (row['ticker'], row['primary_angle'])
            if key not in seen:
                result.append(row); seen.add(key)
        return result

    def notify(self, notifier: ReviewNotifier, *, threshold: float) -> int:
        items, notification_ids = [], []
        for row in self.recommended():
            if row['opportunity_score'] < threshold:
                continue
            key = f"review:{row['opportunity_id']}" if row['opportunity_id'] else f"review:candidate:{row['id']}"
            decision = self.review.notify_candidate(row['id'], 'local', event_key=key)
            notification = self.database.get_row('notifications', decision.notification_id)
            if notification['delivered_at']:
                continue
            notification_ids.append(decision.notification_id)
            items.append({'candidate_id': row['id'], 'opportunity_id': row['opportunity_id'],
                          'ticker': row['ticker'], 'score': row['opportunity_score'],
                          'message': f"{row['ticker']} - {row['opportunity_score']:.1f}; {row['variant_type']} candidate requires human review."})
        if not items:
            return 0
        notifier.send(items)  # Only local console/mock implementations are constructed.
        now = datetime.now(timezone.utc).isoformat()
        for identity, item in zip(notification_ids, items):
            self.database.execute('UPDATE notifications SET delivered_at=?,payload=? WHERE id=?',
                                  (now, json.dumps(item), identity))
        self.database.commit()
        return 1  # One batch, not one alert per variant.
