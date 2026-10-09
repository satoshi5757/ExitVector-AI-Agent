# Regivion agent-v1 integration

Phase 9.1 consumes the production API described and sanitized by the user on
2026-10-08. No Regivion source, configuration, database or deployment was modified.

## Configuration

Set these in `.exitvector.env` (add the read-only token manually and privately):

```dotenv
REGIVION_PROVIDER=http
REGIVION_BASE_URL=https://regivion.com
REGIVION_API_KEY=
REGIVION_CONTRACT=agent-v1
```

The existing contract selector is reused. agent-v1 is the normal default.
Production rejects HTTP, localhost/private literal addresses, alternate hosts,
missing credentials, mock fallback, and valuation-history-only integration.
Explicit disabled reduced operation remains supported with REGIVION_REQUIRED=false.

## Reads and health

GET `/api/agent/v1/health` and GET `/api/agent/v1/ticker/{symbol}` use dedicated
bearer authentication. Redirects are not followed. A 401 rejects credentials;
errors never become mock data. Runner health uses the existing circuit/retry state.
Authenticated health must succeed before Regivion status reports live. Live-check
performs no content generation and writes no business state or provider health.
Normal runs persist safe provider health. Collection, browser, admin, job and scan
endpoints are not consumed.

## Mapping

| Source | Normalized evidence |
| --- | --- |
| psc.score/rank/previous_rank/status | Independent nullable PSC fields |
| psc.entered_top_20/exited_top_20/rank_acceleration | Explicit transitions only |
| psc.portfolio_key/scoring_profile | Preserved context in normalized payload |
| alerts | Real records, category/type, direction, strength, timestamp |
| fundamentals | Explicit YoY/FCF growth only, forward PE, PEG, profitability |
| insiders.recent_buys/recent_sells | Explicit direction, dates, IDs, shares, value bounds |
| politicians.recent_trades | Direction, dates, source, chamber, amount bounds |
| coverage | Retained independently of health capabilities |
| component.as_of | UTC source timestamp, age and stale flag |
| generated_at | Response generation time, never financial freshness |

Null rank is not zero. Score alone is not rank evidence. Missing previous rank
means no computed movement. No Top 20 membership is inferred. Empty alerts with
false coverage mean no usable current coverage, not proof of no historical alerts.
Unsupported growth fields remain null. No midpoint/exact value is computed from
transaction bounds. Events are deduplicated within enrichment; repeated runs use
existing business/content/notification deduplication. Market remains disabled.

Provenance records REGIVION_HTTP, agent-v1, host, component source timestamps,
receipt time, age and stale flags. Parsing uses an allowlist rather than persisting
raw response/request payloads. Credentials, authorization headers and request URLs
are not persisted. Old/unknown source times reduce confidence to LOW and freshness
to zero; cache ages advance without changing source/receipt timestamps.

## Development compatibility

Explicit `REGIVION_CONTRACT=valuation-history` retains GET
`/api/valuation-history/{symbol}` for local development. Only forward PE and
peg_normalized are mapped; it supplies no PSC, alert or flow evidence. Its public
`/livez` check proves reachability only. `unavailable` fails validation.

## Verification

Use live-check, then an MSFT dry run, then an MSFT local run, stopping if any step
fails. Dry runs may make external read/inference calls but isolate business DB
writes. Live reads and inference do not authorize X writes. Human approval remains
mandatory. See PHASE9_1_VERIFICATION.md for actual execution results.
