# Phase 9 live-provider verification

All integration demonstrations below use synthetic HTTP fixtures and disposable databases. LIVE describes the selected implementation/provenance, not a real external verification. No production services or Regivion files were modified; no commit, push, deployment, scraping, browser automation, X actions or trading occurred.

## Focused Phase 9 tests

```text
.............................................................            [100%]
61 passed in 7.60s
```

## Full pytest, including all 208 unchanged baseline tests

```text
........................................................................ [ 26%]
........................................................................ [ 53%]
........................................................................ [ 80%]
.....................................................                    [100%]
269 passed in 40.50s
```

## Development/mock doctor output

```text
$ python -m exitvector_agent doctor
[PASS] Python: 3.11.9
[PASS] Operational configuration: Validated; no secrets displayed
[PASS] Writable data directory: C:\Users\LetzPC Gaming\AppData\Local\Temp\exitvector_phase9_3ufwkcn3
[PASS] Writable log directory: C:\Users\LetzPC Gaming\AppData\Local\Temp\exitvector_phase9_3ufwkcn3\logs
[WARN] SQLite/schema: Not initialized; first run initializes it
[PASS] Process lock: Available
[WARN] Social sources: mock (Stocktwits/Reddit fixtures)
[WARN] Stocktwits live: DISABLED - supported API access not established
[PASS] Regivion: mock
[WARN] Regivion credentials: NOT CONFIGURED
[WARN] Content generator: LLM/mock
[WARN] OpenAI credentials: NOT CONFIGURED
[WARN] Market: DISABLED (no licensed live market API discovered)
[PASS] Review service: Human approval required; only explicitly approved content appears in ready
[WARN] Audience source: mock (auto; database not initialized)
[PASS] X posting: DISABLED
[PASS] X relationship actions: DISABLED
Exit code: 0
```

## Production rejects required mocks

```text
$ python -m exitvector_agent run
ERROR: Production requires live social and OpenAI, and HTTP Regivion or explicit disabled mode; mock fallback is prohibited
Exit code: 2
```

## Actual live-check without credentials

```text
$ python -m exitvector_agent live-check
[SKIP] Reddit: LIVE CHECK SKIPPED - live source/credentials not configured
[WARN] Stocktwits: DISABLED - supported API access not established
[SKIP] Regivion: LIVE CHECK SKIPPED - HTTP contract/credentials not configured
[SKIP] OpenAI: LIVE CHECK SKIPPED - provider/credentials not configured
[SKIP] Market: DISABLED - no supported licensed live endpoint discovered
[PASS] X actions: DISABLED
Exit code: 0
```

## Existing offline run remains operational

```text
$ python -m exitvector_agent run
2 new ExitVector review item(s): MSFT (81.6), NVDA (76.3)
ExitVector Agent — Run #1 — SUCCESS
Providers: social=mock (Stocktwits/Reddit fixtures); regivion=mock; content=LLM/mock; market=DISABLED (no licensed live market API discovered); audience=mock; X posting=DISABLED; X relationship actions=DISABLED
WARNING: MOCK social and Regivion data are offline fixtures; this run does not observe live markets.
Social scan: 56 new observations; 3 trends
Opportunities: 3 new, 0 updated
Content/validation: 6 valid new candidates
Review queue: 2 new item(s); notifications: 1 batch(es)
Audience refresh: SKIPPED
  MSFT — 81.6 — MULTI_SIGNAL_CONVERGENCE — variant PUNCHY (candidate #1)
  NVDA — 76.3 — VALUATION_DISLOCATION — variant PUNCHY (candidate #4)
Review with: python -m exitvector_agent review
Completed in 0.22s. No automatic posts were made.
Exit code: 0
```

## Existing status plus provider health visibility

```text
$ python -m exitvector_agent status
ExitVector — HEALTHY
Database: C:\Users\LetzPC Gaming\AppData\Local\Temp\exitvector_phase9_3ufwkcn3\cli.db
social: mock (Stocktwits/Reddit fixtures)
regivion: mock
content: LLM/mock
market: DISABLED (no licensed live market API discovered)
audience: mock
X posting: DISABLED
X relationship actions: DISABLED
last_run: #1 2026-10-08T08:51:58.938255+00:00 SUCCESS (0.22s)
last_successful_run: #1 2026-10-08T08:51:58.938255+00:00 SUCCESS (0.22s)
last_successful_live_run: none
Next scheduled run: none
Pending review: 6; ready to post: 0; pending opportunities: 2
Recent errors: []
Provider health (null = untested): [{"provider_name": "reddit", "provider_type": "social", "configured": false, "live": true, "read_only": true, "authenticated": null, "reachable": null, "last_success_at": null, "last_failure_at": null, "consecutive_failures": 0, "error_summary": null, "circuit_open_until": 0}, {"provider_name": "stocktwits", "provider_type": "social", "configured": false, "live": false, "read_only": true, "authenticated": null, "reachable": null, "last_success_at": null, "last_failure_at": null, "consecutive_failures": 0, "error_summary": null, "circuit_open_until": 0}, {"provider_name": "regivion", "provider_type": "enrichment", "configured": false, "live": false, "read_only": true, "authenticated": null, "reachable": null, "last_success_at": null, "last_failure_at": null, "consecutive_failures": 0, "error_summary": null, "circuit_open_until": 0}, {"provider_name": "openai", "provider_type": "llm", "configured": false, "live": true, "read_only": true, "authenticated": null, "reachable": null, "last_success_at": null, "last_failure_at": null, "consecutive_failures": 0, "error_summary": null, "circuit_open_until": 0}]
Exit code: 0
```

