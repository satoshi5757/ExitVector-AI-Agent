"""Local operational CLI, diagnostics and SQLite maintenance."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from exitvector_agent.agent import AgentRunner, provider_visibility
from exitvector_agent.content import ContentBrief, validate_content
from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.logging import configure_operational_logging
from exitvector_agent.review import ReviewHandoffService, ReviewService
from exitvector_agent.run_lock import AlreadyRunning, RunLock

COMMANDS = {"run", "watch", "status", "doctor", "backup", "db-check", "review", "ready", "notifications", "live-check"}
EXPECTED_TABLES = {"agent_runs", "social_observations", "ticker_mentions", "trend_score_snapshots", "opportunities",
                   "content_candidates", "notifications", "review_audit", "audience_accounts", "audience_interactions",
                   "audience_data_coverage", "audience_posts"}


def add_parsers(subparsers):
    run = subparsers.add_parser("run", help="run the complete local pipeline once")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--symbol", help="enrich/generate only for one ticker; social reads remain bounded")
    modes = run.add_mutually_exclusive_group()
    modes.add_argument("--verbose", action="store_true")
    modes.add_argument("--quiet", action="store_true")
    watch = subparsers.add_parser("watch", help="run repeatedly until Ctrl+C")
    watch.add_argument("--interval", help="e.g. 30m, 1h, 60s")
    watch.add_argument("--cycles", type=int, help="stop after a finite number of runs (demonstration/testing)")
    modes = watch.add_mutually_exclusive_group()
    modes.add_argument("--verbose", action="store_true")
    modes.add_argument("--quiet", action="store_true")
    for name in ("status", "doctor", "db-check", "ready"):
        command = subparsers.add_parser(name)
        if name == 'doctor':
            command.add_argument('--live', action='store_true', help='also make minimal authenticated read checks')
    subparsers.add_parser('live-check', help='minimal provider reads; no inference or business writes')
    backup = subparsers.add_parser("backup", help="consistent local SQLite backup")
    backup.add_argument("--output", type=Path)
    review = subparsers.add_parser("review", help="human review queue and decisions")
    review.add_argument("action", nargs="?", default="list", choices=["list", "show", "approve", "reject", "edit", "archive"])
    review.add_argument("candidate_id", type=int, nargs="?")
    review.add_argument("--reviewer", default="local-user")
    review.add_argument("--reason", default="")
    review.add_argument("--text")
    notices = subparsers.add_parser("notifications", help="persisted local review notification inbox")
    notices.add_argument("action", nargs="?", default="list", choices=["list", "read"])
    notices.add_argument("notification_id", type=int, nargs="?")
    notices.add_argument("--unread", action="store_true")


def interval_seconds(value):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(s|m|h)", value)
    if not match or float(match[1]) <= 0:
        raise ValueError("Interval must be a positive duration such as 30m, 1h or 60s")
    return float(match[1]) * {"s": 1, "m": 60, "h": 3600}[match[2]]


def db_check(path):
    if not Path(path).is_file():
        return {"ok": False, "error": "Database does not exist; run the agent to initialize it"}
    with Database(path, read_only=True) as db:
        integrity = [row[0] for row in db.execute("PRAGMA integrity_check")]
        missing = sorted(EXPECTED_TABLES - db.list_tables())
        columns = {'agent_runs': {'id', 'status', 'summary', 'started_at'},
                   'content_candidates': {'review_status', 'final_machine_validation', 'ready_to_post', 'content_hash'},
                   'notifications': {'deduplication_key', 'opportunity_id', 'is_read'}}
        missing_columns = {table: sorted(required - {r['name'] for r in db.execute(f'PRAGMA table_info({table})')})
                           for table, required in columns.items() if table not in missing}
        missing_columns = {table: names for table, names in missing_columns.items() if names}
        return {"ok": integrity == ["ok"] and not missing and not missing_columns, "integrity_check": integrity,
                "missing_tables": missing, "missing_columns": missing_columns}


def status(settings):
    output = {"status": "NOT_INITIALIZED", "database": str(settings.database_path.resolve()),
              "providers": provider_visibility(settings), "last_run": None, "last_successful_run": None, "last_successful_live_run": None,
              "pending_review": 0, "ready_to_post": 0, "pending_opportunities": 0, "recent_errors": [],
              "lock": RunLock(settings.database_path, settings.agent_lock_timeout_minutes).state()}
    from exitvector_agent.provider_health import capabilities
    output['provider_status'] = capabilities(settings)
    try:
        settings.validate_operation()
    except ValueError as exc:
        output['status'] = 'CONFIGURATION_INVALID'
        output['configuration_error'] = str(exc)
    if not settings.database_path.is_file():
        return output
    with Database(settings.database_path, read_only=True) as db:
        tables = db.list_tables()
        if EXPECTED_TABLES - tables:
            output["status"] = "SCHEMA_UPDATE_REQUIRED"
            return output
        output["providers"] = provider_visibility(settings, db)
        output['provider_status'] = capabilities(settings, db)
        row = db.execute("SELECT * FROM agent_runs ORDER BY id DESC LIMIT 1").fetchone()
        success = db.execute("SELECT * FROM agent_runs WHERE status='SUCCESS' ORDER BY id DESC LIMIT 1").fetchone()
        output["last_run"] = dict(row) if row else None
        output["last_successful_run"] = dict(success) if success else None
        for successful in db.execute("SELECT * FROM agent_runs WHERE status='SUCCESS' ORDER BY id DESC LIMIT 100"):
            selected = json.loads(successful['summary']).get('providers', {})
            if selected.get('social', '').startswith('live') and selected.get('content', '').startswith('OpenAI/') and selected.get('regivion') != 'mock':
                output['last_successful_live_run'] = dict(successful)
                break
        output["status"] = "RUNNING" if output["lock"]["active"] else "HEALTHY" if not row or row['status'] == 'SUCCESS' else "DEGRADED"
        if output.get('configuration_error'):
            output['status'] = 'CONFIGURATION_INVALID'
        handoff = ReviewHandoffService(db)
        output["pending_review"] = len(handoff.pending())
        output["ready_to_post"] = len(handoff.ready())
        output["pending_opportunities"] = db.execute("SELECT COUNT(*) FROM opportunities WHERE notification_eligible=1 AND id IN (SELECT MAX(id) FROM opportunities GROUP BY ticker)").fetchone()[0]
        for item in db.execute("SELECT id,summary FROM agent_runs WHERE error_count>0 ORDER BY id DESC LIMIT 5"):
            output["recent_errors"].append({"run_id": item['id'], "errors": json.loads(item['summary']).get('errors', [])})
    return output


def doctor(settings):
    checks = []
    def add(level, name, detail):
        checks.append({"status": level, "name": name, "detail": detail})
    add("PASS" if sys.version_info >= (3, 11) else "FAIL", "Python", '.'.join(map(str, sys.version_info[:3])))
    try:
        settings.validate_operation()
        add("PASS", "Operational configuration", "Validated; no secrets displayed")
    except ValueError as exc:
        add("FAIL", "Operational configuration", str(exc))
    for name, directory in [('Writable data directory', settings.database_path.parent),
                            ('Writable log directory', settings.agent_log_dir)]:
        ancestor = directory.resolve()
        while not ancestor.exists():
            ancestor = ancestor.parent
        try:
            with tempfile.TemporaryFile(dir=ancestor):
                pass
            add("PASS", name, str(directory.resolve()))
        except OSError:
            add("FAIL", name, "Write permission unavailable")
    if settings.database_path.exists():
        try:
            result = db_check(settings.database_path)
            add("PASS" if result.get('integrity_check') == ['ok'] else "FAIL", "SQLite integrity", str(result.get('integrity_check', 'unavailable')))
            add("PASS" if not result.get('missing_tables') and not result.get('missing_columns') else "WARN", "Schema", 'Initialized' if result['ok'] else 'Run agent to initialize/update schema')
            with Database(settings.database_path, read_only=True) as db:
                imported = db.execute("SELECT COUNT(*) FROM audience_accounts WHERE source='X_ARCHIVE' AND account_id!='current-user'").fetchone()[0] if 'audience_accounts' in db.list_tables() else 0
            add("PASS" if imported else "WARN", "Audience database", f"{imported} imported account(s)")
        except sqlite3.Error:
            add("FAIL", "SQLite", "Database is unreadable or invalid")
    else:
        add("WARN", "SQLite/schema", "Not initialized; first run initializes it")
    lock = RunLock(settings.database_path, settings.agent_lock_timeout_minutes).state()
    add("WARN" if lock.get('stale') or lock.get('long_running') else "PASS", "Process lock", "ACTIVE; live locks are never stolen" if lock['active'] else "STALE; next owner recovers" if lock.get('stale') else "Available")
    providers = provider_visibility(settings)
    add("WARN" if settings.agent_social_provider == 'mock' else "PASS", "Social sources", providers['social'])
    add('WARN', 'Stocktwits live', 'DISABLED - supported API access not established')
    add('PASS' if settings.agent_regivion_provider == 'mock' else 'WARN', 'Regivion', providers['regivion'])
    add('PASS' if settings.regivion_api_key else 'WARN', 'Regivion credentials', 'CONFIGURED' if settings.regivion_api_key else 'NOT CONFIGURED')
    add('WARN' if settings.ai_provider == 'mock' else 'PASS', 'Content generator', providers['content'])
    add('PASS' if settings.llm_api_key else 'WARN', 'OpenAI credentials', 'CONFIGURED; authentication untested (use live-check)' if settings.llm_api_key else 'NOT CONFIGURED')
    add('WARN', 'Market', providers['market'])
    if settings.database_path.is_file():
        try:
            from exitvector_agent.provider_health import capabilities
            with Database(settings.database_path, read_only=True) as db:
                for provider in capabilities(settings, db):
                    if provider['last_success_at'] or provider['last_failure_at']:
                        add('WARN' if provider['consecutive_failures'] else 'PASS',
                            provider['provider_name'] + ' recorded health',
                            f"last success={provider['last_success_at']}; last failure={provider['last_failure_at']}; consecutive failures={provider['consecutive_failures']}")
        except sqlite3.Error:
            pass
    add("PASS", "Review service", "Human approval required; only explicitly approved content appears in ready")
    if settings.audience_provider == 'archive':
        path = Path(settings.audience_archive_path) if settings.audience_archive_path else None
        add("PASS" if path and path.is_file() and path.suffix.lower() != '.zip' else "FAIL", "Audience source", "Normalized archive selected; native ZIP direct import remains unsupported")
    else:
        selected = settings.audience_provider
        if selected == 'auto' and settings.database_path.is_file():
            try:
                with Database(settings.database_path, read_only=True) as db:
                    selected = provider_visibility(settings, db)['audience']
            except sqlite3.Error:
                selected = 'auto; database unavailable'
        elif selected == 'auto':
            selected = 'mock (auto; database not initialized)'
        add("WARN" if 'mock' in selected else "PASS", "Audience source", selected)
    add("PASS" if not settings.allow_x_posting else "FAIL", "X posting", "DISABLED" if not settings.allow_x_posting else "FORBIDDEN")
    add("PASS" if not settings.allow_x_follow_actions else "FAIL", "X relationship actions", "DISABLED" if not settings.allow_x_follow_actions else "FORBIDDEN")
    return checks


def print_run(result, *, verbose=False, quiet=False):
    if quiet:
        for error in result.errors:
            print("ERROR: " + error)
        for warning in result.warnings:
            if not warning.startswith('MOCK '):
                print("WARNING: " + warning)
        return
    print(f"ExitVector Agent — {'DRY RUN' if result.dry_run else 'Run #' + str(result.run_id)} — {result.status}")
    print("Providers: " + "; ".join(f"{name}={value}" for name, value in result.providers.items()))
    for warning in result.warnings:
        print("WARNING: " + warning)
    print(f"Social scan: {result.observations_created} new observations; {result.trend_count} trends")
    print(f"Opportunities: {result.opportunities_created} new, {result.opportunities_updated} updated")
    print(f"Content/validation: {result.content_candidates_created} valid new candidates")
    print(f"Review queue: {result.review_items_created} new item(s); notifications: {result.notifications_sent} batch(es)")
    print(f"Audience refresh: {result.audience_refresh_result['status']}")
    for item in result.review_handoff:
        print(f"  {item['symbol']} — {item['score']:.1f} — {item['angle']} — variant {item['variant']} (candidate #{item['candidate_id']})")
    for error in result.errors:
        print("ERROR: " + error)
    if result.dry_run:
        print("Preview only: database/review/history unchanged; no notifications sent.")
    elif result.review_handoff:
        print("Review with: python -m exitvector_agent review")
    print(f"Completed in {result.duration_seconds:.2f}s. No automatic posts were made.")
    if verbose:
        print(json.dumps(asdict(result), indent=2))


def execute(args, settings):
    """Dispatch before the legacy CLI opens/initializes its database."""
    try:
        if args.command in {'run', 'watch'}:
            settings.validate_operation()
            configure_operational_logging(settings, quiet=args.quiet, dry_run=getattr(args, 'dry_run', False))
            runner = AgentRunner(settings, quiet=args.quiet)
            if args.command == 'run':
                result = runner.run_once(dry_run=args.dry_run, symbol=args.symbol)
                print_run(result, verbose=args.verbose, quiet=args.quiet)
                return 0 if result.status == 'SUCCESS' else 130 if result.status == 'CANCELLED' else 1
            if args.cycles is not None and args.cycles < 1:
                raise ValueError("--cycles must be positive")
            runner.watch(interval_seconds=interval_seconds(args.interval) if args.interval else None, cycles=args.cycles,
                         on_result=lambda r: print_run(r, verbose=args.verbose, quiet=args.quiet))
            if not args.quiet:
                print("ExitVector stopped safely.")
            return 0
        if args.command == 'doctor':
            checks = doctor(settings)
            if args.live:
                from exitvector_agent.live_checks import live_check
                checks.extend(live_check(settings))
            for check in checks:
                print(f"[{check['status']}] {check['name']}: {check['detail']}")
            return 2 if any(c['status'] == 'FAIL' for c in checks) else 0
        if args.command == 'live-check':
            from exitvector_agent.live_checks import live_check
            checks = live_check(settings)
            for check in checks:
                print(f"[{check['status']}] {check['name']}: {check['detail']}")
            return 2 if any(c['status'] == 'FAIL' for c in checks) else 0
        if args.command == 'status':
            result = status(settings)
            print(f"ExitVector — {result['status']}")
            if result.get('configuration_error'):
                print('ERROR: ' + result['configuration_error'])
            print(f"Database: {result['database']}")
            for name, value in result['providers'].items():
                print(f"{name}: {value}")
            for name in ('last_run', 'last_successful_run', 'last_successful_live_run'):
                row = result[name]
                print(f"{name}: " + (f"#{row['id']} {row['started_at']} {row['status']} ({row['duration_seconds']:.2f}s)" if row else 'none'))
            print(f"Next scheduled run: {result['lock'].get('next_run_at') if result['lock']['active'] else 'none'}")
            print(f"Pending review: {result['pending_review']}; ready to post: {result['ready_to_post']}; pending opportunities: {result['pending_opportunities']}")
            print(f"Recent errors: {json.dumps(result['recent_errors'])}")
            print('Provider health (null = untested): ' + json.dumps(result['provider_status']))
            return 0
        if args.command == 'db-check':
            result = db_check(settings.database_path)
            print(json.dumps(result, indent=2))
            return 0 if result['ok'] else 2
        if args.command == 'backup':
            target = args.output or settings.agent_data_dir / 'backups' / ('exitvector-' + datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S-%f') + '.db')
            with Database(settings.database_path, read_only=True) as db:
                output = db.backup_to(target)
            print(f"Backup created: {output.resolve()}")
            return 0
        if not settings.database_path.exists():
            raise ValueError('Database not initialized; run the agent first')
        with Database(settings.database_path) as db:
            ensure_schema(db)
            if args.command == 'notifications':
                if args.action == 'read':
                    if args.notification_id is None:
                        raise ValueError('A notification ID is required')
                    cursor = db.execute('UPDATE notifications SET is_read=1 WHERE id=?', (args.notification_id,))
                    if not cursor.rowcount:
                        raise ValueError('Notification does not exist')
                    db.commit()
                rows = [dict(r) for r in db.execute('SELECT id,created_at,ticker,opportunity_id,payload,is_read FROM notifications' + (' WHERE is_read=0' if args.unread else '') + ' ORDER BY id DESC LIMIT 50')]
                print(json.dumps(rows, indent=2))
                return 0
            handoff = ReviewHandoffService(db)
            if args.command == 'ready':
                print(json.dumps(handoff.ready(), indent=2))
                return 0
            if args.action == 'list':
                for row in handoff.recommended():
                    print(f"#{row['id']} {row['ticker']} — {row['opportunity_score']:.1f} — {row['variant_type']} — {row['review_status']}")
                return 0
            if args.candidate_id is None:
                raise ValueError('A candidate ID is required')
            row = db.get_row('content_candidates', args.candidate_id)
            if row is None:
                raise ValueError('Candidate does not exist')
            review = ReviewService(db)
            if args.action in {'approve', 'edit'}:
                brief_raw = json.loads(row['brief_snapshot'])
                brief_raw.pop('data_provenance', None)
                if not brief_raw:
                    raise ValueError('Candidate lacks a factuality brief; regenerate before approval/edit')
                text = args.text if args.action == 'edit' else row['full_text']
                if not text or not validate_content(text, ContentBrief(**brief_raw)).valid:
                    raise ValueError('Content failed factuality validation; review decision not applied')
            if args.action == 'approve':
                if row['review_status'] not in {'PENDING', 'EDITED'} or not row['final_machine_validation']:
                    raise ValueError('Only machine-validated pending/edited candidates can be approved')
                result = review.approve_candidate(args.candidate_id, reviewer=args.reviewer)
            elif args.action == 'reject':
                if not args.reason:
                    raise ValueError('Rejection requires --reason')
                result = review.reject_candidate(args.candidate_id, reviewer=args.reviewer, reason=args.reason)
            elif args.action == 'archive':
                result = review.archive_candidate(args.candidate_id, reviewer=args.reviewer)
            elif args.action == 'edit':
                result = review.edit_candidate(args.candidate_id, reviewer=args.reviewer, updates={'full_text': args.text, 'body': args.text})
                # Editing still requires a separate explicit human approval.
                db.execute('UPDATE content_candidates SET ready_to_post=0 WHERE id=?', (args.candidate_id,)); db.commit()
            else:
                result = dict(row)
            print(json.dumps(asdict(result) if hasattr(result, '__dataclass_fields__') else result, default=str, indent=2))
            return 0
    except AlreadyRunning as exc:
        print(f"Run skipped: {exc}")
        return 3
    except KeyboardInterrupt:
        print('ExitVector stopped safely.')
        return 130
    except (ValueError, OSError, sqlite3.Error) as exc:
        # SQLite/OS diagnostics can contain private paths; never echo provider credentials.
        print('ERROR: ' + (str(exc) if isinstance(exc, (ValueError, FileExistsError)) else type(exc).__name__))
        return 2
