from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from exitvector_agent.agent import AgentRunner
from exitvector_agent.config import Settings
from exitvector_agent.content import ContentBrief, GenerationLimitReached, LLMContentGenerator, validate_content
from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.live_checks import live_check
from exitvector_agent.live_providers import OpenAIProvider, RedditLiveSource, StocktwitsLiveSource
from exitvector_agent.operations import doctor, status
from exitvector_agent.provider_health import CircuitOpen, ProviderHealth, capabilities
from exitvector_agent.provider_setup import DisabledRegivionClient, create_providers, mode_label, regivion_target
from exitvector_agent.regivion import HTTPRegivionClient
from exitvector_agent.review import MockReviewNotifier, ReviewHandoffService
from exitvector_agent.social.scan import SocialScanService
from exitvector_agent.social.sources import MockSourceAdapter, SourceRunner

NOW = datetime(2026, 10, 8, 9, tzinfo=timezone.utc)


class FixedDate(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for module in ('social.scan', 'social.sources', 'opportunity_service', 'content'):
        monkeypatch.setattr('exitvector_agent.' + module + '.datetime', FixedDate)
    def forbidden(*args, **kwargs):
        raise AssertionError('Phase 9 tests must not connect to network')
    original_connect = socket.socket.connect
    def checked_connect(sock, address):
        if isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}:
            return original_connect(sock, address)  # Windows asyncio self-pipe only.
        return forbidden()
    monkeypatch.setattr(socket.socket, 'connect', checked_connect)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def live_settings(tmp_path, **overrides):
    return Settings(database_url='sqlite:///' + str(tmp_path / 'live data' / 'agent.db'),
        agent_log_dir=tmp_path / 'logs', agent_social_provider='live', reddit_enabled=True,
        reddit_client_id='synthetic-id', reddit_client_secret='synthetic-secret',
        reddit_user_agent='windows:exitvector-fixture:1 (by /u/example)', reddit_subreddits='stocks',
        agent_regivion_provider='disabled', regivion_required=False, ai_provider='openai',
        ai_model='configured-test-model', llm_api_key='synthetic-openai-key', agent_retry_backoff_seconds=0,
        **overrides)


def reddit_listing(count=40, *, age_minutes=5):
    return {'kind': 'Listing', 'data': {'children': [{'kind': 't3', 'data': {
        'id': 'post' + str(i), 'created_utc': (NOW - timedelta(minutes=age_minutes)).timestamp(),
        'title': '$MSFT stock momentum', 'selftext': 'MSFT shares rally; $NVDA trading.',
        'author': 'private-author-' + str(i), 'score': 100, 'num_comments': 5,
        'permalink': '/r/stocks/comments/post' + str(i)}} for i in range(count)]}}


def valuation_payload():
    return {'symbol': 'MSFT', 'history': [{'symbol': 'MSFT', 'as_of': '2026-10-08',
        'captured_at': NOW.isoformat(), 'forward_pe': 18.5, 'peg_normalized': 1.1}],
        'averages': {'n_rows': 1}}


def openai_payload(text='$MSFT social attention is accelerating.', variant='PUNCHY'):
    return {'id': 'synthetic-response', 'status': 'completed', 'model': 'configured-test-model',
        'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'text': text, 'variant_type': variant})}]}],
        'usage': {'input_tokens': 100, 'output_tokens': 20}}