## Live-shaped Reddit/OpenAI run: explicit missing Regivion mode

```text
{
  "run_id": 1,
  "started_at": "2026-10-08T09:00:00+00:00",
  "completed_at": "2026-10-08T09:00:00+00:00",
  "duration_seconds": 0,
  "status": "SUCCESS",
  "trigger_type": "TEST",
  "dry_run": false,
  "social_scan_result": [
    {
      "source": "REDDIT_LIVE",
      "status": "OK",
      "observed": 40
    }
  ],
  "content_generation_result": [
    {
      "symbol": "MSFT",
      "generated": 3,
      "created": 3,
      "rejected": 0,
      "validation": [
        {
          "variant": "PUNCHY",
          "valid": true,
          "rejection_reasons": []
        },
        {
          "variant": "QUESTION",
          "valid": true,
          "rejection_reasons": []
        },
        {
          "variant": "DATA_DRIVEN",
          "valid": true,
          "rejection_reasons": []
        }
      ]
    }
  ],
  "observations_created": 40,
  "trend_count": 1,
  "opportunities_created": 1,
  "opportunities_updated": 0,
  "content_candidates_created": 3,
  "review_items_created": 1,
  "notifications_sent": 1,
  "audience_refresh_result": {
    "status": "SKIPPED"
  },
  "opportunities": [
    {
      "symbol": "MSFT",
      "score": 75.4,
      "confidence": "MEDIUM",
      "angle": "SOCIAL_SPIKE",
      "notification_eligible": true,
      "reason": "SCORE_DELTA",
      "components": {
        "social": 93.33333333333333,
        "regivion": 0.0,
        "novelty": 20.0
      },
      "trigger_reasons": [
        "social acceleration 40.00x"
      ]
    }
  ],
  "review_handoff": [
    {
      "candidate_id": 1,
      "symbol": "MSFT",
      "score": 75.4,
      "angle": "SOCIAL_SPIKE",
      "variant": "PUNCHY"
    }
  ],
  "providers": {
    "social": "live (Reddit OAuth; Stocktwits DISABLED)",
    "regivion": "disabled",
    "content": "OpenAI/configured-test-model",
    "market": "DISABLED (no licensed live market API discovered)",
    "audience": "mock",
    "X posting": "DISABLED",
    "X relationship actions": "DISABLED"
  },
  "warnings": [
    "LIVE SOCIAL/LLM; REGIVION EXPLICITLY DISABLED"
  ],
  "errors": [],
  "provider_metrics": {
    "reddit": {
      "requests_attempted": 2,
      "requests_succeeded": 2,
      "requests_failed": 0,
      "retries": 0,
      "rate_limit_events": 0,
      "latency_seconds": 0.0,
      "cache_hits": 0
    },
    "openai": {
      "requests_attempted": 3,
      "requests_succeeded": 3,
      "requests_failed": 0,
      "retries": 0,
      "rate_limit_events": 0,
      "latency_seconds": 0.0,
      "cache_hits": 0
    }
  },
  "provider_status": [
    {
      "provider_name": "reddit",
      "provider_type": "social",
      "configured": true,
      "live": true,
      "read_only": true,
      "authenticated": true,
      "reachable": true,
      "last_success_at": "2026-10-08T08:51:59.632863+00:00",
      "last_failure_at": null,
      "consecutive_failures": 0,
      "error_summary": null,
      "circuit_open_until": 0
    },
    {
      "provider_name": "stocktwits",
      "provider_type": "social",
      "configured": false,
      "live": false,
      "read_only": true,
      "authenticated": null,
      "reachable": null,
      "last_success_at": null,
      "last_failure_at": null,
      "consecutive_failures": 0,
      "error_summary": null,
      "circuit_open_until": 0
    },
    {
      "provider_name": "regivion",
      "provider_type": "enrichment",
      "configured": false,
      "live": false,
      "read_only": true,
      "authenticated": null,
      "reachable": null,
      "last_success_at": null,
      "last_failure_at": null,
      "consecutive_failures": 0,
      "error_summary": null,
      "circuit_open_until": 0
    },
    {
      "provider_name": "openai",
      "provider_type": "llm",
      "configured": true,
      "live": true,
      "read_only": true,
      "authenticated": true,
      "reachable": true,
      "last_success_at": "2026-10-08T08:51:59.808628+00:00",
      "last_failure_at": null,
      "consecutive_failures": 0,
      "error_summary": null,
      "circuit_open_until": 0
    }
  ]
}
```

## Identical repeated run

