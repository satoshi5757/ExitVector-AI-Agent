# Phase 9.1 verification

Date: 2026-10-08 (Europe/Madrid)
Classification: PARTIALLY_READY

## Architecture and contract

Extended the existing HTTPRegivionClient, RegivionEnrichment, provider setup,
health/circuit state, opportunity service and content validation. No duplicate
provider architecture was added. The existing contract selector now defaults to
agent-v1; explicit development valuation-history and fail-closed unavailable remain.

The fixture target is the sanitized deployed production JSON supplied by the user,
not an independently fetched production response. GET agent-v1 ticker reads map
independent PSC score/rank/previous rank/status/transitions; explicit fundamentals;
alerts; insider recent_buys/recent_sells; and politician recent_trades. Explicit
buy/sell directions, transaction/disclosure dates, source identifiers, shares,
insider value bounds and politician amount bounds survive normalization. No exact
transaction value is inferred from bounds. The PSC portfolio key and scoring
profile are retained. Unknown response fields are excluded from persisted evidence.

## Nulls, coverage and freshness

A PSC score of 96.2 with null rank is usable scoring evidence. Current rank,
previous rank, rank change, acceleration and Top 20 transitions remain null.
The scoring and brief paths do not invent ranking facts. Unsupported growth
metrics remain null. Missing components remain unavailable. Empty alerts with
usable coverage, false ticker coverage and absent coverage remain distinguishable.
Health capabilities are separate from ticker coverage. Unavailable market fields
remain null and live market scoring remains omitted, with missing-input normalization.

Component source dates produce UTC timestamps, ages and stale flags. The response
generation and receipt times do not refresh financial evidence. Cache hits update
age without changing source or receipt time. The supplied September 29 PSC and
September 22 fundamentals are stale under the default one-day maximum age; source
dates remain visible in briefs, confidence is LOW and freshness is zero. Missing
or future source dates are stale. Old/undated alerts cannot create a fresh bullish
alert trigger, and social acceleration cannot create a live technical breakout angle.

## Health, configuration and status

Authenticated GET agent-v1 health is checked before first enrichment when runner
provider health is attached. Existing safe health history, retries and circuits are
reused. A successful health check records authentication and reachability; a 401
rejects credentials without fallback. Status includes contract and host and only
marks Regivion live after authenticated agent health succeeds. Live-check uses
agent-v1 health with no inference or business DB writes; public development liveness
continues to carry an unverified warning. No request headers or raw exceptions are
persisted in health.

Production HTTP requires agent-v1 at https://regivion.com with a locally configured
read-only credential. HTTP, localhost/private literal hosts, alternate production
hosts, missing credential, mock fallback, secret-bearing base URLs and development
valuation-history are rejected. The existing explicitly approved reduced disabled
mode remains available only with the required flag set false.

## Offline verification

Fixture tests prohibit real network access and cover the supplied production shape,
nullable/optional components, malformed payload/health, authenticated health, 401,
403 and 503 failures, partial fundamentals, score without rank, empty/false alert
coverage, insider direction/dates/bounds, politician ranges, missing market,
source freshness, cache aging, unknown response field exclusion, secret-safe
persistence/logging, provider health/status, production gates, repeated-run dedup,
and dry-run business DB isolation. Existing Phase 9 tests were not weakened.

Focused command: `python -m pytest -q tests/test_phase9_1_regivion.py tests/test_phase9_live.py`

Latest focused result: **109 passed** (48 Phase 9.1 cases and 61 existing Phase 9 cases).
Full-suite command: `python -m pytest -q`

Latest full-suite result: **317 passed in 56.00 seconds**. All 315 prior tests remain green;
two focused SQLite remediation regressions were added. Focused run: 109 passed in 16.78 seconds.

## ContentBrief evidence and factuality

Offline production-shaped brief assertions verify these selected facts:

- PSC score 96.2.
- PSC source date 2026-09-29.
- Forward PE 25.25086417075335 and PEG 1.3255409332062755, formatted for display.
- Social observations and explicit politician transaction counts, where selected.

There is no rank, previous-rank movement, Top 20 entry, current bullish alert,
unsupported growth or current market-price evidence. The guard accepts the supported
PSC score and source date and rejects ranking claims even if the invented rank
reuses the allowed score number. It also rejects unsupported Top 20, acceleration,
alert, growth, price and breakout claims. This is a conservative text validator,
not a general proof of every possible natural-language claim; human review remains
mandatory. No LLM draft was generated during real verification because the opportunity stayed below threshold.
A ContentBrief constructed in memory from the real Regivion opportunity was inspected
and passed the supported-score and unsupported-claim guard probes described below.

