from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from exitvector_agent.audience import (
    ArchiveXAudienceDataProvider, AudienceQueryService, DatabaseXAudienceDataProvider,
    MockXAudienceDataProvider, XArchiveImportService,
)
from exitvector_agent.audience_archive import XArchiveAdapter
from exitvector_agent.database import Database, ensure_schema


@pytest.fixture
def db(tmp_path):
    with Database(tmp_path / "audience.db") as database:
        ensure_schema(database)
        yield database


@pytest.fixture
def service():
    return AudienceQueryService(MockXAudienceDataProvider())


@pytest.fixture
def normalized():
    provider = MockXAudienceDataProvider()
    accounts = provider.get_accounts()
    coverage = asdict(accounts[0].data_coverage)
    return {
        "users": [{"id": a.account_id, "username": a.username} for a in accounts],
        "following": [{"id": a.account_id, "username": a.username} for a in accounts if a.user_follows],
        "followers": [{"id": a.account_id, "username": a.username} for a in accounts if a.follows_user],
        "replies": [{"actor_account_id": i.actor_account_id, "target_account_id": i.target_account_id,
                     "timestamp": i.timestamp.isoformat(), "post_id": f"p-{i.interaction_id}"}
                    for i in provider.get_interactions()],
        "posts": [{"text": "A normalized post", "timestamp": "2026-06-01T00:00:00Z"}],
        "coverage": coverage,
        "account_coverage": {a.account_id: asdict(a.data_coverage) for a in accounts},
    }


def write_archive(tmp_path, payload, name="normalized.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload, default=str), encoding="utf-8")
    return path


def counts(db):
    return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in sorted(db.list_tables()) if table.startswith("audience_")}


def content(db):
    return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in sorted(db.list_tables()) if table.startswith("audience_") or table == "configuration"}


def test_delta_coverage_and_unknown_are_preserved_end_to_end(service):
    delta = service.account_detail("@DELTA")
    coverage = delta["account"].data_coverage
    assert coverage.completeness == .35
    assert coverage.confidence == "LOW"
    assert not coverage.replies_available and not coverage.mentions_available
    assert coverage.observation_window_start is None and coverage.observation_window_end is None
    assert delta["reciprocity"].unknown and delta["reciprocity"].confidence == "LOW"
    assert delta["relationship_value"].unknown
    candidate = delta["unfollow_candidate"]
    assert candidate.confidence == "LOW"
    assert "LOW_CONFIDENCE_DATA" in candidate.reason_codes
    assert "Insufficient data" in candidate.recommendation_text
    provider_detail = service.provider.get_account_detail("@delta")
    assert provider_detail.data_coverage == coverage
    assert provider_detail.unfollow_candidate == candidate


def test_gamma_delta_distinction_is_evidence_driven(service):
    gamma, delta = service.account_detail("GAMMA"), service.account_detail("DELTA")
    assert gamma["unfollow_candidate"].score > delta["unfollow_candidate"].score
    assert gamma["unfollow_candidate"].confidence == "HIGH"
    assert "LONG_NO_CONTACT" in gamma["unfollow_candidate"].reason_codes
    assert gamma["metrics"].days_since_last_interaction == 200
    assert gamma["metrics"].last_outbound_interaction_at is not None
    assert gamma["reciprocity"].unknown is False
    assert gamma["metrics"].relationship_class == delta["metrics"].relationship_class


def test_mock_lists_flags_and_relationships_agree(service):
    provider = service.provider
    assert {a.username for a in provider.get_following()} == {"ALPHA", "BETA", "GAMMA", "DELTA"}
    assert {a.username for a in provider.get_followers()} == {"ALPHA", "EPSILON"}
    by_id = {a.account_id: a for a in provider.get_accounts()}
    for row in provider.get_relationships():
        account = by_id[row["account_id"]]
        assert row["user_follows"] == account.user_follows
        assert row["account_follows_user"] == account.follows_user
        assert row["mutual_follow"] == (account.user_follows and account.follows_user)