```text
{
  "run_id": 2,
  "started_at": "2026-10-08T09:00:00+00:00",
  "completed_at": "2026-10-08T09:00:00+00:00",
  "duration_seconds": 0,
  "status": "SUCCESS",
  "trigger_type": "TEST",
  "dry_run": false,
  "social_scan_result": [
    {
      "source": "REDDIT_LIVE",
      "status": "OK",
      "observed": 40
    }
  ],
  "content_generation_result": [],
  "observations_created": 0,
  "trend_count": 1,
  "opportunities_created": 0,
  "opportunities_updated": 1,
  "content_candidates_created": 0,
  "review_items_created": 0,
  "notifications_sent": 0,
  "audience_refresh_result": {
    "status": "SKIPPED"
  },
  "opportunities": [
    {
      "symbol": "MSFT",
      "score": 75.4,
      "confidence": "MEDIUM",
      "angle": "SOCIAL_SPIKE",
      "notification_eligible": false,
      "reason": null,
      "components": {
        "social": 93.33333333333333,
        "regivion": 0.0,
        "novelty": 20.0
      },
      "trigger_reasons": [
        "social acceleration 40.00x"
      ]
    }
  ],
  "review_handoff": [],
  "providers": {
    "social": "live (Reddit OAuth; Stocktwits DISABLED)",
    "regivion": "disabled",
    "content": "OpenAI/configured-test-model",
    "market": "DISABLED (no licensed live market API discovered)",
    "audience": "mock",
    "X posting": "DISABLED",
    "X relationship actions": "DISABLED"
  },
  "warnings": [
    "LIVE SOCIAL/LLM; REGIVION EXPLICITLY DISABLED"
  ],
  "errors": [],
  "provider_metrics": {
    "reddit": {
      "requests_attempted": 1,
      "requests_succeeded": 1,
      "requests_failed": 0,
      "retries": 0,
      "rate_limit_events": 0,
      "latency_seconds": 0.0,
      "cache_hits": 0
    },
    "openai": {
      "requests_attempted": 0,
      "requests_succeeded": 0,
      "requests_failed": 0,
      "retries": 0,
      "rate_limit_events": 0,
      "latency_seconds": 0.0,
      "cache_hits": 0
    }
  },
  "provider_status": [
    {
      "provider_name": "reddit",
      "provider_type": "social",
      "configured": true,
      "live": true,
      "read_only": true,
      "authenticated": true,
      "reachable": true,
      "last_success_at": "2026-10-08T08:51:59.838151+00:00",
      "last_failure_at": null,
      "consecutive_failures": 0,
      "error_summary": null,
      "circuit_open_until": 0
    },
    {
      "provider_name": "stocktwits",
      "provider_type": "social",
      "configured": false,
      "live": false,
      "read_only": true,
      "authenticated": null,
      "reachable": null,
      "last_success_at": null,
      "last_failure_at": null,
      "consecutive_failures": 0,
      "error_summary": null,
      "circuit_open_until": 0
    },
    {
      "provider_name": "regivion",
      "provider_type": "enrichment",
      "configured": false,
      "live": false,
      "read_only": true,
      "authenticated": null,
      "reachable": null,
      "last_success_at": null,
      "last_failure_at": null,
      "consecutive_failures": 0,
      "error_summary": null,
      "circuit_open_until": 0
    },
    {
      "provider_name": "openai",
      "provider_type": "llm",
      "configured": true,
      "live": true,
      "read_only": true,
      "authenticated": true,
      "reachable": true,
      "last_success_at": "2026-10-08T08:51:59.808628+00:00",
      "last_failure_at": null,
      "consecutive_failures": 0,
      "error_summary": null,
      "circuit_open_until": 0
    }
  ]
}
```

## Reddit normalized persistent evidence (no raw text or author)

```text
[
  {
    "source": "REDDIT_LIVE",
    "external_id": "t3_post0",
    "observed_at": "2026-10-08T08:55:00+00:00",
    "raw_text": "$MSFT $NVDA",
    "author": "",
    "likes": 100,
    "replies": 5,
    "metadata": "{\"is_live_data\": true, \"provider_source\": \"REDDIT_LIVE\", \"source_timestamp\": \"2026-10-08T08:55:00+00:00\", \"subreddit\": \"stocks\"}"
  },
  {
    "source": "REDDIT_LIVE",
    "external_id": "t3_post1",
    "observed_at": "2026-10-08T08:55:00+00:00",
    "raw_text": "$MSFT $NVDA",
    "author": "",
    "likes": 100,
    "replies": 5,
    "metadata": "{\"is_live_data\": true, \"provider_source\": \"REDDIT_LIVE\", \"source_timestamp\": \"2026-10-08T08:55:00+00:00\", \"subreddit\": \"stocks\"}"
  }
]
```

## Live-provider candidate traceability and human-review safeguard

