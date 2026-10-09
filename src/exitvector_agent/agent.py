"""Local agent orchestration; scoring, validation and review remain in services."""
from __future__ import annotations

import json
import logging
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from exitvector_agent.audience import ArchiveXAudienceDataProvider, AudienceQueryService, DatabaseXAudienceDataProvider, MockXAudienceDataProvider
from exitvector_agent.config import Settings
from exitvector_agent.content import ContentGenerationService, LLMContentGenerator, MockLLMProvider, RuleBasedContentGenerator
from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.opportunity_service import OpportunityService
from exitvector_agent.regivion import MockRegivionClient
from exitvector_agent.review import ConsoleReviewNotifier, ReviewHandoffService
from exitvector_agent.run_lock import RunLock
from exitvector_agent.social.scan import SocialScanService
from exitvector_agent.social.sources import SourceRunner
from exitvector_agent.provider_setup import attach_health, create_providers, mode_label, regivion_target

logger = logging.getLogger("exitvector.agent")


class ErrorBudgetExceeded(RuntimeError):
    pass


@dataclass
class AgentRunResult:
    run_id: int | None
    started_at: str
    completed_at: str = ""
    duration_seconds: float = 0
    status: str = "RUNNING"
    trigger_type: str = "MANUAL"
    dry_run: bool = False
    social_scan_result: list[dict[str, Any]] = field(default_factory=list)
    content_generation_result: list[dict[str, Any]] = field(default_factory=list)
    observations_created: int = 0
    trend_count: int = 0
    opportunities_created: int = 0
    opportunities_updated: int = 0
    content_candidates_created: int = 0
    review_items_created: int = 0
    notifications_sent: int = 0
    audience_refresh_result: dict[str, Any] = field(default_factory=lambda: {"status": "SKIPPED"})
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    review_handoff: list[dict[str, Any]] = field(default_factory=list)
    providers: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    provider_metrics: dict[str, Any] = field(default_factory=dict)
    provider_status: list[dict[str, Any]] = field(default_factory=list)


def audience_provider(settings, db):
    source = settings.audience_provider
    if source == "auto":
        source = db.get_config("audience_provider") or ("database" if db.execute("SELECT 1 FROM audience_accounts WHERE source='X_ARCHIVE' LIMIT 1").fetchone() else "mock")
    if source == "database":
        return source, DatabaseXAudienceDataProvider(db)
    if source == "archive":
        if not settings.audience_archive_path:
            raise ValueError("Archive audience source requires AUDIENCE_ARCHIVE_PATH")
        return source, ArchiveXAudienceDataProvider(settings.audience_archive_path)
    return "mock", MockXAudienceDataProvider()


def provider_visibility(settings, db=None):
    audience = settings.audience_provider
    if db is not None and audience == "auto":
        audience = db.get_config("audience_provider") or ("database" if db.execute("SELECT 1 FROM audience_accounts WHERE source='X_ARCHIVE' LIMIT 1").fetchone() else "mock")
    return {"social": settings.agent_social_provider + " (Stocktwits/Reddit fixtures)" if settings.agent_social_provider == "mock" else settings.agent_social_provider + " (Reddit OAuth; Stocktwits DISABLED)",
            "regivion": settings.agent_regivion_provider if settings.agent_regivion_provider != 'http' else 'HTTP ' + settings.regivion_contract + '; ' + regivion_target(settings),
            "content": "LLM/mock" if settings.ai_provider == "mock" else f'OpenAI/{settings.ai_model}' if settings.ai_provider == 'openai' else settings.ai_provider,
            "market": 'DISABLED (no licensed live market API discovered)' if settings.market_provider == 'disabled' else 'mock',
            "audience": audience, "X posting": "DISABLED", "X relationship actions": "DISABLED"}


def transient(exc):
    return isinstance(exc, (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError)) or (
        isinstance(exc, httpx.HTTPStatusError) and (exc.response.status_code == 429 or exc.response.status_code >= 500))