def test_metrics_match_normalized_events_and_timestamps(service):
    events = service.provider.get_interactions()
    for row in service.overview():
        metrics = row["metrics"]
        inbound = [i for i in events if i.actor_account_id == metrics.account_id and i.target_account_id == "current-user"]
        outbound = [i for i in events if i.target_account_id == metrics.account_id and i.actor_account_id == "current-user"]
        assert metrics.inbound_interactions == len(inbound)
        assert metrics.outbound_interactions == len(outbound)
        assert metrics.last_inbound_interaction_at == max((i.timestamp for i in inbound), default=None)
        assert metrics.last_outbound_interaction_at == max((i.timestamp for i in outbound), default=None)
        if inbound:
            assert metrics.replies_to_user == len(inbound)
        if outbound:
            assert metrics.user_replies_to_them == len(outbound)
    assert service.account_detail("EPSILON")["metrics"].last_outbound_interaction_at is None
    assert service.account_detail("DELTA")["metrics"].last_outbound_interaction_at is None


def test_unavailable_categories_are_not_measured_zero(service):
    alpha = service.account_detail("ALPHA")["metrics"]
    delta = service.account_detail("DELTA")["metrics"]
    assert alpha.replies_to_user == 14 and alpha.mentions_of_user == 0
    assert alpha.likes_of_user is None and alpha.reposts_of_user is None and alpha.quotes_of_user is None
    assert delta.replies_to_user is None and delta.user_replies_to_them is None
    assert delta.mentions_of_user is None


def test_value_reasons_require_actual_evidence_and_inbound_value(service):
    alpha, beta, gamma, delta, epsilon = [service.account_detail(n) for n in ("ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON")]
    assert "SUSTAINED_CONVERSATION" in alpha["relationship_value"].reason_codes
    assert "SUSTAINED_CONVERSATION" not in beta["relationship_value"].reason_codes
    assert "OUTBOUND_ONLY_EFFORT" in beta["relationship_value"].reason_codes
    for row in (gamma, delta):
        assert "RECENT_INTERACTION" not in row["relationship_value"].reason_codes
        assert "SUSTAINED_CONVERSATION" not in row["relationship_value"].reason_codes
    assert epsilon["relationship_value"].score > beta["relationship_value"].score


def test_unfollow_exclusions_and_high_value_ranking(service):
    assert [r["account"].username for r in service.unfollow_candidates()] == ["BETA", "GAMMA", "DELTA"]
    assert service.account_detail("ALPHA")["unfollow_candidate"].score == 0
    assert service.account_detail("EPSILON")["unfollow_candidate"].score == 0
    assert "MUTUAL_FOLLOW" not in service.account_detail("EPSILON")["unfollow_candidate"].reason_codes
    ranked = [r["account"].username for r in service.high_value()]
    assert ranked[:2] == ["ALPHA", "EPSILON"]


def test_recommendation_matches_confidence(service):
    beta = service.account_detail("BETA")["unfollow_candidate"]
    delta = service.account_detail("DELTA")["unfollow_candidate"]
    assert beta.confidence == "HIGH" and "high-confidence" in beta.recommendation_text
    assert "low-confidence" not in beta.recommendation_text
    assert delta.confidence == "LOW" and "Insufficient data" in delta.recommendation_text


def test_real_follow_queries(service):
    assert [r["account"].username for r in service.following_not_back()] == ["BETA", "GAMMA", "DELTA"]
    assert [r["account"].username for r in service.followers_not_followed()] == ["EPSILON"]
    assert [r["account"].username for r in service.mutuals()] == ["ALPHA"]


def test_never_interact_has_rows_windows_and_honest_uncertainty(service):
    rows = {r["username"]: r for r in service.never_interact()}
    assert set(rows) == {"BETA", "GAMMA", "DELTA"}
    assert rows["GAMMA"]["confidence"] == "HIGH" and not rows["GAMMA"]["unknown"]
    assert rows["GAMMA"]["explanation"].startswith("No observed interaction in the selected period.")
    assert rows["GAMMA"]["observation_window_start"] is not None
    assert rows["DELTA"]["confidence"] == "LOW" and rows["DELTA"]["unknown"]
    assert "not proof of absence" in rows["DELTA"]["explanation"]
    assert rows["DELTA"]["observation_window_start"] is None


@pytest.mark.parametrize("window", ["30d", "90d", "180d", "365d", "all"])
def test_observation_windows_filter_actual_events(window):
    service = AudienceQueryService(MockXAudienceDataProvider(), window=window)
    gamma = service.account_detail("GAMMA")
    assert gamma["metrics"].outbound_interactions == (5 if window in {"365d", "all"} else 0)
    if window not in {"365d", "all"}:
        assert gamma["metrics"].last_outbound_interaction_at is None
        assert "LONG_NO_CONTACT" not in gamma["unfollow_candidate"].reason_codes


