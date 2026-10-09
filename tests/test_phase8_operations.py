from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from exitvector_agent.agent import AgentRunner
from exitvector_agent.config import Settings, load_settings
from exitvector_agent.content import ContentBrief, LLMContentGenerator, MockLLMProvider
from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.logging import SafeJsonFormatter, configure_operational_logging
from exitvector_agent.operations import db_check, doctor, status
from exitvector_agent.regivion import MockRegivionClient
from exitvector_agent.review import MockReviewNotifier, ReviewHandoffService, ReviewService
from exitvector_agent.run_lock import AlreadyRunning, RunLock
from exitvector_agent.social.scan import SocialScanService
from exitvector_agent.social.sources import MockSourceAdapter, SourceAdapter


NOW = datetime(2026, 10, 8, 9, tzinfo=timezone.utc)


class FixedDate(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def offline_clock_and_network(monkeypatch):
    # Business service clocks must agree, not just the runner's timestamps.
    for name in ('social.sources', 'social.scan', 'opportunity_service', 'content'):
        monkeypatch.setattr('exitvector_agent.' + name + '.datetime', FixedDate)
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError('Phase 8 tests must not access the network')
    monkeypatch.setattr(socket, 'create_connection', forbidden)


@pytest.fixture
def settings(tmp_path):
    return Settings(database_url='sqlite:///' + str(tmp_path / 'data with spaces' / 'agent.db'),
                    agent_log_dir=tmp_path / 'logs', agent_data_dir=tmp_path / 'data with spaces',
                    agent_retry_backoff_seconds=0)


def runner(settings, **kwargs):
    kwargs.setdefault('notifier', MockReviewNotifier())
    kwargs.setdefault('clock', lambda: NOW)
    return AgentRunner(settings, **kwargs)


def state(path):
    if not path.exists():
        return None
    with Database(path, read_only=True) as db:
        return {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                for table in sorted(db.list_tables()) if not table.startswith('sqlite_')}


class FailingSource(SourceAdapter):
    name = 'failed'
    def __init__(self, exception=RuntimeError, failures=100):
        self.exception, self.failures, self.calls = exception, failures, 0
    async def collect(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exception('sensitive-token-must-not-leak')
        return MockSourceAdapter('recovered').mock_observations()


def test_complete_run_reuses_services_and_records_history(settings):
    agent = runner(settings)
    result = agent.run_once()
    assert result.status == 'SUCCESS' and result.trigger_type == 'MANUAL'
    assert result.observations_created == 56 and result.trend_count == 3
    assert [o['symbol'] for o in result.opportunities] == ['MSFT', 'NVDA', 'UBER']
    assert result.content_candidates_created == 6 and result.review_items_created == 2
    assert result.notifications_sent == 1 and len(agent.notifier.batches) == 1
    assert {i['ticker'] for i in agent.notifier.batches[0]} == {'MSFT', 'NVDA'}
    assert result.content_generation_result and all(v['valid'] for r in result.content_generation_result for v in r['validation'])
    with Database(settings.database_path) as db:
        run = db.get_row('agent_runs', result.run_id)
        assert run['status'] == 'SUCCESS' and run['trigger_type'] == 'MANUAL'
        assert run['candidate_count'] == 6 and run['notification_count'] == 1
        assert not ReviewHandoffService(db).ready()
        assert all(r['requires_human_review'] == 1 and r['ready_to_post'] == 0 for r in ReviewHandoffService(db).pending())
        assert db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0] == 2
    assert not agent.lock.state()['active']


def test_repeated_run_deduplicates_and_preserves_review_decisions(settings):
    agent = runner(settings)
    first = agent.run_once()
    with Database(settings.database_path) as db:
        candidate_id = first.review_handoff[0]['candidate_id']
        ReviewService(db).approve_candidate(candidate_id, reviewer='human')
        original = tuple(db.get_row('content_candidates', candidate_id))
    second = agent.run_once()
    assert second.observations_created == second.content_candidates_created == second.notifications_sent == 0
    assert second.review_items_created == 0
    with Database(settings.database_path) as db:
        assert db.execute('SELECT COUNT(*) FROM agent_runs').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM social_observations').fetchone()[0] == 56
        assert db.execute('SELECT COUNT(*) FROM content_candidates').fetchone()[0] == 6
        assert tuple(db.get_row('content_candidates', candidate_id)) == original
        assert len(ReviewHandoffService(db).ready()) == 1


def test_material_change_creates_one_additional_review_notification(settings):
    client = MockRegivionClient()
    agent = runner(settings, regivion=client)
    agent.run_once(); agent.run_once()
    client.data['MSFT']['psc'].update(rank=3, previous_rank=10)
    changed = agent.run_once()
    assert changed.status == 'SUCCESS'
    assert changed.review_items_created == 1 and changed.notifications_sent == 1
    assert changed.content_candidates_created > 0
    assert changed.review_handoff[0]['symbol'] == 'MSFT'
    assert len(agent.notifier.batches) == 2 and len(agent.notifier.batches[-1]) == 1
    with Database(settings.database_path, read_only=True) as db:
        texts = [r['full_text'] for r in db.execute('SELECT full_text FROM content_candidates WHERE id>6')]
        assert any('#10' in text and '#3' in text for text in texts)
        assert all('#28' not in text for text in texts)


def test_brief_does_not_invent_rank_acceleration_or_psc_score(settings):
    from dataclasses import replace
    from exitvector_agent.opportunity_service import OpportunityService
    runner(settings).run_once()
    with Database(settings.database_path) as db:
        opportunity = OpportunityService(db, MockRegivionClient()).scan()[0]
    item = replace(opportunity, strongest_fact='', supporting_facts=[],
                   trigger_reasons=[], regivion_summary='', social_summary='')
    brief = ContentBrief.from_opportunity(item)
    assert not any('rank' in fact.lower() or 'acceleration' in fact.lower() or 'PSC score' in fact
                   for fact in brief.allowed_facts)


def test_question_variant_validation_preserves_failed_factuality(settings):
    from dataclasses import replace
    from exitvector_agent.opportunity_service import OpportunityService
    runner(settings).run_once()
    with Database(settings.database_path) as db:
        opportunity = OpportunityService(db, MockRegivionClient()).scan()[0]
    class UnsupportedQuestion(MockLLMProvider):
        def generate(self, prompt, structured_input):
            response = super().generate(prompt, structured_input)
            return replace(response, text='$MSFT at $999?') if 'QUESTION variant' in prompt else response
    generator = LLMContentGenerator(provider=UnsupportedQuestion(), max_repair_attempts=0)
    candidates = generator.generate_for_opportunity(opportunity)
    question = next(c for c in candidates if c.variant_type == 'QUESTION')
    assert not question.validation_result.valid
    assert question.review_status == 'REJECTED_BY_VALIDATOR'


@pytest.mark.parametrize('existing', [False, True])
def test_dry_run_has_no_persistent_database_review_or_notification_changes(settings, existing):
    agent = runner(settings)
    if existing:
        agent.run_once()
    before = state(settings.database_path)
    delivered = len(agent.notifier.batches)
    result = agent.run_once(dry_run=True)
    assert result.dry_run and result.notifications_sent == 0
    assert state(settings.database_path) == before
    assert len(agent.notifier.batches) == delivered
    assert not agent.lock.state()['active']


def test_single_instance_and_status_do_not_block_readers(settings):
    agent = runner(settings); agent.run_once()
    with RunLock(settings.database_path):
        with pytest.raises(AlreadyRunning):
            agent.run_once()
        assert status(settings)['lock']['active']
        with Database(settings.database_path, read_only=True) as db:
            assert db.execute('SELECT COUNT(*) FROM agent_runs').fetchone()[0] == 1
    assert not agent.lock.state()['active']


def test_stale_metadata_and_abandoned_run_are_recovered(settings):
    settings.database_path.parent.mkdir(parents=True)
    lock = RunLock(settings.database_path)
    lock.path.write_bytes(b'\0' + json.dumps({'active': True, 'pid': 999999}).encode())
    with Database(settings.database_path) as db:
        ensure_schema(db)
        db.execute("INSERT INTO agent_runs(started_at,status,trigger_type) VALUES(?,'RUNNING','TEST')", (NOW.isoformat(),)); db.commit()
    assert lock.state()['stale']
    result = runner(settings).run_once()
    assert any('stale process' in w for w in result.warnings)
    with Database(settings.database_path) as db:
        assert db.get_row('agent_runs', 1)['status'] == 'CANCELLED'
        assert db.execute("SELECT COUNT(*) FROM agent_runs WHERE status='RUNNING'").fetchone()[0] == 0


def test_kernel_lock_recovers_after_child_process_death(settings):
    env = os.environ.copy(); env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
    code = "from pathlib import Path; from exitvector_agent.run_lock import RunLock; import sys,time; lock=RunLock(Path(sys.argv[1])).acquire(); print('LOCKED',flush=True); time.sleep(60)"
    process = subprocess.Popen([sys.executable, '-c', code, str(settings.database_path)], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        assert process.stdout.readline().strip() == 'LOCKED'
        with pytest.raises(AlreadyRunning):
            RunLock(settings.database_path).acquire()
    finally:
        process.kill(); process.communicate(timeout=10)
    with RunLock(settings.database_path) as recovered:
        assert recovered.recovered


@pytest.mark.parametrize('error,status_name', [(RuntimeError, 'FAILED'), (KeyboardInterrupt, 'CANCELLED')])
def test_exception_or_cancellation_finishes_run_and_releases_lock(settings, monkeypatch, error, status_name):
    agent = runner(settings)
    original = SocialScanService.run_sync
    def failed(*args, **kwargs):
        raise error('private secret')
    monkeypatch.setattr(SocialScanService, 'run_sync', failed)
    result = agent.run_once()
    assert result.status == status_name and not agent.lock.state()['active']
    with Database(settings.database_path) as db:
        assert db.get_row('agent_runs', result.run_id)['status'] == status_name
    monkeypatch.setattr(SocialScanService, 'run_sync', original)
    assert agent.run_once().status == 'SUCCESS'


def test_partial_source_failure_keeps_other_source_processing(settings):
    bad = FailingSource()
    result = runner(settings, adapters=[bad, MockSourceAdapter('working')]).run_once()
    assert result.status == 'PARTIAL_SUCCESS'
    assert bad.calls == 1 and result.observations_created > 0
    assert result.trend_count > 0 and any(r['status'] == 'OK' for r in result.social_scan_result)
    assert 'sensitive-token' not in json.dumps(asdict(result))


def test_all_source_failures_mark_failed(settings):
    result = runner(settings, adapters=[FailingSource()]).run_once()
    assert result.status == 'FAILED' and result.errors


def test_transient_source_retry_is_bounded_and_nontransient_is_not_retried(settings):
    recovered = FailingSource(TimeoutError, failures=1)
    assert runner(settings, adapters=[recovered]).run_once().status == 'SUCCESS'
    assert recovered.calls == 2
    exhausted = FailingSource(TimeoutError)
    assert runner(settings, adapters=[exhausted]).run_once().status == 'FAILED'
    assert exhausted.calls == settings.agent_provider_max_retries + 1
    validation = FailingSource(ValueError)
    runner(settings, adapters=[validation]).run_once()
    assert validation.calls == 1


def test_error_budget_stops_remaining_providers_and_optional_stages(settings):
    settings = settings.model_copy(update={'agent_max_errors_per_run': 1})
    bad, skipped = FailingSource(), FailingSource()
    result = runner(settings, adapters=[bad, skipped]).run_once()
    assert result.status == 'FAILED' and bad.calls == 1 and skipped.calls == 0
    assert any('Error budget' in warning for warning in result.warnings)
    assert result.notifications_sent == 0


def test_regivion_failure_isolated_by_ticker_and_retry_limit(settings):
    class Provider(MockRegivionClient):
        def __init__(self):
            super().__init__(); self.calls = 0
        def get_ticker(self, symbol):
            if symbol == 'MSFT':
                self.calls += 1
                raise TimeoutError('secret')
            return super().get_ticker(symbol)
    provider = Provider()
    result = runner(settings, regivion=provider, sleeper=lambda _: False).run_once()
    assert result.status == 'PARTIAL_SUCCESS'
    assert provider.calls == 3 and 'NVDA' in {o['symbol'] for o in result.opportunities}


def test_llm_failure_preserves_opportunities_and_retries_on_next_run(settings):
    provider = MockLLMProvider(fail_for_symbols={'MSFT'})
    agent = runner(settings, llm=provider)
    first = agent.run_once()
    assert first.status == 'PARTIAL_SUCCESS'
    with Database(settings.database_path) as db:
        assert db.get_recent_opportunity('MSFT') is not None
        assert db.get_config('agent_content_pending:MSFT')
    provider.fail_for_symbols.clear()
    recovered = agent.run_once()
    assert recovered.status == 'SUCCESS' and recovered.review_items_created == 1
    assert recovered.review_handoff[0]['symbol'] == 'MSFT'


def test_notifier_failure_keeps_candidates_and_retries_without_regeneration(settings):
    class Broken:
        def send(self, items):
            raise RuntimeError('secret')
    agent = runner(settings, notifier=Broken())
    first = agent.run_once()
    assert first.status == 'PARTIAL_SUCCESS' and first.content_candidates_created == 6
    agent.notifier = MockReviewNotifier()
    recovered = agent.run_once()
    assert recovered.notifications_sent == 1 and recovered.content_candidates_created == 0
    assert len(agent.notifier.batches) == 1


def test_factuality_rejection_is_not_retried_or_queued(settings):
    agent = runner(settings, llm=MockLLMProvider(malformed_response=True))
    result = agent.run_once()
    assert result.content_candidates_created == 0 and result.notifications_sent == 0
    assert any('rejected by factuality' in w for w in result.warnings)
    with Database(settings.database_path) as db:
        assert db.execute('SELECT COUNT(*) FROM content_candidates').fetchone()[0] == 0


def test_audience_refresh_interval_and_failure_isolation(settings):
    settings = settings.model_copy(update={'agent_audience_refresh_enabled': True, 'audience_provider': 'mock'})
    agent = runner(settings)
    assert agent.run_once().audience_refresh_result['status'] == 'OK'
    assert agent.run_once().audience_refresh_result['status'] == 'NOT_DUE'
    agent.clock = lambda: NOW + timedelta(hours=25)
    assert agent.run_once().audience_refresh_result['status'] == 'OK'
    bad = settings.model_copy(update={'audience_provider': 'archive', 'audience_archive_path': 'missing.json'})
    other = runner(bad)
    other.clock = lambda: NOW + timedelta(hours=50)
    failed = other.run_once()
    assert failed.status == 'PARTIAL_SUCCESS' and failed.audience_refresh_result['status'] == 'FAILED'
    assert failed.opportunities


def test_archive_audience_refresh_does_not_import(tmp_path, settings):
    archive = tmp_path / 'audience.json'
    archive.write_text(json.dumps({'following': [{'id': 'real', 'username': 'REAL'}]}))
    settings = settings.model_copy(update={'agent_audience_refresh_enabled': True, 'audience_provider': 'archive', 'audience_archive_path': str(archive)})
    result = runner(settings).run_once()
    assert result.audience_refresh_result == {'status': 'OK', 'source': 'archive', 'accounts': 1, 'persisted': False}
    with Database(settings.database_path) as db:
        assert db.execute('SELECT COUNT(*) FROM audience_import_runs').fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM audience_accounts WHERE source='X_ARCHIVE'").fetchone()[0] == 0


def test_watch_injected_sleep_trigger_schedule_and_clean_stop(settings):
    intervals, schedules = [], []
    agent = runner(settings)
    def sleeper(seconds):
        intervals.append(seconds)
        schedules.append(agent.lock.read_metadata()['next_run_at'])
        assert agent.lock.state()['active']
        return False
    agent.sleeper = sleeper
    results = agent.watch(interval_seconds=60, cycles=2)
    assert intervals == [60] and schedules[0] is not None
    assert [r.trigger_type for r in results] == ['WATCH', 'WATCH']
    assert not agent.lock.state()['active'] and agent.lock.state()['next_run_at'] is None


def test_watch_ctrl_c_while_waiting_releases_lock(settings):
    def interrupt(_):
        raise KeyboardInterrupt
    agent = runner(settings, sleeper=interrupt)
    results = agent.watch(interval_seconds=60, cycles=2)
    assert len(results) == 1 and not agent.lock.state()['active']


def test_watch_run_on_start_false_and_minimum_interval(settings):
    settings = settings.model_copy(update={'agent_run_on_start': False})
    waits = []
    agent = runner(settings, sleeper=lambda seconds: waits.append(seconds) or False)
    assert len(agent.watch(interval_seconds=60, cycles=1)) == 1
    assert waits == [60]
    with pytest.raises(ValueError, match='MIN_INTERVAL'):
        agent.watch(interval_seconds=1, cycles=1)


def test_status_doctor_and_provider_visibility_are_honest(settings):
    runner(settings).run_once()
    report = status(settings)
    assert report['status'] == 'HEALTHY' and report['pending_review'] == 6 and report['ready_to_post'] == 0
    assert 'mock' in report['providers']['social'] and report['providers']['regivion'] == 'mock'
    assert report['providers']['content'] == 'LLM/mock'
    assert report['providers']['X posting'] == report['providers']['X relationship actions'] == 'DISABLED'
    checks = doctor(settings)
    assert not any(c['status'] == 'FAIL' for c in checks)
    assert any(c['name'] == 'Audience database' and c['status'] == 'WARN' for c in checks)


@pytest.mark.parametrize('overrides', [{'environment': 'production'}, {'allow_x_posting': True},
                                     {'allow_x_follow_actions': True}, {'agent_social_provider': 'live'},
                                     {'agent_regivion_provider': 'http'}, {'ai_provider': 'unconfigured-live'}])
def test_production_and_unsafe_provider_settings_fail_before_pipeline(settings, overrides):
    unsafe = settings.model_copy(update=overrides)
    with pytest.raises(ValueError):
        runner(unsafe).run_once()
    assert not unsafe.database_path.exists()
    assert any(c['status'] == 'FAIL' for c in doctor(unsafe))


def test_env_file_precedence_and_data_directory(monkeypatch, tmp_path):
    envfile = tmp_path / '.exitvector.env'
    envfile.write_text('AGENT_SCAN_INTERVAL_MINUTES=45\nAGENT_LOG_LEVEL=DEBUG\nAGENT_DATA_DIR=custom-data\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('AGENT_SCAN_INTERVAL_MINUTES', '20')
    settings = load_settings()
    assert settings.agent_scan_interval_minutes == 20 and settings.agent_log_level == 'DEBUG'
    assert settings.database_path == Path('custom-data') / 'exitvector.db'


def test_rotating_logs_redact_credentials_and_provider_exceptions(settings):
    settings = settings.model_copy(update={'regivion_api_key': 'super-secret-key'})
    logger = configure_operational_logging(settings)
    logger.info('run_start super-secret-key', extra={'context': {'api_key': 'super-secret-key'}})
    filehandler = next(h for h in logger.handlers if hasattr(h, 'maxBytes'))
    filehandler.maxBytes = 200
    for _ in range(10):
        logger.info('bounded daily operational record')
    for handler in logger.handlers:
        handler.flush()
    assert (settings.agent_log_dir / 'exitvector.log.1').exists()
    for path in settings.agent_log_dir.glob('*'):
        assert 'super-secret-key' not in path.read_text()
    record = logging.LogRecord('test', logging.INFO, '', 0, 'token=private-value', (), None)
    assert 'private-value' not in SafeJsonFormatter().format(record)


def test_backup_integrity_no_overwrite_and_paths_with_spaces(settings):
    runner(settings).run_once()
    target = settings.agent_data_dir / 'backups with spaces' / 'first.db'
    with Database(settings.database_path, read_only=True) as db:
        db.backup_to(target)
        with pytest.raises(FileExistsError):
            db.backup_to(target)
    assert db_check(target)['ok'] and db_check(settings.database_path)['ok']
    assert state(target) == state(settings.database_path)


def cli(settings, *args, env_extra=None):
    env = os.environ.copy()
    env.update({'EXITVECTOR_DATABASE_URL': 'sqlite:///' + str(settings.database_path),
                'AGENT_LOG_DIR': str(settings.agent_log_dir), 'AGENT_DATA_DIR': str(settings.agent_data_dir),
                'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'), 'PYTHONIOENCODING': 'utf-8'})
    env.update(env_extra or {})
    return subprocess.run([sys.executable, '-m', 'exitvector_agent', *args], env=env,
                          capture_output=True, text=True, encoding='utf-8', timeout=20)


def test_run_quiet_verbose_and_dry_cli_modes(settings):
    dry = cli(settings, 'run', '--dry-run')
    assert dry.returncode == 0 and 'DRY RUN' in dry.stdout and not settings.database_path.exists()
    quiet = cli(settings, 'run', '--quiet')
    assert quiet.returncode == 0 and quiet.stdout == '' and quiet.stderr == ''
    verbose = cli(settings, 'run', '--verbose')
    assert verbose.returncode == 0 and 'components' in verbose.stdout and 'notification_eligible' in verbose.stdout
    assert 'No automatic posts were made' in verbose.stdout


@pytest.mark.parametrize('command', ['status', 'doctor', 'db-check', 'backup', 'review', 'ready', 'notifications'])
def test_operational_cli_commands(settings, command):
    runner(settings).run_once()
    result = cli(settings, command)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip()


def test_review_cli_requires_human_approval_and_revalidates_edits(settings):
    first = runner(settings).run_once()
    identity = str(first.review_handoff[0]['candidate_id'])
    assert json.loads(cli(settings, 'ready').stdout) == []
    edited = cli(settings, 'review', 'edit', identity, '--text', '$MSFT will reach $999 tomorrow')
    assert edited.returncode == 2
    approved = cli(settings, 'review', 'approve', identity, '--reviewer', 'human')
    assert approved.returncode == 0
    assert len(json.loads(cli(settings, 'ready').stdout)) == 1
    assert cli(settings, 'review', 'archive', identity).returncode == 0
    assert json.loads(cli(settings, 'ready').stdout) == []


def test_notification_inbox_read_and_watch_cli(settings):
    runner(settings).run_once()
    unread = json.loads(cli(settings, 'notifications', '--unread').stdout)
    assert len(unread) == 2
    assert cli(settings, 'notifications', 'read', str(unread[0]['id'])).returncode == 0
    assert len(json.loads(cli(settings, 'notifications', '--unread').stdout)) == 1
    watched = cli(settings, 'watch', '--interval', '0.01s', '--cycles', '2', env_extra={'AGENT_MIN_INTERVAL_SECONDS': '0.001'})
    assert watched.returncode == 0 and 'ExitVector stopped safely.' in watched.stdout


def test_cli_invalid_configuration_does_not_print_secret_values(settings):
    result = cli(settings, 'run', env_extra={'AGENT_PROVIDER_MAX_RETRIES': 'private-secret-value'})
    assert result.returncode == 2 and 'private-secret-value' not in result.stdout + result.stderr


@pytest.mark.parametrize('command', ['scan', 'opportunities', 'content', 'audience'])
def test_production_cannot_bypass_mock_prohibition_with_legacy_commands(settings, command):
    result = cli(settings, command, env_extra={'EXITVECTOR_ENV': 'production'})
    assert result.returncode == 2 and 'mock fallback is prohibited' in result.stdout
    assert not settings.database_path.exists()