class FixtureAPI:
    def __init__(self):
        self.requests = []
        self.listing = reddit_listing()
        self.valuation = valuation_payload()
        self.fail_host = None
    def __call__(self, request):
        self.requests.append(request)
        if request.url.host == self.fail_host:
            return httpx.Response(503, json={'error': 'synthetic outage'})
        if request.url.path == '/api/v1/access_token':
            return httpx.Response(200, json={'access_token': 'synthetic-oauth-token', 'expires_in': 3600})
        if request.url.host == 'oauth.reddit.com':
            return httpx.Response(200, json=self.listing)
        if request.url.path.startswith('/api/valuation-history/'):
            data = dict(self.valuation)
            data['symbol'] = request.url.path.rsplit('/', 1)[-1]
            return httpx.Response(200, json=data)
        if request.url.path == '/livez':
            return httpx.Response(200, json={'ok': True})
        if request.url.path.startswith('/v1/models/'):
            return httpx.Response(200, json={'id': 'configured-test-model'})
        if request.url.path == '/v1/responses':
            body = json.loads(request.content)
            variant = body['text']['format']['schema']['properties']['variant_type']['enum'][0]
            brief = json.loads(body['input'])
            text = {'PUNCHY': f"${brief['symbol']} social attention is accelerating.",
                    'DATA_DRIVEN': f"${brief['symbol']}: {brief['social_summary']}.",
                    'QUESTION': f"Could ${brief['symbol']} deserve a closer look as social attention accelerates?"}[variant]
            return httpx.Response(200, json=openai_payload(text, variant))
        raise AssertionError('Unexpected API request: ' + str(request.url))


async def no_sleep(seconds):
    pass


def fixture_runner(settings, api):
    transport = httpx.MockTransport(api)
    reddit = RedditLiveSource(settings, transport=transport, clock=lambda: NOW, sleeper=no_sleep)
    llm = OpenAIProvider(settings, transport=transport)
    return AgentRunner(settings, adapters=[reddit], regivion=DisabledRegivionClient(), llm=llm,
                       notifier=MockReviewNotifier(), clock=lambda: NOW, sleeper=lambda seconds: False)


def brief_fixture(tmp_path):
    from exitvector_agent.opportunity_service import OpportunityService
    from exitvector_agent.regivion import MockRegivionClient
    with Database(tmp_path / 'brief.db') as db:
        ensure_schema(db)
        SocialScanService(db).run_sync()
        return ContentBrief.from_opportunity(OpportunityService(db, MockRegivionClient()).scan()[0])


def test_reddit_normalization_provenance_utc_privacy_and_dedup(tmp_path):
    settings = live_settings(tmp_path)
    api = FixtureAPI()
    source = RedditLiveSource(settings, transport=httpx.MockTransport(api), clock=lambda: NOW, sleeper=no_sleep)
    rows = asyncio.run(source.collect())
    assert len(rows) == 40 and rows[0].tickers == ['MSFT', 'NVDA']
    assert rows[0].source == 'REDDIT_LIVE' and rows[0].external_id == 't3_post0'
    assert rows[0].timestamp.utcoffset() == timedelta(0) and rows[0].raw_metadata['is_live_data']
    assert 'private-author' not in rows[0].author and rows[0].text == '$MSFT $NVDA'
    with Database(settings.database_path) as db:
        ensure_schema(db)
        service = SocialScanService(db, adapters=[source])
        first = service.run_sync(); second = service.run_sync()
        assert [asdict(t) for t in first] == [asdict(t) for t in second]
        assert db.execute('SELECT COUNT(*) FROM social_observations').fetchone()[0] == 40
        assert db.execute("SELECT COUNT(*) FROM social_observations WHERE author!=''").fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM ticker_mentions').fetchone()[0] == 80


@pytest.mark.parametrize('title,expected', [('$MSFT, stock momentum!', ['MSFT']), ('MSFT shares rally.', ['MSFT']),
    ('$msft stock; $nvda trading', ['MSFT', 'NVDA']), ('THE CEO AND FED', []), ('great day to relax', [])])
def test_live_shaped_ticker_extraction(tmp_path, title, expected):
    settings = live_settings(tmp_path)
    api = FixtureAPI(); api.listing = reddit_listing(1)
    item = api.listing['data']['children'][0]['data']; item.update(title=title, selftext='')
    source = RedditLiveSource(settings, transport=httpx.MockTransport(api), clock=lambda: NOW, sleeper=no_sleep)
    rows = asyncio.run(source.collect())
    assert (rows[0].tickers if rows else []) == expected


