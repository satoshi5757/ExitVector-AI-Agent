"""Regivion client abstractions and normalized enrichment data."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RegivionAlert:
    """A normalized alert item returned by Regivion."""

    name: str | None = None
    category: str | None = None
    direction: str | None = None
    strength: float | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class RegivionInsider:
    """An insider transaction that may support a content signal."""

    buyer: str | None = None
    role: str | None = None
    action: str | None = None
    estimated_value: float | None = None
    value_range: str | None = None
    disclosure_date: datetime | None = None
    source_id: str | None = None
    source: str | None = None
    value_min: float | None = None
    value_max: float | None = None
    shares: float | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class RegivionPoliticianTrade:
    """A politician trade that may support a content signal."""

    actor: str | None = None
    chamber: str | None = None
    source: str | None = None
    action: str | None = None
    amount_range: str | None = None
    amount_min: float | None = None
    amount_max: float | None = None
    disclosure_date: datetime | None = None
    source_id: str | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class RegivionEnrichment:
    """Normalized enrichment returned for one ticker."""

    symbol: str
    psc_score: float | None = None
    psc_rank: int | None = None
    previous_psc_rank: int | None = None
    psc_status: str | None = None
    freshness: float | None = None
    revenue_growth_yoy: float | None = None
    earnings_growth_yoy: float | None = None
    forward_pe: float | None = None
    peg: float | None = None
    free_cash_flow_growth: float | None = None
    profitability_status: str | None = None
    recent_alerts: list[RegivionAlert] = field(default_factory=list)
    recent_insider_buys: list[RegivionInsider] = field(default_factory=list)
    recent_insider_sells: list[RegivionInsider] = field(default_factory=list)
    recent_politician_trades: list[RegivionPoliticianTrade] = field(default_factory=list)
    entered_top_20: bool | None = None
    exited_top_20: bool | None = None
    rank_acceleration: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def rank_change(self) -> int | None:
        if self.psc_rank is None or self.previous_psc_rank is None:
            return None
        return self.psc_rank - self.previous_psc_rank

    @property
    def fresh_revenue_growth(self) -> bool:
        return bool(self.revenue_growth_yoy is not None and self.revenue_growth_yoy > 0.0)

    @property
    def recent_alert_names(self) -> list[str]:
        return [alert.name for alert in self.recent_alerts if alert.name]

    @property
    def bullish_alerts(self) -> list[RegivionAlert]:
        return [alert for alert in self.recent_alerts if alert.direction == "bullish"]

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        return None

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "RegivionEnrichment":
        if payload is None:
            return cls(symbol="")
        data = dict(payload)
        symbol = str(data.get("symbol") or data.get("ticker") or "").upper()
        psc = data.get("psc") or {}
        fundamentals = data.get("fundamentals") or {}
        alerts = data.get("alerts") or []
        insiders = data.get("insiders") or []
        politician_trades = data.get("politicians") or []

        return cls(
            symbol=symbol,
            psc_score=_nullable_float(psc.get("score")),
            psc_rank=_nullable_int(psc.get("rank")),
            previous_psc_rank=_nullable_int(psc.get("previous_rank")),
            psc_status=_nullable_str(psc.get("status")),
            freshness=_nullable_float(psc.get("freshness")),
            revenue_growth_yoy=_nullable_float(fundamentals.get("revenue_growth_yoy")),
            earnings_growth_yoy=_nullable_float(fundamentals.get("earnings_growth_yoy")),
            forward_pe=_nullable_float(fundamentals.get("forward_pe")),
            peg=_nullable_float(fundamentals.get("peg")),
            free_cash_flow_growth=_nullable_float(fundamentals.get("free_cash_flow_growth")),
            profitability_status=_nullable_str(fundamentals.get("profitability_status")),
            recent_alerts=[
                RegivionAlert(
                    name=_nullable_str(alert.get("name")),
                    category=_nullable_str(alert.get("category")),
                    direction=_nullable_str(alert.get("direction")),
                    strength=_nullable_float(alert.get("strength")),
                    timestamp=cls._parse_datetime(alert.get("timestamp")),
                )
                for alert in alerts
            ],
            recent_insider_buys=[
                RegivionInsider(
                    buyer=_nullable_str(item.get("buyer")),
                    role=_nullable_str(item.get("role")),
                    action=_nullable_str(item.get("action")),
                    estimated_value=_nullable_float(item.get("estimated_value")),
                    value_range=_nullable_str(item.get("value_range")),
                    value_min=_nullable_float(item.get("value_min")),
                    value_max=_nullable_float(item.get("value_max")),
                    shares=_nullable_float(item.get("shares")),
                    source=_nullable_str(item.get("source")),
                    timestamp=cls._parse_datetime(item.get("timestamp")),
                    disclosure_date=cls._parse_datetime(item.get("disclosure_date")),
                    source_id=_nullable_str(item.get("source_id") or item.get("id")),
                )
                for item in insiders if (item.get("action") or "").lower() in {"buy", "buying"}
            ],
            recent_insider_sells=[
                RegivionInsider(
                    buyer=_nullable_str(item.get("buyer")),
                    role=_nullable_str(item.get("role")),
                    action=_nullable_str(item.get("action")),
                    estimated_value=_nullable_float(item.get("estimated_value")),
                    value_range=_nullable_str(item.get("value_range")),
                    value_min=_nullable_float(item.get("value_min")),
                    value_max=_nullable_float(item.get("value_max")),
                    shares=_nullable_float(item.get("shares")),
                    source=_nullable_str(item.get("source")),
                    timestamp=cls._parse_datetime(item.get("timestamp")),
                    disclosure_date=cls._parse_datetime(item.get("disclosure_date")),
                    source_id=_nullable_str(item.get("source_id") or item.get("id")),
                )
                for item in insiders if (item.get("action") or "").lower() in {"sell", "selling"}
            ],
            recent_politician_trades=[
                RegivionPoliticianTrade(
                    actor=_nullable_str(item.get("actor")),
                    chamber=_nullable_str(item.get("chamber")),
                    source=_nullable_str(item.get("source")),
                    action=_nullable_str(item.get("action")),
                    amount_range=_nullable_str(item.get("amount_range")),
                    amount_min=_nullable_float(item.get("amount_min")),
                    amount_max=_nullable_float(item.get("amount_max")),
                    timestamp=cls._parse_datetime(item.get("timestamp")),
                    disclosure_date=cls._parse_datetime(item.get("disclosure_date")),
                    source_id=_nullable_str(item.get("source_id") or item.get("id")),
                )
                for item in politician_trades
            ],
            entered_top_20=_nullable_bool(data.get("entered_top_20")),
            exited_top_20=_nullable_bool(data.get("exited_top_20")),
            rank_acceleration=_nullable_float(data.get("rank_acceleration")),
            raw=data,
        )


@runtime_checkable
class RegivionClient(Protocol):
    """Interface for a Regivion-backed enrichment client."""

    def get_ticker(self, symbol: str) -> RegivionEnrichment | None:
        ...

    def get_top(self, limit: int = 20) -> list[RegivionEnrichment]:
        ...

    def get_alerts(self, limit: int = 20) -> list[RegivionEnrichment]:
        ...

    def get_insiders(self, limit: int = 20) -> list[RegivionEnrichment]:
        ...

    def get_politicians(self, limit: int = 20) -> list[RegivionEnrichment]:
        ...

    def get_rank_changes(self, limit: int = 20) -> list[RegivionEnrichment]:
        ...


class MockRegivionClient:
    """Deterministic offline Regivion client for tests and demonstrations."""

    def __init__(self, data: dict[str, dict[str, Any]] | None = None) -> None:
        self.data = {
            "MSFT": {
                "symbol": "MSFT",
                "psc": {"score": 98.4, "rank": 10, "previous_rank": 28, "status": "bullish", "freshness": 0.96},
                "fundamentals": {"revenue_growth_yoy": 0.12, "earnings_growth_yoy": 0.10, "forward_pe": 27.0, "peg": 1.4, "free_cash_flow_growth": 0.18, "profitability_status": "strong"},
                "alerts": [{"name": "Positive momentum", "category": "momentum", "direction": "bullish", "strength": 92.0, "timestamp": "2026-10-07T09:00:00Z"}],
                "insiders": [{"buyer": "CEO", "role": "Chief Executive Officer", "action": "buy", "estimated_value": 2500000.0, "value_range": "$2.5M-$3.0M", "timestamp": "2026-10-06T14:00:00Z"}],
                "politicians": [],
                "entered_top_20": True,
                "rank_acceleration": 18.0,
            },
            "NVDA": {
                "symbol": "NVDA",
                "psc": {"score": 100.0, "rank": 1, "previous_rank": 1, "status": "bullish", "freshness": 0.34},
                "fundamentals": {"revenue_growth_yoy": 0.38, "earnings_growth_yoy": 0.47, "forward_pe": 42.0, "peg": 1.7, "free_cash_flow_growth": 0.26, "profitability_status": "strong"},
                "alerts": [],
                "insiders": [],
                "politicians": [],
                "entered_top_20": False,
                "rank_acceleration": 0.0,
            },
            "UBER": {
                "symbol": "UBER",
                "psc": {"score": 91.0, "rank": 24, "previous_rank": 31, "status": "bullish", "freshness": 0.78},
                "fundamentals": {"revenue_growth_yoy": 0.18, "earnings_growth_yoy": 0.22, "forward_pe": 21.0, "peg": 1.2, "free_cash_flow_growth": 0.28, "profitability_status": "strong"},
                "alerts": [{"name": "FCF trend", "category": "valuation", "direction": "bullish", "strength": 84.0, "timestamp": "2026-10-07T06:00:00Z"}],
                "insiders": [],
                "politicians": [],
                "entered_top_20": False,
                "rank_acceleration": 7.0,
            },
        }
        self.data.update(data or {})

    def get_ticker(self, symbol: str) -> RegivionEnrichment | None:
        payload = self.data.get(symbol.upper())
        return None if payload is None else RegivionEnrichment.from_payload(payload)

    def get_top(self, limit: int = 20) -> list[RegivionEnrichment]:
        return [RegivionEnrichment.from_payload(item) for item in list(self.data.values())[:limit]]

    def get_alerts(self, limit: int = 20) -> list[RegivionEnrichment]:
        return [RegivionEnrichment.from_payload(item) for item in list(self.data.values()) if item.get("alerts")][:limit]

    def get_insiders(self, limit: int = 20) -> list[RegivionEnrichment]:
        return [RegivionEnrichment.from_payload(item) for item in list(self.data.values()) if item.get("insiders")][:limit]

    def get_politicians(self, limit: int = 20) -> list[RegivionEnrichment]:
        return [RegivionEnrichment.from_payload(item) for item in list(self.data.values()) if item.get("politicians")][:limit]

    def get_rank_changes(self, limit: int = 20) -> list[RegivionEnrichment]:
        return [RegivionEnrichment.from_payload(item) for item in list(self.data.values()) if item.get("psc") and item["psc"].get("previous_rank") is not None][:limit]


class HTTPRegivionClient:
    """HTTP scaffolding. It is disabled unless explicitly configured."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        http_client: Any | None = None,
        contract: str = 'agent-v1',
        cache_ttl_seconds: float = 60,
        max_age_seconds: float = 86400,
        health: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = float(timeout_seconds)
        self.http_client = http_client
        self.contract = contract
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_age_seconds = max_age_seconds
        self.health = health
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cache = {}

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def get_ticker(self, symbol: str) -> RegivionEnrichment | None:
        import httpx
        import re
        from contextlib import nullcontext
        if not self.is_configured() or self.contract not in {'valuation-history', 'agent-v1'}:
            raise RuntimeError('HTTP Regivion contract unavailable; see REGIVION_INTEGRATION.md')
        symbol = symbol.upper()
        if not re.fullmatch(r'[A-Z]{1,5}', symbol):
            raise ValueError('Invalid ticker symbol')
        if self.contract == 'agent-v1' and self.health and not self.health.state.get('agent_health_verified'):
            self.check_health()
        now = self.clock()
        cached = self.cache.get(symbol)
        if cached and (now - cached[0]).total_seconds() < self.cache_ttl_seconds:
            if self.health:
                self.health.metrics['cache_hits'] += 1
            if cached[1] is not None:
                from dataclasses import replace
                provenance = dict(cached[1].raw.get('provenance', {}))
                source_time = RegivionEnrichment._parse_datetime(provenance.get('source_timestamp'))
                age = (now - source_time).total_seconds() if source_time else None
                provenance.update(age_seconds=age, stale=age is None or age > self.max_age_seconds or age < -300)
                if 'components' in provenance:
                    provenance['components'] = {key: self._freshness(value.get('source_timestamp'), now) for key, value in provenance['components'].items()}
                    if any(value['stale'] for key, value in provenance['components'].items() if cached[1].raw.get(key) and cached[1].raw.get('coverage', {}).get(key) is not False):
                        provenance['stale'] = True
                return replace(cached[1], raw={**cached[1].raw, 'provenance': provenance})
            return None
        def execute():
            context = nullcontext(self.http_client) if self.http_client else httpx.Client(timeout=self.timeout_seconds, follow_redirects=False)
            with context as client:
                endpoint = '/api/agent/v1/ticker/' if self.contract == 'agent-v1' else '/api/valuation-history/'
                response = client.get(self.base_url + endpoint + symbol,
                    headers={'Authorization': 'Bearer ' + self.api_key}, timeout=self.timeout_seconds)
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict):
                raise ValueError('Malformed Regivion JSON')
            if self.contract == 'agent-v1':
                return self._normalize_agent_v1(data, symbol, now)
            if data.get('detail') == 'No valuation history for symbol':
                return None
            if data.get('symbol') != symbol or not isinstance(data.get('history'), list):
                raise ValueError('Malformed Regivion valuation history')
            if not data['history']:
                return None
            rows = data['history']
            if not all(isinstance(r, dict) for r in rows):
                raise ValueError('Malformed Regivion snapshot')
            def timestamp(row):
                return RegivionEnrichment._parse_datetime(row.get('captured_at') or row.get('created_at') or row.get('as_of'))
            dated = [(timestamp(row), row) for row in rows]
            dated = [(date, row) for date, row in dated if date is not None]
            source_time, latest = max(dated, key=lambda item: item[0]) if dated else (None, rows[0])
            age = (now - source_time).total_seconds() if source_time else None
            stale = age is None or age > self.max_age_seconds or age < -300
            normalized = {'symbol': symbol, 'fundamentals': {k: latest[k] for k in ('forward_pe',) if latest.get(k) is not None}}
            if latest.get('peg_normalized') is not None:
                normalized['fundamentals']['peg'] = latest['peg_normalized']
            normalized['provenance'] = {'source': 'REGIVION_HTTP', 'is_live_data': True,
                'endpoint': '/api/valuation-history/{symbol}', 'source_timestamp': source_time.isoformat() if source_time else None,
                'received_timestamp': now.isoformat(), 'age_seconds': age, 'stale': stale,
                'missing_fields': ['psc', 'alerts', 'insiders', 'politicians', 'market']}
            return RegivionEnrichment.from_payload(normalized)
        result = self.health.perform(execute) if self.health else execute()
        self.cache[symbol] = (now, result)
        return result

    def check_health(self):
        import httpx
        from contextlib import nullcontext
        if not self.is_configured() or self.contract != 'agent-v1':
            raise RuntimeError('Authenticated health requires configured agent-v1')
        def execute():
            context = nullcontext(self.http_client) if self.http_client else httpx.Client(timeout=self.timeout_seconds, follow_redirects=False)
            with context as client:
                response = client.get(self.base_url + '/api/agent/v1/health',
                    headers={'Authorization': 'Bearer ' + self.api_key}, timeout=self.timeout_seconds)
                response.raise_for_status()
                health_data = response.json()
                if not isinstance(health_data, dict):
                    raise ValueError('Malformed Regivion health object')
                if self.health and isinstance(health_data.get('capabilities'), dict):
                    self.health.state['capabilities'] = {key: value for key, value in health_data['capabilities'].items() if key in {'psc', 'alerts', 'fundamentals', 'insiders', 'politicians', 'market'} and isinstance(value, bool)}
            if self.health:
                self.health.state['agent_health_verified'] = True
            return True
        return self.health.perform(execute) if self.health else execute()

    def _freshness(self, timestamp, now):
        source = RegivionEnrichment._parse_datetime(timestamp)
        age = (now - source).total_seconds() if source else None
        return {'source_timestamp': source.isoformat() if source else None,
                'age_seconds': age, 'stale': age is None or age > self.max_age_seconds or age < -300}

    def _normalize_agent_v1(self, data, symbol, now):
        from urllib.parse import urlsplit
        if (data.get('symbol') or data.get('ticker')) != symbol:
            raise ValueError('Malformed Regivion agent-v1 ticker')
        normalized = {'symbol': symbol}
        coverage = data.get('coverage') or {}
        capabilities = data.get('capabilities', {})
        if not isinstance(coverage, dict) or not isinstance(capabilities, dict):
            raise ValueError('Malformed Regivion coverage')
        components = {}
        for name in ('psc', 'fundamentals', 'alerts', 'insiders', 'politicians', 'market'):
            component = data.get(name)
            if component is not None and not isinstance(component, (dict, list)):
                raise ValueError('Malformed Regivion component')
            meta = component if isinstance(component, dict) else {}
            stamp = meta.get('timestamp') or meta.get('source_timestamp') or meta.get('source_date') or meta.get('as_of')
            components[name] = self._freshness(stamp, now)
            usable = coverage.get(name, meta.get('coverage', meta.get('available')))
            if isinstance(usable, dict):
                usable = usable.get('usable', usable.get('available'))
            if usable is False or component is None:
                normalized[name] = [] if name in {'alerts', 'insiders', 'politicians'} else {}
                if name == 'market' and isinstance(component, dict):
                    normalized[name] = {key: None for key in ('price', 'daily_change_pct', 'volume', 'average_volume', 'as_of') if key in component}
                continue
            if name in {'alerts', 'insiders', 'politicians'}:
                records = component if isinstance(component, list) else component.get('items', component.get('transactions', component.get('recent_trades', component.get('recent', component.get('active', [])))))
                if name == 'insiders' and isinstance(component, dict):
                    buys, sells = component.get('recent_buys') or [], component.get('recent_sells') or []
                    if not isinstance(buys, list) or not isinstance(sells, list):
                        raise ValueError('Malformed Regivion insider records')
                    records = buys + sells
                if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
                    raise ValueError('Malformed Regivion records')
                mapped = []
                seen = set()
                for item in records:
                    # Only explicit directions; ranges never become exact amounts.
                    action = item.get('action') or item.get('direction') or item.get('transaction_type')
                    action = {'purchase': 'buy', 'sale': 'sell', 'buying': 'buy', 'selling': 'sell'}.get(str(action).lower(), str(action).lower() if action is not None else None)
                    row = {key: item[key] for key in ('name', 'category', 'direction', 'strength', 'buyer', 'role', 'actor', 'chamber', 'source', 'estimated_value', 'value_range', 'amount_range', 'disclosure_date', 'source_id', 'id', 'shares', 'value_min', 'value_max', 'amount_min', 'amount_max') if key in item}
                    row['action'] = action
                    row['source_id'] = item.get('transaction_id') or item.get('source_id') or item.get('id')
                    row['timestamp'] = item.get('transaction_date') or item.get('timestamp') or item.get('date')
                    if name == 'alerts':
                        row['category'] = item.get('category') or item.get('type')
                    identity = json.dumps(row, sort_keys=True)
                    if identity not in seen:
                        mapped.append(row)
                        seen.add(identity)
                normalized[name] = mapped
            else:
                if not isinstance(component, dict):
                    raise ValueError('Malformed Regivion financial component')
                fields = {'psc': ('score', 'rank', 'previous_rank', 'status', 'context', 'portfolio_key', 'scoring_profile'),
                          'fundamentals': ('revenue_growth_yoy', 'earnings_growth_yoy', 'free_cash_flow_growth', 'forward_pe', 'peg', 'profitability_status'),
                          'market': ('price', 'daily_change_pct', 'volume', 'average_volume', 'timestamp')}[name]
                normalized[name] = {key: component[key] for key in fields if key in component}
                if name == 'psc':
                    for key in ('entered_top_20', 'exited_top_20', 'rank_acceleration'):
                        normalized[key] = component.get(key)
        normalized['coverage'] = coverage
        normalized['generated_at'] = data.get('generated_at')
        normalized['capabilities'] = capabilities
        available = [value for name, value in components.items() if normalized.get(name) and coverage.get(name) is not False]
        dated = [v['source_timestamp'] for v in available if v['source_timestamp']]
        source = min(dated) if dated else None
        normalized['provenance'] = {'source': 'REGIVION_HTTP', 'provider_source': 'REGIVION_HTTP',
            'contract': 'agent-v1', 'base_host': urlsplit(self.base_url).hostname,
            'is_live_data': True, 'endpoint': '/api/agent/v1/ticker/{symbol}',
            'received_timestamp': now.isoformat(), 'components': components,
            **self._freshness(source, now)}
        if any(v['stale'] for v in available):
            normalized['provenance']['stale'] = True
        return RegivionEnrichment.from_payload(normalized)

    def get_top(self, limit: int = 20) -> list[RegivionEnrichment]:
        raise RuntimeError("HTTPRegivionClient is disabled; configure REGIVION_BASE_URL and REGIVION_API_KEY to enable it")

    def get_alerts(self, limit: int = 20) -> list[RegivionEnrichment]:
        raise RuntimeError("HTTPRegivionClient is disabled; configure REGIVION_BASE_URL and REGIVION_API_KEY to enable it")

    def get_insiders(self, limit: int = 20) -> list[RegivionEnrichment]:
        raise RuntimeError("HTTPRegivionClient is disabled; configure REGIVION_BASE_URL and REGIVION_API_KEY to enable it")

    def get_politicians(self, limit: int = 20) -> list[RegivionEnrichment]:
        raise RuntimeError("HTTPRegivionClient is disabled; configure REGIVION_BASE_URL and REGIVION_API_KEY to enable it")

    def get_rank_changes(self, limit: int = 20) -> list[RegivionEnrichment]:
        raise RuntimeError("HTTPRegivionClient is disabled; configure REGIVION_BASE_URL and REGIVION_API_KEY to enable it")


def _nullable_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nullable_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _nullable_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _nullable_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def build_regivion_client_from_env() -> RegivionClient | MockRegivionClient:
    """Use central configuration and the same production no-fallback gate."""
    from exitvector_agent.config import load_settings
    from exitvector_agent.provider_setup import create_providers
    settings = load_settings()
    settings.validate_operation()
    return create_providers(settings)[1]