```text
[
  {
    "id": 1,
    "opportunity_id": 1,
    "ticker": "MSFT",
    "provider": "openai",
    "model": "configured-test-model",
    "prompt_version": "EXITVECTOR_CONTENT_PROMPT_V1",
    "full_text": "$MSFT social attention is accelerating.",
    "review_status": "PENDING",
    "requires_human_review": 1,
    "ready_to_post": 0,
    "final_machine_validation": 1,
    "brief_snapshot": "{\"symbol\": \"MSFT\", \"primary_angle\": \"SOCIAL_SPIKE\", \"secondary_angles\": [\"SOCIAL_SPIKE\"], \"tone\": \"FinX-native, punchy, conversational\", \"preferred_format\": \"SHORT\", \"strongest_fact\": \"social acceleration 40.00x\", \"supporting_facts\": [\"40 mentions in the latest window\"], \"social_summary\": \"40 mentions with a 40.00x velocity ratio\", \"regivion_summary\": \"No Regivion coverage\", \"urgency\": \"high\", \"confidence\": \"MEDIUM\", \"visual_recommendation\": \"social volume chart + timestamped mentions\", \"allowed_numbers\": [\"93.3\", \"40.00\", \"40\"], \"allowed_facts\": [\"symbol = MSFT\", \"social trend score = 93.3\", \"social acceleration = 40.00x\", \"social acceleration 40.00x\", \"40 mentions in the latest window\", \"No Regivion coverage\", \"40 mentions with a 40.00x velocity ratio\"], \"forbidden_claim_types\": [\"share price\", \"price target\", \"revenue\", \"earnings\", \"EPS\", \"margins\", \"valuation\", \"analyst targets\", \"insider transactions\", \"politician trades\", \"PSC score\", \"PSC ranking\", \"percentage returns\", \"technical levels\", \"catalysts\", \"dates\", \"market-cap figures\"], \"factuality_constraints\": [\"Only facts explicitly present in the supplied brief may appear as factual claims.\", \"Never invent numeric claims, dates, prices, valuations, targets, or catalysts.\", \"Do not discuss unsupported insider or politician activity.\", \"Do not mention a different ticker than the brief symbol.\"], \"style_profile\": {\"concise\": true, \"punchy\": true, \"natural\": true, \"cashtags\": true, \"avoid_hashtags\": true, \"avoid_emojis\": true, \"preferred_length\": \"STANDARD\"}, \"maximum_length\": 280, \"prompt_version\": \"EXITVECTOR_CONTENT_PROMPT_V1\", \"data_provenance\": {\"social\": [{\"id\": 1, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post0\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 2, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post1\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 11, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post10\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 12, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post11\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 13, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post12\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 14, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post13\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 15, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post14\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 16, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post15\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 17, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post16\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 18, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post17\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 19, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post18\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 20, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post19\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 3, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post2\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 21, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post20\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 22, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post21\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 23, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post22\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 24, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post23\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 25, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post24\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 26, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post25\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 27, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post26\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 28, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post27\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 29, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post28\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 30, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post29\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 4, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post3\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 31, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post30\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 32, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post31\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 33, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post32\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 34, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post33\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 35, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post34\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 36, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post35\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 37, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post36\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 38, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post37\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 39, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post38\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 40, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post39\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 5, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post4\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 6, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post5\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 7, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post6\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 8, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post7\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 9, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post8\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 10, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post9\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}], \"regivion\": {}, \"market\": \"disabled\"}}"
  },
  {
    "id": 2,
    "opportunity_id": 1,
    "ticker": "MSFT",
    "provider": "openai",
    "model": "configured-test-model",
    "prompt_version": "EXITVECTOR_CONTENT_PROMPT_V1",
    "full_text": "Could $MSFT deserve a closer look as social attention accelerates?",
    "review_status": "PENDING",
    "requires_human_review": 1,
    "ready_to_post": 0,
    "final_machine_validation": 1,
    "brief_snapshot": "{\"symbol\": \"MSFT\", \"primary_angle\": \"SOCIAL_SPIKE\", \"secondary_angles\": [\"SOCIAL_SPIKE\"], \"tone\": \"FinX-native, punchy, conversational\", \"preferred_format\": \"SHORT\", \"strongest_fact\": \"social acceleration 40.00x\", \"supporting_facts\": [\"40 mentions in the latest window\"], \"social_summary\": \"40 mentions with a 40.00x velocity ratio\", \"regivion_summary\": \"No Regivion coverage\", \"urgency\": \"high\", \"confidence\": \"MEDIUM\", \"visual_recommendation\": \"social volume chart + timestamped mentions\", \"allowed_numbers\": [\"93.3\", \"40.00\", \"40\"], \"allowed_facts\": [\"symbol = MSFT\", \"social trend score = 93.3\", \"social acceleration = 40.00x\", \"social acceleration 40.00x\", \"40 mentions in the latest window\", \"No Regivion coverage\", \"40 mentions with a 40.00x velocity ratio\"], \"forbidden_claim_types\": [\"share price\", \"price target\", \"revenue\", \"earnings\", \"EPS\", \"margins\", \"valuation\", \"analyst targets\", \"insider transactions\", \"politician trades\", \"PSC score\", \"PSC ranking\", \"percentage returns\", \"technical levels\", \"catalysts\", \"dates\", \"market-cap figures\"], \"factuality_constraints\": [\"Only facts explicitly present in the supplied brief may appear as factual claims.\", \"Never invent numeric claims, dates, prices, valuations, targets, or catalysts.\", \"Do not discuss unsupported insider or politician activity.\", \"Do not mention a different ticker than the brief symbol.\"], \"style_profile\": {\"concise\": true, \"punchy\": true, \"natural\": true, \"cashtags\": true, \"avoid_hashtags\": true, \"avoid_emojis\": true, \"preferred_length\": \"STANDARD\"}, \"maximum_length\": 280, \"prompt_version\": \"EXITVECTOR_CONTENT_PROMPT_V1\", \"data_provenance\": {\"social\": [{\"id\": 1, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post0\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 2, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post1\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 11, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post10\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 12, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post11\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 13, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post12\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 14, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post13\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 15, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post14\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 16, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post15\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 17, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post16\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 18, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post17\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 19, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post18\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 20, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post19\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 3, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post2\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 21, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post20\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 22, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post21\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 23, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post22\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 24, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post23\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 25, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post24\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 26, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post25\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 27, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post26\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 28, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post27\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 29, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post28\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 30, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post29\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 4, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post3\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 31, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post30\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 32, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post31\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 33, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post32\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 34, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post33\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 35, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post34\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 36, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post35\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 37, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post36\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 38, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post37\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 39, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post38\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 40, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post39\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 5, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post4\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 6, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post5\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 7, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post6\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 8, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post7\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 9, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post8\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 10, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post9\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}], \"regivion\": {}, \"market\": \"disabled\"}}"
  },
  {
    "id": 3,
    "opportunity_id": 1,
    "ticker": "MSFT",
    "provider": "openai",
    "model": "configured-test-model",
    "prompt_version": "EXITVECTOR_CONTENT_PROMPT_V1",
    "full_text": "$MSFT: 40 mentions with a 40.00x velocity ratio.",
    "review_status": "PENDING",
    "requires_human_review": 1,
    "ready_to_post": 0,
    "final_machine_validation": 1,
    "brief_snapshot": "{\"symbol\": \"MSFT\", \"primary_angle\": \"SOCIAL_SPIKE\", \"secondary_angles\": [\"SOCIAL_SPIKE\"], \"tone\": \"FinX-native, punchy, conversational\", \"preferred_format\": \"SHORT\", \"strongest_fact\": \"social acceleration 40.00x\", \"supporting_facts\": [\"40 mentions in the latest window\"], \"social_summary\": \"40 mentions with a 40.00x velocity ratio\", \"regivion_summary\": \"No Regivion coverage\", \"urgency\": \"high\", \"confidence\": \"MEDIUM\", \"visual_recommendation\": \"social volume chart + timestamped mentions\", \"allowed_numbers\": [\"93.3\", \"40.00\", \"40\"], \"allowed_facts\": [\"symbol = MSFT\", \"social trend score = 93.3\", \"social acceleration = 40.00x\", \"social acceleration 40.00x\", \"40 mentions in the latest window\", \"No Regivion coverage\", \"40 mentions with a 40.00x velocity ratio\"], \"forbidden_claim_types\": [\"share price\", \"price target\", \"revenue\", \"earnings\", \"EPS\", \"margins\", \"valuation\", \"analyst targets\", \"insider transactions\", \"politician trades\", \"PSC score\", \"PSC ranking\", \"percentage returns\", \"technical levels\", \"catalysts\", \"dates\", \"market-cap figures\"], \"factuality_constraints\": [\"Only facts explicitly present in the supplied brief may appear as factual claims.\", \"Never invent numeric claims, dates, prices, valuations, targets, or catalysts.\", \"Do not discuss unsupported insider or politician activity.\", \"Do not mention a different ticker than the brief symbol.\"], \"style_profile\": {\"concise\": true, \"punchy\": true, \"natural\": true, \"cashtags\": true, \"avoid_hashtags\": true, \"avoid_emojis\": true, \"preferred_length\": \"STANDARD\"}, \"maximum_length\": 280, \"prompt_version\": \"EXITVECTOR_CONTENT_PROMPT_V1\", \"data_provenance\": {\"social\": [{\"id\": 1, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post0\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 2, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post1\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 11, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post10\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 12, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post11\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 13, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post12\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 14, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post13\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 15, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post14\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 16, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post15\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 17, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post16\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 18, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post17\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 19, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post18\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 20, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post19\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 3, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post2\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 21, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post20\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 22, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post21\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 23, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post22\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 24, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post23\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 25, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post24\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 26, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post25\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 27, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post26\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 28, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post27\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 29, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post28\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 30, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post29\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 4, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post3\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 31, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post30\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 32, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post31\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 33, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post32\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 34, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post33\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 35, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post34\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 36, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post35\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 37, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post36\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 38, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post37\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 39, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post38\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 40, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post39\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 5, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post4\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 6, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post5\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 7, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post6\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 8, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post7\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 9, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post8\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}, {\"id\": 10, \"source\": \"REDDIT_LIVE\", \"external_id\": \"t3_post9\", \"observed_at\": \"2026-10-08T08:55:00+00:00\"}], \"regivion\": {}, \"market\": \"disabled\"}}"
  }
]
```

