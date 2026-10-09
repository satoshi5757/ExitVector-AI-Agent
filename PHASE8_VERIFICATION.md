# Phase 8 operational verification

All outputs below were captured locally by `python scripts/verify_phase8.py`. No production credentials, external providers, posting, scraping, browser automation, OS scheduler installation, deployment, commit or push were used. Temporary databases/backups are removed after verification; paths are evidence, not retained user backups.

## Focused Phase 8 tests

```text
..................................................                       [100%]
50 passed in 21.41s
```

## Full pytest suite, including unchanged Phase 1-7 tests

```text
........................................................................ [ 34%]
........................................................................ [ 69%]
................................................................         [100%]
208 passed in 32.52s
```

## Doctor before initialization

```text
$ python -m exitvector_agent doctor
[PASS] Python: 3.11.9
[PASS] Operational configuration: Validated; no secrets displayed
[PASS] Writable data directory: C:\Users\LetzPC Gaming\AppData\Local\Temp\exitvector_phase8_rk8l2xbc\data with spaces
[PASS] Writable log directory: C:\Users\LetzPC Gaming\AppData\Local\Temp\exitvector_phase8_rk8l2xbc\logs
[WARN] SQLite/schema: Not initialized; first run initializes it
[PASS] Process lock: Available
[WARN] Social sources: MOCK Stocktwits/Reddit fixtures; live integrations unavailable
[PASS] Regivion: MOCK; HTTP integration disabled
[WARN] Content generator: LLM/MOCK; no live LLM configured
[PASS] Review service: Human approval required; only explicitly approved content appears in ready
[WARN] Audience source: mock (auto; database not initialized)
[PASS] X posting: DISABLED
[PASS] X relationship actions: DISABLED
Exit code: 0
```

## Actual one-command run output

```text
$ python -m exitvector_agent run
2 new ExitVector review item(s): MSFT (81.6), NVDA (76.3)
ExitVector Agent — Run #1 — SUCCESS
Providers: social=mock (Stocktwits/Reddit fixtures); regivion=mock; content=LLM/mock; audience=mock; X posting=DISABLED; X relationship actions=DISABLED
WARNING: MOCK social and Regivion data are offline fixtures; this run does not observe live markets.
Social scan: 56 new observations; 3 trends
Opportunities: 3 new, 0 updated
Content/validation: 6 valid new candidates
Review queue: 2 new item(s); notifications: 1 batch(es)
Audience refresh: SKIPPED
  MSFT — 81.6 — MULTI_SIGNAL_CONVERGENCE — variant PUNCHY (candidate #1)
  NVDA — 76.3 — VALUATION_DISLOCATION — variant PUNCHY (candidate #4)
Review with: python -m exitvector_agent review
Completed in 0.20s. No automatic posts were made.
Exit code: 0
```

## Actual status output

```text
$ python -m exitvector_agent status
ExitVector — HEALTHY
Database: C:\Users\LetzPC Gaming\AppData\Local\Temp\exitvector_phase8_rk8l2xbc\data with spaces\agent.db
social: mock (Stocktwits/Reddit fixtures)
regivion: mock
content: LLM/mock
audience: mock
X posting: DISABLED
X relationship actions: DISABLED
last_run: #1 2026-10-08T07:43:16.592712+00:00 SUCCESS (0.20s)
last_successful_run: #1 2026-10-08T07:43:16.592712+00:00 SUCCESS (0.20s)
Next scheduled run: none
Pending review: 6; ready to post: 0; pending opportunities: 2
Recent errors: []
Exit code: 0
```

## Actual doctor output