@pytest.mark.parametrize('payload', [{'data': {'children': []}}, reddit_listing(1, age_minutes=180)])
def test_reddit_empty_or_stale_ignored(tmp_path, payload):
    api = FixtureAPI(); api.listing = payload
    source = RedditLiveSource(live_settings(tmp_path), transport=httpx.MockTransport(api), clock=lambda: NOW, sleeper=no_sleep)
    assert asyncio.run(source.collect()) == []


@pytest.mark.parametrize('failure', ['401', '403', '429', '503', 'timeout', 'malformed'])
def test_reddit_failures_bounded_and_isolated(tmp_path, failure):
    settings = live_settings(tmp_path)
    calls = []
    def handler(request):
        calls.append(request)
        if failure == 'timeout':
            raise httpx.ReadTimeout('synthetic', request=request)
        if failure == 'malformed':
            return httpx.Response(200, text='not JSON')
        return httpx.Response(int(failure), json={}, headers={'retry-after': '0'})
    source = RedditLiveSource(settings, transport=httpx.MockTransport(handler), sleeper=no_sleep)
    result = asyncio.run(SourceRunner(retries=2, backoff_seconds=0).run(source))
    assert result.error and len(calls) <= 3
    assert len(calls) == (3 if failure in {'timeout', '429', '503'} else 1)


def test_reddit_pacing_honors_rate_limit_reset(tmp_path):
    settings = live_settings(tmp_path)
    api = FixtureAPI(); waits = []
    def handler(request):
        response = api(request)
        response.headers.update({'x-ratelimit-remaining': '0', 'x-ratelimit-reset': '7'})
        return response
    async def wait(seconds):
        waits.append(seconds)
    source = RedditLiveSource(settings, transport=httpx.MockTransport(handler), sleeper=wait, clock=lambda: NOW)
    asyncio.run(source.collect())
    assert waits and waits[0] > 6


def test_stocktwits_disabled_without_scraping():
    assert not StocktwitsLiveSource().is_configured()
    with pytest.raises(RuntimeError, match='disabled'):
        asyncio.run(StocktwitsLiveSource().collect())


def http_regivion(api, settings, **kwargs):
    return HTTPRegivionClient(base_url='http://127.0.0.1:8000', api_key='synthetic-read-token',
        contract='valuation-history', http_client=httpx.Client(transport=httpx.MockTransport(api)),
        health=ProviderHealth('regivion', settings), clock=lambda: NOW, **kwargs)


def test_real_discovered_regivion_shape_partial_normalization_and_cache(tmp_path):
    api = FixtureAPI(); settings = live_settings(tmp_path)
    client = http_regivion(api, settings)
    first = client.get_ticker('MSFT'); second = client.get_ticker('MSFT')
    assert first == second and len(api.requests) == 1
    assert first.forward_pe == 18.5 and first.peg == 1.1
    assert first.psc_score is first.psc_rank is first.previous_psc_rank is None
    assert not first.recent_alerts and not first.recent_insider_buys
    provenance = first.raw['provenance']
    assert provenance['source'] == 'REGIVION_HTTP' and provenance['age_seconds'] == 0
    assert provenance['source_timestamp'].endswith('+00:00') and not provenance['stale']
    assert client.health.metrics['cache_hits'] == 1
    assert api.requests[0].method == 'GET' and api.requests[0].url.path == '/api/valuation-history/MSFT'


@pytest.mark.parametrize('failure', ['401', '403', 'timeout', 'malformed', 'wrong-symbol'])
def test_regivion_invalid_responses_never_mock_fallback(tmp_path, failure):
    def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('synthetic', request=request)
        if failure.isdigit():
            return httpx.Response(int(failure), json={})
        return httpx.Response(200, json=[] if failure == 'malformed' else {'symbol': 'WRONG', 'history': []})
    client = http_regivion(handler, live_settings(tmp_path))
    with pytest.raises((httpx.HTTPError, ValueError)):
        client.get_ticker('MSFT')
    assert not client.cache


