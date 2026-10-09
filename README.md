# ExitVector Agent

ExitVector Agent is a modular Python application that monitors financial and social sources for unusual market attention, enriches tickers with Regivion data, ranks content opportunities, and produces review-ready X post suggestions.

## Requirements

- Python 3.11+
- SQLite

## Local setup

1. Install Python 3.11 or newer.
2. Create a virtual environment.
3. Install the project in editable mode with development dependencies:

```bash
python -m pip install -e ".[dev]"
```

4. Copy `.env.example` to `.exitvector.env` and configure the read-only Regivion token locally.
   For fully offline development, instead set `REGIVION_PROVIDER=mock`; no credentials are needed.
5. Run tests:

```bash
python -m pytest
```

## Security

- Never commit secrets or `.env` files.
- Production Regivion access uses only the authorized read-only agent-v1 API.
- Phase 8 notifications are local console/inbox only. No Telegram, email or Slack delivery is implemented.
- Before production use, review source API terms, licensing, rate limits, and data usage restrictions.

## Phase 2: social signals and trend detection

### Architecture

- `exitvector_agent.social.models`: normalized observation model
- `exitvector_agent.social.extractors`: ticker extraction and false-positive filtering
- `exitvector_agent.social.sources`: adapter interface, retry runner, and offline mock adapter
- `exitvector_agent.social.velocity`: rolling mention, baseline, velocity-ratio, and acceleration calculations
- `exitvector_agent.social.trends`: configurable 0-100 social trend scoring
- `exitvector_agent.social.scan`: collection, persistence, and ranking orchestration

### Supported sources

- Stocktwits: adapter interface is included; live API access requires credentials and has not been implemented
- Reddit: adapter interface is included; live API access requires credentials and has not been implemented
- RSS/Atom: adapter interface is included; feed parsing uses standard-library XML support and requires endpoints
- Mock source: deterministic offline adapter for development, tests, and CLI demonstrations

### Source limitations

No browser automation, authenticated scraping, or platform bypasses are used. Missing API credentials or unavailable sources fail locally and do not stop the rest of the scan. Live adapters will be added only when public, documented, and authorized access is available.

### Mock mode

The application runs fully offline using the built-in mock adapter. It provides three representative scenarios:

- a genuinely accelerating ticker
- a steadily active ticker
- a low-volume false-positive candidate

### CLI usage

```bash
python -m exitvector_agent scan
python -m exitvector_agent trends
python -m exitvector_agent trends --limit 20
```

Example output:

```text
Observation count: 15
1. MSFT   73.1   +1000% mention acceleration
Main sources:
- mock: 15 observations, 14 unique authors
```

The current mock scoring is intentionally deterministic and does not connect to the internet.

### Environment variables

The default local values are documented in `.env.example`.

- `EXITVECTOR_ENV`
- `EXITVECTOR_DATABASE_URL`
- `EXITVECTOR_SCAN_INTERVAL_SECONDS`
- `EXITVECTOR_NOTIFY_THRESHOLD`
- `EXITVECTOR_REGIVION_BASE_URL`
- `EXITVECTOR_REGIVION_API_KEY`
- `EXITVECTOR_TELEGRAM_BOT_TOKEN`
- `EXITVECTOR_TELEGRAM_CHAT_ID`
- `EXITVECTOR_AI_PROVIDER`
- `EXITVECTOR_AI_MODEL`

The live social adapters require additional credentials, but none are required for mock mode.

## Phase 3: Regivion enrichment and post opportunities

### Architecture

- `exitvector_agent.regivion`: Regivion protocol, normalized ticker enrichment model, offline mock client, and disabled HTTP scaffold
- `exitvector_agent.opportunity`: configurable 0-100 opportunity scoring, content-angle classification, and visual recommendations
- `exitvector_agent.opportunity_service`: orchestrates social trends, Regivion enrichment, and database persistence
- `exitvector_agent.database`: additive Phase 3 schema for snapshots, opportunities, and notification state

### Regivion interface

The `RegivionClient` protocol supports ticker queries plus collection interfaces. Phase 9.1 implements HTTP ticker enrichment; collection endpoints are not part of agent-v1 and are not called. HTTP selection requires an explicit base URL and read-only credential. Missing credentials fail validation without mock fallback.

### Post Opportunity Score

The initial scoring weights are:

| Component | Weight |
| --- | ---: |
| Social Trend | 30% |
| Regivion Conviction | 25% |
| Market / Price-Volume Signal | 15% |
| Freshness | 10% |
| Novelty | 10% |
| Estimated Engagement Potential | 10% |

