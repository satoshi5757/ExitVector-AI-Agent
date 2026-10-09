"""Reproduce offline Phase 9 integrations; optionally probe configured live reads."""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
from test_phase9_live import (FixtureAPI, FixedDate, NOW, brief_fixture, fixture_runner,
                              http_regivion, live_settings)
from exitvector_agent.config import Settings, load_settings
from exitvector_agent.content import validate_content
from exitvector_agent.database import Database
from exitvector_agent.live_checks import live_check
from exitvector_agent.live_providers import OpenAIProvider
from exitvector_agent.operations import doctor, status
from exitvector_agent.provider_health import CircuitOpen
from exitvector_agent.provider_setup import create_providers, regivion_target


def main():
    sections = ['# Phase 9 live-provider verification',
        'All integration demonstrations below use synthetic HTTP fixtures and disposable databases. '
        'LIVE describes the selected implementation/provenance, not a real external verification. '
        'No production services or Regivion files were modified; no commit, push, deployment, '
        'scraping, browser automation, X actions or trading occurred.']
    def record(title, data):
        text = data if isinstance(data, str) else json.dumps(data, indent=2, default=str)
        sections.append(f'## {title}\n\n```text\n{text.rstrip()}\n```')
    results = []
    for title, args in [('Focused Phase 9 tests', ['tests/test_phase9_live.py']),
                        ('Full pytest, including all 208 unchanged baseline tests', [])]:
        done = subprocess.run([sys.executable, '-m', 'pytest', *args, '-q', '--tb=short'],
                              cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=180)
        record(title, done.stdout + done.stderr)
        results.append(done.returncode)
        print(f'{title}: exit {done.returncode}', flush=True)
    assert not any(results), 'Tests must pass before provider demonstrations'

    with tempfile.TemporaryDirectory(prefix='exitvector_phase9_') as folder:
        base = Path(folder)
        settings = live_settings(base)
        empty = base / 'empty.env'; empty.write_text('', encoding='utf-8')
        env = {key: value for key, value in os.environ.items() if not key.startswith(
            ('EXITVECTOR_', 'AGENT_', 'REDDIT_', 'REGIVION_', 'LLM_', 'OPENAI_', 'AUDIENCE_',
             'ALLOW_X_', 'SOCIAL_', 'MARKET_', 'CONTENT_', 'MAX_OPPORTUNITIES_', 'PROVIDER_'))}
        env.update(PYTHONPATH=str(ROOT / 'src'), PYTHONIOENCODING='utf-8',
                   EXITVECTOR_DATABASE_URL='sqlite:///' + str(base / 'cli.db'),
                   AGENT_LOG_DIR=str(base / 'logs'), AGENT_DATA_DIR=str(base / 'data'))
        def cli(title, arguments, extra=None, expected=0):
            done = subprocess.run([sys.executable, '-m', 'exitvector_agent', '--env-file', str(empty), *arguments],
                                  env={**env, **(extra or {})}, cwd=ROOT, capture_output=True,
                                  text=True, encoding='utf-8', timeout=30)
            record(title, '$ python -m exitvector_agent ' + ' '.join(arguments) + '\n' +
                   done.stdout + done.stderr + f'Exit code: {done.returncode}')
            assert done.returncode == expected
        cli('Development/mock doctor output', ['doctor'])
        cli('Production rejects required mocks', ['run'], {'EXITVECTOR_ENV': 'production'}, expected=2)
        cli('Actual live-check without credentials', ['live-check'])
        cli('Existing offline run remains operational', ['run'])
        cli('Existing status plus provider health visibility', ['status'])

        patches = [patch.object(importlib.import_module('exitvector_agent.' + module), 'datetime', FixedDate)
                   for module in ('social.scan', 'social.sources', 'opportunity_service', 'content')]
        for item in patches:
            item.start()
        try:
            api = FixtureAPI()
            agent = fixture_runner(settings, api)
            first = agent.run_once(symbol='MSFT', trigger_type='TEST')
            second = agent.run_once(symbol='MSFT', trigger_type='TEST')
            record('Live-shaped Reddit/OpenAI run: explicit missing Regivion mode', asdict(first))
            record('Identical repeated run', asdict(second))
            assert first.status == second.status == 'SUCCESS'
            assert first.content_candidates_created > 0 and second.content_candidates_created == second.notifications_sent == second.observations_created == 0
            with Database(settings.database_path, read_only=True) as db:
                record('Reddit normalized persistent evidence (no raw text or author)', [dict(row) for row in db.execute(
                    'SELECT source,external_id,observed_at,raw_text,author,likes,replies,metadata FROM social_observations ORDER BY id LIMIT 2')])
                candidates = [dict(row) for row in db.execute('''SELECT id,opportunity_id,ticker,provider,model,prompt_version,
                    full_text,review_status,requires_human_review,ready_to_post,final_machine_validation,brief_snapshot
                    FROM content_candidates ORDER BY id''')]
                record('Live-provider candidate traceability and human-review safeguard', candidates)
                record('Run history metrics', [dict(row) for row in db.execute('SELECT id,status,trigger_type,candidate_count,notification_count,error_count FROM agent_runs')])
            record('Provider status/health after repeated run', status(settings)['provider_status'])
            record('Mocked live-check: minimal reads, no inference', live_check(settings, transport=httpx.MockTransport(api)))

            partial_settings = settings.model_copy(update={'agent_regivion_provider': 'http', 'regivion_required': True,
                'regivion_base_url': 'http://127.0.0.1:8000', 'regivion_api_key': 'synthetic-read-token',
                'regivion_contract': 'valuation-history'})
            partial_settings.validate_operation()
            regivion_api = FixtureAPI()
            client = http_regivion(regivion_api, partial_settings)
            enrichment = client.get_ticker('MSFT'); client.get_ticker('MSFT')
            record('Discovered HTTP Regivion valuation response normalized; cache hit', {
                'endpoint': '/api/valuation-history/MSFT', 'target': regivion_target(partial_settings),
                'enrichment': asdict(enrichment), 'metrics': client.health.metrics})
            record('Mocked Regivion reachability does not prove auth', live_check(partial_settings, transport=httpx.MockTransport(api)))
            production = partial_settings.model_copy(update={'environment': 'production', 'regivion_base_url': 'https://regivion.example.invalid'})
            try:
                production.validate_operation()
            except ValueError as exc:
                record('Hetzner production-target configuration and actual server-contract gate',
                       {'target': regivion_target(production), 'result': str(exc), 'network_requests': 0})
            else:
                raise AssertionError('Unimplemented production authentication was accepted')
            local_production = production.model_copy(update={'regivion_base_url': 'http://127.0.0.1:8000'})
            try:
                local_production.validate_operation()
            except ValueError as exc:
                record('Localhost is development-only', str(exc))

            draft_api = FixtureAPI()
            brief = brief_fixture(base)
            writer = OpenAIProvider(settings, transport=httpx.MockTransport(draft_api))
            response = writer.generate('Write a PUNCHY variant', brief)
            body = json.loads(draft_api.requests[-1].content)
            record('OpenAI structured draft and deterministic factuality validation', {
                'response': asdict(response), 'validation': asdict(validate_content(response.text, brief)),
                'request_contract': {'tools': body['tools'], 'store': body['store'], 'strict': body['text']['format']['strict'],
                                     'input_is_ContentBrief_only': json.loads(body['input']) == asdict(brief)}})

            mixed = settings.model_copy(update={'database_url': 'sqlite:///' + str(base / 'mixed.db'),
                'agent_social_provider': 'mixed', 'agent_regivion_provider': 'mock', 'ai_provider': 'mock'})
            mixed_agent = fixture_runner(mixed, FixtureAPI())
            mixed_agent.adapters.extend(create_providers(mixed)[0][1:])
            mixed_result = mixed_agent.run_once(trigger_type='TEST')
            record('Explicit development mixed-mode warning', {'warnings': mixed_result.warnings, 'providers': mixed_result.providers})
            with Database(mixed.database_path, read_only=True) as db:
                record('Separate live/mock source provenance', [dict(row) for row in db.execute('SELECT source,COUNT(*) count FROM social_observations GROUP BY source')])

            failing_settings = settings.model_copy(update={'database_url': 'sqlite:///' + str(base / 'outage.db')})
            outage_api = FixtureAPI(); outage_api.fail_host = 'api.openai.com'
            failing = fixture_runner(failing_settings, outage_api)
            outage = failing.run_once(symbol='MSFT', trigger_type='TEST')
            record('LLM outage: partial success, preserved opportunity, bounded retries and persistent circuit', asdict(outage))
            assert outage.status == 'PARTIAL_SUCCESS' and outage.opportunities_created == 1 and outage.content_candidates_created == 0
            prior = len(outage_api.requests)
            blocked = failing.run_once(symbol='MSFT', trigger_type='TEST')
            new_requests = outage_api.requests[prior:]
            record('Circuit breaker next-run demonstration', {'errors': blocked.errors, 'metrics': blocked.provider_metrics,
                'new_openai_requests': sum(r.url.host == 'api.openai.com' for r in new_requests)})
            assert not any(r.url.host == 'api.openai.com' for r in new_requests)

            def rate_limited(request):
                return httpx.Response(429, json={}, headers={'Retry-After': '300'})
            limited = OpenAIProvider(settings, transport=httpx.MockTransport(rate_limited))
            failures = []
            for _ in range(2):
                try:
                    limited.generate('PUNCHY variant', brief)
                except (httpx.HTTPError, CircuitOpen) as exc:
                    failures.append(type(exc).__name__)
            record('429 Retry-After cooldown demonstration', {'outcomes': failures, 'metrics': limited.health.metrics,
                                                             'health': limited.health.state})

            budget_settings = settings.model_copy(update={'database_url': 'sqlite:///' + str(base / 'budget.db'),
                                                         'llm_max_generations_per_run': 1})
            budget_api = FixtureAPI()
            budget_run = fixture_runner(budget_settings, budget_api).run_once(symbol='MSFT', trigger_type='TEST')
            record('Content cost limit: one total inference attempt', {'created': budget_run.content_candidates_created,
                'warnings': budget_run.warnings, 'metrics': budget_run.provider_metrics,
                'inference_requests': sum(r.url.path == '/v1/responses' for r in budget_api.requests)})
            assert sum(r.url.path == '/v1/responses' for r in budget_api.requests) == 1
        finally:
            for item in reversed(patches):
                item.stop()

    actual = load_settings()
    selected = actual.agent_social_provider in {'live', 'mixed'} or actual.agent_regivion_provider == 'http' or actual.ai_provider == 'openai'
    configured = bool(actual.reddit_client_id and actual.reddit_client_secret) or bool(actual.regivion_api_key) or bool(actual.llm_api_key)
    if selected and configured:
        record('Optional real external read smoke test', live_check(actual))
    else:
        record('Optional real external read smoke test', 'LIVE CHECK SKIPPED - credentials not configured for selected live providers. Synthetic fixture results are not external verification.')

    sections.append('''## Architecture, discovered endpoints and limitations

Existing interfaces and Phase 8 runner/locks/history/review/notifier are reused.
Reddit OAuth plus bounded GET listings normalize stable IDs, UTC times and distinct provenance.
OpenAI Responses returns schema-validated drafts from ContentBrief only, then existing deterministic
factuality/repair/human-review safeguards run. Small provider-health configuration records persist
circuits; per-run summaries store request counts, retries, rate limits, latency and cache hits.
Cost controls bound all inference attempts, including repairs and retries.

The inspected `C:\\Users\\LetzPC Gaming\\investcopilot` source has GET `/livez`, `/readyz`, `/healthz`,
`/api/valuation-history/{symbol}`, `/api/symbols/search` and PSC job diagnostics.
PSC/alert business views are HTML. Financial API access uses browser sessions; a dedicated
read-only token contract was not found. No actual Hetzner deployment/API was probed.
See REGIVION_INTEGRATION.md for code evidence, response mappings and missing server requirements.
The partial development HTTP adapter maps real valuation fields only. Production HTTP Regivion
is blocked until real machine-auth/enrichment APIs exist; explicitly disabled Regivion is an
optional reduced production mode with missing-component scoring, never a mock fallback.

Stocktwits live remains disabled: official developer registrations are paused and supported
access was not established. Live market context remains disabled: no existing licensed HTTP
market interface was found. Local normalized/database audience analysis and native ZIP inspection
remain unchanged. No real live market/PSC performance claim is made by this verification.
''')
    record('Files changed or added', '\n'.join([
        '.env.example', 'README.md', 'REGIVION_INTEGRATION.md (new)', 'PHASE9_VERIFICATION.md (new)',
        'scripts/verify_phase9.py (new)', 'src/exitvector_agent/__main__.py', 'src/exitvector_agent/agent.py',
        'src/exitvector_agent/config.py', 'src/exitvector_agent/content.py', 'src/exitvector_agent/logging.py',
        'src/exitvector_agent/opportunity.py', 'src/exitvector_agent/opportunity_service.py',
        'src/exitvector_agent/operations.py', 'src/exitvector_agent/regivion.py',
        'src/exitvector_agent/social/extractors.py', 'src/exitvector_agent/social/scan.py',
        'src/exitvector_agent/social/sources.py', 'src/exitvector_agent/live_checks.py (new)',
        'src/exitvector_agent/live_providers.py (new)', 'src/exitvector_agent/provider_health.py (new)',
        'src/exitvector_agent/provider_setup.py (new)', 'tests/test_phase9_live.py (new)']))
    (ROOT / 'PHASE9_VERIFICATION.md').write_text('\n\n'.join(sections) + '\n', encoding='utf-8')
    print('Wrote PHASE9_VERIFICATION.md', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