def test_regivion_staleness_unknown_dates_and_cache_expiry(tmp_path):
    api = FixtureAPI(); api.valuation['history'][0]['captured_at'] = (NOW - timedelta(days=3)).isoformat()
    client = http_regivion(api, live_settings(tmp_path), cache_ttl_seconds=1)
    assert client.get_ticker('MSFT').raw['provenance']['stale']
    client.clock = lambda: NOW + timedelta(seconds=2)
    client.get_ticker('MSFT')
    assert len(api.requests) == 2
    api.valuation['history'][0] = {'forward_pe': 12}
    client.cache.clear()
    assert client.get_ticker('MSFT').raw['provenance']['source_timestamp'] is None


def test_regivion_local_and_production_targets_and_server_contract_gate(tmp_path):
    settings = live_settings(tmp_path).model_copy(update={'agent_regivion_provider': 'http', 'regivion_required': True,
        'regivion_base_url': 'http://127.0.0.1:8000', 'regivion_api_key': 'synthetic', 'regivion_contract': 'valuation-history'})
    settings.validate_operation()
    assert '127.0.0.1' in regivion_target(settings)
    production = settings.model_copy(update={'environment': 'production'})
    with pytest.raises(ValueError, match='HTTPS Hetzner'):
        production.validate_operation()
    production = production.model_copy(update={'regivion_base_url': 'https://regivion.example.invalid'})
    assert 'Hetzner production target' in regivion_target(production)
    with pytest.raises(ValueError, match='lacks dedicated read-only'):
        production.validate_operation()


def test_openai_structured_brief_only_no_tools_no_storage(tmp_path):
    api = FixtureAPI(); settings = live_settings(tmp_path)
    provider = OpenAIProvider(settings, transport=httpx.MockTransport(api))
    brief = brief_fixture(tmp_path)
    response = provider.generate('Write a PUNCHY variant', brief)
    body = json.loads(api.requests[0].content)
    assert body['tools'] == [] and body['store'] is False
    assert json.loads(body['input']) == asdict(brief)
    assert 'audience' not in body['input'].lower() and 'private-author' not in body['input']
    assert body['text']['format']['strict'] and response.provider == 'openai'
    assert response.model == settings.ai_model and validate_content(response.text, brief).valid
    with pytest.raises(ValueError, match='ContentBrief only'):
        provider.generate('prompt', {'raw_reddit_history': 'never send this'})


@pytest.mark.parametrize('failure', ['401', '403', '429', '503', 'timeout', 'malformed', 'empty', 'refusal'])
def test_openai_provider_failures(tmp_path, failure):
    def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('synthetic', request=request)
        if failure.isdigit():
            return httpx.Response(int(failure), json={}, headers={'retry-after': '0'})
        data = openai_payload('' if failure == 'empty' else 'draft')
        if failure == 'malformed':
            data['output'][0]['content'][0]['text'] = '{invalid'
        if failure == 'refusal':
            data['status'] = 'incomplete'
        return httpx.Response(200, json=data)
    provider = OpenAIProvider(live_settings(tmp_path), transport=httpx.MockTransport(handler))
    with pytest.raises((ValueError, httpx.HTTPError)):
        provider.generate('PUNCHY variant', brief_fixture(tmp_path))
    assert provider.health.metrics['requests_failed'] == 1


@pytest.mark.parametrize('changes', [{'reddit_enabled': False}, {'reddit_client_secret': None},
    {'ai_model': None}, {'llm_api_key': None}, {'reddit_subreddits': '../escape'}, {'regivion_required': True}])
def test_live_config_fails_before_writes(tmp_path, changes):
    settings = live_settings(tmp_path).model_copy(update=changes)
    with pytest.raises(ValueError):
        AgentRunner(settings).run_once()
    assert not settings.database_path.exists()


