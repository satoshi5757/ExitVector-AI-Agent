"""Minimal authenticated read checks; no LLM generation or business DB writes."""
import asyncio
import httpx

from exitvector_agent.live_providers import RedditLiveSource
from exitvector_agent.provider_setup import regivion_target


def live_check(settings, *, transport=None):
    rows = []
    def add(name, level, detail):
        rows.append({'name': name, 'status': level, 'detail': detail})
    try:
        settings.validate_operation()
    except ValueError as exc:
        add('Configuration', 'FAIL', str(exc))
        return rows
    if settings.agent_social_provider in {'live', 'mixed'}:
        minimal = settings.model_copy(update={'reddit_max_items_per_scan': 1,
            'reddit_subreddits': settings.reddit_subreddits.split(',')[0]})
        try:
            asyncio.run(RedditLiveSource(minimal, transport=transport).collect())
            add('Reddit', 'PASS', 'OAuth and minimal read listing succeeded')
        except Exception as exc:
            add('Reddit', 'FAIL', type(exc).__name__)
    else:
        add('Reddit', 'SKIP', 'LIVE CHECK SKIPPED - live source/credentials not configured')
    add('Stocktwits', 'WARN', 'DISABLED - supported API access not established')
    if settings.agent_regivion_provider == 'http':
        try:
            with httpx.Client(transport=transport, timeout=settings.regivion_timeout_seconds, follow_redirects=False) as client:
                agent_v1 = settings.regivion_contract == 'agent-v1'
                response = client.get(settings.regivion_base_url.rstrip('/') + ('/api/agent/v1/health' if agent_v1 else '/livez'),
                    headers={'Authorization': 'Bearer ' + settings.regivion_api_key} if agent_v1 else {})
                response.raise_for_status()
                if not isinstance(response.json(), dict):
                    raise ValueError('Malformed health object')
            if agent_v1:
                add('Regivion', 'PASS', 'authenticated agent-v1 health succeeded; ' + regivion_target(settings))
            else:
                add('Regivion reachability', 'PASS', regivion_target(settings))
                add('Regivion authentication/enrichment', 'WARN', 'UNVERIFIED - development valuation-history only')
        except Exception as exc:
            code = getattr(getattr(exc, 'response', None), 'status_code', None)
            add('Regivion', 'FAIL', 'credentials rejected (401)' if code == 401 else type(exc).__name__)
    else:
        add('Regivion', 'SKIP', 'LIVE CHECK SKIPPED - HTTP contract/credentials not configured')
    if settings.ai_provider == 'openai':
        try:
            from urllib.parse import quote
            with httpx.Client(transport=transport, timeout=settings.llm_timeout_seconds, follow_redirects=False) as client:
                response = client.get('https://api.openai.com/v1/models/' + quote(settings.ai_model, safe=''),
                    headers={'Authorization': 'Bearer ' + settings.llm_api_key})
                response.raise_for_status()
                if response.json().get('id') != settings.ai_model:
                    raise ValueError('Unexpected model response')
            add('OpenAI', 'PASS', 'Authentication/model visibility valid; no inference requested')
        except Exception as exc:
            add('OpenAI', 'FAIL', type(exc).__name__)
    else:
        add('OpenAI', 'SKIP', 'LIVE CHECK SKIPPED - provider/credentials not configured')
    add('Market', 'SKIP', 'DISABLED - no supported licensed live endpoint discovered')
    add('X actions', 'PASS', 'DISABLED')
    return rows