The weights are configurable through `OpportunityScorer(weights=...)`. Missing components are not silently treated as zero; the scorer renormalizes the available components and records explicit uncertainty through the history confidence value.

### Regivion conviction

Regivion conviction combines:

- PSC score and rank
- PSC rank changes and Top 20 movement
- fresh bullish alerts
- revenue, earnings, and free-cash-flow growth
- insider buying and politician activity
- multiple independent signals agreeing

The score deliberately distinguishes absolute conviction from recency and rank acceleration.

### Content angles

- `MOMENTUM_CONVERGENCE`
- `VALUATION_DISLOCATION`
- `PSC_RANK_JUMP`
- `NEW_TOP20_ENTRY`
- `INSIDER_BUY`
- `POLITICIAN_BUY`
- `EARNINGS_ACCELERATION`
- `REVENUE_GROWTH_DISLOCATION`
- `TECHNICAL_BREAKOUT`
- `SOCIAL_SPIKE`
- `MULTI_SIGNAL_CONVERGENCE`

The primary angle is selected by rule-based precedence, and multiple supporting angles may be persisted.

### Visual recommendations

- PSC rank jump: PSC screenshot + price chart
- insider activity: insider transaction screenshot/card
- politician trade: politician disclosure graphic
- valuation dislocation: price drawdown + valuation chart
- momentum convergence: TradingView chart + PSC score
- other angles: generic price or trend chart

No image generation or automated posting is implemented.

### Cold-start handling

A zero historical baseline reduces scoring confidence instead of treating zero and established volume as equivalent. The opportunity scorer uses a minimum-observation threshold and a reduced history confidence factor so emerging trends can still qualify while avoiding overconfidence from very small samples.

### Novelty protection

Opportunities are not re-notified on every scan. A new alert must exceed the configured threshold, materialize a score increase of at least `OPPORTUNITY_RENOTIFY_DELTA`, or include a meaningful new Regivion or content signal. An opportunity may also receive a cooldown through `OPPORTUNITY_COOLDOWN_MINUTES` before it is eligible again.

### Mock mode

The Phase 3 mock scenario is deterministic and offline:

- MSFT: strong social acceleration, PSC rank jump, fresh bullish alert
- NVDA: strong social activity and excellent PSC score with little new change
- UBER: moderate social trend with strong valuation/FCF Regivion data
- XYZ: low social volume and no Regivion coverage

Provider selection is explicit: set `REGIVION_PROVIDER=http` for the API or `mock` for offline fixtures.

### CLI usage

```bash
python -m exitvector_agent scan
python -m exitvector_agent trends
python -m exitvector_agent opportunities
python -m exitvector_agent opportunities --limit 20
python -m exitvector_agent opportunity MSFT
```

Example output:

```text
1. MSFT  91.4  HIGH
   Social: 75.2
   Regivion: 98.0
   Angle: MULTI_SIGNAL_CONVERGENCE
   Reason: social acceleration + PSC rank 28 → 10
```

### Environment variables

- `EXITVECTOR_ENV`
- `EXITVECTOR_DATABASE_URL`
- `EXITVECTOR_SCAN_INTERVAL_SECONDS`
- `EXITVECTOR_NOTIFY_THRESHOLD`
- `REGIVION_BASE_URL`
- `REGIVION_API_KEY`
- `REGIVION_TIMEOUT_SECONDS`
- `EXITVECTOR_REGIVION_BASE_URL` and `EXITVECTOR_REGIVION_API_KEY` are accepted aliases
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

The Regivion API and Telegram integrations remain disabled unless explicitly configured and authorized.

### Current limitations

- No live Regivion integration or production endpoint access
- No AI-generated post copy
- No automatic X posting
- No Telegram delivery or deployment
- Opportunity freshness is based on local timestamps and mock data
- Market price data is intentionally modeled as an optional component for Phase 3

## Current Phase 1

The initial foundation includes:

- environment-backed settings
- structured JSON logging
- SQLite schema and configuration storage
- test coverage for the core contracts
- a project package and dependency configuration

## Phase 7 audience analysis

Audience analysis is offline and returns JSON with the selected source, reference
time, coverage, observed interaction metrics, scores, reasons, and recommendations.