@pytest.mark.parametrize('changes', [{'agent_social_provider': 'mock'}, {'agent_social_provider': 'mixed'},
    {'agent_regivion_provider': 'mock'}, {'ai_provider': 'mock'}, {'market_provider': 'mock'}])
def test_production_rejects_each_required_mock(tmp_path, changes):
    settings = live_settings(tmp_path).model_copy(update={'environment': 'production', **changes})
    with pytest.raises(ValueError, match='mock fallback is prohibited'):
        settings.validate_operation()


def test_production_explicit_missing_regivion_has_no_fallback(tmp_path):
    settings = live_settings(tmp_path, environment='production')
    settings.validate_operation()
    assert isinstance(create_providers(settings)[1], DisabledRegivionClient)
    assert create_providers(settings)[1].get_ticker('MSFT') is None


def test_live_check_mocked_and_without_credentials_no_business_writes(tmp_path):
    api = FixtureAPI(); settings = live_settings(tmp_path)
    rows = live_check(settings, transport=httpx.MockTransport(api))
    assert all(row['status'] != 'FAIL' for row in rows)
    assert any(row['name'] == 'OpenAI' and row['status'] == 'PASS' for row in rows)
    assert not any(request.url.path == '/v1/responses' for request in api.requests)
    assert not settings.database_path.exists()
    skipped = live_check(Settings())
    assert sum(row['status'] == 'SKIP' for row in skipped) >= 3


def test_circuit_health_persists_cools_down_and_metrics_are_safe(tmp_path):
    settings = live_settings(tmp_path, provider_circuit_failure_threshold=2)
    time_now = [1000]
    with Database(settings.database_path) as db:
        ensure_schema(db)
        health = ProviderHealth('openai', settings, db, clock=lambda: time_now[0])
        def broken():
            raise TimeoutError('synthetic-secret-must-not-persist')
        for _ in range(2):
            with pytest.raises(TimeoutError):
                health.perform(broken)
        with pytest.raises(CircuitOpen):
            health.perform(lambda: None)
        another = ProviderHealth('openai', settings, db, clock=lambda: time_now[0])
        with pytest.raises(CircuitOpen):
            another.check()
        time_now[0] += 301
        another.perform(lambda: 'ok')
        state = json.loads(db.get_config('provider_health:openai'))
        assert state['consecutive_failures'] == 0 and state['last_success_at']
        assert 'synthetic-secret' not in json.dumps(state)
        assert health.metrics['requests_attempted'] == health.metrics['requests_failed'] == 2


def test_live_run_repeat_provenance_cost_trace_and_human_review(tmp_path):
    settings = live_settings(tmp_path)
    api = FixtureAPI(); agent = fixture_runner(settings, api)
    first = agent.run_once(symbol='MSFT'); second = agent.run_once(symbol='MSFT')
    assert first.status == second.status == 'SUCCESS'
    assert first.content_candidates_created > 0 and second.content_candidates_created == 0
    assert first.review_items_created == 1 and second.notifications_sent == 0
    assert second.observations_created == 0 and first.trend_count == 1
    assert first.provider_metrics['reddit']['requests_succeeded'] == 2
    assert first.provider_metrics['openai']['requests_attempted'] <= 9
    with Database(settings.database_path) as db:
        row = dict(db.execute('SELECT * FROM content_candidates LIMIT 1').fetchone())
        assert row['provider'] == 'openai' and row['requires_human_review'] and not row['ready_to_post']
        provenance = json.loads(row['brief_snapshot'])['data_provenance']
        assert provenance['social'] and all(r['source'] == 'REDDIT_LIVE' for r in provenance['social'])
        assert not ReviewHandoffService(db).ready()
        assert json.loads(db.get_config('provider_health:openai'))['last_success_at']
    assert status(settings)['provider_status'] and any('OpenAI' in item['detail'] for item in doctor(settings))