## Run history metrics

```text
[
  {
    "id": 1,
    "status": "SUCCESS",
    "trigger_type": "TEST",
    "candidate_count": 3,
    "notification_count": 1,
    "error_count": 0
  },
  {
    "id": 2,
    "status": "SUCCESS",
    "trigger_type": "TEST",
    "candidate_count": 0,
    "notification_count": 0,
    "error_count": 0
  }
]
```

## Provider status/health after repeated run

```text
[
  {
    "provider_name": "reddit",
    "provider_type": "social",
    "configured": true,
    "live": true,
    "read_only": true,
    "authenticated": true,
    "reachable": true,
    "last_success_at": "2026-10-08T08:51:59.838151+00:00",
    "last_failure_at": null,
    "consecutive_failures": 0,
    "error_summary": null,
    "circuit_open_until": 0
  },
  {
    "provider_name": "stocktwits",
    "provider_type": "social",
    "configured": false,
    "live": false,
    "read_only": true,
    "authenticated": null,
    "reachable": null,
    "last_success_at": null,
    "last_failure_at": null,
    "consecutive_failures": 0,
    "error_summary": null,
    "circuit_open_until": 0
  },
  {
    "provider_name": "regivion",
    "provider_type": "enrichment",
    "configured": false,
    "live": false,
    "read_only": true,
    "authenticated": null,
    "reachable": null,
    "last_success_at": null,
    "last_failure_at": null,
    "consecutive_failures": 0,
    "error_summary": null,
    "circuit_open_until": 0
  },
  {
    "provider_name": "openai",
    "provider_type": "llm",
    "configured": true,
    "live": true,
    "read_only": true,
    "authenticated": true,
    "reachable": true,
    "last_success_at": "2026-10-08T08:51:59.808628+00:00",
    "last_failure_at": null,
    "consecutive_failures": 0,
    "error_summary": null,
    "circuit_open_until": 0
  }
]
```