```powershell
python -m exitvector_agent audience
python -m exitvector_agent audience --window 90d
python -m exitvector_agent audience never-interact
python -m exitvector_agent audience low-reciprocity
python -m exitvector_agent audience unfollow-candidates
python -m exitvector_agent audience high-value
python -m exitvector_agent audience following-not-back
python -m exitvector_agent audience followers-not-followed
python -m exitvector_agent audience mutuals
python -m exitvector_agent audience account @BETA
python -m exitvector_agent audience import normalized.json
python -m exitvector_agent audience --source database
python -m exitvector_agent audience --source archive --archive normalized.json
python -m exitvector_agent audience inspect-archive downloaded-x-archive.zip
```

Source selection: `--source mock|database|archive` overrides
`AUDIENCE_PROVIDER` (also `EXITVECTOR_AUDIENCE_PROVIDER`). The default `auto`
uses the database after a successful import, or an existing imported dataset;
otherwise it uses the mock fixture. Explicit database/archive sources never fall
back to mock data. Archive source paths can also use `AUDIENCE_ARCHIVE_PATH`.
Importing a normalized archive atomically selects the database for subsequent
automatic source selection. Mock and imported snapshots are isolated by source.

Windows: `30d`, `90d`, `180d`, `365d`, `all`. Events are actually filtered before
metrics and scoring. Windows end at the provider's evidence horizon, so an old
archive is not silently interpreted as a current snapshot. `--as-of 2026-06-30T00:00:00Z`
sets an explicit reference time. Requested periods outside known source coverage
reduce confidence rather than extending coverage. Original source coverage stays
intact when a selected window is materialized.

The never-interact query concerns **observed inbound interaction** from followed
accounts. It includes accounts with outbound user activity. High-confidence rows
describe absence only within covered categories and the selected period; low
coverage rows explicitly say the evidence is insufficient. An unavailable
category is JSON `null`, not a measured zero. Positive counts in incomplete
categories mean observed events, not complete history. Aggregate zero counts
always mean zero observed supported events, never proof that nothing happened.

Relationship value rewards inbound engagement, mutual status and bidirectional
conversation. Outbound effort alone does not establish reciprocal value.
The default high-value query threshold is 40; service score weights and this
threshold are configurable. Unfollow results require an existing outbound follow
and exclude relationships with value at least 70. Results are recommendations
for human review, with no follow/unfollow action capability.

Normalized JSON import is separate from native ZIP inspection. Its supported
top-level sections are `users`, `following`, `followers`, `posts`, `replies`,
`mentions`, `likes_received`, `likes_performed`, `reposts`, `quotes`, `coverage`,
`account_coverage`, and `current_user_id`. Unknown sections are rejected to avoid
silent data loss. Accounts need `id` or `account_id` (a username/handle is a
fallback). Following/follower membership is reconciled into both account and
relationship flags. Interactions need actor/target identity and a valid ISO time;
legacy inbound reply/mention records may use `user_id` and default their target
to the current user. Performed likes default the actor to the current user.
Post records store minimal text, author and timestamp data. Missing IDs use
canonical SHA-256 identifiers. If an explicit interaction ID conflicts with an
existing record's content, the entire import fails without changing prior data.

An explicit normalized section, including an empty array, signals availability
of that category. It does not establish a complete observation period. Without
explicit coverage, completeness is capped at 50% and window boundaries remain
unknown. A trustworthy normalized producer should provide coverage explicitly:

```json
{
  "following": [{"id": "u1", "username": "example"}],
  "followers": [],
  "replies": [],
  "coverage": {
    "following_available": true,
    "followers_available": true,
    "replies_available": false,
    "mentions_available": false,
    "likes_received_available": false,
    "reposts_available": false,
    "completeness": 0.35,
    "confidence": "LOW"
  }
}
```

`account_coverage` maps account IDs to complete account-specific coverage objects
and overrides global coverage without optimistic defaults. Direction-specific
flags include `replies_outbound_available`, `mentions_outbound_available`, and
`likes_performed_available`; `quotes_available` covers quotes. Inbound and outbound
availability should not be inferred from one another.

Imports commit accounts, reconciled relationships, interactions, minimal posts,
coverage, score snapshots and actual import-run/account links in one transaction.
Any failure rolls them all back, including source selection; no successful import
record remains. Repeat imports preserve entity counts and add a new audit run.
Coverage/score tables hold latest materialized values, not a historical time
series. Selected-window context is saved in configuration under
`audience_snapshot_context:<source>`.