The repeated-run fixture explicitly lowers its test notification threshold to 65
to exercise content/review creation with stale score-only PSC evidence. Production
thresholds and stale-data safeguards are unchanged. Below-threshold evidence may
legitimately produce no draft in a real run. A repeated fixture run creates no
new observations/content/review items or notifications. Dry-run writes are isolated.

## SQLite dry-run remediation

### Confirmed root cause and reproduction

Exact exception: **sqlite3.OperationalError: no such column: deduplication_key**.

The local business database had the legacy notifications columns: id, ticker,
score, channel, payload, created_at, delivered_at. CREATE TABLE IF NOT EXISTS
retained that table unchanged. The existing additive migration added opportunity_id
and is_read, but omitted candidate_id, review_action and deduplication_key. Its next
statement attempted to index the absent deduplication_key column. This is a schema
migration defect, not a provider-health, Windows URI, permission or backup defect.

Reproduction command: `python -m exitvector_agent run --dry-run --symbol MSFT`.
The exception was captured in memory without printing local variables or credentials.
The application caught it and returned CLI exit code 2. Relevant traceback:

```text
operations.py:236 execute -> runner.run_once(...)
agent.py:139 run_once -> _open_and_run(...)
agent.py:159 _open_and_run -> ensure_schema(db)
database.py:1010 ensure_schema -> CREATE UNIQUE INDEX IF NOT EXISTS
    notifications_event_key ON notifications(deduplication_key)
    WHERE deduplication_key IS NOT NULL
database.py:36 execute -> self._connection.execute(query, parameters)
sqlite3.OperationalError: no such column: deduplication_key
```

Paths captured during reproduction:

- Working directory: `C:\Users\LetzPC Gaming\AI Agents\exitvector-agent`.
- Business database: `C:\Users\LetzPC Gaming\AI Agents\exitvector-agent\data\exitvector.db`.
- Disposable copy: `C:\Users\LETZPC~1\AppData\Local\Temp\exitvector_dry_run_hy4j98db\preview.db`.

The read-only source opened successfully, SQLite online backup completed, and the
writable disposable copy opened successfully. Failure occurred afterward during
schema initialization, before providers or health writes were initialized. Journal
mode was delete; no WAL/SHM files existed. Business DB bytes were unchanged after
reproduction. The temporary directory was cleaned up during exception unwinding.

### Minimal fix and isolation audit

The notification migration now adds candidate_id, review_action and deduplication_key
alongside its existing columns before creating the deduplication index. Existing
rows remain intact; new fields are nullable, and repeated schema initialization is
idempotent. No unrelated provider, scoring, logging or runner implementation changed.

The dry-run flow still uses a read-only source connection and SQLite online backup,
closes the destination connection, closes the source, opens the copy writable,
initializes its schema, and passes that same copy connection to all business services
and provider health/circuit persistence. No DB URL rewrite is needed because those
services receive the explicit copy Database object. Providers receive the copy via
attach_health. DB context exit precedes temporary-directory cleanup. Dry runs skip
the notifier and file logging. Lock/crash recovery implementation is unchanged.

### Regression and test results

Added two offline tests in tests/test_phase9_1_regivion.py:

- test_dry_run_migrates_legacy_notifications_only_on_backup reproduces the exact
  seven-column legacy schema with an existing row; authenticated agent-v1 health
  and enrichment succeed on the temporary copy; original DB bytes/schema/notification
  row remain unchanged; no run/opportunity/content/review/health writes persist;
  notifier receives no batches; temporary-directory cleanup completes.
- test_legacy_notification_migration_preserves_rows_and_is_idempotent verifies
  existing records survive, nullable defaults are correct and the index exists.

Targeted command: both named tests via `python -m pytest -q`: **2 passed**.
Focused command: `python -m pytest -q tests/test_phase9_1_regivion.py tests/test_phase9_live.py`:
**109 passed**.
Full suite: **317 passed in 56.00 seconds**.

The first full-suite attempt returned 316 passed / 1 failed because an existing
subprocess CLI test discovered the newly configured local .exitvector.env and used
live Regivion rather than its expected mock provider. That attempt made live GET
reads from temporary test databases; it was not an entirely offline run. No test
assertions or credentials were changed. The final full-suite run used a disposable
working directory inside the repository, with the absolute tests directory and
PYTHONPATH pointing to src, preventing subprocesses from discovering the local
secret file. Its directory was removed afterward. The final suite passed unchanged.

## Ordered real external verification after tests

All three requested commands completed with **exit code 0** in order. PYTHONPATH=src
was set for this checkout's src-layout interpreter. Verification instrumentation
captured command output, HTTP method/host/path, evidence, in-memory brief validation,
DB counts and file hashes. Headers, credential values and local variables were not
printed or persisted. Final database/log byte checks found no configured credential
values. No credential configuration was changed.

### Step 1: live-check