```text
$ python -m exitvector_agent doctor
[PASS] Python: 3.11.9
[PASS] Operational configuration: Validated; no secrets displayed
[PASS] Writable data directory: C:\Users\LetzPC Gaming\AppData\Local\Temp\exitvector_phase8_rk8l2xbc\data with spaces
[PASS] Writable log directory: C:\Users\LetzPC Gaming\AppData\Local\Temp\exitvector_phase8_rk8l2xbc\logs
[PASS] SQLite integrity: ['ok']
[PASS] Schema: Initialized
[WARN] Audience database: 0 imported account(s)
[PASS] Process lock: Available
[WARN] Social sources: MOCK Stocktwits/Reddit fixtures; live integrations unavailable
[PASS] Regivion: MOCK; HTTP integration disabled
[WARN] Content generator: LLM/MOCK; no live LLM configured
[PASS] Review service: Human approval required; only explicitly approved content appears in ready
[WARN] Audience source: mock
[PASS] X posting: DISABLED
[PASS] X relationship actions: DISABLED
Exit code: 0
```

## Actual repeated CLI run

```text
$ python -m exitvector_agent run
ExitVector Agent — Run #2 — SUCCESS
Providers: social=mock (Stocktwits/Reddit fixtures); regivion=mock; content=LLM/mock; audience=mock; X posting=DISABLED; X relationship actions=DISABLED
WARNING: MOCK social and Regivion data are offline fixtures; this run does not observe live markets.
Social scan: 0 new observations; 3 trends
Opportunities: 0 new, 3 updated
Content/validation: 0 valid new candidates
Review queue: 0 new item(s); notifications: 0 batch(es)
Audience refresh: SKIPPED
Completed in 0.17s. No automatic posts were made.
Exit code: 0
```

## Actual dry-run output

```text
$ python -m exitvector_agent run --dry-run
ExitVector Agent — DRY RUN — SUCCESS
Providers: social=mock (Stocktwits/Reddit fixtures); regivion=mock; content=LLM/mock; audience=mock; X posting=DISABLED; X relationship actions=DISABLED
WARNING: MOCK social and Regivion data are offline fixtures; this run does not observe live markets.
Social scan: 0 new observations; 3 trends
Opportunities: 0 new, 3 updated
Content/validation: 0 valid new candidates
Review queue: 0 new item(s); notifications: 0 batch(es)
Audience refresh: SKIPPED
Preview only: database/review/history unchanged; no notifications sent.
Completed in 0.17s. No automatic posts were made.
Exit code: 0
```

## Dry-run verification

```text
Real run history and all candidate/review columns unchanged. No notifier delivery; disposable database only.
```

## Review handoff output

```text
$ python -m exitvector_agent review
#1 MSFT — 81.6 — PUNCHY — PENDING
#4 NVDA — 76.3 — PUNCHY — PENDING
Exit code: 0
```

## Ready requires approval

```text
$ python -m exitvector_agent ready
[]
Exit code: 0
```

## Local notification inbox

```text
$ python -m exitvector_agent notifications --unread
[
  {
    "id": 2,
    "created_at": "2026-10-08T07:43:16.792189+00:00",
    "ticker": "NVDA",
    "opportunity_id": 3,
    "payload": "{\"candidate_id\": 4, \"opportunity_id\": 3, \"ticker\": \"NVDA\", \"score\": 76.3, \"message\": \"NVDA - 76.3; PUNCHY candidate requires human review.\"}",
    "is_read": 0
  },
  {
    "id": 1,
    "created_at": "2026-10-08T07:43:16.789033+00:00",
    "ticker": "MSFT",
    "opportunity_id": 1,
    "payload": "{\"candidate_id\": 1, \"opportunity_id\": 1, \"ticker\": \"MSFT\", \"score\": 81.6, \"message\": \"MSFT - 81.6; PUNCHY candidate requires human review.\"}",
    "is_read": 0
  }
]
Exit code: 0
```

## Production refuses mock fallback

```text
$ python -m exitvector_agent run
ERROR: Production operation is unavailable: live social, Regivion and LLM providers are not implemented; mock fallback is prohibited
Exit code: 2
```

## Posting safety flag refuses operation

```text
$ python -m exitvector_agent run
ERROR: X posting and relationship actions must remain disabled
Exit code: 2
```