**Native ZIP import remains UNSUPPORTED.** The separate inspector discovers
supported account/following/follower/tweet JS or JSON sections, including numbered
parts, and returns normalized previews plus missing/unsupported sections. It reads
bounded ZIP members without extracting files or executing JavaScript and rejects
unsafe paths, encrypted members and executable/non-JSON payloads. It does not
claim that all archive versions are supported, or infer inbound likes/replies
received from a user's own posts. A real ZIP can currently be provided for
compatibility inspection, not guaranteed direct import.

Reproduce all Phase 7 checks and regenerate the detailed verification report:

```powershell
python scripts/verify_phase7.py
```

The script uses disposable databases and synthetic archives, runs focused and
full tests, and writes `PHASE7_VERIFICATION.md` with actual scores, query results,
idempotency/rollback counts, native compatibility and a CLI command matrix.

## Phase 8: local operation

Provider availability described in this historical Phase 8 section is updated
by the Phase 9 section below; the operating commands and safety boundaries remain.

`AgentRunner` coordinates the existing services. It validates configuration,
acquires an OS lock for the resolved database path, ensures schema, records a
RUNNING history row, collects social observations, deduplicates observations,
calculates trends, enriches each ticker through Regivion, scores opportunities,
generates eligible content, validates final drafts, deduplicates before saving,
updates the human review queue, optionally refreshes audience analysis when due,
sends one local notification batch for actionable recommendations, and records
the final result. `watch` holds the lock while waiting between runs.

### First-time setup in Windows PowerShell

```powershell
Set-Location 'C:\Users\LetzPC Gaming\AI Agents\exitvector-agent'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
Copy-Item .env.example .exitvector.env
python -m exitvector_agent doctor
python -m exitvector_agent run --dry-run
python -m exitvector_agent run
python -m exitvector_agent status
```

Before the first real run, doctor warns that the database is not initialized.
The first run creates it. This workspace is not a Git repository. Keep local
configuration and secrets out of any future repository; ignore `.exitvector.env`,
`exitvector.env`, `.env`, `data/`, and `logs/` when introducing Git.

### Using ExitVector daily

1. Start: `python -m exitvector_agent watch`.
2. Check in another terminal: `python -m exitvector_agent status`.
3. Review: `python -m exitvector_agent review`, then `review show 1` for full text.
4. Approve with `review approve 1 --reviewer your-name`, or edit with
   `review edit 1 --text '$MSFT: your supported draft' --reviewer your-name`.
   Editing revalidates facts and requires a separate approval. Reject with
   `review reject 1 --reason 'Your reason'`, or archive with `review archive 1`.
5. View approved content: `python -m exitvector_agent ready`.
6. Manually post approved content to X.

**ExitVector does not automatically post to X.** Human approval remains required.
The operational ready view requires explicit approval, a reviewer, successful
machine validation, and no remaining human-review requirement. Legacy internal
queue semantics are preserved for compatibility; use the operational CLI for
this stricter handoff. Review lists one recommendation per opportunity; use
`review show <id>` to inspect a candidate and `ready` to see approved full text.

### Commands and scheduling

```powershell
python -m exitvector_agent run
python -m exitvector_agent run --verbose
python -m exitvector_agent run --quiet
python -m exitvector_agent run --dry-run
python -m exitvector_agent watch --interval 30m
python -m exitvector_agent status
python -m exitvector_agent doctor
python -m exitvector_agent notifications --unread
python -m exitvector_agent notifications read 1
python -m exitvector_agent backup
python -m exitvector_agent backup --output 'data\backups\manual-copy.db'
python -m exitvector_agent db-check
```

Stop watch with Ctrl+C: it closes connections, finishes the current run as
CANCELLED when interrupted, releases the lock, and prints
`ExitVector stopped safely.` Already committed valid work is preserved.
A finite demonstration supports `watch --cycles 2`; short intervals require
explicitly lowering `AGENT_MIN_INTERVAL_SECONDS` for testing. Watch waits after
completion, rather than trying to catch up missed wall-clock slots. Its next
scheduled run is visible through lock metadata while waiting.

External scheduling is optional; no scheduler configuration is installed.
For Windows Task Scheduler, use the absolute virtual-environment `python.exe`
as Program, `-m exitvector_agent run --quiet` as Arguments, and this workspace
as Start in. Choose a 30-minute trigger and prevent overlapping instances.
For cron, an example entry is:

```cron
*/30 * * * * cd /path/to/exitvector-agent && /path/to/.venv/bin/python -m exitvector_agent run --quiet
```

