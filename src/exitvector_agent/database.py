"""SQLite persistence for ExitVector Agent."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any


class Database:
    """Thin SQLite wrapper with application-specific helpers."""

    def __init__(self, database_path: str | Path, *, read_only: bool = False) -> None:
        self.database_path = Path(database_path)
        if read_only:
            self._connection = sqlite3.connect(self.database_path.resolve().as_uri() + "?mode=ro", uri=True)
        else:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def execute(self, query: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self._connection.execute(query, parameters)

    def commit(self) -> None:
        self._connection.commit()

    def backup_to(self, target: str | Path) -> Path:
        """Use SQLite's online backup API; reserve the destination without overwriting."""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb"):
            pass
        try:
            with closing(sqlite3.connect(target)) as destination:
                self._connection.backup(destination)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target

    def list_tables(self) -> set[str]:
        rows = self.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name;"
        ).fetchall()
        return {row["name"] for row in rows}

    def set_config(self, key: str, value: str) -> None:
        self.execute(
            """
            INSERT INTO configuration(key, value)
            VALUES(?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        self.commit()

    def get_config(self, key: str) -> str | None:
        row = self.execute(
            "SELECT value FROM configuration WHERE key = ?",
            (key,),
        ).fetchone()
        return None if row is None else row["value"]

    def get_row(self, table: str, row_id: int) -> sqlite3.Row | None:
        return self.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()

    def insert_observation(
        self,
        *,
        source: str,
        external_id: str,
        timestamp: str,
        text: str,
        author: str,
        url: str,
        tickers: str,
        likes: int = 0,
        replies: int = 0,
        reposts: int = 0,
        views: int = 0,
        raw_metadata: str = "{}",
    ) -> int:
        cursor = self.execute(
            """
            INSERT OR IGNORE INTO social_observations(
                source, external_id, observed_at, raw_text, author, url,
                ticker, likes, replies, reposts, views, metadata
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source,
                external_id,
                timestamp,
                text,
                author,
                url,
                tickers,
                likes,
                replies,
                reposts,
                views,
                raw_metadata,
            ),
        )
        self.commit()
        row = self.execute(
            "SELECT id FROM social_observations WHERE source = ? AND external_id = ?",
            (source, external_id),
        ).fetchone()
        return int(row["id"])

    def insert_ticker_mention(
        self,
        *,
        ticker: str,
        source: str,
        observation_id: int,
        engagement_score: float,
    ) -> None:
        self.execute(
            """
            INSERT OR IGNORE INTO ticker_mentions(
                ticker, source, observation_id, engagement_score
            ) VALUES(?, ?, ?, ?)
            """,
            (ticker, source, observation_id, engagement_score),
        )
        self.commit()

    def insert_trend_snapshot(
        self,
        *,
        ticker: str,
        score: float,
        velocity_ratio: float,
        acceleration: float,
        baseline_mentions: int,
        current_mentions: int,
        unique_authors: int,
        confirming_sources: int,
    ) -> None:
        self.execute(
            """
            INSERT OR IGNORE INTO trend_score_snapshots(
                ticker, score, velocity_ratio, acceleration,
                baseline_mentions, current_mentions, unique_authors, confirming_sources
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                score,
                velocity_ratio,
                acceleration,
                baseline_mentions,
                current_mentions,
                unique_authors,
                confirming_sources,
            ),
        )
        self.commit()

    def get_recent_trend_snapshots(self, *, limit: int = 20) -> list[sqlite3.Row]:
        rows = self.execute(
            """
            SELECT *
            FROM trend_score_snapshots
            ORDER BY created_at DESC, score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return list(rows)

    def get_social_summary(self) -> list[sqlite3.Row]:
        rows = self.execute(
            """
            SELECT source,
                   COUNT(*) AS observation_count,
                   COUNT(DISTINCT author) AS unique_authors
            FROM social_observations
            GROUP BY source
            ORDER BY observation_count DESC
            """
        ).fetchall()
        return list(rows)

    def insert_regivion_snapshot(self, *, ticker: str, payload: dict[str, Any]) -> None:
        self.execute(
            """
            INSERT OR REPLACE INTO regivion_enrichment_snapshots(
                ticker, payload, created_at
            ) VALUES(?, ?, CURRENT_TIMESTAMP)
            """,
            (ticker.upper(), str(json.dumps(payload, ensure_ascii=False)),),
        )
        self.commit()

    def get_regivion_snapshot(self, ticker: str) -> sqlite3.Row | None:
        row = self.execute(
            "SELECT ticker, payload, created_at FROM regivion_enrichment_snapshots WHERE ticker = ? ORDER BY created_at DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()
        return row

    def insert_opportunity(
        self,
        *,
        ticker: str,
        total_score: float,
        confidence: str,
        social_trend_score: float,
        regivion_score: float,
        market_score: float | None,
        freshness_score: float,
        novelty_score: float,
        engagement_potential_score: float,
        trigger_reasons: str,
        social_summary: str,
        regivion_summary: str,
        strongest_fact: str,
        supporting_facts: str,
        urgency: str,
        suggested_content_angle: str,
        suggested_visual_type: str,
        content_angles: str,
        notification_eligible: int = 1,
        detected_at: str | None = None,
        re_notification_reason: str | None = None,
    ) -> int:
        cursor = self.execute(
            """
            INSERT INTO opportunities(
                ticker, score, confidence, social_trend_score, regivion_score, market_score,
                freshness_score, novelty_score, engagement_potential_score, trigger_reasons,
                social_summary, regivion_summary, strongest_fact, supporting_facts, urgency,
                suggested_content_angle, suggested_visual_type, content_angles,
                notification_eligible, detected_at, re_notification_reason
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker.upper(),
                total_score,
                confidence,
                social_trend_score,
                regivion_score,
                market_score,
                freshness_score,
                novelty_score,
                engagement_potential_score,
                trigger_reasons,
                social_summary,
                regivion_summary,
                strongest_fact,
                supporting_facts,
                urgency,
                suggested_content_angle,
                suggested_visual_type,
                content_angles,
                notification_eligible,
                detected_at or __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                re_notification_reason,
            ),
        )
        self.commit()
        return int(cursor.lastrowid)

    def list_opportunities(self, *, limit: int = 20) -> list[sqlite3.Row]:
        return self.execute(
            """
            SELECT * FROM opportunities
            WHERE notification_eligible = 1
            ORDER BY score DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def get_recent_opportunity(self, ticker: str) -> sqlite3.Row | None:
        return self.execute(
            "SELECT * FROM opportunities WHERE ticker = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()

    @staticmethod
    def _event_signature(item: Any) -> tuple[Any, ...]:
        if isinstance(item, dict):
            return tuple((key, Database._event_signature(value)) for key, value in sorted(item.items()))
        if isinstance(item, list):
            return tuple(Database._event_signature(value) for value in item)
        if isinstance(item, set):
            return tuple(sorted(Database._event_signature(value) for value in item))
        return (item,)

    def evaluate_re_notification(
        self,
        ticker: str,
        *,
        score: float,
        threshold: float,
        delta: float,
        now: datetime,
        cooldown_minutes: int = 180,
        current_enrichment: dict[str, Any] | None = None,
        current_primary_angle: str | None = None,
        previous_enrichment: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        row = self.get_recent_opportunity(ticker)
        if row is None:
            return (score >= threshold, "SCORE_DELTA" if score >= threshold else None)

        previous_score = float(row["score"])
        if score < threshold:
            return (False, None)

        if previous_enrichment is None:
            previous_snapshot = self.get_regivion_snapshot(ticker)
            previous_enrichment = json.loads(previous_snapshot["payload"]) if previous_snapshot else {}
        previous_enrichment_payload = previous_enrichment or {}
        previous_angle = row["suggested_content_angle"]
        elapsed_minutes = (now - __import__("datetime").datetime.fromisoformat(row["detected_at"]).astimezone(__import__("datetime").timezone.utc)).total_seconds() / 60.0

        if score - previous_score >= delta:
            return (True, "SCORE_DELTA")

        current_payload = current_enrichment or {}
        previous_alerts = [str(alert.get("name") or "").lower() for alert in (previous_enrichment_payload.get("alerts") or []) if alert.get("name")]
        current_alerts = [str(alert.get("name") or "").lower() for alert in (current_payload.get("alerts") or []) if alert.get("name")]
        if current_alerts and any(alert not in previous_alerts for alert in current_alerts):
            return (True, "NEW_ALERT")

        previous_rank = previous_enrichment_payload.get("psc", {}).get("rank")
        current_rank = current_payload.get("psc", {}).get("rank")
        if previous_rank is not None and current_rank is not None:
            rank_gap = int(previous_rank) - int(current_rank)
            if rank_gap >= 5 and current_rank <= 20:
                return (True, "PSC_RANK_MILESTONE")

        previous_top20 = bool(previous_enrichment_payload.get("entered_top_20"))
        current_top20 = bool(current_payload.get("entered_top_20"))
        if not previous_top20 and current_top20:
            return (True, "NEW_TOP20_ENTRY")

        previous_insiders = previous_enrichment_payload.get("insiders") or []
        current_insiders = current_payload.get("insiders") or []
        if any(Database._event_signature(item) not in {Database._event_signature(previous) for previous in previous_insiders} for item in current_insiders):
            return (True, "NEW_INSIDER_TRANSACTION")

        previous_politicians = previous_enrichment_payload.get("politicians") or []
        current_politicians = current_payload.get("politicians") or []
        if any(Database._event_signature(item) not in {Database._event_signature(previous) for previous in previous_politicians} for item in current_politicians):
            return (True, "NEW_POLITICIAN_TRANSACTION")

        if previous_angle and current_primary_angle and previous_angle != current_primary_angle:
            return (True, "ANGLE_CHANGE")

        if elapsed_minutes >= cooldown_minutes:
            return (True, "COOLDOWN_EXPIRED")

        return (False, None)

    def is_opportunity_eligible(
        self,
        ticker: str,
        *,
        score: float,
        threshold: float,
        delta: float,
        now: datetime,
        cooldown_minutes: int = 180,
    ) -> bool:
        eligible, _ = self.evaluate_re_notification(
            ticker,
            score=score,
            threshold=threshold,
            delta=delta,
            now=now,
            cooldown_minutes=cooldown_minutes,
        )
        return eligible

    def set_opportunity_eligibility(self, ticker: str, eligible: bool) -> None:
        self.execute(
            "UPDATE opportunities SET notification_eligible = ? WHERE ticker = ? ORDER BY created_at DESC LIMIT 1",
            (1 if eligible else 0, ticker.upper()),
        )
        self.commit()

    def insert_content_candidate(
        self,
        *,
        opportunity_id: int | None,
        symbol: str,
        opportunity_score: float,
        primary_angle: str,
        secondary_angles: str,
        content_format: str,
        hook: str,
        body: str,
        call_to_action: str,
        full_text: str,
        confidence: str,
        estimated_engagement_score: int,
        tone: str,
        facts_used: str,
        facts_omitted: str,
        generated_at: str,
        factuality_warnings: str,
        missing_context: str,
        visual_recommendation: str,
        review_status: str,
        requires_human_review: int,
        content_hash: str,
        generator_type: str = "RULE_BASED",
        provider: str | None = None,
        model: str | None = None,
        prompt_version: str = "EXITVECTOR_CONTENT_PROMPT_V1",
        raw_output: str = "",
        original_raw_output: str = "",
        brief_snapshot: str = "{}",
        validation_result: str = "{}",
        original_validation_result: str = "{}",
        repaired_text: str = "",
        final_machine_validation: int = 0,
        repair_attempt_count: int = 0,
        variant_type: str = "STANDARD",
        deduplication_status: str = "UNIQUE",
    ) -> int:
        cursor = self.execute(
            """
            INSERT OR REPLACE INTO content_candidates(
                opportunity_id, ticker, opportunity_score, primary_angle, secondary_angles, format,
                hook, body, call_to_action, full_text, confidence,
                estimated_engagement_score, tone, facts_used, facts_omitted,
                generated_at, factuality_warnings, missing_context,
                visual_recommendation, review_status, requires_human_review,
                content_hash, generator_type, provider, model, prompt_version,
                raw_output, original_raw_output, brief_snapshot, validation_result,
                original_validation_result, repaired_text, final_machine_validation,
                repair_attempt_count, variant_type, deduplication_status
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opportunity_id,
                symbol.upper(),
                opportunity_score,
                primary_angle,
                secondary_angles,
                content_format,
                hook,
                body,
                call_to_action,
                full_text,
                confidence,
                estimated_engagement_score,
                tone,
                facts_used,
                facts_omitted,
                generated_at,
                factuality_warnings,
                missing_context,
                visual_recommendation,
                review_status,
                requires_human_review,
                content_hash,
                generator_type,
                provider,
                model,
                prompt_version,
                raw_output,
                original_raw_output,
                brief_snapshot,
                validation_result,
                original_validation_result,
                repaired_text,
                final_machine_validation,
                repair_attempt_count,
                variant_type,
                deduplication_status,
            ),
        )
        self.commit()
        return int(cursor.lastrowid)

    def get_recent_candidate(self, ticker: str) -> sqlite3.Row | None:
        return self.execute(
            "SELECT * FROM content_candidates WHERE ticker = ? ORDER BY generated_at DESC LIMIT 1",
            (ticker.upper(),),
        ).fetchone()

    def get_recent_content_by_hash(self, content_hash: str) -> sqlite3.Row | None:
        return self.execute(
            "SELECT * FROM content_candidates WHERE content_hash = ? ORDER BY generated_at DESC LIMIT 1",
            (content_hash,),
        ).fetchone()


def ensure_schema(database: Database) -> None:
    """Create the initial database schema."""

    tables = {row["name"] for row in database.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    if "opportunities" in tables:
        columns = {row["name"] for row in database.execute("PRAGMA table_info(opportunities)").fetchall()}
        if "re_notification_reason" not in columns:
            database.execute("ALTER TABLE opportunities ADD COLUMN re_notification_reason TEXT")
            database.commit()

    database.execute(
        """
        CREATE TABLE IF NOT EXISTS configuration (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS social_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            ticker TEXT NOT NULL DEFAULT '',
            likes INTEGER NOT NULL DEFAULT 0,
            replies INTEGER NOT NULL DEFAULT 0,
            reposts INTEGER NOT NULL DEFAULT 0,
            views INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source, external_id)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS ticker_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            source TEXT NOT NULL,
            observation_id INTEGER NOT NULL,
            engagement_score REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(observation_id) REFERENCES social_observations(id),
            UNIQUE(ticker, source, observation_id, engagement_score)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS ticker_velocity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            window_minutes INTEGER NOT NULL,
            mentions INTEGER NOT NULL,
            velocity REAL NOT NULL,
            observed_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, window_minutes, observed_at)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS trend_score_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            score REAL NOT NULL,
            velocity_ratio REAL NOT NULL,
            acceleration REAL NOT NULL,
            baseline_mentions INTEGER NOT NULL,
            current_mentions INTEGER NOT NULL,
            unique_authors INTEGER NOT NULL,
            confirming_sources INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, score, velocity_ratio, acceleration, baseline_mentions, current_mentions, unique_authors, confirming_sources)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            score REAL NOT NULL,
            confidence TEXT NOT NULL DEFAULT 'LOW',
            social_trend_score REAL NOT NULL DEFAULT 0,
            regivion_score REAL NOT NULL DEFAULT 0,
            market_score REAL,
            freshness_score REAL NOT NULL DEFAULT 0,
            novelty_score REAL NOT NULL DEFAULT 0,
            engagement_potential_score REAL NOT NULL DEFAULT 0,
            trigger_reasons TEXT NOT NULL DEFAULT '[]',
            social_summary TEXT NOT NULL DEFAULT '',
            regivion_summary TEXT NOT NULL DEFAULT '',
            strongest_fact TEXT NOT NULL DEFAULT '',
            supporting_facts TEXT NOT NULL DEFAULT '[]',
            urgency TEXT NOT NULL DEFAULT 'low',
            suggested_content_angle TEXT NOT NULL DEFAULT '',
            suggested_visual_type TEXT NOT NULL DEFAULT '',
            content_angles TEXT NOT NULL DEFAULT '[]',
            notification_eligible INTEGER NOT NULL DEFAULT 1,
            detected_at TEXT NOT NULL,
            re_notification_reason TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'new'
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS regivion_enrichment_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, created_at)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS generated_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            payload TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'draft'
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS content_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opportunity_id INTEGER,
            ticker TEXT NOT NULL,
            opportunity_score REAL NOT NULL DEFAULT 0,
            primary_angle TEXT NOT NULL,
            secondary_angles TEXT NOT NULL DEFAULT '[]',
            format TEXT NOT NULL,
            hook TEXT NOT NULL,
            body TEXT NOT NULL,
            call_to_action TEXT NOT NULL,
            full_text TEXT NOT NULL,
            confidence TEXT NOT NULL,
            estimated_engagement_score INTEGER NOT NULL DEFAULT 0,
            tone TEXT NOT NULL DEFAULT 'natural',
            facts_used TEXT NOT NULL DEFAULT '[]',
            facts_omitted TEXT NOT NULL DEFAULT '[]',
            generated_at TEXT NOT NULL,
            factuality_warnings TEXT NOT NULL DEFAULT '[]',
            missing_context TEXT NOT NULL DEFAULT '[]',
            visual_recommendation TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT 'PENDING',
            requires_human_review INTEGER NOT NULL DEFAULT 1,
            content_hash TEXT NOT NULL,
            generator_type TEXT NOT NULL DEFAULT 'RULE_BASED',
            provider TEXT,
            model TEXT,
            prompt_version TEXT NOT NULL DEFAULT 'EXITVECTOR_CONTENT_PROMPT_V1',
            raw_output TEXT NOT NULL DEFAULT '',
            brief_snapshot TEXT NOT NULL DEFAULT '{}',
            validation_result TEXT NOT NULL DEFAULT '{}',
            repair_attempt_count INTEGER NOT NULL DEFAULT 0,
            variant_type TEXT NOT NULL DEFAULT 'STANDARD',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(content_hash)
        )
        """
    )
    columns = {row["name"] for row in database.execute("PRAGMA table_info(content_candidates)").fetchall()}
    for column, value in {
        "generator_type": "TEXT NOT NULL DEFAULT 'RULE_BASED'",
        "provider": "TEXT",
        "model": "TEXT",
        "prompt_version": "TEXT NOT NULL DEFAULT 'EXITVECTOR_CONTENT_PROMPT_V1'",
        "raw_output": "TEXT NOT NULL DEFAULT ''",
        "original_raw_output": "TEXT NOT NULL DEFAULT ''",
        "brief_snapshot": "TEXT NOT NULL DEFAULT '{}'",
        "validation_result": "TEXT NOT NULL DEFAULT '{}'",
        "original_validation_result": "TEXT NOT NULL DEFAULT '{}'",
        "repaired_text": "TEXT NOT NULL DEFAULT ''",
        "final_machine_validation": "INTEGER NOT NULL DEFAULT 0",
        "repair_attempt_count": "INTEGER NOT NULL DEFAULT 0",
        "variant_type": "TEXT NOT NULL DEFAULT 'STANDARD'",
        "deduplication_status": "TEXT NOT NULL DEFAULT 'UNIQUE'",
        "reviewed_by": "TEXT",
        "reviewed_at": "TEXT",
        "ready_to_post": "INTEGER NOT NULL DEFAULT 0",
        "active_review_state": "TEXT NOT NULL DEFAULT 'PENDING'",
        "superseded_by": "INTEGER",
        "export_status": "TEXT NOT NULL DEFAULT 'PENDING'",
        "export_format": "TEXT",
        "exported_at": "TEXT",
    }.items():
        if column not in columns:
            database.execute(f"ALTER TABLE content_candidates ADD COLUMN {column} {value}")
    database.commit()
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            score REAL NOT NULL,
            channel TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            delivered_at TEXT,
            candidate_id INTEGER,
            review_action TEXT,
            deduplication_key TEXT,
            UNIQUE(candidate_id, channel, review_action)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS review_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            reason TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(candidate_id) REFERENCES content_candidates(id)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS review_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            reviewer TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            snapshot TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(candidate_id) REFERENCES content_candidates(id)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS post_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            impressions INTEGER,
            engagements INTEGER,
            link_clicks INTEGER,
            published_at TEXT,
            observed_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS audience_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            username TEXT NOT NULL,
            display_name TEXT NOT NULL DEFAULT '',
            follows_user INTEGER NOT NULL DEFAULT 0,
            user_follows INTEGER NOT NULL DEFAULT 0,
            mutual_follow INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT,
            last_seen_at TEXT,
            source TEXT NOT NULL DEFAULT 'MOCK',
            source_confidence REAL NOT NULL DEFAULT 0,
            bio TEXT NOT NULL DEFAULT '',
            follower_count INTEGER,
            following_count INTEGER,
            verified INTEGER,
            account_created_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, source)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS audience_relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            username TEXT NOT NULL,
            user_follows INTEGER NOT NULL DEFAULT 0,
            account_follows_user INTEGER NOT NULL DEFAULT 0,
            mutual_follow INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT,
            last_seen_at TEXT,
            source TEXT NOT NULL DEFAULT 'MOCK',
            source_confidence REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, source)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS audience_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interaction_id TEXT NOT NULL,
            actor_account_id TEXT NOT NULL,
            target_account_id TEXT NOT NULL,
            interaction_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            post_id TEXT,
            source TEXT NOT NULL DEFAULT 'MOCK',
            confidence REAL NOT NULL DEFAULT 0,
            import_run_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(interaction_id)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS audience_import_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            archive_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OK',
            coverage_summary TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS audience_data_coverage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'MOCK',
            following_available INTEGER NOT NULL DEFAULT 0,
            followers_available INTEGER NOT NULL DEFAULT 0,
            replies_available INTEGER NOT NULL DEFAULT 0,
            mentions_available INTEGER NOT NULL DEFAULT 0,
            likes_received_available INTEGER NOT NULL DEFAULT 0,
            reposts_available INTEGER NOT NULL DEFAULT 0,
            observation_window_start TEXT,
            observation_window_end TEXT,
            completeness REAL NOT NULL DEFAULT 0,
            confidence TEXT NOT NULL DEFAULT 'LOW',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, source)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS audience_reciprocity_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'MOCK',
            score REAL NOT NULL DEFAULT 0,
            confidence TEXT NOT NULL DEFAULT 'LOW',
            unknown INTEGER NOT NULL DEFAULT 0,
            reason_codes TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, source)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS audience_relationship_value_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'MOCK',
            score REAL NOT NULL DEFAULT 0,
            confidence TEXT NOT NULL DEFAULT 'LOW',
            unknown INTEGER NOT NULL DEFAULT 0,
            reason_codes TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, source)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS audience_unfollow_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            username TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'MOCK',
            score REAL NOT NULL DEFAULT 0,
            confidence TEXT NOT NULL DEFAULT 'LOW',
            reason_codes TEXT NOT NULL DEFAULT '[]',
            relationship_class TEXT NOT NULL DEFAULT 'UNKNOWN_INSUFFICIENT_DATA',
            reciprocity_score REAL NOT NULL DEFAULT 0,
            relationship_value_score REAL NOT NULL DEFAULT 0,
            inbound_interactions INTEGER NOT NULL DEFAULT 0,
            outbound_interactions INTEGER NOT NULL DEFAULT 0,
            last_interaction_at TEXT,
            mutual_follow INTEGER NOT NULL DEFAULT 0,
            recommendation TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, source)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS audience_high_value_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            username TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'MOCK',
            score REAL NOT NULL DEFAULT 0,
            confidence TEXT NOT NULL DEFAULT 'LOW',
            reason_codes TEXT NOT NULL DEFAULT '[]',
            relationship_class TEXT NOT NULL DEFAULT 'UNKNOWN_INSUFFICIENT_DATA',
            reciprocity_score REAL NOT NULL DEFAULT 0,
            relationship_value_score REAL NOT NULL DEFAULT 0,
            inbound_interactions INTEGER NOT NULL DEFAULT 0,
            outbound_interactions INTEGER NOT NULL DEFAULT 0,
            last_interaction_at TEXT,
            mutual_follow INTEGER NOT NULL DEFAULT 0,
            recommendation TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, source)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS audience_import_run_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_run_id INTEGER NOT NULL,
            account_id TEXT NOT NULL,
            UNIQUE(import_run_id, account_id)
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS audience_posts (
            post_id TEXT NOT NULL,
            source TEXT NOT NULL,
            author_account_id TEXT NOT NULL,
            timestamp TEXT,
            text TEXT NOT NULL DEFAULT '',
            import_run_id INTEGER,
            PRIMARY KEY(post_id, source)
        )
        """
    )
    # Additive migration for existing Phase 7 databases.
    coverage_columns = {row["name"] for row in database.execute("PRAGMA table_info(audience_data_coverage)")}
    for column in ("replies_outbound_available", "mentions_outbound_available", "likes_performed_available", "quotes_available"):
        if column not in coverage_columns:
            database.execute(f"ALTER TABLE audience_data_coverage ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0")
    # Older Phase 7 ranking tables were keyed only by account_id. Preserve their
    # records while isolating materialized mock and imported results by source.
    for table in ("audience_unfollow_candidates", "audience_high_value_connections"):
        columns = {row["name"] for row in database.execute(f"PRAGMA table_info({table})")}
        if "source" not in columns:
            database.execute(f"ALTER TABLE {table} ADD COLUMN source TEXT NOT NULL DEFAULT 'LEGACY_UNKNOWN'")
        single_account_key = any(
            row["unique"] and [c["name"] for c in database.execute(f"PRAGMA index_info('{row['name']}')")] == ["account_id"]
            for row in database.execute(f"PRAGMA index_list({table})")
        )
        if single_account_key:
            create_sql = database.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
            create_sql, replaced = re.subn(r"UNIQUE\s*\(\s*account_id\s*\)", "UNIQUE(account_id, source)", create_sql, flags=re.I)
            if not replaced:
                create_sql = re.sub(r"(\baccount_id\s+TEXT[^,]*?)\s+UNIQUE\b", r"\1", create_sql, flags=re.I)
                head, tail = create_sql.rsplit(")", 1)
                create_sql = head + ", UNIQUE(account_id, source))" + tail
            database.execute(f"ALTER TABLE {table} RENAME TO {table}_phase7_legacy")
            database.execute(create_sql)
            database.execute(f"INSERT INTO {table} SELECT * FROM {table}_phase7_legacy")
            database.execute(f"DROP TABLE {table}_phase7_legacy")
    database.execute("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
            duration_seconds REAL NOT NULL DEFAULT 0, trigger_type TEXT NOT NULL,
            dry_run INTEGER NOT NULL DEFAULT 0, social_count INTEGER NOT NULL DEFAULT 0,
            opportunity_count INTEGER NOT NULL DEFAULT 0, candidate_count INTEGER NOT NULL DEFAULT 0,
            notification_count INTEGER NOT NULL DEFAULT 0, warning_count INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0, summary TEXT NOT NULL DEFAULT '{}'
        )
    """)
    notification_columns = {row["name"] for row in database.execute("PRAGMA table_info(notifications)")}
    # CREATE TABLE IF NOT EXISTS leaves pre-review notification schemas intact.
    # Add every later column before creating indexes or running review services.
    for column, definition in (("candidate_id", "INTEGER"), ("review_action", "TEXT"),
                               ("deduplication_key", "TEXT"), ("opportunity_id", "INTEGER"),
                               ("is_read", "INTEGER NOT NULL DEFAULT 0")):
        if column not in notification_columns:
            database.execute(f"ALTER TABLE notifications ADD COLUMN {column} {definition}")
    database.execute("CREATE UNIQUE INDEX IF NOT EXISTS notifications_event_key ON notifications(deduplication_key) WHERE deduplication_key IS NOT NULL")
    database.commit()