def test_live_openai_outage_preserves_opportunities_and_recovers(tmp_path):
    settings = live_settings(tmp_path)
    api = FixtureAPI(); api.fail_host = 'api.openai.com'
    agent = fixture_runner(settings, api)
    failed = agent.run_once(symbol='MSFT')
    assert failed.status == 'PARTIAL_SUCCESS' and failed.opportunities_created == 1
    assert failed.content_candidates_created == 0
    assert failed.provider_metrics['openai']['requests_attempted'] == 3
    assert failed.provider_status[-1]['consecutive_failures'] == 3


def test_mixed_mode_warning_and_source_provenance(tmp_path):
    settings = live_settings(tmp_path).model_copy(update={'agent_social_provider': 'mixed', 'agent_regivion_provider': 'mock', 'ai_provider': 'mock'})
    api = FixtureAPI(); agent = fixture_runner(settings, api)
    agent.adapters.extend(create_providers(settings)[0][1:])
    result = agent.run_once()
    assert any('MIXED DATA MODE' in warning for warning in result.warnings)
    with Database(settings.database_path) as db:
        assert {r[0] for r in db.execute('SELECT DISTINCT source FROM social_observations')} == {'REDDIT_LIVE', 'MOCK_REDDIT', 'MOCK_STOCKTWITS'}


def test_content_cost_limit_includes_variants_repairs_and_retries(tmp_path):
    settings = live_settings(tmp_path, llm_max_generations_per_run=1)
    api = FixtureAPI(); agent = fixture_runner(settings, api)
    result = agent.run_once(symbol='MSFT')
    assert result.content_candidates_created == 1
    assert len([r for r in api.requests if r.url.path == '/v1/responses']) == 1
    with pytest.raises(GenerationLimitReached):
        agent.llm.generate('PUNCHY variant', brief_fixture(tmp_path))


def test_live_llm_unsupported_numbers_fail_validation(tmp_path):
    settings = live_settings(tmp_path)
    api = FixtureAPI()
    def handler(request):
        response = api(request)
        if request.url.path == '/v1/responses':
            body = json.loads(request.content)
            variant = body['text']['format']['schema']['properties']['variant_type']['enum'][0]
            return httpx.Response(200, json=openai_payload('$MSFT will reach $999 tomorrow', variant))
        return response
    agent = fixture_runner(settings, handler)
    result = agent.run_once(symbol='MSFT')
    assert result.content_candidates_created == 0 and result.notifications_sent == 0
    assert any('rejected by factuality' in w for w in result.warnings)


def test_production_refuses_fixture_database_before_history_write(tmp_path):
    settings = live_settings(tmp_path)
    AgentRunner(settings.model_copy(update={'agent_social_provider': 'mock', 'agent_regivion_provider': 'mock', 'ai_provider': 'mock'}),
                notifier=MockReviewNotifier()).run_once()
    with Database(settings.database_path) as db:
        before = db.execute('SELECT COUNT(*) FROM agent_runs').fetchone()[0]
    production = settings.model_copy(update={'environment': 'production'})
    with pytest.raises(ValueError, match='separate live database'):
        fixture_runner(production, FixtureAPI()).run_once()
    with Database(settings.database_path) as db:
        assert db.execute('SELECT COUNT(*) FROM agent_runs').fetchone()[0] == before


def test_reddit_total_request_limit_across_irrelevant_communities(tmp_path):
    settings = live_settings(tmp_path).model_copy(update={'reddit_subreddits': 'stocks,investing,options', 'reddit_max_items_per_scan': 10})
    api = FixtureAPI(); api.listing = {'data': {'children': []}}
    source = RedditLiveSource(settings, transport=httpx.MockTransport(api), sleeper=no_sleep)
    assert asyncio.run(source.collect()) == []
    assert sum(int(r.url.params['limit']) for r in api.requests if r.url.host == 'oauth.reddit.com') <= 10