For systemd, a oneshot service can use `WorkingDirectory=/path/to/exitvector-agent`
and `ExecStart=/path/to/.venv/bin/python -m exitvector_agent run --quiet`, with a
separate timer using `OnUnitActiveSec=30min`. Use either an external scheduler or
built-in watch for a database. The OS lock also rejects concurrent scheduled runs.
Externally invoked CLI runs currently record MANUAL; WATCH and injected TEST
triggers are supported, and the runner accepts SCHEDULED_EXTERNAL for future use.

### Configuration and provider modes

Priority is CLI arguments (such as `--interval`) > environment variables > local
configuration file > defaults. `.exitvector.env` is discovered first, then
`exitvector.env`. Choose another file with
`python -m exitvector_agent --env-file 'path\local.env' run`.
Paths are relative to the working directory. `EXITVECTOR_DATABASE_URL` explicitly
selects the database; if absent, `AGENT_DATA_DIR/exitvector.db` is used. The legacy
`EXITVECTOR_SCAN_INTERVAL_SECONDS` setting is preserved; watch uses the Phase 8
minute setting below.

| Setting | Default / purpose |
| --- | --- |
| `EXITVECTOR_ENV` | `development`; production fails clearly because required live providers are unavailable |
| `AGENT_SCAN_INTERVAL_MINUTES` | 30 |
| `AGENT_MIN_INTERVAL_SECONDS` | 60; minimum watch interval |
| `AGENT_RUN_ON_START` | true; otherwise wait before the first watch run |
| `AGENT_DATA_DIR` / `AGENT_LOG_DIR` | `data` / `logs` |
| `AGENT_LOG_LEVEL` | INFO; DEBUG, WARNING, ERROR also supported |
| `AGENT_LOCK_TIMEOUT_MINUTES` | 60; long-running diagnostic, never steals a live lock |
| `AGENT_MAX_ERRORS_PER_RUN` | 10; stop remaining work when reached |
| `AGENT_PROVIDER_MAX_RETRIES` | 2; bounded transient retries, at most 5 configurable |
| `AGENT_RETRY_BACKOFF_SECONDS` | 0.1; bounded linear backoff |
| `AGENT_PROVIDER_TIMEOUT_SECONDS` | 10; timeout for asynchronous social collection |
| `AGENT_SOCIAL_PROVIDER` | mock; live adapters unavailable |
| `AGENT_REGIVION_PROVIDER` | mock; HTTP integration remains disabled |
| `EXITVECTOR_AI_PROVIDER` | mock; deterministic `rule-based` also supported |
| `EXITVECTOR_NOTIFY_THRESHOLD` | 75; meaningful review notification threshold |
| `AGENT_NOTIFY_REVIEW_ENABLED` | true; console and persisted local inbox only |
| `AGENT_AUDIENCE_REFRESH_ENABLED` | false |
| `AGENT_AUDIENCE_REFRESH_INTERVAL_HOURS` | 24 |
| `AUDIENCE_PROVIDER` | auto; also mock, database, archive |
| `ALLOW_X_POSTING` / `ALLOW_X_FOLLOW_ACTIONS` | false; enabling either rejects operation |

Mock social, Regivion and LLM providers are shown explicitly in run/status/doctor
output. They do not observe live markets. Quiet mode suppresses routine output,
including mock notices, so check status/doctor when configuring a scheduled job.
Production never falls back to mocks. No production Regivion or real LLM calls
are enabled. Existing imported audience data can be analyzed locally. Audience
refresh never automatically imports an archive: database/mock analysis is saved,
normalized archive analysis is read directly without import, and native ZIP
direct import remains unsupported.

### State, failures, dry runs, and maintenance

`agent_runs` stores timestamps, trigger, duration, status, counts and a compact
structured summary. Status reports the last run, last success, provider selection,
queue sizes, schedule and recent errors. Provider exceptions are recorded by stage
and type rather than raw text. Logs are structured JSON at `logs/exitvector.log`,
rotating at 2 MiB with three backups. They omit raw content/archive payloads and
redact configured secrets and credential-like fields.

Failures isolate social sources, ticker enrichment, content, audience and local
notification delivery. Transient timeouts/connections/provider 429 or server errors
receive bounded retries where applicable; malformed configuration, factuality
rejections and unsupported archives are not retried. Content provider failure
leaves the opportunity saved and pending for the next run. Notification failure
leaves a local undelivered item available for the next run. SUCCESS,
PARTIAL_SUCCESS, FAILED and CANCELLED distinguish outcomes. Recovery is partial
commit recovery, not an atomic rollback of an entire successful pipeline.