def test_window_changes_scores_and_does_not_erase_history():
    provider = MockXAudienceDataProvider()
    all_time = AudienceQueryService(provider).account_detail("GAMMA")
    recent = AudienceQueryService(provider, window="90d").account_detail("GAMMA")
    assert all_time["unfollow_candidate"].score > recent["unfollow_candidate"].score
    assert len(provider.get_interactions()) == 57
    # BETA's event 29 days ago is included; moving the reference filters all of it.
    future = AudienceQueryService(provider, window="30d", as_of=provider.as_of + timedelta(days=60))
    assert future.account_detail("BETA")["metrics"].outbound_interactions == 0


def test_import_memberships_reconcile_account_and_relationship_flags(db, tmp_path, normalized):
    XArchiveImportService(db).import_archive(write_archive(tmp_path, normalized))
    rows = {r["account_id"]: r for r in db.execute("SELECT * FROM audience_accounts")}
    assert rows["alpha"]["user_follows"] == rows["alpha"]["follows_user"] == rows["alpha"]["mutual_follow"] == 1
    assert rows["beta"]["user_follows"] == 1 and rows["beta"]["follows_user"] == 0
    assert rows["epsilon"]["user_follows"] == 0 and rows["epsilon"]["follows_user"] == 1
    for row in db.execute("SELECT * FROM audience_relationships"):
        account = rows[row["account_id"]]
        assert row["user_follows"] == account["user_follows"]
        assert row["account_follows_user"] == account["follows_user"]
        assert row["mutual_follow"] == account["mutual_follow"]
    imported = AudienceQueryService(DatabaseXAudienceDataProvider(db))
    assert [r["account"].username for r in imported.mutuals()] == ["ALPHA"]
    assert {r["account"].username for r in imported.following_not_back()} == {"BETA", "GAMMA", "DELTA"}
    assert [r["account"].username for r in imported.followers_not_followed()] == ["EPSILON"]


def test_idless_interactions_posts_and_links_are_idempotent(db, tmp_path, normalized):
    path = write_archive(tmp_path, normalized)
    importer = XArchiveImportService(db)
    first = importer.import_archive(path)
    after_first = counts(db)
    second = importer.import_archive(path)
    after_second = counts(db)
    assert first.interactions == 57 and second.interactions == 0
    assert first.posts == second.posts == 1
    for table in ("audience_accounts", "audience_relationships", "audience_interactions", "audience_posts",
                  "audience_data_coverage", "audience_reciprocity_scores", "audience_relationship_value_scores",
                  "audience_unfollow_candidates", "audience_high_value_connections"):
        assert after_first[table] == after_second[table]
    assert after_second["audience_import_runs"] == 2
    assert after_second["audience_import_run_accounts"] == 12
    assert db.execute("SELECT COUNT(*) FROM audience_import_run_accounts WHERE account_id='' ").fetchone()[0] == 0
    for run_id in (first.import_run_id, second.import_run_id):
        linked = {r[0] for r in db.execute("SELECT account_id FROM audience_import_run_accounts WHERE import_run_id=?", (run_id,))}
        assert linked == {"current-user", "alpha", "beta", "gamma", "delta", "epsilon"}
    hashes = [r[0] for r in db.execute("SELECT archive_hash FROM audience_import_runs")]
    assert hashes[0] == hashes[1] and len(hashes[0]) == 64
    assert all(len(r[0]) == 64 for r in db.execute("SELECT interaction_id FROM audience_interactions"))


def test_coverage_and_score_snapshots_are_populated_and_context_saved(db, tmp_path, normalized):
    XArchiveImportService(db).import_archive(write_archive(tmp_path, normalized))
    result = counts(db)
    assert result["audience_data_coverage"] == 6
    assert result["audience_reciprocity_scores"] == result["audience_relationship_value_scores"] == 5
    assert result["audience_unfollow_candidates"] == 3
    assert result["audience_high_value_connections"] == 2
    delta = db.execute("SELECT * FROM audience_reciprocity_scores WHERE account_id='delta'").fetchone()
    assert delta["unknown"] == 1 and delta["confidence"] == "LOW"
    assert "LOW_CONFIDENCE_DATA" in json.loads(delta["reason_codes"])
    service = AudienceQueryService(DatabaseXAudienceDataProvider(db), window="90d", database=db)
    service.persist()
    context = json.loads(db.get_config("audience_snapshot_context:X_ARCHIVE"))
    assert context["window"] == "90d"
    # Materializing a short window cannot overwrite original source coverage.
    original = db.execute("SELECT observation_window_start FROM audience_data_coverage WHERE account_id='alpha'").fetchone()[0]
    assert original == "2025-06-30T00:00:00+00:00"


