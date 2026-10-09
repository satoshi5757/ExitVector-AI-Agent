"""Small, persistent provider health/circuit state; never stores request payloads."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


class CircuitOpen(RuntimeError):
    pass


@dataclass
class ProviderStatus:
    provider_name: str
    provider_type: str
    configured: bool
    live: bool
    read_only: bool = True
    authenticated: bool | None = None
    reachable: bool | None = None
    last_success_at: str | None = None
    last_failure_at: str | None = None
    consecutive_failures: int = 0
    error_summary: str | None = None
    circuit_open_until: float = 0


class ProviderHealth:
    def __init__(self, name, settings, database=None, *, clock=time.time):
        self.name, self.settings, self.database, self.clock = name, settings, database, clock
        self.state = {'consecutive_failures': 0, 'circuit_open_until': 0}
        if database:
            self.state.update(json.loads(database.get_config('provider_health:' + name) or '{}'))
        self.metrics = dict(requests_attempted=0, requests_succeeded=0, requests_failed=0,
                            retries=0, rate_limit_events=0, latency_seconds=0.0, cache_hits=0)

    def check(self):
        if self.state.get('circuit_open_until', 0) > self.clock():
            raise CircuitOpen('Provider temporarily degraded; circuit cooldown active')

    def finish(self, started, error=None):
        self.metrics['latency_seconds'] += max(0, time.monotonic() - started)
        now = datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()
        if error is None:
            self.metrics['requests_succeeded'] += 1
            self.state.update(last_success_at=now, consecutive_failures=0, reachable=True,
                              authenticated=(True if self.state.get('agent_health_verified') else None) if self.name == 'regivion' else True, error_summary=None, circuit_open_until=0)
        else:
            self.metrics['requests_failed'] += 1
            code = getattr(getattr(error, 'response', None), 'status_code', None)
            self.metrics['rate_limit_events'] += int(code == 429)
            count = self.state['consecutive_failures'] + 1
            if self.name == 'regivion' and code in {401, 403}:
                self.state['agent_health_verified'] = False
            self.state.update(last_failure_at=now, consecutive_failures=count,
                              error_summary=f'{type(error).__name__}' + (f' HTTP {code}' if code else ''),
                              reachable=True if code else False,
                              authenticated=False if code in {401, 403} else self.state.get('authenticated'))
            if count >= self.settings.provider_circuit_failure_threshold:
                self.state['circuit_open_until'] = self.clock() + self.settings.provider_circuit_cooldown_seconds
            if code == 429:
                from email.utils import parsedate_to_datetime
                value = error.response.headers.get('retry-after', '60')
                try:
                    delay = float(value)
                except ValueError:
                    try:
                        delay = parsedate_to_datetime(value).timestamp() - self.clock()
                    except (ValueError, TypeError):
                        delay = 60
                self.state['circuit_open_until'] = max(self.state.get('circuit_open_until', 0), self.clock() + max(0, delay))
        if self.database:
            self.database.set_config('provider_health:' + self.name, json.dumps(self.state))

    def perform(self, operation):
        self.check()
        self.metrics['requests_attempted'] += 1
        started = time.monotonic()
        try:
            result = operation()
        except Exception as exc:
            self.finish(started, exc)
            raise
        self.finish(started)
        return result

    async def perform_async(self, operation):
        self.check()
        self.metrics['requests_attempted'] += 1
        started = time.monotonic()
        try:
            result = await operation()
        except BaseException as exc:
            self.finish(started, exc)
            raise
        self.finish(started)
        return result


def capabilities(settings, database=None):
    items = [ProviderStatus('reddit', 'social', settings.reddit_enabled and bool(settings.reddit_client_id and settings.reddit_client_secret and settings.reddit_user_agent), True),
             ProviderStatus('stocktwits', 'social', False, False),
             ProviderStatus('regivion', 'enrichment', settings.agent_regivion_provider == 'http' and bool(settings.regivion_api_key) and settings.regivion_contract != 'unavailable', settings.agent_regivion_provider == 'http'),
             ProviderStatus('openai', 'llm', settings.ai_provider == 'openai' and bool(settings.llm_api_key and settings.ai_model), True)]
    output = []
    for item in items:
        row = asdict(item)
        if database:
            row.update(json.loads(database.get_config('provider_health:' + item.provider_name) or '{}'))
        if item.provider_name == 'regivion':
            from urllib.parse import urlsplit
            row.update(contract=settings.regivion_contract, base_host=urlsplit(settings.regivion_base_url).hostname)
            row['live'] = bool(row['configured'] and settings.regivion_contract == 'agent-v1' and row.get('agent_health_verified') and row.get('authenticated') and row.get('reachable'))
        output.append(row)
    return output