## Mocked live-check: minimal reads, no inference

```text
[
  {
    "name": "Reddit",
    "status": "PASS",
    "detail": "OAuth and minimal read listing succeeded"
  },
  {
    "name": "Stocktwits",
    "status": "WARN",
    "detail": "DISABLED - supported API access not established"
  },
  {
    "name": "Regivion",
    "status": "SKIP",
    "detail": "LIVE CHECK SKIPPED - HTTP contract/credentials not configured"
  },
  {
    "name": "OpenAI",
    "status": "PASS",
    "detail": "Authentication/model visibility valid; no inference requested"
  },
  {
    "name": "Market",
    "status": "SKIP",
    "detail": "DISABLED - no supported licensed live endpoint discovered"
  },
  {
    "name": "X actions",
    "status": "PASS",
    "detail": "DISABLED"
  }
]
```

## Discovered HTTP Regivion valuation response normalized; cache hit

```text
{
  "endpoint": "/api/valuation-history/MSFT",
  "target": "LOCAL/DEVELOPMENT target: 127.0.0.1",
  "enrichment": {
    "symbol": "MSFT",
    "psc_score": null,
    "psc_rank": null,
    "previous_psc_rank": null,
    "psc_status": null,
    "freshness": null,
    "revenue_growth_yoy": null,
    "earnings_growth_yoy": null,
    "forward_pe": 18.5,
    "peg": 1.1,
    "free_cash_flow_growth": null,
    "profitability_status": null,
    "recent_alerts": [],
    "recent_insider_buys": [],
    "recent_insider_sells": [],
    "recent_politician_trades": [],
    "entered_top_20": null,
    "exited_top_20": null,
    "rank_acceleration": null,
    "raw": {
      "symbol": "MSFT",
      "fundamentals": {
        "forward_pe": 18.5,
        "peg": 1.1
      },
      "provenance": {
        "source": "REGIVION_HTTP",
        "is_live_data": true,
        "endpoint": "/api/valuation-history/{symbol}",
        "source_timestamp": "2026-10-08T09:00:00+00:00",
        "received_timestamp": "2026-10-08T09:00:00+00:00",
        "age_seconds": 0.0,
        "stale": false,
        "missing_fields": [
          "psc",
          "alerts",
          "insiders",
          "politicians",
          "market"
        ]
      }
    }
  },
  "metrics": {
    "requests_attempted": 1,
    "requests_succeeded": 1,
    "requests_failed": 0,
    "retries": 0,
    "rate_limit_events": 0,
    "latency_seconds": 0.0,
    "cache_hits": 1
  }
}
```

## Mocked Regivion reachability does not prove auth

```text
[
  {
    "name": "Reddit",
    "status": "PASS",
    "detail": "OAuth and minimal read listing succeeded"
  },
  {
    "name": "Stocktwits",
    "status": "WARN",
    "detail": "DISABLED - supported API access not established"
  },
  {
    "name": "Regivion reachability",
    "status": "PASS",
    "detail": "LOCAL/DEVELOPMENT target: 127.0.0.1"
  },
  {
    "name": "Regivion authentication/enrichment",
    "status": "WARN",
    "detail": "UNVERIFIED - health endpoint does not prove token authorization; PSC API unavailable"
  },
  {
    "name": "OpenAI",
    "status": "PASS",
    "detail": "Authentication/model visibility valid; no inference requested"
  },
  {
    "name": "Market",
    "status": "SKIP",
    "detail": "DISABLED - no supported licensed live endpoint discovered"
  },
  {
    "name": "X actions",
    "status": "PASS",
    "detail": "DISABLED"
  }
]
```