Single-instance locking uses a retained `.db.agent.lock` alongside the database:
Windows byte locking or POSIX flock. Process death releases the kernel lock;
leftover active metadata is recovered by the next owner, which also marks old
RUNNING rows CANCELLED. A live lock is never stolen due to elapsed time. Read-only
status/doctor/db-check and SQLite online backup remain available during watch.
Do not delete an active lock file.

Dry runs use a disposable SQLite online backup, because existing services commit
independently. Calculations, generation and validation run on the copy. The real
database, history, candidates, review decisions, audience state and inbox remain
unchanged; no notifier is called and no log file is written by the dry-run CLI.
A lock file and its parent directory may be created/updated for mutual exclusion;
console output is still produced. Reported preview run IDs are temporary.

Backup uses SQLite's online backup API rather than copying an open database file.
Defaults are timestamped under `AGENT_DATA_DIR/backups`; existing destinations
are rejected. `db-check` checks integrity, expected tables and essential columns
without VACUUM or mutation. Keep backups local and inspect integrity before use.

Reproduce the Phase 8 verification with `python scripts/verify_phase8.py`.
It uses disposable local databases, deterministic fixtures and injected waits;
its detailed CLI/history/recovery evidence is written to `PHASE8_VERIFICATION.md`.

## Phase 9: live read-only integrations

The existing runner selects implementations of `SourceAdapter`, `RegivionClient`
and `LLMProvider`. `RedditLiveSource` uses registered application OAuth and bounded
GET listings. `OpenAIProvider` uses Responses structured output with no tools and
`store=false`. Both use Phase 8 failure isolation and retry paths.

**Phase 9.1 supports the deployed read-only Regivion agent-v1 contract.**
`HTTPRegivionClient` consumes authenticated `GET /api/agent/v1/ticker/{symbol}`
and `GET /api/agent/v1/health` at `https://regivion.com`. See
[REGIVION_INTEGRATION.md](REGIVION_INTEGRATION.md) for normalization and null semantics.
Development `valuation-history` remains available through explicit selection.
Production requires agent-v1, the production HTTPS host, and a locally configured
read-only token; it never silently substitutes mock data. The previously approved
explicit reduced mode (`disabled`, `REGIVION_REQUIRED=false`) remains available.
No Regivion server changes are required or made.

There is no licensed market API/provider abstraction available here, so live
market integration remains disabled. The old development/mock market score is a
social-velocity proxy, not market-price evidence. Live runs omit this component
and renormalize missing inputs.

### Reddit and Stocktwits setup

Obtain approved Reddit Data API access appropriate to your use, a confidential
application's client ID/secret, and a truthful descriptive User-Agent. Access is
subject to Reddit's approval/terms; configured credentials do not prove access.
Select communities with `REDDIT_SUBREDDITS`. Only bounded authenticated
`/r/<community>/new` submission listings are read; no comments or full histories.
OAuth token acquisition uses POST and does not write account/content data.

Defaults: 60-minute lookback, at most 100 requested items total across selected
communities, one page/100 items per community, 1-second pacing, and a 10-second
HTTP timeout. Use a 120-minute lookback for an initial preceding-hour baseline;
subsequent scans reuse unique local rolling observations for the selected sources.
This is a bounded sample, not exhaustive Reddit coverage. Rate-limit headers and
Retry-After impose pacing/cooldown. The whole source also has Phase 8's scan
timeout: increase `AGENT_PROVIDER_TIMEOUT_SECONDS` for many communities while
retaining bounded individual request timeouts.

Stable observation IDs are `REDDIT_LIVE/t3_<id>`. Existing ticker extraction is
reused; lowercase explicit cashtags now work without weakening bare-word checks.
Title/body are transient extraction input. Persisted text contains only extracted
cashtags, time, engagement, community and provenance; usernames, profiles and raw
histories are not saved. Current-scan author diversity uses an ephemeral hash;
historical author diversity is conservative because identifiers are not stored.

Stocktwits' official developer page says new registrations are paused while its
APIs/documentation/terms are reviewed. Supported access for this application was
not established. Stocktwits live is explicitly disabled, with no scraping or
legacy unauthenticated endpoint workaround.

### OpenAI setup and cost controls