def test_database_analysis_matches_normalized_provider(db, tmp_path, normalized):
    path = write_archive(tmp_path, normalized)
    XArchiveImportService(db).import_archive(path)
    imported = AudienceQueryService(DatabaseXAudienceDataProvider(db))
    direct = AudienceQueryService(ArchiveXAudienceDataProvider(path))
    for name in ("ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON"):
        left, right = imported.account_detail(name), direct.account_detail(name)
        assert left["metrics"] == right["metrics"]
        assert left["reciprocity"] == right["reciprocity"]
        assert left["unfollow_candidate"] == right["unfollow_candidate"]


@pytest.mark.parametrize("failure", ["json", "account", "interaction", "late", "conflict"])
def test_atomic_import_rolls_back_all_new_state(db, tmp_path, normalized, monkeypatch, failure):
    importer = XArchiveImportService(db)
    path = write_archive(tmp_path, normalized)
    importer.import_archive(path)
    before = content(db)
    bad = {"users": [{"id": "new", "username": "NEW"}], "following": [{"id": "new", "username": "NEW"}]}
    if failure == "json":
        path.write_text("{bad", encoding="utf-8")
    elif failure == "account":
        bad["users"].append(None)
        write_archive(tmp_path, bad)
    elif failure == "interaction":
        bad["replies"] = [{"id": "invalid", "actor_account_id": "new", "timestamp": "not-a-date"}]
        write_archive(tmp_path, bad)
    elif failure == "late":
        write_archive(tmp_path, bad)
        def fail_after_writes(self, **kwargs):
            assert self.database.execute("SELECT 1 FROM audience_accounts WHERE account_id='new'").fetchone()
            assert self.database.execute("SELECT 1 FROM audience_relationships WHERE account_id='new'").fetchone()
            raise RuntimeError("injected late snapshot failure")
        monkeypatch.setattr(AudienceQueryService, "persist", fail_after_writes)
    else:
        existing = db.execute("SELECT interaction_id FROM audience_interactions LIMIT 1").fetchone()[0]
        bad["replies"] = [{"id": existing, "actor_account_id": "new", "timestamp": "2026-06-01T00:00:00Z"}]
        write_archive(tmp_path, bad)
    with pytest.raises((ValueError, RuntimeError)):
        importer.import_archive(path)
    assert content(db) == before
    # Check durable state from a separate connection as well.
    with Database(db.database_path) as reopened:
        assert content(reopened) == before
    assert db.execute("SELECT COUNT(*) FROM audience_import_runs WHERE status!='OK'").fetchone()[0] == 0


def test_empty_available_sections_and_absent_windows_stay_honest(tmp_path):
    provider = ArchiveXAudienceDataProvider(write_archive(tmp_path, {"following": [], "replies": []}))
    assert provider.coverage.following_available and provider.coverage.replies_available
    assert provider.coverage.observation_window_start is None
    assert provider.coverage.confidence == "LOW"


@pytest.fixture
def native_zip(tmp_path):
    path = tmp_path / "native.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("download/data/account.js", 'window.YTD.account.part0 = [{"account":{"accountId":"owner","username":"owner"}}];')
        archive.writestr("download/data/following.js", 'window.YTD.following.part0 = [{"following":{"accountId":"alpha"}}];')
        archive.writestr("download/data/following-part1.js", 'window.YTD.following.part1 = [{"following":{"accountId":"beta"}}];')
        archive.writestr("download/data/follower.json", '[{"follower":{"accountId":"alpha"}}]')
        archive.writestr("download/data/tweets.js", 'window.YTD.tweets.part0 = [{"tweet":{"id_str":"p1","full_text":"hello","created_at":"Mon Jun 01 00:00:00 +0000 2026"}}];')
        archive.writestr("download/data/like.js", 'window.YTD.like.part0 = [];')
    return path