## Deterministic first run

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
      "source": "stocktwits",
      "status": "OK",
      "observed": 28
    },
    {
      "source": "reddit",
      "status": "OK",
      "observed": 28
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
          "variant": "DATA_DRIVEN",
          "valid": true,
          "rejection_reasons": []
        },
        {
          "variant": "QUESTION",
          "valid": true,
          "rejection_reasons": []
        }
      ]
    },
    {
      "symbol": "NVDA",
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
          "variant": "DATA_DRIVEN",
          "valid": true,
          "rejection_reasons": []
        },
        {
          "variant": "QUESTION",
          "valid": true,
          "rejection_reasons": []
        }
      ]
    }
  ],
  "observations_created": 56,
  "trend_count": 3,
  "opportunities_created": 3,
  "opportunities_updated": 0,
  "content_candidates_created": 6,
  "review_items_created": 2,
  "notifications_sent": 1,
  "audience_refresh_result": {
    "status": "SKIPPED"
  },
  "opportunities": [
    {
      "symbol": "MSFT",
      "score": 81.6,
      "confidence": "HIGH",
      "angle": "MULTI_SIGNAL_CONVERGENCE",
      "notification_eligible": true,
      "reason": "SCORE_DELTA",
      "components": {
        "social": 75.16666666666666,
        "regivion": 100.0,
        "novelty": 100.0
      },
      "trigger_reasons": [
        "social acceleration 3.33x",
        "PSC score 98.4",
        "PSC rank 28 -> 10",
        "fresh bullish Regivion alert",
        "1 insider buy"
      ]
    },
    {
      "symbol": "NVDA",
      "score": 76.3,
      "confidence": "HIGH",
      "angle": "VALUATION_DISLOCATION",
      "notification_eligible": true,
      "reason": "SCORE_DELTA",
      "components": {
        "social": 72.06666666666666,
        "regivion": 94.0,
        "novelty": 55.0
      },
      "trigger_reasons": [
        "social acceleration 8.00x",
        "PSC score 100.0"
      ]
    },
    {
      "symbol": "UBER",
      "score": 74.1,
      "confidence": "MEDIUM",
      "angle": "MULTI_SIGNAL_CONVERGENCE",
      "notification_eligible": false,
      "reason": null,
      "components": {
        "social": 72.36666666666667,
        "regivion": 91.0,
        "novelty": 71.5
      },
      "trigger_reasons": [
        "social acceleration 3.50x",
        "PSC score 91.0",
        "PSC rank 31 -> 24",
        "fresh bullish Regivion alert"
      ]
    }
  ],
  "review_handoff": [
    {
      "candidate_id": 1,
      "symbol": "MSFT",
      "score": 81.6,
      "angle": "MULTI_SIGNAL_CONVERGENCE",
      "variant": "PUNCHY"
    },
    {
      "candidate_id": 4,
      "symbol": "NVDA",
      "score": 76.3,
      "angle": "VALUATION_DISLOCATION",
      "variant": "PUNCHY"
    }
  ],
  "providers": {
    "social": "mock (Stocktwits/Reddit fixtures)",
    "regivion": "mock",
    "content": "LLM/mock",
    "audience": "mock",
    "X posting": "DISABLED",
    "X relationship actions": "DISABLED"
  },
  "warnings": [
    "MOCK social and Regivion data are offline fixtures; this run does not observe live markets."
  ],
  "errors": []
}
```

## Deterministic identical run

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
      "source": "stocktwits",
      "status": "OK",
      "observed": 28
    },
    {
      "source": "reddit",
      "status": "OK",
      "observed": 28
    }
  ],
  "content_generation_result": [],
  "observations_created": 0,
  "trend_count": 3,
  "opportunities_created": 0,
  "opportunities_updated": 3,
  "content_candidates_created": 0,
  "review_items_created": 0,
  "notifications_sent": 0,
  "audience_refresh_result": {
    "status": "SKIPPED"
  },
  "opportunities": [
    {
      "symbol": "MSFT",
      "score": 81.6,
      "confidence": "HIGH",
      "angle": "MULTI_SIGNAL_CONVERGENCE",
      "notification_eligible": false,
      "reason": null,
      "components": {
        "social": 75.16666666666666,
        "regivion": 100.0,
        "novelty": 100.0
      },
      "trigger_reasons": [
        "social acceleration 3.33x",
        "PSC score 98.4",
        "PSC rank 28 -> 10",
        "fresh bullish Regivion alert",
        "1 insider buy"
      ]
    },
    {
      "symbol": "NVDA",
      "score": 76.3,
      "confidence": "HIGH",
      "angle": "VALUATION_DISLOCATION",
      "notification_eligible": false,
      "reason": null,
      "components": {
        "social": 72.06666666666666,
        "regivion": 94.0,
        "novelty": 55.0
      },
      "trigger_reasons": [
        "social acceleration 8.00x",
        "PSC score 100.0"
      ]
    },
    {
      "symbol": "UBER",
      "score": 74.1,
      "confidence": "MEDIUM",
      "angle": "MULTI_SIGNAL_CONVERGENCE",
      "notification_eligible": false,
      "reason": null,
      "components": {
        "social": 72.36666666666667,
        "regivion": 91.0,
        "novelty": 71.5
      },
      "trigger_reasons": [
        "social acceleration 3.50x",
        "PSC score 91.0",
        "PSC rank 31 -> 24",
        "fresh bullish Regivion alert"
      ]
    }
  ],
  "review_handoff": [],
  "providers": {
    "social": "mock (Stocktwits/Reddit fixtures)",
    "regivion": "mock",
    "content": "LLM/mock",
    "audience": "mock",
    "X posting": "DISABLED",
    "X relationship actions": "DISABLED"
  },
  "warnings": [
    "MOCK social and Regivion data are offline fixtures; this run does not observe live markets."
  ],
  "errors": []
}
```