class RetryingProvider:
    def __init__(self, provider, retry):
        self.provider, self.retry = provider, retry

    def get_ticker(self, symbol):
        return self.retry(lambda: self.provider.get_ticker(symbol), health=getattr(self.provider, 'health', None))

    def generate(self, prompt, structured_input):
        return self.retry(lambda: self.provider.generate(prompt, structured_input), health=getattr(self.provider, 'health', None))


class AgentRunner:
    def __init__(self, settings: Settings, *, adapters=None, regivion=None, llm=None, notifier=None,
                 clock=None, sleeper=None, stop_event=None, quiet=False):
        self.settings = settings
        self.adapters = adapters
        self.regivion = regivion
        self.llm = llm
        self._configured_providers = None
        self.symbol = None
        self.notifier = notifier or ConsoleReviewNotifier(quiet=quiet)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.stop_event = stop_event or threading.Event()
        self.sleeper = sleeper or self.stop_event.wait
        self.lock = RunLock(settings.database_path, settings.agent_lock_timeout_minutes)

    def _retry(self, operation, health=None):
        for attempt in range(self.settings.agent_provider_max_retries + 1):
            if self.stop_event.is_set():
                raise KeyboardInterrupt
            try:
                return operation()
            except Exception as exc:
                if not transient(exc) or attempt == self.settings.agent_provider_max_retries:
                    raise
                if health:
                    health.metrics['retries'] += 1
                logger.info("provider_retry", extra={"context": {"attempt": attempt + 1, "error_type": type(exc).__name__}})
                if self.sleeper(self.settings.agent_retry_backoff_seconds * (attempt + 1)):
                    raise KeyboardInterrupt

    def run_once(self, *, dry_run=False, trigger_type="MANUAL", symbol=None) -> AgentRunResult:
        import re
        if symbol is not None and not re.fullmatch(r'[A-Za-z]{1,5}', symbol):
            raise ValueError('Invalid single-ticker symbol')
        self.symbol = symbol.upper() if symbol else None
        self.settings.validate_operation()
        with self.lock:
            return self._open_and_run(dry_run=dry_run, trigger_type=trigger_type)

    def _open_and_run(self, *, dry_run, trigger_type):
        if self.settings.environment.casefold() == 'production':
            if isinstance(self.regivion, MockRegivionClient) or isinstance(self.llm, MockLLMProvider):
                raise ValueError('Production rejects injected mock providers')
            if self.settings.database_path.is_file():
                with Database(self.settings.database_path, read_only=True) as existing:
                    if 'social_observations' in existing.list_tables() and existing.execute(
                        "SELECT 1 FROM social_observations WHERE COALESCE(json_extract(metadata,'$.is_live_data'),0)!=1 LIMIT 1").fetchone():
                        raise ValueError('Production database contains fixture/unknown provenance observations; select a separate live database')
        if dry_run:
            # Existing services commit independently; a disposable SQLite backup is
            # stronger than an outer rollback that their commits could defeat.
            with tempfile.TemporaryDirectory(prefix="exitvector_dry_run_") as folder:
                target = Path(folder) / "preview.db"
                if self.settings.database_path.exists():
                    with Database(self.settings.database_path, read_only=True) as source:
                        source.backup_to(target)
                with Database(target) as db:
                    ensure_schema(db)
                    return self._run(db, dry_run=True, trigger_type=trigger_type)
        with Database(self.settings.database_path) as db:
            ensure_schema(db)
            return self._run(db, dry_run=False, trigger_type=trigger_type)

    def _run(self, db, *, dry_run, trigger_type):
        if trigger_type not in {"MANUAL", "WATCH", "TEST", "SCHEDULED_EXTERNAL"}:
            raise ValueError("Invalid run trigger")
        started = self.clock()
        # Owning the OS lock proves prior RUNNING rows have no active owner.
        db.execute("UPDATE agent_runs SET status='CANCELLED',completed_at=?,error_count=1,summary=? WHERE status='RUNNING'",
                   (started.isoformat(), json.dumps({"errors": ["Recovered abandoned process run"]})))
        cursor = db.execute("INSERT INTO agent_runs(started_at,status,trigger_type,dry_run) VALUES(?,'RUNNING',?,?)",
                            (started.isoformat(), trigger_type, dry_run)); db.commit()
        result = AgentRunResult(int(cursor.lastrowid), started.isoformat(), trigger_type=trigger_type, dry_run=dry_run)
        self.lock.update(run_id=result.run_id, started_at=started.isoformat(), mode=trigger_type)
        result.providers = provider_visibility(self.settings, db)
        result.warnings.append(mode_label(self.settings))
        if self._configured_providers is None:
            self._configured_providers = create_providers(self.settings)
        configured_social, configured_regivion, configured_llm = self._configured_providers
        adapters = self.adapters if self.adapters is not None else configured_social
        regivion = self.regivion if self.regivion is not None else configured_regivion
        llm = self.llm if self.llm is not None else configured_llm
        health = attach_health([*adapters, regivion, llm], self.settings, db)
        if self.lock.recovered:
            result.warnings.append("Recovered stale process metadata; the previous OS lock was no longer held.")
        progress = 0
        logger.info("run_start", extra={"context": {"run_id": result.run_id, "trigger": trigger_type, "dry_run": dry_run, "providers": result.providers}})

        def guard():
            if self.stop_event.is_set():
                raise KeyboardInterrupt
            if len(result.errors) >= self.settings.agent_max_errors_per_run:
                raise ErrorBudgetExceeded

        def failure(stage, exc):
            # Never persist raw provider exception text, which can contain tokens.
            message = f"{stage}: {type(exc).__name__}"
            result.errors.append(message)
            logger.warning("component_failed", extra={"context": {"run_id": result.run_id, "stage": stage, "error_type": type(exc).__name__}})

        seen_sources = set()
        def source_result(source):
            nonlocal progress
            if self.settings.environment.casefold() == 'production' and any(not row.raw_metadata.get('is_live_data') for row in source.observations):
                raise ValueError('Production rejected non-live social observation')
            if source.error:
                failure("social:" + source.source, RuntimeError())
            else:
                progress += 1
            seen_sources.update(row.source for row in source.observations)
            result.social_scan_result.append({"source": source.source, "status": "FAILED" if source.error else "OK", "observed": len(source.observations)})
            guard()

        before = None
        try:
            guard()
            before = db.execute("SELECT COUNT(*) FROM social_observations").fetchone()[0]
            scanner = SocialScanService(db, adapters=adapters,
                        runner=SourceRunner(self.settings.agent_provider_timeout_seconds, self.settings.agent_provider_max_retries,
                                            self.settings.agent_retry_backoff_seconds), on_source_result=source_result)
            trends = scanner.run_sync(limit=None if self.symbol else self.settings.max_opportunities_per_run)
            if self.symbol:
                trends = [trend for trend in trends if trend.ticker == self.symbol]
            result.observations_created = db.execute("SELECT COUNT(*) FROM social_observations").fetchone()[0] - before
            result.trend_count = len(trends)
            logger.info("social_scan_complete", extra={"context": {"sources": len(result.social_scan_result), "trends": len(trends), "new_observations": result.observations_created}})
            opportunity_service = OpportunityService(db, RetryingProvider(regivion, self._retry), threshold=self.settings.notify_threshold,
                live_mode=self.settings.agent_social_provider != 'mock' or self.settings.agent_regivion_provider != 'mock')
            generator = (LLMContentGenerator(database=db, provider=RetryingProvider(llm, self._retry), auto_persist=False,
                         variants_per_opportunity=self.settings.content_variants_per_opportunity)
                         if self.settings.ai_provider in {"mock", "openai"} else RuleBasedContentGenerator(database=db))
            content = ContentGenerationService(db, generator, social_sources=seen_sources)
            for trend in trends:
                guard()
                previous = db.get_recent_opportunity(trend.ticker)
                try:
                    opportunities = opportunity_service.scan(trends=[trend])
                except Exception as exc:
                    failure("enrichment:" + trend.ticker, exc)
                    if self.settings.agent_regivion_provider != 'http':
                        continue
                    from exitvector_agent.provider_setup import DisabledRegivionClient
                    opportunities = OpportunityService(db, DisabledRegivionClient(), threshold=self.settings.notify_threshold,
                                                       live_mode=True).scan(trends=[trend])
                    result.warnings.append(trend.ticker + ': enrichment unavailable; missing-component scoring used, no mock fallback')
                for opportunity in opportunities:
                    if getattr(regivion, 'cache', None):
                        cached = regivion.cache.get(opportunity.symbol)
                        if cached and cached[1] and cached[1].raw.get('provenance', {}).get('stale'):
                            result.warnings.append(opportunity.symbol + ': Regivion snapshot stale or timestamp unknown; confidence reduced')
                    progress += 1
                    if previous:
                        result.opportunities_updated += 1
                    else:
                        result.opportunities_created += 1
                    result.opportunities.append({"symbol": opportunity.symbol, "score": opportunity.total_score,
                        "confidence": opportunity.confidence, "angle": opportunity.suggested_content_angle,
                        "notification_eligible": opportunity.notification_eligible, "reason": opportunity.re_notification_reason,
                        "components": {"social": opportunity.social_trend_score, "regivion": opportunity.regivion_score,
                                       "novelty": opportunity.novelty_score}, "trigger_reasons": opportunity.trigger_reasons})
                    logger.info("opportunity_scored", extra={"context": {"symbol": opportunity.symbol, "score": opportunity.total_score, "actionable": opportunity.notification_eligible}})
                    guard()
                    retry_pending = db.get_config('agent_content_pending:' + opportunity.symbol)
                    if not opportunity.notification_eligible and not retry_pending:
                        continue
                    if getattr(llm, 'generations', 0) >= self.settings.llm_max_generations_per_run:
                        db.set_config('agent_content_pending:' + opportunity.symbol, 'budget_exhausted')
                        result.warnings.append(opportunity.symbol + ': inference budget exhausted; opportunity retained for next run')
                        continue
                    try:
                        generated = content.generate(opportunity)
                        result.content_generation_result.append({"symbol": opportunity.symbol, "generated": generated['generated'],
                            "created": len(generated['created']), "rejected": generated['rejected'], "validation": generated['validation']})
                        new = generated["created"]
                        db.execute('DELETE FROM configuration WHERE key=?', ('agent_content_pending:' + opportunity.symbol,))
                        db.commit()
                        result.content_candidates_created += len(new)
                        if generated["rejected"]:
                            result.warnings.append(f"{opportunity.symbol}: {generated['rejected']} candidate(s) rejected by factuality validation")
                        if new:
                            best = max(new, key=lambda row: row['estimated_engagement_score'])
                            result.review_items_created += 1
                            result.review_handoff.append({"candidate_id": best['id'], "symbol": opportunity.symbol,
                                "score": opportunity.total_score, "angle": opportunity.suggested_content_angle,
                                "variant": best['variant_type']})
                        logger.info("content_validated", extra={"context": {"symbol": opportunity.symbol,
                            "generated": generated["generated"], "created": len(new), "rejected": generated["rejected"]}})
                    except Exception as exc:
                        failure("content:" + opportunity.symbol, exc)
                        db.set_config('agent_content_pending:' + opportunity.symbol, 'provider_failure')
            guard()
            if getattr(llm, 'generations', 0) >= self.settings.llm_max_generations_per_run:
                result.warnings.append('Live LLM generation budget reached; remaining inference skipped')
            if self.settings.agent_audience_refresh_enabled:
                last = db.get_config("agent_last_audience_refresh")
                due = not last or started - datetime.fromisoformat(last) >= timedelta(hours=self.settings.agent_audience_refresh_interval_hours)
                if due:
                    try:
                        source, provider = audience_provider(self.settings, db)
                        analysis = AudienceQueryService(provider, database=db if source != 'archive' else None)
                        if source != 'archive':
                            analysis.persist()
                        else:
                            analysis.overview()  # Analyze directly; never re-import the archive.
                        result.audience_refresh_result = {"status": "OK", "source": source, "accounts": len(provider.get_accounts()),
                                                          "persisted": source != 'archive'}
                        db.set_config("agent_last_audience_refresh", started.isoformat())
                    except Exception as exc:
                        result.audience_refresh_result = {"status": "FAILED"}
                        failure("audience", exc)
                else:
                    result.audience_refresh_result = {"status": "NOT_DUE"}
            guard()
            if self.settings.agent_notify_review_enabled and not dry_run:
                try:
                    result.notifications_sent = ReviewHandoffService(db).notify(self.notifier, threshold=self.settings.notify_threshold)
                    logger.info("review_notification", extra={"context": {"batches": result.notifications_sent}})
                except Exception as exc:
                    failure("notification", exc)
        except KeyboardInterrupt:
            result.status = "CANCELLED"
            result.warnings.append("Run cancelled safely; committed valid work is preserved.")
        except ErrorBudgetExceeded:
            result.warnings.append("Error budget reached; remaining optional operations stopped.")
        except Exception as exc:
            failure("pipeline", exc)
        finally:
            from exitvector_agent.provider_health import capabilities
            result.provider_metrics = {name: item.metrics for name, item in health.items()}
            result.provider_status = capabilities(self.settings, db)
            if before is not None:
                result.observations_created = db.execute("SELECT COUNT(*) FROM social_observations").fetchone()[0] - before
            if result.status != "CANCELLED":
                result.status = "PARTIAL_SUCCESS" if result.errors and progress else "FAILED" if result.errors else "SUCCESS"
            completed = self.clock()
            result.completed_at = completed.isoformat()
            result.duration_seconds = max(0, (completed - started).total_seconds())
            result.opportunities.sort(key=lambda row: -row['score'])
            db.execute("""UPDATE agent_runs SET completed_at=?,status=?,duration_seconds=?,social_count=?,opportunity_count=?,
                       candidate_count=?,notification_count=?,warning_count=?,error_count=?,summary=? WHERE id=?""",
                       (result.completed_at, result.status, result.duration_seconds,
                        sum(r['observed'] for r in result.social_scan_result), result.opportunities_created + result.opportunities_updated,
                        result.content_candidates_created, result.notifications_sent, len(result.warnings), len(result.errors),
                        json.dumps(asdict(result)), result.run_id)); db.commit()
            logger.info("run_end", extra={"context": {"run_id": result.run_id, "status": result.status,
                        "candidates": result.content_candidates_created, "review_items": result.review_items_created,
                        "errors": len(result.errors), "duration": result.duration_seconds}})
        return result

    def watch(self, *, interval_seconds=None, cycles=None, on_result=None):
        self.settings.validate_operation()
        interval = interval_seconds if interval_seconds is not None else self.settings.agent_scan_interval_minutes * 60
        if interval < self.settings.agent_min_interval_seconds:
            raise ValueError("Watch interval is below AGENT_MIN_INTERVAL_SECONDS")
        results = []
        with self.lock:
            try:
                if not self.settings.agent_run_on_start:
                    self.lock.update(mode="WATCH", next_run_at=(self.clock() + timedelta(seconds=interval)).isoformat())
                    if self.sleeper(interval):
                        return results
                while not self.stop_event.is_set() and (cycles is None or len(results) < cycles):
                    self.lock.update(mode="WATCH", next_run_at=None)
                    result = self._open_and_run(dry_run=False, trigger_type="WATCH")
                    # Keep watch memory bounded; only tests/finite demonstrations retain results.
                    if cycles is not None:
                        results.append(result)
                    if on_result:
                        on_result(result)
                    if result.status == "CANCELLED" or (cycles is not None and len(results) >= cycles):
                        break
                    self.lock.update(next_run_at=(self.clock() + timedelta(seconds=interval)).isoformat())
                    if self.sleeper(interval):
                        break
            except KeyboardInterrupt:
                self.stop_event.set()
        return results