def test_native_zip_inspection_is_explicitly_partial_and_import_unsupported(db, native_zip):
    report = XArchiveAdapter().inspect(native_zip)
    assert report["status"] == "INSPECTED_PARTIAL"
    assert report["native_import_supported"] is False
    assert not report["missing_sections"] and not report["errors"]
    assert report["sections"]["following"]["records"] == 2
    assert report["normalized_preview"]["posts"][0]["id"] == "p1"
    assert report["normalized_preview"]["followers"][0]["id"] == "alpha"
    assert report["unsupported_files"] == ["download/data/like.js"]
    before = content(db)
    with pytest.raises(ValueError, match="Native archive import is UNSUPPORTED"):
        XArchiveImportService(db).import_archive(native_zip)
    assert content(db) == before


@pytest.mark.parametrize("member,text", [
    ("../following.js", "window.YTD.following.part0 = [];"),
    ("/following.js", "window.YTD.following.part0 = [];"),
    ("data/account.js", "window.YTD.account.part0 = []; dangerous();"),
    ("data/account.js", "window.YTD.account.part0 = [dangerous()];"),
])
def test_zip_inspector_rejects_unsafe_paths_and_executable_js(tmp_path, member, text):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, text)
    report = XArchiveAdapter().inspect(path)
    assert report["status"] == "UNSUPPORTED" and report["errors"]


def test_zip_size_limit_and_unknown_layout(tmp_path):
    path = tmp_path / "size.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data/account.json", '[]' + ' ' * 100)
    adapter = XArchiveAdapter()
    adapter.max_section_bytes = 10
    assert adapter.inspect(path)["errors"]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("unknown.json", '[]')
    report = adapter.inspect(path)
    assert report["status"] == "UNSUPPORTED" and report["missing_sections"]


def cli(tmp_path, *args, provider=None):
    env = os.environ.copy()
    env["EXITVECTOR_DATABASE_URL"] = "sqlite:///" + str(tmp_path / "cli.db")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env.pop("EXITVECTOR_AUDIENCE_PROVIDER", None)
    env.pop("AUDIENCE_PROVIDER", None)
    if provider:
        env["AUDIENCE_PROVIDER"] = provider
    return subprocess.run([sys.executable, "-m", "exitvector_agent", "audience", *args],
                          env=env, capture_output=True, text=True)


@pytest.mark.parametrize("args", [[], ["--window", "90d"], ["never-interact"], ["low-reciprocity"],
                                    ["unfollow-candidates"], ["high-value"], ["following-not-back"],
                                    ["followers-not-followed"], ["mutuals"], ["account", "@BETA"]])
def test_requested_cli_analysis_contract_returns_real_structured_results(tmp_path, args):
    completed = cli(tmp_path, *args, provider="mock")
    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads(completed.stdout)
    assert result["source"] == "mock" and result["results"]
    if args and args[0] == "account":
        row = result["results"]
        assert row["account"]["user_follows"] is True and row["account"]["follows_user"] is False
        assert row["metrics"]["username"] == "BETA"
        assert row["unfollow_candidate"]["recommendation_text"]
    if args and args[0] == "unfollow-candidates":
        assert [r["account"]["username"] for r in result["results"]] == ["BETA", "GAMMA", "DELTA"]


def test_cli_import_selects_database_and_never_falls_back_to_mock(tmp_path):
    path = write_archive(tmp_path, {"following": [{"id": "real", "username": "REAL"}]})
    imported = cli(tmp_path, "import", str(path))
    assert imported.returncode == 0, imported.stderr + imported.stdout
    result = json.loads(cli(tmp_path).stdout)
    assert result["source"] == "database"
    assert [r["account"]["username"] for r in result["results"]] == ["REAL"]
    assert json.loads(cli(tmp_path, "--source", "mock").stdout)["source"] == "mock"
    assert json.loads(cli(tmp_path, provider="database").stdout)["results"][0]["account"]["username"] == "REAL"
    archive = cli(tmp_path, "--source", "archive", "--archive", str(path))
    assert archive.returncode == 0 and json.loads(archive.stdout)["source"] == "archive"


def test_explicit_empty_database_source_does_not_return_mock(tmp_path):
    result = cli(tmp_path, "--source", "database")
    assert result.returncode == 0
    assert json.loads(result.stdout)["results"] == []