## Material change: MSFT PSC rank 10 to 3

```text
{
  "run_id": 3,
  "started_at": "2026-10-08T09:00:00+00:00",
  "completed_at": "2026-10-08T09:00:00+00:00",
  "duration_seconds": 0,
  "status": "SUCCESS",
  "trigger_type": "TEST",
  "dry_run": false,
  "social_scan_result": [
    {
      "source": "stocktwits",
      "status": "OK",
      "observed": 28
    },
    {
      "source": "reddit",
      "status": "OK",
      "observed": 28
    }
  ],
  "content_generation_result": [
    {
      "symbol": "MSFT",
      "generated": 3,
      "created": 2,
      "rejected": 0,
      "validation": [
        {
          "variant": "PUNCHY",
          "valid": true,
          "rejection_reasons": []
        },
        {
          "variant": "DATA_DRIVEN",
          "valid": true,
          "rejection_reasons": []
        },
        {
          "variant": "QUESTION",
          "valid": true,
          "rejection_reasons": []
        }
      ]
    }
  ],
  "observations_created": 0,
  "trend_count": 3,
  "opportunities_created": 0,
  "opportunities_updated": 3,
  "content_candidates_created": 2,
  "review_items_created": 1,
  "notifications_sent": 1,
  "audience_refresh_result": {
    "status": "SKIPPED"
  },
  "opportunities": [
    {
      "symbol": "MSFT",
      "score": 81.6,
      "confidence": "HIGH",
      "angle": "MULTI_SIGNAL_CONVERGENCE",
      "notification_eligible": true,
      "reason": "PSC_RANK_MILESTONE",
      "components": {
        "social": 75.16666666666666,
        "regivion": 100.0,
        "novelty": 100.0
      },
      "trigger_reasons": [
        "social acceleration 3.33x",
        "PSC score 98.4",
        "PSC rank 10 -> 3",
        "fresh bullish Regivion alert",
        "1 insider buy"
      ]
    },
    {
      "symbol": "NVDA",
      "score": 76.3,
      "confidence": "HIGH",
      "angle": "VALUATION_DISLOCATION",
      "notification_eligible": false,
      "reason": null,
      "components": {
        "social": 72.06666666666666,
        "regivion": 94.0,
        "novelty": 55.0
      },
      "trigger_reasons": [
        "social acceleration 8.00x",
        "PSC score 100.0"
      ]
    },
    {
      "symbol": "UBER",
      "score": 74.1,
      "confidence": "MEDIUM",
      "angle": "MULTI_SIGNAL_CONVERGENCE",
      "notification_eligible": false,
      "reason": null,
      "components": {
        "social": 72.36666666666667,
        "regivion": 91.0,
        "novelty": 71.5
      },
      "trigger_reasons": [
        "social acceleration 3.50x",
        "PSC score 91.0",
        "PSC rank 31 -> 24",
        "fresh bullish Regivion alert"
      ]
    }
  ],
  "review_handoff": [
    {
      "candidate_id": 7,
      "symbol": "MSFT",
      "score": 81.6,
      "angle": "MULTI_SIGNAL_CONVERGENCE",
      "variant": "PUNCHY"
    }
  ],
  "providers": {
    "social": "mock (Stocktwits/Reddit fixtures)",
    "regivion": "mock",
    "content": "LLM/mock",
    "audience": "mock",
    "X posting": "DISABLED",
    "X relationship actions": "DISABLED"
  },
  "warnings": [
    "MOCK social and Regivion data are offline fixtures; this run does not observe live markets."
  ],
  "errors": []
}
```