`python -m exitvector_agent live-check`: **PASS**.
Authenticated agent-v1 health at regivion.com succeeded. Reddit/OpenAI were skipped;
Stocktwits and market stayed disabled. Business DB/log bytes stayed unchanged.
The only external request was GET /api/agent/v1/health.

### Step 2: MSFT dry run

`python -m exitvector_agent run --dry-run --symbol MSFT`: **SUCCESS**.
The disposable DB ran the full pipeline; original business DB and real log file
hashes were identical before/after. Temporary-directory cleanup completed. No
notifications were sent. External requests were GET agent-v1 health and ticker/MSFT.

Actual normalized Regivion evidence:

| Evidence | Verified value |
| --- | --- |
| PSC score | 96.2 |
| Current/previous rank, rank change | null |
| Top 20 entry/exit, acceleration | null |
| PSC source timestamp | 2026-09-29T00:00:00+00:00 |
| PSC age | Approximately 852704 seconds at receipt; stale=true |
| Fundamentals source | 2026-09-22; stale=true |
| Forward PE / PEG | 25.25086417075335 / 1.3255409332062755 |
| Revenue/earnings/FCF growth | null |
| Alerts | Empty; ticker coverage=false; health capability=true |
| Insider buys/sells | 0 / 6 |
| Politician trades | 20; amount bounds preserved by normalization |
| Market | coverage=false; price/change/volume fields null |
| Provenance | REGIVION_HTTP, agent-v1, regivion.com, is_live_data=true |

The dry-run receipt time was 2026-10-08T20:51:43.930782+00:00; financial source times
remained unchanged. The opportunity was score 61.2, confidence LOW, freshness zero,
market score null, and notification-ineligible. No draft was forced below threshold.

A verification-only ContentBrief was constructed in memory from this real enrichment
and the configured mock social observations. Its allowed facts included PSC score
96.2, PSC source date 2026-09-29, Forward PE 25.2509, PEG 1.32554, and supported
transaction counts. This is not an LLM-generated draft. The guard accepted the
supported PSC-score claim and rejected all eight probes: invented rank, Top 20,
rank acceleration, fresh bullish alert, revenue growth, earnings growth, current
price, and technical breakout. Top 20 was rejected despite 20 being an otherwise
allowed count, preserving the distinction between numerical and ranking evidence.

### Step 3: MSFT local run

`python -m exitvector_agent run --symbol MSFT`: **SUCCESS**, run #1.
The same real Regivion evidence and guard results were observed. The existing MSFT
opportunity was updated by appending a persisted snapshot (opportunity rows 15 -> 16).
One completed agent run and the live agent-v1 Regivion snapshot/health were persisted.
Read-only inspection afterward confirmed score 61.2, rank null, September 29 PSC
source time, market score null, freshness zero, confidence LOW, and authenticated/
reachable provider health. Only GET agent-v1 health and ticker/MSFT were requested.

Content candidate rows remained 9; no new candidates or review items were created.
Notifications and review audit rows remained zero. Eligible pending review and
ready-to-post queues were empty. Three pre-existing MSFT legacy candidates remained
PENDING with requires_human_review=1 and ready_to_post=0; they had no brief snapshots
and were not treated as newly validated drafts. Human approval remains mandatory.

### Final classification and scope

**PARTIALLY_READY** for full production use. The SQLite defect is fixed, all tests
are green, real authenticated Regivion health/enrichment work, both MSFT runs succeed,
and real null-rank/freshness/factuality semantics are verified. However, the local
configuration still selects development mode, mock social and mock content providers.
This is verified live Regivion with mixed inputs, not verified live Reddit/OpenAI or
an approved production configuration. No providers or thresholds were changed to
force a draft. The no-draft result is valid threshold/stale-data behavior.

No X HTTP requests, posting, follow/unfollow operations or automatic approval occurred.
Regivion, Hetzner, production credentials, deployments, commits and pushes were untouched.

## Files changed

- src/exitvector_agent/database.py (focused SQLite remediation)
- src/exitvector_agent/regivion.py
- src/exitvector_agent/config.py
- src/exitvector_agent/live_checks.py
- src/exitvector_agent/provider_health.py
- src/exitvector_agent/provider_setup.py
- src/exitvector_agent/agent.py
- src/exitvector_agent/opportunity_service.py
- src/exitvector_agent/content.py
- tests/test_phase9_1_regivion.py
- .env.example
- README.md
- REGIVION_INTEGRATION.md
- PHASE9_1_VERIFICATION.md

No Regivion modifications, production deployment, commits, pushes, X writes,
follow/unfollow actions, Stocktwits activation or market integration were performed.
Tests use temporary databases. The authorized real local MSFT run persisted business state
only after the repaired dry run passed; dry-run business state remained unchanged.