Set `LLM_PROVIDER=openai`, `LLM_API_KEY` (or `OPENAI_API_KEY`), and explicit
`LLM_MODEL`. Choose an accessible model supporting Responses structured output;
no model is silently selected. `LLM_TEMPERATURE` is optional: omit it for models
that reject temperature. Timeout defaults to 30 seconds; each response is bounded
to 800 output tokens. Model retrieval in live-check performs no inference but
cannot prove generation-parameter compatibility.

Only ContentBrief and writing constraints go to OpenAI. No raw Reddit history,
audience relationship data or archives are sent. Tools/browsing are unavailable.
Strict JSON requires text and the requested variant. Refused, incomplete, empty
or malformed responses fail. Existing allowlist, numeric/claim/ticker checks,
repair, final validation and mandatory human approval remain in force. Candidates
now save the actual provider/model and locally attached source observation IDs,
timestamps and Regivion provenance. Provenance is added after generation, not sent
to the model.

`LLM_MAX_GENERATIONS_PER_RUN=9` bounds attempted inference calls, including repairs
and retries. `CONTENT_VARIANTS_PER_OPPORTUNITY=3` and
`MAX_OPPORTUNITIES_PER_RUN=20` add bounds. Only actionable opportunities or pending
failed generations use inference. Identical scans do not regenerate unchanged
content. Budget exhaustion preserves completed valid variants and warns. These
are call/token bounds, not a guaranteed currency budget; configure account spend
limits separately.

### Configuration, provider health and diagnostics

New aliases take priority when both names are provided: `SOCIAL_PROVIDER_MODE`
over `AGENT_SOCIAL_PROVIDER`, `REGIVION_PROVIDER` over `AGENT_REGIVION_PROVIDER`,
and `LLM_PROVIDER`/`LLM_MODEL` over `EXITVECTOR_AI_PROVIDER`/`EXITVECTOR_AI_MODEL`.
CLI > environment > local file > defaults priority remains. Local secret files
must never be committed. This workspace has no Git repository or .gitignore;
ignore local env files, databases and logs before introducing Git.

Development allows explicit mock/live/mixed selection. Mixed output warns
`MIXED DATA MODE`; fixtures have `MOCK_REDDIT`/`MOCK_STOCKTWITS` provenance.
Production requires live Reddit and OpenAI, prohibits required mocks/mixed social,
and rejects existing fixture/unknown-provenance observations in its database.
Use a separate production database. Optional audience analysis remains explicitly
offline/mock/database/archive, with its actual source visible. No live X audience
collection exists. Both X action flags must remain false.

| Setting | Default / meaning |
| --- | --- |
| `SOCIAL_PROVIDER_MODE` | mock; live or explicit development mixed |
| `REDDIT_ENABLED` | false |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | required for live Reddit |
| `REDDIT_SUBREDDITS` | stocks,investing; 1-10 configurable communities |
| `REDDIT_MAX_ITEMS_PER_SCAN` | 100; 1-500 requested items total |
| `REDDIT_REQUEST_TIMEOUT_SECONDS` | 10 |
| `REDDIT_MIN_REQUEST_INTERVAL_SECONDS` | 1; minimum 0.6 |
| `SOCIAL_LOOKBACK_MINUTES` | 60; 1-1440 |
| `REGIVION_PROVIDER` | mock/http/disabled |
| `REGIVION_REQUIRED` | true; disabled requires explicit false |
| `REGIVION_CONTRACT` | agent-v1 (default); valuation-history is development only; unavailable fails validation |
| `REGIVION_BASE_URL`, `REGIVION_API_KEY` | explicit target and dedicated read credential; never browser/admin credentials |
| `REGIVION_TIMEOUT_SECONDS` | 10 |
| `REGIVION_CACHE_TTL_SECONDS` | 60 |
| `REGIVION_MAX_AGE_SECONDS` | 86400; old/unknown timestamps lower confidence |
| `LLM_TIMEOUT_SECONDS` | 30 |
| `LLM_MAX_GENERATIONS_PER_RUN` | 9, including repairs/retries |
| `CONTENT_VARIANTS_PER_OPPORTUNITY` | 3 |
| `MAX_OPPORTUNITIES_PER_RUN` | 20 |
| `MARKET_PROVIDER` | disabled; no live price API integrated |
| `PROVIDER_CIRCUIT_FAILURE_THRESHOLD` | 3 |
| `PROVIDER_CIRCUIT_COOLDOWN_SECONDS` | 300 |