def test_regivion_cache_freshness_ages_before_ttl_expires(tmp_path):
    api = FixtureAPI(); client = http_regivion(api, live_settings(tmp_path), max_age_seconds=1)
    assert not client.get_ticker('MSFT').raw['provenance']['stale']
    client.clock = lambda: NOW + timedelta(seconds=2)
    assert client.get_ticker('MSFT').raw['provenance']['stale']
    assert len(api.requests) == 1


def test_live_regivion_outage_uses_missing_components_without_mocks(tmp_path):
    settings = live_settings(tmp_path).model_copy(update={'agent_regivion_provider': 'http',
        'regivion_base_url': 'http://127.0.0.1:8000', 'regivion_api_key': 'synthetic', 'regivion_contract': 'valuation-history'})
    api = FixtureAPI(); api.fail_host = '127.0.0.1'
    agent = fixture_runner(settings, api); agent.regivion = http_regivion(api, settings)
    result = agent.run_once(symbol='MSFT')
    assert result.status == 'PARTIAL_SUCCESS' and result.opportunities_created == 1
    assert any('missing-component scoring' in w for w in result.warnings)
    assert result.opportunities[0]['components']['regivion'] == 0


def test_stale_live_regivion_confidence_and_market_component(tmp_path):
    settings = live_settings(tmp_path).model_copy(update={'agent_regivion_provider': 'http',
        'regivion_base_url': 'http://127.0.0.1:8000', 'regivion_api_key': 'synthetic', 'regivion_contract': 'valuation-history'})
    api = FixtureAPI(); api.valuation['history'][0]['captured_at'] = (NOW - timedelta(days=7)).isoformat()
    agent = fixture_runner(settings, api); agent.regivion = http_regivion(api, settings)
    result = agent.run_once(symbol='MSFT')
    assert result.opportunities[0]['confidence'] == 'LOW'
    assert any('snapshot stale' in w for w in result.warnings)
    with Database(settings.database_path) as db:
        row = db.get_recent_opportunity('MSFT')
        assert row['market_score'] is None and row['freshness_score'] == 0


def test_rate_limit_cooldown_blocks_next_request_and_records_event(tmp_path):
    settings = live_settings(tmp_path)
    def handler(request):
        return httpx.Response(429, json={}, headers={'Retry-After': '300'})
    provider = OpenAIProvider(settings, transport=httpx.MockTransport(handler))
    brief = brief_fixture(tmp_path)
    with pytest.raises(httpx.HTTPStatusError):
        provider.generate('PUNCHY variant', brief)
    with pytest.raises(CircuitOpen):
        provider.generate('PUNCHY variant', brief)
    assert provider.health.metrics['requests_attempted'] == provider.health.metrics['rate_limit_events'] == 1


def test_health_capabilities_start_untested_not_falsely_authenticated(tmp_path):
    rows = capabilities(live_settings(tmp_path))
    assert all(row['authenticated'] is None and row['reachable'] is None for row in rows)


def test_cost_skipped_opportunity_remains_pending_for_next_run(tmp_path):
    settings = live_settings(tmp_path, llm_max_generations_per_run=1)
    agent = fixture_runner(settings, FixtureAPI())
    first = agent.run_once()
    assert first.content_candidates_created == 1
    with Database(settings.database_path) as db:
        assert db.get_config('agent_content_pending:NVDA') == 'budget_exhausted'
    second = agent.run_once()
    assert second.content_candidates_created == 1 and second.review_handoff[0]['symbol'] == 'NVDA'


def test_legacy_regivion_factory_cannot_silently_mock_in_production(monkeypatch):
    from exitvector_agent.regivion import build_regivion_client_from_env
    monkeypatch.setenv('EXITVECTOR_ENV', 'production')
    with pytest.raises(ValueError, match='mock fallback is prohibited'):
        build_regivion_client_from_env()
