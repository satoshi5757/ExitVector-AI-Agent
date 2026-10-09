"""Offline contract tests based on the user-supplied sanitized production shape."""
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta

import httpx
import pytest

from test_phase9_live import (NOW, FixtureAPI, fixture_runner, live_settings, offline, reddit_listing)
from exitvector_agent.config import Settings
from exitvector_agent.content import ContentBrief, validate_content
from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.live_checks import live_check
from exitvector_agent.opportunity_service import OpportunityService
from exitvector_agent.provider_health import ProviderHealth, capabilities
from exitvector_agent.regivion import HTTPRegivionClient
from exitvector_agent.social.scan import SocialScanService


def production_payload():
    return {
        'api_version': 'v1', 'symbol': 'MSFT', 'generated_at': NOW.isoformat(),
        'psc': {'score': 96.2, 'rank': None, 'previous_rank': None, 'status': None,
                'entered_top_20': None, 'exited_top_20': None, 'rank_acceleration': None,
                'portfolio_key': 'psc_legacy_auto', 'scoring_profile': 'psc_legacy', 'as_of': '2026-09-29'},
        'alerts': [],
        'fundamentals': {'revenue_growth_yoy': None, 'earnings_growth_yoy': None,
                         'free_cash_flow_growth': None, 'forward_pe': 25.25086417075335,
                         'peg': 1.3255409332062755, 'profitability_status': None, 'as_of': '2026-09-22'},
        'insiders': {'recent_buys': [], 'recent_sells': [{
            'transaction_id': 'insider-1', 'direction': 'SELL', 'transaction_date': '2026-09-14',
            'disclosure_date': '2026-09-15', 'shares': None, 'value_min': None,
            'value_max': None, 'source': 'filing'}], 'as_of': '2026-09-16T11:34:34.624125Z'},
        'politicians': {'recent_trades': [{
            'transaction_id': 'politician-1', 'chamber': 'HOUSE', 'direction': 'BUY',
            'transaction_date': '2026-08-14', 'disclosure_date': '2026-09-15',
            'amount_min': 500001, 'amount_max': 1000000, 'source': 'disclosure'}],
            'as_of': '2026-09-16T11:34:34.919524Z'},
        'market': {'price': None, 'daily_change_pct': None, 'volume': None,
                   'average_volume': None, 'as_of': None},
        'coverage': {'psc': True, 'alerts': False, 'fundamentals': True,
                     'insiders': True, 'politicians': True, 'market': False}}


def client_for(payload=None, handler=None, health=None):
    calls = []
    def api(request):
        calls.append(request)
        assert request.headers['authorization'] == 'Bearer fixture-only'
        if handler:
            return handler(request)
        if request.url.path == '/api/agent/v1/health':
            return httpx.Response(200, json={'capabilities': {'psc': True, 'alerts': True, 'market': False}})
        assert request.url.path == '/api/agent/v1/ticker/MSFT'
        return httpx.Response(200, json=payload if payload is not None else production_payload())
    client = HTTPRegivionClient(base_url='https://regivion.com', api_key='fixture-only',
        http_client=httpx.Client(transport=httpx.MockTransport(api)), clock=lambda: NOW, health=health)
    return client, calls


def test_production_normalization_nulls_flows_freshness_and_cache():
    client, calls = client_for()
    row = client.get_ticker('MSFT')
    assert row.psc_score == 96.2
    assert row.psc_rank is row.previous_psc_rank is row.rank_change is None
    assert row.entered_top_20 is row.exited_top_20 is row.rank_acceleration is None
    assert row.revenue_growth_yoy is row.earnings_growth_yoy is row.free_cash_flow_growth is None
    assert row.forward_pe == 25.25086417075335 and row.peg == 1.3255409332062755
    assert row.recent_alerts == row.recent_insider_buys == []
    sale = row.recent_insider_sells[0]
    assert sale.action == 'sell' and sale.source_id == 'insider-1'
    assert sale.timestamp.date().isoformat() == '2026-09-14'
    assert sale.disclosure_date.date().isoformat() == '2026-09-15'
    trade = row.recent_politician_trades[0]
    assert trade.action == 'buy' and trade.amount_min == 500001 and trade.amount_max == 1000000
    assert trade.amount_range is None and trade.source_id == 'politician-1'
    assert row.raw['coverage']['market'] is False and all(value is None for value in row.raw['market'].values())
    provenance = row.raw['provenance']
    assert provenance['contract'] == 'agent-v1' and provenance['base_host'] == 'regivion.com'
    assert provenance['provider_source'] == 'REGIVION_HTTP' and provenance['is_live_data']
    assert provenance['components']['psc']['source_timestamp'].startswith('2026-09-29')
    assert provenance['components']['psc']['age_seconds'] > 8 * 86400
    assert provenance['components']['psc']['stale'] and provenance['stale']
    assert provenance['received_timestamp'] == NOW.isoformat()
    assert client.get_ticker('MSFT') == row and len(calls) == 1
    client.clock = lambda: NOW + timedelta(seconds=10)
    aged = client.get_ticker('MSFT')
    assert aged.raw['provenance']['components']['psc']['age_seconds'] == provenance['components']['psc']['age_seconds'] + 10
    assert aged.raw['provenance']['received_timestamp'] == provenance['received_timestamp']