## Hetzner production-target configuration and actual server-contract gate

```text
{
  "target": "Hetzner production target (configured; not deployment-verified): regivion.example.invalid",
  "result": "Regivion production HTTP blocked: discovered server lacks dedicated read-only token authentication and PSC enrichment API",
  "network_requests": 0
}
```

## Localhost is development-only

```text
Production Regivion requires the explicitly configured remote HTTPS Hetzner target
```

## OpenAI structured draft and deterministic factuality validation

```text
{
  "response": {
    "text": "$MSFT social attention is accelerating.",
    "raw_output": "{\"text\": \"$MSFT social attention is accelerating.\", \"variant_type\": \"PUNCHY\"}",
    "provider": "openai",
    "model": "configured-test-model",
    "prompt_version": "EXITVECTOR_CONTENT_PROMPT_V1",
    "metadata": {
      "response_id": "synthetic-response",
      "usage": {
        "input_tokens": 100,
        "output_tokens": 20
      }
    }
  },
  "validation": {
    "valid": true,
    "unsupported_numbers": [],
    "unsupported_claims": [],
    "symbol_mismatch": false,
    "length_violation": false,
    "formatting_issues": [],
    "warnings": [],
    "rejection_reasons": []
  },
  "request_contract": {
    "tools": [],
    "store": false,
    "strict": true,
    "input_is_ContentBrief_only": true
  }
}
```

## Explicit development mixed-mode warning

```text
{
  "warnings": [
    "MIXED DATA MODE: results combine live and fixture/disabled providers; not production analysis"
  ],
  "providers": {
    "social": "mixed (Reddit OAuth; Stocktwits DISABLED)",
    "regivion": "mock",
    "content": "LLM/mock",
    "market": "DISABLED (no licensed live market API discovered)",
    "audience": "mock",
    "X posting": "DISABLED",
    "X relationship actions": "DISABLED"
  }
}
```

## Separate live/mock source provenance

```text
[
  {
    "source": "MOCK_REDDIT",
    "count": 28
  },
  {
    "source": "MOCK_STOCKTWITS",
    "count": 28
  },
  {
    "source": "REDDIT_LIVE",
    "count": 40
  }
]
```

## LLM outage: partial success, preserved opportunity, bounded retries and persistent circuit

```text
{
  "run_id": 1,
  "started_at": "2026-10-08T09:00:00+00:00",
  "completed_at": "2026-10-08T09:00:00+00:00",
  "duration_seconds": 0,
  "status": "PARTIAL_SUCCESS",
  "trigger_type": "TEST",
  "dry_run": false,
  "social_scan_result": [
    {
      "source": "REDDIT_LIVE",
      "status": "OK",
      "observed": 40
    }
  ],
  "content_generation_result": [],
  "observations_created": 40,
  "trend_count": 1,
  "opportunities_created": 1,
  "opportunities_updated": 0,
  "content_candidates_created": 0,
  "review_items_created": 0,
  "notifications_sent": 0,
  "audience_refresh_result": {
    "status": "SKIPPED"
  },
  "opportunities": [
    {
      "symbol": "MSFT",
      "score": 75.4,
      "confidence": "MEDIUM",
      "angle": "SOCIAL_SPIKE",
      "notification_eligible": true,
      "reason": "SCORE_DELTA",
      "components": {
        "social": 93.33333333333333,
        "regivion": 0.0,
        "novelty": 20.0
      },
      "trigger_reasons": [
        "social acceleration 40.00x"
      ]
    }
  ],
  "review_handoff": [],
  "providers": {
    "social": "live (Reddit OAuth; Stocktwits DISABLED)",
    "regivion": "disabled",
    "content": "OpenAI/configured-test-model",
    "market": "DISABLED (no licensed live market API discovered)",
    "audience": "mock",
    "X posting": "DISABLED",
    "X relationship actions": "DISABLED"
  },
  "warnings": [
    "LIVE SOCIAL/LLM; REGIVION EXPLICITLY DISABLED"
  ],
  "errors": [
    "content:MSFT: HTTPStatusError"
  ],
  "provider_metrics": {
    "reddit": {
      "requests_attempted": 2,
      "requests_succeeded": 2,
      "requests_failed": 0,
      "retries": 0,
      "rate_limit_events": 0,
      "latency_seconds": 0.0,
      "cache_hits": 0
    },
    "openai": {
      "requests_attempted": 3,
      "requests_succeeded": 0,
      "requests_failed": 3,
      "retries": 2,
      "rate_limit_events": 0,
      "latency_seconds": 0.0,
      "cache_hits": 0
    }
  },
  "provider_status": [
    {
      "provider_name": "reddit",
      "provider_type": "social",
      "configured": true,
      "live": true,
      "read_only": true,
      "authenticated": true,
      "reachable": true,
      "last_success_at": "2026-10-08T08:52:02.818655+00:00",
      "last_failure_at": null,
      "consecutive_failures": 0,
      "error_summary": null,
      "circuit_open_until": 0
    },
    {
      "provider_name": "stocktwits",
      "provider_type": "social",
      "configured": false,
      "live": false,
      "read_only": true,
      "authenticated": null,
      "reachable": null,
      "last_success_at": null,
      "last_failure_at": null,
      "consecutive_failures": 0,
      "error_summary": null,
      "circuit_open_until": 0
    },
    {
      "provider_name": "regivion",
      "provider_type": "enrichment",
      "configured": false,
      "live": false,
      "read_only": true,
      "authenticated": null,
      "reachable": null,
      "last_success_at": null,
      "last_failure_at": null,
      "consecutive_failures": 0,
      "error_summary": null,
      "circuit_open_until": 0
    },
    {
      "provider_name": "openai",
      "provider_type": "llm",
      "configured": true,
      "live": true,
      "read_only": true,
      "authenticated": null,
      "reachable": true,
      "last_success_at": null,
      "last_failure_at": "2026-10-08T08:52:02.994761+00:00",
      "consecutive_failures": 3,
      "error_summary": "HTTPStatusError HTTP 503",
      "circuit_open_until": 1791449822.9952617
    }
  ]
}
```

