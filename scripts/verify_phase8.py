"""Reproduce Phase 8 locally; all databases and providers are disposable fixtures."""
from __future__ import annotations

import importlib
import json
import os
import socket
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from exitvector_agent.agent import AgentRunner
from exitvector_agent.config import Settings
from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.logging import configure_operational_logging
from exitvector_agent.operations import db_check, print_run, status
from exitvector_agent.regivion import MockRegivionClient
from exitvector_agent.review import MockReviewNotifier, ReviewHandoffService
from exitvector_agent.run_lock import AlreadyRunning, RunLock
from exitvector_agent.social.scan import SocialScanService
from exitvector_agent.social.sources import MockSourceAdapter, SourceAdapter

NOW = datetime(2026, 10, 8, 9, tzinfo=timezone.utc)


class FixedDate(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


class FailedSource(SourceAdapter):
    name = 'reddit-failure-simulation'

    async def collect(self):
        raise TimeoutError('Simulated provider timeout; no network connection')


def main():
    sections = ['# Phase 8 operational verification',
                'All outputs below were captured locally by `python scripts/verify_phase8.py`. '
                'No production credentials, external providers, posting, scraping, browser automation, '
                'OS scheduler installation, deployment, commit or push were used. '
                'Temporary databases/backups are removed after verification; paths are evidence, not retained user backups.']

    def record(title, data):
        rendered = data if isinstance(data, str) else json.dumps(data, indent=2, default=str)
        sections.append(f'## {title}\n\n```text\n{rendered.rstrip()}\n```')

    test_results = []
    for title, arguments in [
        ('Focused Phase 8 tests', ['tests/test_phase8_operations.py']),
        ('Full pytest suite, including unchanged Phase 1-7 tests', [])]:
        completed = subprocess.run([sys.executable, '-m', 'pytest', *arguments, '-q', '--tb=short'],
                                   cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=180)
        record(title, completed.stdout + completed.stderr)
        test_results.append(completed.returncode)
        print(f'{title}: exit {completed.returncode}', flush=True)

    with tempfile.TemporaryDirectory(prefix='exitvector_phase8_') as folder:
        base = Path(folder)
        settings = Settings(database_url='sqlite:///' + str(base / 'data with spaces' / 'agent.db'),
                            agent_data_dir=base / 'data with spaces', agent_log_dir=base / 'logs',
                            agent_retry_backoff_seconds=0)
        env = os.environ.copy()
        # Remove operational settings inherited from a user's shell before local verification.
        for key in list(env):
            if key.startswith(('EXITVECTOR_', 'AGENT_', 'AUDIENCE_', 'ALLOW_X_')):
                del env[key]
        env.update({'PYTHONPATH': str(ROOT / 'src'), 'PYTHONIOENCODING': 'utf-8',
                    'EXITVECTOR_DATABASE_URL': 'sqlite:///' + str(settings.database_path),
                    'AGENT_DATA_DIR': str(settings.agent_data_dir), 'AGENT_LOG_DIR': str(settings.agent_log_dir)})
        empty_env = base / 'empty.env'
        empty_env.write_text('', encoding='utf-8')

        def cli(title, *arguments, extra=None, expected=0):
            completed = subprocess.run([sys.executable, '-m', 'exitvector_agent', '--env-file', str(empty_env), *arguments],
                                       cwd=ROOT, env={**env, **(extra or {})}, capture_output=True,
                                       text=True, encoding='utf-8', timeout=30)
            record(title, '$ python -m exitvector_agent ' + ' '.join(arguments) + '\n' +
                   completed.stdout + completed.stderr + f'Exit code: {completed.returncode}')
            assert completed.returncode == expected, title
            return completed

        cli('Doctor before initialization', 'doctor')
        cli('Actual one-command run output', 'run')
        cli('Actual status output', 'status')
        cli('Actual doctor output', 'doctor')
        cli('Actual repeated CLI run', 'run')
        with Database(settings.database_path, read_only=True) as db:
            count_before = db.execute('SELECT COUNT(*) FROM agent_runs').fetchone()[0]
            review_before = [tuple(r) for r in db.execute('SELECT * FROM content_candidates ORDER BY id')]
        cli('Actual dry-run output', 'run', '--dry-run')
        with Database(settings.database_path, read_only=True) as db:
            assert count_before == db.execute('SELECT COUNT(*) FROM agent_runs').fetchone()[0]
            assert review_before == [tuple(r) for r in db.execute('SELECT * FROM content_candidates ORDER BY id')]
        record('Dry-run verification', 'Real run history and all candidate/review columns unchanged. No notifier delivery; disposable database only.')
        cli('Review handoff output', 'review')
        cli('Ready requires approval', 'ready')
        cli('Local notification inbox', 'notifications', '--unread')
        cli('Production refuses mock fallback', 'run', extra={'EXITVECTOR_ENV': 'production'}, expected=2)
        cli('Posting safety flag refuses operation', 'run', extra={'ALLOW_X_POSTING': 'true'}, expected=2)

        # Freeze all pipeline business clocks for repeated/material-change comparisons.
        patches = [patch.object(importlib.import_module('exitvector_agent.' + name), 'datetime', FixedDate)
                   for name in ('social.sources', 'social.scan', 'opportunity_service', 'content')]
        for item in patches:
            item.start()
        def no_network(*args, **kwargs):
            raise AssertionError('Verification must remain offline')
        try:
            with patch.object(socket, 'create_connection', no_network):
                deterministic = settings.model_copy(update={'database_url': 'sqlite:///' + str(base / 'deterministic.db')})
                notifier = MockReviewNotifier()
                client = MockRegivionClient()
                agent = AgentRunner(deterministic, regivion=client, notifier=notifier, clock=lambda: NOW)
                first = agent.run_once(trigger_type='TEST')
                second = agent.run_once(trigger_type='TEST')
                client.data['MSFT']['psc'].update(rank=3, previous_rank=10)
                changed = agent.run_once(trigger_type='TEST')
                for title, result in [('Deterministic first run', first), ('Deterministic identical run', second),
                                      ('Material change: MSFT PSC rank 10 to 3', changed)]:
                    record(title, asdict(result))
                assert first.status == second.status == changed.status == 'SUCCESS'
                assert second.observations_created == second.content_candidates_created == second.notifications_sent == 0
                assert changed.review_items_created == changed.notifications_sent == 1
                record('Notification batches: one per run, never per variant', notifier.batches)
                with Database(deterministic.database_path, read_only=True) as db:
                    record('Run history rows', [dict(r) for r in db.execute('''SELECT id,started_at,completed_at,status,
                        trigger_type,duration_seconds,social_count,opportunity_count,candidate_count,
                        notification_count,error_count FROM agent_runs ORDER BY id''')])
                    record('Material-change candidate evidence', [dict(r) for r in db.execute(
                        'SELECT id,ticker,opportunity_id,full_text,review_status,ready_to_post FROM content_candidates WHERE id>6')])
                    assert not ReviewHandoffService(db).ready()
                with RunLock(deterministic.database_path):
                    try:
                        agent.run_once()
                    except AlreadyRunning as exc:
                        record('Concurrent run rejected; status remains readable', {'rejection': str(exc), 'status': status(deterministic)['status']})
                    else:
                        raise AssertionError('Concurrent run was not rejected')
                record('Released lock', agent.lock.state())

                failures = settings.model_copy(update={'database_url': 'sqlite:///' + str(base / 'failures.db')})
                partial = AgentRunner(failures, adapters=[FailedSource(), MockSourceAdapter('stocktwits')],
                                      notifier=MockReviewNotifier(), clock=lambda: NOW).run_once(trigger_type='TEST')
                record('Isolated transient source failure (bounded retries)', asdict(partial))
                assert partial.status == 'PARTIAL_SUCCESS' and partial.content_candidates_created > 0
                recovery = AgentRunner(failures, notifier=MockReviewNotifier(), clock=lambda: NOW)
                with patch.object(SocialScanService, 'run_sync', side_effect=RuntimeError('simulated crash')):
                    crashed = recovery.run_once(trigger_type='TEST')
                recovered = recovery.run_once(trigger_type='TEST')
                record('Mid-run exception then recovery', {'failed': asdict(crashed), 'subsequent_status': recovered.status,
                                                         'lock': recovery.lock.state(), 'integrity': db_check(failures.database_path)})
                assert crashed.status == 'FAILED' and recovered.status == 'SUCCESS'

                # Simulate a hard process death, then let the next owner recover its history.
                code = '''import sys,time
from pathlib import Path
from exitvector_agent.database import Database,ensure_schema
from exitvector_agent.run_lock import RunLock
p=Path(sys.argv[1]); lock=RunLock(p); lock.acquire(); lock.update(started_at="2026-10-08T09:00:00+00:00")
with Database(p) as db:
 ensure_schema(db)
 db.execute("INSERT INTO agent_runs(started_at,status,trigger_type) VALUES('2026-10-08T09:00:00+00:00','RUNNING','TEST')"); db.commit()
print("LOCKED",flush=True)
time.sleep(60)
'''
                child = subprocess.Popen([sys.executable, '-u', '-c', code, str(failures.database_path)], env=env,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    assert child.stdout.readline().strip() == 'LOCKED'
                    child.kill()
                    child.communicate(timeout=10)
                finally:
                    if child.poll() is None:
                        child.kill(); child.communicate(timeout=10)
                stale_before = recovery.lock.state()
                after_death = recovery.run_once(trigger_type='TEST')
                with Database(failures.database_path, read_only=True) as db:
                    abandoned = dict(db.execute("SELECT id,status,error_count,summary FROM agent_runs WHERE status='CANCELLED' ORDER BY id DESC LIMIT 1").fetchone())
                record('Killed-process OS lock and stale RUNNING recovery', {'before': stale_before, 'next_run': after_death.status,
                        'abandoned_row': abandoned, 'after': recovery.lock.state()})
                assert stale_before['stale'] and after_death.status == 'SUCCESS'

                waits = []
                watch_agent = AgentRunner(deterministic, regivion=client, notifier=MockReviewNotifier(), clock=lambda: NOW,
                                          sleeper=lambda seconds: waits.append(seconds) or False)
                watched = watch_agent.watch(interval_seconds=60, cycles=2)
                record('Watch with injected wait', {'statuses': [r.status for r in watched],
                        'triggers': [r.trigger_type for r in watched], 'requested_waits_seconds': waits,
                        'actual_wait_seconds': 0, 'lock_after': watch_agent.lock.state()})
                def interrupt(_):
                    raise KeyboardInterrupt
                stopped = AgentRunner(deterministic, regivion=client, notifier=MockReviewNotifier(),
                                      clock=lambda: NOW, sleeper=interrupt)
                stopped.watch(interval_seconds=60, cycles=2)
                record('Ctrl+C during watch wait', {'lock_active_after': stopped.lock.state()['active'],
                                                    'stop_event': stopped.stop_event.is_set()})
        finally:
            for item in reversed(patches):
                item.stop()

        cli('Actual short watch CLI demonstration', 'watch', '--interval', '0.01s', '--cycles', '2',
            extra={'AGENT_MIN_INTERVAL_SECONDS': '0.001'})
        cli('SQLite online backup', 'backup')
        backups = list((settings.agent_data_dir / 'backups').glob('*.db'))
        assert len(backups) == 1
        record('Backup integrity', {'path': str(backups[0]), 'result': db_check(backups[0])})
        cli('Backup refuses overwrite', 'backup', '--output', str(backups[0]), expected=2)
        cli('Database integrity and schema', 'db-check')
        with Database(settings.database_path, read_only=True) as db:
            record('Final CLI run history', [dict(r) for r in db.execute('SELECT id,status,trigger_type,candidate_count,notification_count,error_count FROM agent_runs ORDER BY id')])

    sections.append('''## Architecture and exact pipeline

`Settings` -> rotating safe logs -> `RunLock` -> `Database/ensure_schema` -> history RUNNING ->
`SocialScanService/SourceRunner` -> current trends -> per-ticker `OpportunityService` with bounded
Regivion retries -> existing generator/repair -> `ContentGenerationService` final validation and
dedup before persistence -> `ReviewHandoffService` -> optional due audience analysis -> one
console/mock notification batch plus local inbox -> final history -> wait/repeat or release lock.

The runner reuses scoring, novelty, repair, review audit and audience services. New operational
review/ready views require real validation and explicit human approval. Production fails before
pipeline execution; required live providers do not exist. All X action flags must remain false.
Native X ZIP inspection remains separate from normalized JSON import; no direct ZIP import was added.

Integration defects corrected: content briefs previously invented fixed rank/acceleration facts
and mislabeled composite Regivion score as PSC score; mock MSFT output now follows supplied evidence.
Malformed question drafts now undergo validation rather than pretending to be provider transport
failures. Latest opportunity selection now breaks timestamp ties by descending ID, preventing rapid
runs from attaching new candidates to old opportunity notification keys. SQLite backup destinations
are explicitly closed; connection context management alone did not close Windows file handles.

Dry-run calculation writes only to a disposable SQLite backup. The real DB/history/review/inbox/log
files are unchanged; lock metadata and its parent directory can persist. Live locks are never stolen.
Killed process RUNNING rows are marked CANCELLED by the next lock owner. Failure recovery preserves
already committed valid work. Backups use SQLite online backup and refuse existing destinations.
''')
    record('Files changed or added in Phase 8', '\n'.join([
        '.env.example', 'README.md', 'PHASE8_VERIFICATION.md', 'scripts/verify_phase8.py',
        'src/exitvector_agent/__main__.py', 'src/exitvector_agent/agent.py (new)',
        'src/exitvector_agent/config.py', 'src/exitvector_agent/content.py',
        'src/exitvector_agent/database.py', 'src/exitvector_agent/logging.py',
        'src/exitvector_agent/operations.py (new)', 'src/exitvector_agent/opportunity_service.py',
        'src/exitvector_agent/review.py', 'src/exitvector_agent/run_lock.py (new)',
        'src/exitvector_agent/social/scan.py', 'src/exitvector_agent/social/sources.py',
        'tests/test_phase8_operations.py (new)']))
    (ROOT / 'PHASE8_VERIFICATION.md').write_text('\n\n'.join(sections) + '\n', encoding='utf-8')
    print('Wrote PHASE8_VERIFICATION.md', flush=True)
    return 1 if any(test_results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