@pytest.mark.parametrize('component', ['psc', 'fundamentals', 'alerts', 'insiders', 'politicians', 'market'])
def test_optional_components(component):
    payload = production_payload()
    del payload[component]
    client, _ = client_for(payload)
    row = client.get_ticker('MSFT')
    assert row.symbol == 'MSFT'
    if component == 'psc':
        assert row.psc_score is row.psc_rank is None


@pytest.mark.parametrize('coverage', [True, False, None])
def test_empty_alert_coverage_states_preserved(coverage):
    payload = production_payload()
    payload['coverage']['alerts'] = coverage
    client, _ = client_for(payload)
    row = client.get_ticker('MSFT')
    assert row.recent_alerts == [] and row.raw['coverage']['alerts'] is coverage


def test_false_coverage_suppresses_unusable_alert_records():
    payload = production_payload()
    payload['alerts'] = [{'name': 'old alert', 'direction': 'bullish'}]
    client, _ = client_for(payload)
    assert client.get_ticker('MSFT').recent_alerts == []


def test_usable_alerts_insider_buys_and_duplicate_events():
    payload = production_payload()
    payload['coverage']['alerts'] = True
    payload['alerts'] = [{'name': 'Momentum', 'type': 'momentum', 'direction': 'bullish',
                          'strength': 80, 'timestamp': NOW.isoformat()}]
    buy = {'transaction_id': 'buy-1', 'direction': 'BUY', 'transaction_date': '2026-10-07',
           'disclosure_date': '2026-10-08', 'value_min': 100, 'value_max': 200}
    payload['insiders']['recent_buys'] = [buy, deepcopy(buy)]
    client, _ = client_for(payload)
    row = client.get_ticker('MSFT')
    assert row.bullish_alerts[0].category == 'momentum'
    assert row.bullish_alerts[0].timestamp == NOW
    assert len(row.recent_insider_buys) == 1
    assert row.recent_insider_buys[0].estimated_value is None
    assert row.recent_insider_buys[0].value_min == 100
    assert row.recent_insider_buys[0].value_max == 200


@pytest.mark.parametrize('date', [None, 'invalid', '2026-10-10'])
def test_unknown_or_future_source_never_refreshed_by_generated_at(date):
    payload = production_payload()
    payload['psc']['as_of'] = date
    client, _ = client_for(payload)
    row = client.get_ticker('MSFT')
    assert row.raw['provenance']['components']['psc']['stale']
    assert row.raw['provenance']['stale']


def test_unknown_response_fields_not_persisted():
    payload = production_payload()
    payload['debug'] = {'credential': 'fixture-only'}
    payload['psc']['unrecognized'] = 'fixture-only'
    client, _ = client_for(payload)
    assert 'fixture-only' not in json.dumps(client.get_ticker('MSFT').raw)


def test_malformed_health_rejected():
    client, _ = client_for(handler=lambda request: httpx.Response(200, json=[]))
    with pytest.raises(ValueError, match='health'):
        client.check_health()


@pytest.mark.parametrize('payload', [[], {'symbol': 'OTHER'}, {'symbol': 'MSFT', 'psc': []},
                                   {'symbol': 'MSFT', 'insiders': {'recent_sells': 'bad'}},
                                   {'symbol': 'MSFT', 'coverage': 'bad'}])
def test_malformed_never_cached(payload):
    client, _ = client_for(payload)
    with pytest.raises(ValueError):
        client.get_ticker('MSFT')
    assert client.cache == {}