def test_cli_errors_are_graceful_and_native_report_is_available(tmp_path, native_zip):
    missing = cli(tmp_path, "account", "@UNKNOWN", provider="mock")
    assert missing.returncode == 2 and "Account not found" in json.loads(missing.stdout)["error"]
    imported = cli(tmp_path, "import", str(native_zip))
    assert imported.returncode == 2 and "UNSUPPORTED" in json.loads(imported.stdout)["error"]
    inspected = cli(tmp_path, "inspect-archive", str(native_zip))
    assert inspected.returncode == 0 and json.loads(inspected.stdout)["native_import_supported"] is False


def test_explicit_low_source_confidence_is_not_upgraded(tmp_path, normalized):
    normalized["coverage"]["confidence"] = "LOW"
    normalized.pop("account_coverage")
    provider = ArchiveXAudienceDataProvider(write_archive(tmp_path, normalized))
    beta = AudienceQueryService(provider).account_detail("BETA")
    assert beta["account"].data_coverage.completeness == .9
    assert beta["account"].data_coverage.confidence == "LOW"
    assert beta["reciprocity"].unknown
    assert beta["unfollow_candidate"].confidence == "LOW"
    assert "Insufficient data" in beta["unfollow_candidate"].recommendation_text


def test_window_outside_known_coverage_is_low_confidence():
    provider = MockXAudienceDataProvider()
    future = AudienceQueryService(provider, window="30d", as_of=provider.as_of + timedelta(days=60))
    beta = future.account_detail("BETA")
    assert beta["reciprocity"].unknown and beta["reciprocity"].confidence == "LOW"
    assert beta["metrics"].outbound_interactions == 0
    assert beta["metrics"].coverage.observation_window_start is None


def test_custom_weights_reach_nested_scores_and_rankings():
    zero_value = {"reply": 0, "mutual": 0, "recent": 0, "frequency": 0}
    zero_reciprocity = {"inbound": 0, "outbound": 0, "mutual": 0, "recency": 0}
    service = AudienceQueryService(MockXAudienceDataProvider(), value_weights=zero_value,
                                  reciprocity_weights=zero_reciprocity)
    alpha = service.account_detail("ALPHA")
    assert alpha["relationship_value"].score == alpha["reciprocity"].score == 0
    assert alpha["unfollow_candidate"].relationship_value_score == 0
    assert alpha["high_value_connection"].score == 0
    assert service.high_value() == []


def test_mock_snapshots_do_not_overwrite_imported_snapshots(db, tmp_path, normalized):
    path = write_archive(tmp_path, normalized)
    XArchiveImportService(db).import_archive(path)
    before = [tuple(r) for r in db.execute("SELECT * FROM audience_unfollow_candidates WHERE source='X_ARCHIVE' ORDER BY account_id")]
    AudienceQueryService(MockXAudienceDataProvider(), database=db, window="90d").persist()
    after = [tuple(r) for r in db.execute("SELECT * FROM audience_unfollow_candidates WHERE source='X_ARCHIVE' ORDER BY account_id")]
    assert before == after
    assert db.execute("SELECT COUNT(*) FROM audience_unfollow_candidates WHERE source='MOCK'").fetchone()[0] == 3
    assert db.execute("SELECT COUNT(*) FROM audience_accounts WHERE source='X_ARCHIVE'").fetchone()[0] == 6


def test_legacy_ranking_schema_migration_preserves_rows(tmp_path):
    with Database(tmp_path / "legacy.db") as db:
        # A minimal old table exercises the actual legacy unique-key migration.
        for table in ("audience_unfollow_candidates", "audience_high_value_connections"):
            db.execute(f"CREATE TABLE {table}(account_id TEXT NOT NULL UNIQUE, score REAL)")
            db.execute(f"INSERT INTO {table} VALUES('existing',42)")
        db.commit()
        ensure_schema(db)
        ensure_schema(db)
        for table in ("audience_unfollow_candidates", "audience_high_value_connections"):
            row = db.execute(f"SELECT * FROM {table}").fetchone()
            assert row["account_id"] == "existing" and row["score"] == 42
            assert row["source"] == "LEGACY_UNKNOWN"
            db.execute(f"INSERT INTO {table}(account_id,score,source) VALUES('existing',10,'MOCK')")
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 2