## Notification batches: one per run, never per variant

```text
[
  [
    {
      "candidate_id": 1,
      "opportunity_id": 1,
      "ticker": "MSFT",
      "score": 81.6,
      "message": "MSFT - 81.6; PUNCHY candidate requires human review."
    },
    {
      "candidate_id": 4,
      "opportunity_id": 3,
      "ticker": "NVDA",
      "score": 76.3,
      "message": "NVDA - 76.3; PUNCHY candidate requires human review."
    }
  ],
  [
    {
      "candidate_id": 7,
      "opportunity_id": 7,
      "ticker": "MSFT",
      "score": 81.6,
      "message": "MSFT - 81.6; PUNCHY candidate requires human review."
    }
  ]
]
```

## Run history rows

```text
[
  {
    "id": 1,
    "started_at": "2026-10-08T09:00:00+00:00",
    "completed_at": "2026-10-08T09:00:00+00:00",
    "status": "SUCCESS",
    "trigger_type": "TEST",
    "duration_seconds": 0.0,
    "social_count": 56,
    "opportunity_count": 3,
    "candidate_count": 6,
    "notification_count": 1,
    "error_count": 0
  },
  {
    "id": 2,
    "started_at": "2026-10-08T09:00:00+00:00",
    "completed_at": "2026-10-08T09:00:00+00:00",
    "status": "SUCCESS",
    "trigger_type": "TEST",
    "duration_seconds": 0.0,
    "social_count": 56,
    "opportunity_count": 3,
    "candidate_count": 0,
    "notification_count": 0,
    "error_count": 0
  },
  {
    "id": 3,
    "started_at": "2026-10-08T09:00:00+00:00",
    "completed_at": "2026-10-08T09:00:00+00:00",
    "status": "SUCCESS",
    "trigger_type": "TEST",
    "duration_seconds": 0.0,
    "social_count": 56,
    "opportunity_count": 3,
    "candidate_count": 2,
    "notification_count": 1,
    "error_count": 0
  }
]
```

## Material-change candidate evidence

```text
[
  {
    "id": 7,
    "ticker": "MSFT",
    "opportunity_id": 7,
    "full_text": "$MSFT just moved from #10 to #3 in PSC. Social attention is accelerating too.",
    "review_status": "PENDING",
    "ready_to_post": 0
  },
  {
    "id": 8,
    "ticker": "MSFT",
    "opportunity_id": 7,
    "full_text": "Could the market be overlooking $MSFT after a #10-to-#3 PSC move? Social acceleration is 3.33x, so the setup deserves a closer look.",
    "review_status": "PENDING",
    "ready_to_post": 0
  }
]
```

## Concurrent run rejected; status remains readable

```text
{
  "rejection": "Another ExitVector orchestrator owns this database lock",
  "status": "RUNNING"
}
```

## Released lock