def test_health_authentication_status_and_no_secrets(tmp_path, caplog):
    settings = live_settings(tmp_path).model_copy(update={'agent_regivion_provider': 'http',
        'regivion_base_url': 'https://regivion.com', 'regivion_api_key': 'fixture-only'})
    with Database(tmp_path / 'health.db') as db:
        ensure_schema(db)
        health = ProviderHealth('regivion', settings, db)
        client, calls = client_for(health=health)
        assert not capabilities(settings, db)[2]['live']
        client.get_ticker('MSFT')
        assert [r.url.path for r in calls] == ['/api/agent/v1/health', '/api/agent/v1/ticker/MSFT']
        status = capabilities(settings, db)[2]
        assert status['authenticated'] and status['reachable'] and status['live']
        assert status['contract'] == 'agent-v1'
        persisted = db.get_config('provider_health:regivion')
        assert 'fixture-only' not in persisted + json.dumps(client.get_ticker('MSFT').raw) + caplog.text


@pytest.mark.parametrize('code', [401, 403, 503])
def test_health_failure_no_fallback(tmp_path, code):
    health = ProviderHealth('regivion', live_settings(tmp_path))
    client, calls = client_for(handler=lambda r: httpx.Response(code, json={}), health=health)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_ticker('MSFT')
    assert not client.cache and len(calls) == 1
    assert health.metrics['requests_failed'] == 1
    if code == 401:
        assert health.state['authenticated'] is False


@pytest.mark.parametrize('code', [200, 401])
def test_live_check_authenticated_health_without_inference(tmp_path, code):
    settings = live_settings(tmp_path).model_copy(update={'agent_regivion_provider': 'http',
        'regivion_base_url': 'https://regivion.com', 'regivion_api_key': 'fixture-only'})
    api = FixtureAPI()
    def handler(request):
        if request.url.host == 'regivion.com':
            assert request.url.path == '/api/agent/v1/health'
            assert request.headers['authorization'] == 'Bearer fixture-only'
            return httpx.Response(code, json={'capabilities': {'psc': True}})
        return api(request)
    rows = live_check(settings, transport=httpx.MockTransport(handler))
    regivion = next(row for row in rows if row['name'] == 'Regivion')
    assert regivion['status'] == ('PASS' if code == 200 else 'FAIL')
    assert not settings.database_path.exists()
    assert not any(r.url.path == '/v1/responses' for r in api.requests)


@pytest.mark.parametrize('changes', [{}, {'regivion_base_url': 'http://regivion.com'},
    {'regivion_base_url': 'https://localhost'}, {'regivion_api_key': None},
    {'regivion_contract': 'valuation-history'}, {'agent_regivion_provider': 'mock'},
    {'regivion_base_url': 'https://other.example'}, {'regivion_base_url': 'https://regivion.com?token=x'}])
def test_production_config(tmp_path, changes):
    settings = live_settings(tmp_path).model_copy(update={'environment': 'production',
        'agent_regivion_provider': 'http', 'regivion_base_url': 'https://regivion.com',
        'regivion_api_key': 'fixture-only', **changes})
    if changes:
        with pytest.raises(ValueError):
            settings.validate_operation()
    else:
        settings.validate_operation()


def score_only_brief(tmp_path):
    client, _ = client_for()
    with Database(tmp_path / 'brief.db') as db:
        ensure_schema(db)
        trends = SocialScanService(db).run_sync()
        opportunity = OpportunityService(db, client, live_mode=True).scan(trends=[trend for trend in trends if trend.ticker == 'MSFT'])[0]
        assert opportunity.regivion_score > 0 and opportunity.market_score is None
        assert opportunity.confidence == 'LOW' and opportunity.freshness_score == 0
        assert 'rank' not in opportunity.regivion_summary
        return ContentBrief.from_opportunity(opportunity)


@pytest.mark.parametrize('text', ['$MSFT is ranked #96.2', '$MSFT entered Top 20',
    '$MSFT rank acceleration is strong', '$MSFT has a fresh bullish alert',
    '$MSFT revenue growth is strong', '$MSFT earnings growth is accelerating',
    '$MSFT has a technical breakout', '$MSFT current price is 96.2'])
def test_score_without_rank_rejects_unsupported_claims(tmp_path, text):
    assert not validate_content(text, score_only_brief(tmp_path)).valid


def test_score_without_rank_brief_supported_facts(tmp_path):
    brief = score_only_brief(tmp_path)
    assert validate_content('$MSFT PSC score 96.2.', brief).valid
    assert validate_content('$MSFT PSC score 96.2, source date 2026-09-29.', brief).valid
    assert any('2026-09-29' in fact for fact in brief.allowed_facts)
    assert any('Forward PE' in fact for fact in brief.allowed_facts)


