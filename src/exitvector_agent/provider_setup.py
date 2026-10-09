"""Configured implementations of existing social, Regivion and LLM interfaces."""
from urllib.parse import urlsplit

from exitvector_agent.content import MockLLMProvider
from exitvector_agent.live_providers import OpenAIProvider, RedditLiveSource
from exitvector_agent.provider_health import ProviderHealth
from exitvector_agent.regivion import HTTPRegivionClient, MockRegivionClient
from exitvector_agent.social.sources import MockSourceAdapter


class ProvenanceMockSource(MockSourceAdapter):
    async def collect(self):
        observations = await super().collect()
        for row in observations:
            row.source = 'MOCK_' + self.name.upper()
            row.raw_metadata.update(is_live_data=False, provider_source=row.source)
        return observations


class DisabledRegivionClient:
    def get_ticker(self, symbol):
        return None


def create_providers(settings):
    social = []
    if settings.agent_social_provider in {'live', 'mixed'}:
        social.append(RedditLiveSource(settings))
    if settings.agent_social_provider in {'mock', 'mixed'}:
        social.extend([ProvenanceMockSource('stocktwits'), ProvenanceMockSource('reddit')])
    if settings.agent_regivion_provider == 'http':
        regivion = HTTPRegivionClient(base_url=settings.regivion_base_url, api_key=settings.regivion_api_key,
            timeout_seconds=settings.regivion_timeout_seconds, contract=settings.regivion_contract,
            cache_ttl_seconds=settings.regivion_cache_ttl_seconds, max_age_seconds=settings.regivion_max_age_seconds)
    elif settings.agent_regivion_provider == 'disabled':
        regivion = DisabledRegivionClient()
    else:
        regivion = MockRegivionClient()
    llm = OpenAIProvider(settings) if settings.ai_provider == 'openai' else MockLLMProvider()
    return social, regivion, llm


def attach_health(providers, settings, database):
    health = {}
    for provider in providers:
        name = ('reddit' if isinstance(provider, RedditLiveSource) else 'regivion' if isinstance(provider, HTTPRegivionClient)
                else 'openai' if isinstance(provider, OpenAIProvider) else None)
        if name:
            provider.health = ProviderHealth(name, settings, database)
            health[name] = provider.health
        if isinstance(provider, OpenAIProvider):
            provider.generations = 0
    return health


def regivion_target(settings):
    host = urlsplit(settings.regivion_base_url).hostname or 'unconfigured'
    label = 'Hetzner production target (configured; not deployment-verified)' if settings.environment.casefold() == 'production' else 'LOCAL/DEVELOPMENT target'
    return f'{label}: {host}'


def mode_label(settings):
    flags = [settings.agent_social_provider == 'live', settings.agent_regivion_provider == 'http', settings.ai_provider == 'openai']
    if all(flags):
        return 'LIVE INPUTS (Regivion agent-v1; consult provider health for verification)' if settings.regivion_contract == 'agent-v1' else 'LIVE INPUTS (Regivion partial valuation only; PSC unavailable)'
    if any(flags) or settings.agent_social_provider == 'mixed':
        if settings.agent_social_provider == 'live' and settings.agent_regivion_provider == 'disabled' and settings.ai_provider == 'openai':
            return 'LIVE SOCIAL/LLM; REGIVION EXPLICITLY DISABLED'
        return 'MIXED DATA MODE: results combine live and fixture/disabled providers; not production analysis'
    return 'MOCK social and Regivion data are offline fixtures; this run does not observe live markets.'