```text
{
  "active": false,
  "pid": 8140,
  "next_run_at": null,
  "run_id": null,
  "stale": false,
  "long_running": false,
  "path": "C:\\Users\\LetzPC Gaming\\AppData\\Local\\Temp\\exitvector_phase8_rk8l2xbc\\deterministic.db.agent.lock"
}
```

## Isolated transient source failure (bounded retries)

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
      "source": "reddit-failure-simulation",
      "status": "FAILED",
      "observed": 0
    },
    {
      "source": "stocktwits",
      "status": "OK",
      "observed": 28
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
          "variant": "DATA_DRIVEN",
          "valid": true,
          "rejection_reasons": []
        },
        {
          "variant": "QUESTION",
          "valid": true,
          "rejection_reasons": []
        }
      ]
    }
  ],
  "observations_created": 28,
  "trend_count": 2,
  "opportunities_created": 2,
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
      "score": 77.4,
      "confidence": "HIGH",
      "angle": "MULTI_SIGNAL_CONVERGENCE",
      "notification_eligible": true,
      "reason": "SCORE_DELTA",
      "components": {
        "social": 68.08333333333333,
        "regivion": 100.0,
        "novelty": 100.0
      },
      "trigger_reasons": [
        "social acceleration 3.33x",
        "PSC score 98.4",
        "PSC rank 28 -> 10",
        "fresh bullish Regivion alert",
        "1 insider buy"
      ]
    },
    {
      "symbol": "UBER",
      "score": 70.8,
      "confidence": "MEDIUM",
      "angle": "MULTI_SIGNAL_CONVERGENCE",
      "notification_eligible": false,
      "reason": null,
      "components": {
        "social": 66.40833333333333,
        "regivion": 91.0,
        "novelty": 71.5
      },
      "trigger_reasons": [
        "social acceleration 3.50x",
        "PSC score 91.0",
        "PSC rank 31 -> 24",
        "fresh bullish Regivion alert"
      ]
    }
  ],
  "review_handoff": [
    {
      "candidate_id": 1,
      "symbol": "MSFT",
      "score": 77.4,
      "angle": "MULTI_SIGNAL_CONVERGENCE",
      "variant": "PUNCHY"
    }
  ],
  "providers": {
    "social": "mock (Stocktwits/Reddit fixtures)",
    "regivion": "mock",
    "content": "LLM/mock",
    "audience": "mock",
    "X posting": "DISABLED",
    "X relationship actions": "DISABLED"
  },
  "warnings": [
    "MOCK social and Regivion data are offline fixtures; this run does not observe live markets."
  ],
  "errors": [
    "social:reddit-failure-simulation: RuntimeError"
  ]
}
```

## Mid-run exception then recovery

```text
{
  "failed": {
    "run_id": 2,
    "started_at": "2026-10-08T09:00:00+00:00",
    "completed_at": "2026-10-08T09:00:00+00:00",
    "duration_seconds": 0,
    "status": "FAILED",
    "trigger_type": "TEST",
    "dry_run": false,
    "social_scan_result": [],
    "content_generation_result": [],
    "observations_created": 0,
    "trend_count": 0,
    "opportunities_created": 0,
    "opportunities_updated": 0,
    "content_candidates_created": 0,
    "review_items_created": 0,
    "notifications_sent": 0,
    "audience_refresh_result": {
      "status": "SKIPPED"
    },
    "opportunities": [],
    "review_handoff": [],
    "providers": {
      "social": "mock (Stocktwits/Reddit fixtures)",
      "regivion": "mock",
      "content": "LLM/mock",
      "audience": "mock",
      "X posting": "DISABLED",
      "X relationship actions": "DISABLED"
    },
    "warnings": [
      "MOCK social and Regivion data are offline fixtures; this run does not observe live markets."
    ],
    "errors": [
      "pipeline: RuntimeError"
    ]
  },
  "subsequent_status": "SUCCESS",
  "lock": {
    "active": false,
    "pid": 8140,
    "next_run_at": null,
    "run_id": null,
    "started_at": "2026-10-08T09:00:00+00:00",
    "mode": "TEST",
    "stale": false,
    "long_running": false,
    "path": "C:\\Users\\LetzPC Gaming\\AppData\\Local\\Temp\\exitvector_phase8_rk8l2xbc\\failures.db.agent.lock"
  },
  "integrity": {
    "ok": true,
    "integrity_check": [
      "ok"
    ],
    "missing_tables": [],
    "missing_columns": {}
  }
}
```

## Killed-process OS lock and stale RUNNING recovery

```text
{
  "before": {
    "active": false,
    "pid": 21880,
    "next_run_at": null,
    "started_at": "2026-10-08T09:00:00+00:00",
    "stale": true,
    "long_running": false,
    "path": "C:\\Users\\LetzPC Gaming\\AppData\\Local\\Temp\\exitvector_phase8_rk8l2xbc\\failures.db.agent.lock"
  },
  "next_run": "SUCCESS",
  "abandoned_row": {
    "id": 4,
    "status": "CANCELLED",
    "error_count": 1,
    "summary": "{\"errors\": [\"Recovered abandoned process run\"]}"
  },
  "after": {
    "active": false,
    "pid": 8140,
    "next_run_at": null,
    "run_id": null,
    "started_at": "2026-10-08T09:00:00+00:00",
    "mode": "TEST",
    "stale": false,
    "long_running": false,
    "path": "C:\\Users\\LetzPC Gaming\\AppData\\Local\\Temp\\exitvector_phase8_rk8l2xbc\\failures.db.agent.lock"
  }
}
```

## Watch with injected wait

```text
{
  "statuses": [
    "SUCCESS",
    "SUCCESS"
  ],
  "triggers": [
    "WATCH",
    "WATCH"
  ],
  "requested_waits_seconds": [
    60
  ],
  "actual_wait_seconds": 0,
  "lock_after": {
    "active": false,
    "pid": 8140,
    "next_run_at": null,
    "mode": "WATCH",
    "run_id": null,
    "started_at": "2026-10-08T09:00:00+00:00",
    "stale": false,
    "long_running": false,
    "path": "C:\\Users\\LetzPC Gaming\\AppData\\Local\\Temp\\exitvector_phase8_rk8l2xbc\\deterministic.db.agent.lock"
  }
}
```

## Ctrl+C during watch wait

```text
{
  "lock_active_after": false,
  "stop_event": true
}
```

## Actual short watch CLI demonstration

```text
$ python -m exitvector_agent watch --interval 0.01s --cycles 2
ExitVector Agent — Run #3 — SUCCESS
Providers: social=mock (Stocktwits/Reddit fixtures); regivion=mock; content=LLM/mock; audience=mock; X posting=DISABLED; X relationship actions=DISABLED
WARNING: MOCK social and Regivion data are offline fixtures; this run does not observe live markets.
Social scan: 0 new observations; 3 trends
Opportunities: 0 new, 3 updated
Content/validation: 0 valid new candidates
Review queue: 0 new item(s); notifications: 0 batch(es)
Audience refresh: SKIPPED
Completed in 0.17s. No automatic posts were made.
ExitVector Agent — Run #4 — SUCCESS
Providers: social=mock (Stocktwits/Reddit fixtures); regivion=mock; content=LLM/mock; audience=mock; X posting=DISABLED; X relationship actions=DISABLED
WARNING: MOCK social and Regivion data are offline fixtures; this run does not observe live markets.
Social scan: 0 new observations; 3 trends
Opportunities: 0 new, 3 updated
Content/validation: 0 valid new candidates
Review queue: 0 new item(s); notifications: 0 batch(es)
Audience refresh: SKIPPED
Completed in 0.17s. No automatic posts were made.
ExitVector stopped safely.
Exit code: 0
```

## SQLite online backup

```text
$ python -m exitvector_agent backup
Backup created: C:\Users\LetzPC Gaming\AppData\Local\Temp\exitvector_phase8_rk8l2xbc\data with spaces\backups\exitvector-2026-10-08-074323-093098.db
Exit code: 0
```

## Backup integrity

```text
{
  "path": "C:\\Users\\LETZPC~1\\AppData\\Local\\Temp\\exitvector_phase8_rk8l2xbc\\data with spaces\\backups\\exitvector-2026-10-08-074323-093098.db",
  "result": {
    "ok": true,
    "integrity_check": [
      "ok"
    ],
    "missing_tables": [],
    "missing_columns": {}
  }
}
```

## Backup refuses overwrite

```text
$ python -m exitvector_agent backup --output C:\Users\LETZPC~1\AppData\Local\Temp\exitvector_phase8_rk8l2xbc\data with spaces\backups\exitvector-2026-10-08-074323-093098.db
ERROR: [Errno 17] File exists: 'C:\\Users\\LETZPC~1\\AppData\\Local\\Temp\\exitvector_phase8_rk8l2xbc\\data with spaces\\backups\\exitvector-2026-10-08-074323-093098.db'
Exit code: 2
```

## Database integrity and schema

```text
$ python -m exitvector_agent db-check
{
  "ok": true,
  "integrity_check": [
    "ok"
  ],
  "missing_tables": [],
  "missing_columns": {}
}
Exit code: 0
```

## Final CLI run history

```text
[
  {
    "id": 1,
    "status": "SUCCESS",
    "trigger_type": "MANUAL",
    "candidate_count": 6,
    "notification_count": 1,
    "error_count": 0
  },
  {
    "id": 2,
    "status": "SUCCESS",
    "trigger_type": "MANUAL",
    "candidate_count": 0,
    "notification_count": 0,
    "error_count": 0
  },
  {
    "id": 3,
    "status": "SUCCESS",
    "trigger_type": "WATCH",
    "candidate_count": 0,
    "notification_count": 0,
    "error_count": 0
  },
  {
    "id": 4,
    "status": "SUCCESS",
    "trigger_type": "WATCH",
    "candidate_count": 0,
    "notification_count": 0,
    "error_count": 0
  }
]
```

## Architecture and exact pipeline

`Settings` -> rotating safe logs -> `RunLock` -> `Database/ensure_schema` -> history RUNNING ->
`SocialScanService/SourceRunner` -> current trends -> per-ticker `OpportunityService` with bounded
Regivion retries -> existing generator/repair -> `ContentGenerationService` final validation and
dedup before persistence -> `ReviewHandoffService` -> optional due audience analysis -> one
console/mock notification batch plus local inbox -> final history -> wait/repeat or release lock.

The runner reuses scoring, novelty, repair, review audit and audience services. New operational
review/ready views require real validation and explicit human approval. Production fails before
pipeline execution; required live providers do not exist. All X action flags must remain false.
Native X ZIP inspection remains separate from normalized JSON import; no direct ZIP import was added.

Integration defects corrected: content briefs previously invented fixed rank/acceleration facts
and mislabeled composite Regivion score as PSC score; mock MSFT output now follows supplied evidence.
Malformed question drafts now undergo validation rather than pretending to be provider transport
failures. Latest opportunity selection now breaks timestamp ties by descending ID, preventing rapid
runs from attaching new candidates to old opportunity notification keys. SQLite backup destinations
are explicitly closed; connection context management alone did not close Windows file handles.

Dry-run calculation writes only to a disposable SQLite backup. The real DB/history/review/inbox/log
files are unchanged; lock metadata and its parent directory can persist. Live locks are never stolen.
Killed process RUNNING rows are marked CANCELLED by the next lock owner. Failure recovery preserves
already committed valid work. Backups use SQLite online backup and refuse existing destinations.


## Files changed or added in Phase 8

```text
.env.example
README.md
PHASE8_VERIFICATION.md
scripts/verify_phase8.py
src/exitvector_agent/__main__.py
src/exitvector_agent/agent.py (new)
src/exitvector_agent/config.py
src/exitvector_agent/content.py
src/exitvector_agent/database.py
src/exitvector_agent/logging.py
src/exitvector_agent/operations.py (new)
src/exitvector_agent/opportunity_service.py
src/exitvector_agent/review.py
src/exitvector_agent/run_lock.py (new)
src/exitvector_agent/social/scan.py
src/exitvector_agent/social/sources.py
tests/test_phase8_operations.py (new)
```