def test_repeat_run_dedup_and_dry_run_isolation(tmp_path):
    settings = live_settings(tmp_path).model_copy(update={'agent_regivion_provider': 'http',
        'regivion_base_url': 'https://regivion.com', 'regivion_api_key': 'fixture-only'})
    api = FixtureAPI()
    api.listing = reddit_listing(200)
    settings = settings.model_copy(update={'notify_threshold': 65})
    runner = fixture_runner(settings, api)
    runner.regivion, calls = client_for()
    dry = runner.run_once(symbol='MSFT', dry_run=True)
    assert not settings.database_path.exists()
    first = runner.run_once(symbol='MSFT')
    second = runner.run_once(symbol='MSFT')
    assert dry.status == first.status == second.status == 'SUCCESS'
    assert first.content_candidates_created > 0 and second.content_candidates_created == 0, (first.opportunities, first.warnings, first.content_generation_result)
    assert second.observations_created == second.notifications_sent == 0
    assert second.review_items_created == 0
    with Database(settings.database_path) as db:
        snapshot = db.get_regivion_snapshot('MSFT')['payload']
        assert 'fixture-only' not in snapshot
        brief = json.loads(db.execute('SELECT brief_snapshot FROM content_candidates LIMIT 1').fetchone()[0])
        assert any('2026-09-29' in fact for fact in brief['allowed_facts'])
        assert brief['data_provenance']['regivion']['contract'] == 'agent-v1'


def test_dry_run_migrates_legacy_notifications_only_on_backup(tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path
    from exitvector_agent.review import MockReviewNotifier

    settings = live_settings(tmp_path).model_copy(update={'agent_regivion_provider': 'http',
        'regivion_base_url': 'https://regivion.com', 'regivion_api_key': 'fixture-only'})
    with Database(settings.database_path) as db:
        # Exact seven-column notifications schema observed in the real database.
        db.execute('''CREATE TABLE notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
            score REAL NOT NULL, channel TEXT NOT NULL, payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, delivered_at TEXT)''')
        db.execute("INSERT INTO notifications(ticker,score,channel,payload) VALUES('MSFT',75,'console','{}')")
        ensure_schema(db)
        # Keep all other tables current and roll back just this migration to
        # reproduce the actual failure without coupling to unrelated migrations.
        db.execute('DROP INDEX notifications_event_key')
        for column in ('candidate_id', 'review_action', 'deduplication_key', 'opportunity_id', 'is_read'):
            db.execute(f'ALTER TABLE notifications DROP COLUMN {column}')
        db.commit()

    before = hashlib.sha256(settings.database_path.read_bytes()).hexdigest()
    copied = []
    backup = Database.backup_to
    def observe_backup(self, target):
        copied.append(Path(target))
        return backup(self, target)
    monkeypatch.setattr(Database, 'backup_to', observe_backup)
    notifier = MockReviewNotifier()
    runner = fixture_runner(settings, FixtureAPI())
    runner.notifier = notifier
    runner.regivion, calls = client_for()
    result = runner.run_once(symbol='MSFT', dry_run=True)
    assert result.status == 'SUCCESS'
    assert result.provider_metrics['regivion']['requests_succeeded'] == 2
    assert result.provider_status[2]['authenticated'] is True
    assert result.notifications_sent == 0
    assert notifier.batches == []
    assert copied and all(not path.parent.exists() for path in copied)
    assert hashlib.sha256(settings.database_path.read_bytes()).hexdigest() == before
    with Database(settings.database_path, read_only=True) as db:
        assert 'deduplication_key' not in {row['name'] for row in db.execute('PRAGMA table_info(notifications)')}
        assert db.execute('SELECT COUNT(*) FROM notifications').fetchone()[0] == 1
        for table in ('agent_runs', 'opportunities', 'content_candidates', 'review_audit'):
            assert db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0
        assert db.get_config('provider_health:regivion') is None


def test_legacy_notification_migration_preserves_rows_and_is_idempotent(tmp_path):
    with Database(tmp_path / 'legacy.db') as db:
        db.execute('''CREATE TABLE notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
            score REAL NOT NULL, channel TEXT NOT NULL, payload TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, delivered_at TEXT)''')
        db.execute("INSERT INTO notifications(ticker,score,channel,payload) VALUES('MSFT',75,'console','{}')")
        ensure_schema(db)
        ensure_schema(db)
        row = db.execute('SELECT * FROM notifications').fetchone()
        assert row['ticker'] == 'MSFT' and row['payload'] == '{}'
        assert row['candidate_id'] is row['review_action'] is row['deduplication_key'] is None
        assert row['opportunity_id'] is None and row['is_read'] == 0
        assert any(row['name'] == 'notifications_event_key' for row in db.execute('PRAGMA index_list(notifications)'))