Small `provider_health:<name>` configuration records store last success/failure,
consecutive failures, auth/reachability state and cooldown. Per-run history stores
attempted/succeeded/failed requests, retries, 429 events, latency and cache hits.
Null means untested, not authenticated/reachable. Retry-After gates further calls;
repeated failures open a bounded circuit that persists across watch runs. Health
contains no headers, payloads or raw exception messages. Regivion outages use
visibly missing-component scoring; LLM outages preserve pending opportunities.

`doctor` is local and makes no network calls. `doctor --live` and `live-check`
perform minimal read probes: Reddit OAuth plus one listing, OpenAI model GET,
and authenticated Regivion `/api/agent/v1/health`. A 200 verifies agent authorization;
a 401 reports rejected credentials. No draft is generated. Development
valuation-history still uses public liveness with an UNVERIFIED warning.
Live-check neither writes business data nor persists health; normal runs do.
Status displays recorded provider health rather than pretending to have probed it.

### Going live

1. Copy `.env.example` to `.exitvector.env`; add credentials locally.
2. Select live Reddit and OpenAI with their required settings.
3. Set `REGIVION_PROVIDER=http`, `REGIVION_BASE_URL=https://regivion.com`, and
   `REGIVION_CONTRACT=agent-v1`. Add the dedicated read-only token manually in
   `.exitvector.env`. Never paste it into chat, reports, or source files.
4. Choose a clean production database and `EXITVECTOR_ENV=production` once all
   selected required providers are configured. Never substitute localhost.
5. Run `python -m exitvector_agent doctor`, then
   `python -m exitvector_agent live-check`.
6. Only after live-check passes, run `python -m exitvector_agent run --dry-run --symbol MSFT`.
7. Only after the dry run succeeds, run `python -m exitvector_agent run --symbol MSFT`.
   Review the generated ContentBrief, factuality result, and local review state.
8. Start `python -m exitvector_agent watch`; stop with Ctrl+C.

Single-ticker selection bounds enrichment/generation; social reads still use the
bounded community sample. Legacy scan/trends/opportunities/content generation
commands remain fixture-only and reject live configurations; use run with the
configured provider set. Existing review/ready/audience commands remain available.
A live dry run protects local business state but **can read external providers
and spend bounded LLM inference calls**. No review notifications or publication occur.

**ExitVector does not post to X automatically.** External operations are social
OAuth and reads, authenticated Regivion/market reads when supported, and LLM
inference. Posting, replies, likes, follows/unfollows, DMs, account modifications,
trading and order execution are absent. No production deployment or scheduler
configuration is changed by this phase.

Reproduce offline checks with `python scripts/verify_phase9.py`; outputs and
limitations are recorded in `PHASE9_VERIFICATION.md`.

Primary technical references checked during implementation:
[Reddit OAuth](https://github.com/reddit-archive/reddit/wiki/OAuth2),
[Reddit API guidance](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki),
[Stocktwits developer status](https://api.stocktwits.com/developers),
[OpenAI structured output](https://developers.openai.com/api/docs/guides/structured-outputs),
and [OpenAI model retrieval](https://developers.openai.com/api/reference/resources/models/methods/retrieve).

### Phase 9.1 evidence semantics

PSC score and rank are independent: score 96.2 with null rank is valid evidence.
Null current/previous ranks never imply Top 20 membership, movement or acceleration.
The production PSC context (`portfolio_key`) and scoring profile are preserved.
Empty alerts with `coverage.alerts=false` mean no usable ticker coverage; this is
separate from an empty list with coverage true, missing components, and health
capabilities. Unsupported growth metrics remain null. Insider buy/sell directions,
transaction/disclosure dates, identifiers and politician amount bounds are preserved;
no exact amount is derived from a range. Market coverage false supplies no market score.

Component `as_of` values determine age and staleness. `generated_at` describes the
response generation time; `received_timestamp` records the local receipt. Neither
refreshes financial source dates. PSC evidence dated September 29 remains visibly
dated September 29 in summaries and briefs. Old, unknown or future source times
reduce confidence and freshness; cache reads advance age without changing receipt
time. The factuality guard rejects unsupported ranking, alerts, growth and market
claims even when a hallucinated number matches an allowed PSC score.

Regivion status includes contract, host, authenticated and reachable state. It reports
live only after authenticated agent health succeeds; public liveness cannot do this.
The fixture tests validate the supplied production shape; real verification requires
local credentials and is recorded separately in [PHASE9_1_VERIFICATION.md](PHASE9_1_VERIFICATION.md).