## Circuit breaker next-run demonstration

```text
{
  "errors": [
    "content:MSFT: CircuitOpen"
  ],
  "metrics": {
    "reddit": {
      "requests_attempted": 1,
      "requests_succeeded": 1,
      "requests_failed": 0,
      "retries": 0,
      "rate_limit_events": 0,
      "latency_seconds": 0.0,
      "cache_hits": 0
    },
    "openai": {
      "requests_attempted": 0,
      "requests_succeeded": 0,
      "requests_failed": 0,
      "retries": 0,
      "rate_limit_events": 0,
      "latency_seconds": 0.0,
      "cache_hits": 0
    }
  },
  "new_openai_requests": 0
}
```

## 429 Retry-After cooldown demonstration

```text
{
  "outcomes": [
    "HTTPStatusError",
    "CircuitOpen"
  ],
  "metrics": {
    "requests_attempted": 1,
    "requests_succeeded": 0,
    "requests_failed": 1,
    "retries": 0,
    "rate_limit_events": 1,
    "latency_seconds": 0.0,
    "cache_hits": 0
  },
  "health": {
    "consecutive_failures": 1,
    "circuit_open_until": 1791449823.169202,
    "last_failure_at": "2026-10-08T08:52:03.169202+00:00",
    "error_summary": "HTTPStatusError HTTP 429",
    "reachable": true,
    "authenticated": null
  }
}
```

## Content cost limit: one total inference attempt

```text
{
  "created": 1,
  "warnings": [
    "LIVE SOCIAL/LLM; REGIVION EXPLICITLY DISABLED",
    "Live LLM generation budget reached; remaining inference skipped"
  ],
  "metrics": {
    "reddit": {
      "requests_attempted": 2,
      "requests_succeeded": 2,
      "requests_failed": 0,
      "retries": 0,
      "rate_limit_events": 0,
      "latency_seconds": 0.0,
      "cache_hits": 0
    },
    "openai": {
      "requests_attempted": 1,
      "requests_succeeded": 1,
      "requests_failed": 0,
      "retries": 0,
      "rate_limit_events": 0,
      "latency_seconds": 0.0,
      "cache_hits": 0
    }
  },
  "inference_requests": 1
}
```

## Optional real external read smoke test

```text
LIVE CHECK SKIPPED - credentials not configured for selected live providers. Synthetic fixture results are not external verification.
```

## Architecture, discovered endpoints and limitations

Existing interfaces and Phase 8 runner/locks/history/review/notifier are reused.
Reddit OAuth plus bounded GET listings normalize stable IDs, UTC times and distinct provenance.
OpenAI Responses returns schema-validated drafts from ContentBrief only, then existing deterministic
factuality/repair/human-review safeguards run. Small provider-health configuration records persist
circuits; per-run summaries store request counts, retries, rate limits, latency and cache hits.
Cost controls bound all inference attempts, including repairs and retries.

The inspected `C:\Users\LetzPC Gaming\investcopilot` source has GET `/livez`, `/readyz`, `/healthz`,
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


## Files changed or added

```text
.env.example
README.md
REGIVION_INTEGRATION.md (new)
PHASE9_VERIFICATION.md (new)
scripts/verify_phase9.py (new)
src/exitvector_agent/__main__.py
src/exitvector_agent/agent.py
src/exitvector_agent/config.py
src/exitvector_agent/content.py
src/exitvector_agent/logging.py
src/exitvector_agent/opportunity.py
src/exitvector_agent/opportunity_service.py
src/exitvector_agent/operations.py
src/exitvector_agent/regivion.py
src/exitvector_agent/social/extractors.py
src/exitvector_agent/social/scan.py
src/exitvector_agent/social/sources.py
src/exitvector_agent/live_checks.py (new)
src/exitvector_agent/live_providers.py (new)
src/exitvector_agent/provider_health.py (new)
src/exitvector_agent/provider_setup.py (new)
tests/test_phase9_live.py (new)
```
