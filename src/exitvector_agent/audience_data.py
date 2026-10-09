"""Phase 7 providers, transactional normalized imports, and audience queries."""
from __future__ import annotations

import json
from dataclasses import asdict, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from exitvector_agent.audience import (
    AudienceAccount, AudienceDataCoverage, AudienceRelationship, ImportSummary,
    Interaction, InteractionType, RelationshipMetrics, _normalize_datetime, _stable_id,
    compute_reciprocity, compute_relationship_value, score_high_value_connection,
    score_unfollow_candidate,
)
from exitvector_agent.database import Database, ensure_schema


def coverage_from_dict(raw: dict[str, Any]) -> AudienceDataCoverage:
    values = {f.name: raw[f.name] for f in fields(AudienceDataCoverage) if f.name in raw}
    for key in ("observation_window_start", "observation_window_end"):
        if key in values:
            value = _normalize_datetime(values[key])
            if values[key] and value is None:
                raise ValueError(f"Invalid coverage {key}")
            values[key] = value
    for key in values.keys() - {"observation_window_start", "observation_window_end", "completeness", "confidence"}:
        if values[key] not in (True, False, 0, 1):
            raise ValueError(f"Coverage {key} must be boolean")
        values[key] = bool(values[key])
    try:
        completeness = float(values.get("completeness", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Coverage completeness must be a number") from exc
    if not 0 <= completeness <= 1:
        raise ValueError("Coverage completeness must be between zero and one")
    values["completeness"] = completeness
    derived = "HIGH" if completeness >= .8 else "MEDIUM" if completeness >= .6 else "LOW"
    supplied = values.get("confidence", derived)
    if not isinstance(supplied, str) or supplied not in {"HIGH", "MEDIUM", "LOW"}:
        raise ValueError("Coverage confidence must be HIGH, MEDIUM or LOW")
    levels = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    values["confidence"] = min((derived, supplied), key=levels.get)
    result = AudienceDataCoverage(**values)
    if result.observation_window_start and result.observation_window_end and result.observation_window_start > result.observation_window_end:
        raise ValueError("Coverage window is reversed")
    return result


def normalize_account(raw: dict[str, Any], source: str) -> AudienceAccount:
    if not isinstance(raw, dict):
        raise ValueError("Account must be an object")
    identity = raw.get("account_id") or raw.get("id") or raw.get("username") or raw.get("handle")
    if not isinstance(identity, (str, int)) or isinstance(identity, bool) or not str(identity).strip():
        raise ValueError("Account requires a stable identity")
    username = str(raw.get("username") or raw.get("handle") or identity).lstrip("@")
    follows = bool(raw.get("follows_user") or raw.get("account_follows_user"))
    following = bool(raw.get("user_follows") or raw.get("following"))
    return AudienceAccount(
        account_id=str(identity), username=username,
        display_name=str(raw.get("name") or raw.get("display_name") or ""),
        follows_user=follows, user_follows=following, mutual_follow=follows and following,
        first_seen_at=_normalize_datetime(raw.get("first_seen_at") or raw.get("account_created_at")),
        last_seen_at=_normalize_datetime(raw.get("last_seen_at") or raw.get("updated_at")),
        source=source, source_confidence=.7,
        bio=str(raw.get("bio") or raw.get("description") or ""),
        follower_count=raw.get("follower_count"), following_count=raw.get("following_count"),
        verified=raw.get("verified"), account_created_at=_normalize_datetime(raw.get("account_created_at") or raw.get("created_at")),
    )


def load_normalized(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"Archive not found: {path}")
    if path.suffix.lower() == ".zip":
        from exitvector_agent.audience_archive import XArchiveAdapter
        report = XArchiveAdapter().inspect(path)
        raise ValueError("Native archive import is UNSUPPORTED; inspection report: " + json.dumps(report))
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unsupported normalized JSON format: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Expected a normalized JSON object")
    allowed = {"users", "following", "followers", "posts", "replies", "mentions", "likes_received",
               "likes_performed", "reposts", "quotes", "coverage", "account_coverage", "current_user_id"}
    unknown = payload.keys() - allowed
    if unknown:
        raise ValueError(f"Unsupported normalized sections: {', '.join(sorted(unknown))}")
    return payload


class ProviderQueries:
    """Shared compatibility methods; all analysis uses the same event-derived path."""
    def get_following(self) -> list[AudienceAccount]:
        return [a for a in self.get_accounts() if a.user_follows]

    def get_followers(self) -> list[AudienceAccount]:
        return [a for a in self.get_accounts() if a.follows_user]

    def get_replies(self) -> list[dict[str, Any]]:
        return [asdict(i) for i in self.get_interactions() if "REPLY" in i.interaction_type.value]

    def get_mentions(self) -> list[dict[str, Any]]:
        return [asdict(i) for i in self.get_interactions() if "MENTION" in i.interaction_type.value]

    def get_likes_received(self) -> list[dict[str, Any]]:
        return [asdict(i) for i in self.get_interactions()
                if i.interaction_type == InteractionType.LIKE and i.target_account_id == "current-user"]

    def get_account_metadata(self, account_id: str) -> dict[str, Any]:
        return asdict(self.get_account_detail(account_id))

    def get_account_detail(self, account_id: str) -> AudienceAccount:
        row = AudienceQueryService(self).account_detail(account_id)
        return replace(row["account"], relationship_class=row["metrics"].relationship_class,
                       unfollow_candidate=row["unfollow_candidate"])

    def get_relationships(self) -> list[dict[str, Any]]:
        return [{"account_id": r["account"].account_id, "username": r["account"].username,
                 "user_follows": r["account"].user_follows, "account_follows_user": r["account"].follows_user,
                 "mutual_follow": r["account"].mutual_follow,
                 "inbound_interactions": r["metrics"].inbound_interactions,
                 "outbound_interactions": r["metrics"].outbound_interactions,
                 "last_inbound": r["metrics"].last_inbound_interaction_at,
                 "last_outbound": r["metrics"].last_outbound_interaction_at,
                 "coverage": r["metrics"].coverage, "relationship_class": r["metrics"].relationship_class,
                 "unfollow_score": r["unfollow_candidate"].score}
                for r in AudienceQueryService(self).overview()]


class MockXAudienceDataProvider(ProviderQueries):
    """One consistent offline fixture. Every metric is derived from its events."""
    as_of = datetime(2026, 6, 30, tzinfo=timezone.utc)
    source = "MOCK"

    def get_accounts(self) -> list[AudienceAccount]:
        coverage = AudienceDataCoverage(
            following_available=True, followers_available=True, replies_available=True,
            mentions_available=True, replies_outbound_available=True, mentions_outbound_available=True,
            observation_window_start=self.as_of - timedelta(days=365), observation_window_end=self.as_of,
            completeness=.9, confidence="HIGH",
        )
        partial = AudienceDataCoverage(following_available=True, followers_available=True,
                                       completeness=.35, confidence="LOW")
        return [AudienceAccount(name.lower(), name, name, follows_user=follower,
                                user_follows=following, mutual_follow=follower and following,
                                first_seen_at=coverage.observation_window_start, last_seen_at=self.as_of,
                                source=self.source, source_confidence=.9,
                                data_coverage=partial if name == "DELTA" else coverage)
                for name, following, follower in [("ALPHA", True, True), ("BETA", True, False),
                                                  ("GAMMA", True, False), ("DELTA", True, False),
                                                  ("EPSILON", False, True)]]

    def get_interactions(self) -> list[Interaction]:
        events = []
        for name, inbound, count, age in [("alpha", True, 14, 5), ("alpha", False, 8, 10),
                                         ("beta", False, 20, 10), ("gamma", False, 5, 200),
                                         ("epsilon", True, 10, 12)]:
            for index in range(count):
                events.append(Interaction(f"{name}-{'in' if inbound else 'out'}-{index}",
                                          name if inbound else "current-user",
                                          "current-user" if inbound else name, InteractionType.REPLY,
                                          self.as_of - timedelta(days=age + index), source="MOCK", confidence=.9))
        return events

    def get_posts(self) -> list[dict[str, Any]]:
        return []


class ArchiveXAudienceDataProvider(ProviderQueries):
    """Read the documented normalized JSON contract, separately from native ZIP inspection."""
    source = "X_ARCHIVE"

    def __init__(self, archive_path: str | Path) -> None:
        self.archive_path = Path(archive_path)
        self.archive = load_normalized(archive_path)
        self._normalize()

    def _list(self, key: str) -> list[dict[str, Any]]:
        value = self.archive.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ValueError(f"{key} must be a list of objects")
        return value

    def _normalize(self) -> None:
        raw_accounts = [*self._list("users"), *self._list("following"), *self._list("followers")]
        accounts = {}
        for raw in raw_accounts:
            account = normalize_account(raw, self.source)
            prior = accounts.get(account.account_id)
            if prior:
                account = replace(account, username=prior.username if account.username == account.account_id else account.username,
                                  display_name=account.display_name or prior.display_name,
                                  user_follows=account.user_follows or prior.user_follows,
                                  follows_user=account.follows_user or prior.follows_user)
            accounts[account.account_id] = account
        following = {normalize_account(r, self.source).account_id for r in self._list("following")}
        followers = {normalize_account(r, self.source).account_id for r in self._list("followers")}
        self._interactions = []
        raw_owner = self.archive.get("current_user_id") or "current-user"
        if not isinstance(raw_owner, (str, int)) or isinstance(raw_owner, bool):
            raise ValueError("current_user_id must be a stable account identity")
        owner = str(raw_owner)
        accounts.pop(owner, None)
        for section, kind in [("replies", InteractionType.REPLY), ("mentions", InteractionType.MENTION),
                              ("likes_received", InteractionType.LIKE), ("likes_performed", InteractionType.LIKE),
                              ("reposts", InteractionType.REPOST), ("quotes", InteractionType.QUOTE)]:
            for raw in self._list(section):
                actor = raw.get("actor_account_id") or raw.get("user_id") or raw.get("account_id")
                target = raw.get("target_account_id") or raw.get("target_id")
                if not actor and section == "likes_performed":
                    actor = owner
                if not target and section not in {"likes_performed", "reposts", "quotes"}:
                    target = owner
                timestamp = _normalize_datetime(raw.get("created_at") or raw.get("timestamp"))
                if not actor or not target or timestamp is None:
                    raise ValueError(f"Invalid {section} interaction: actor, target and valid timestamp required")
                if any(not isinstance(identity, (str, int)) or isinstance(identity, bool) for identity in (actor, target)):
                    raise ValueError("Interaction identities must be strings or integers")
                actor, target = str(actor), str(target)
                actor = "current-user" if actor == owner else actor
                target = "current-user" if target == owner else target
                supplied_kind = raw.get("interaction_type", kind.value)
                try:
                    interaction_kind = InteractionType(supplied_kind)
                except ValueError as exc:
                    raise ValueError(f"Unsupported interaction type: {supplied_kind}") from exc
                canonical = {"actor": actor, "target": target, "type": interaction_kind.value,
                             "timestamp": timestamp.isoformat(), "post_id": str(raw.get("post_id") or raw.get("tweet_id") or "")}
                identity = raw.get("id") or raw.get("interaction_id") or _stable_id(canonical)
                self._interactions.append(Interaction(str(identity), actor, target, interaction_kind,
                                                      timestamp, canonical["post_id"] or None, self.source, .7))
                for identity in (actor, target):
                    if identity != "current-user" and identity not in accounts:
                        accounts[identity] = normalize_account({"id": identity}, self.source)
        self.coverage = self._coverage()
        per_account = self.archive.get("account_coverage", {})
        if not isinstance(per_account, dict) or any(not isinstance(v, dict) for v in per_account.values()):
            raise ValueError("account_coverage must map account IDs to coverage objects")
        self._accounts = []
        for identity, account in accounts.items():
            user_follows = identity in following or account.user_follows
            follows_user = identity in followers or account.follows_user
            self._accounts.append(replace(account, user_follows=user_follows, follows_user=follows_user,
                                          mutual_follow=user_follows and follows_user,
                                          data_coverage=coverage_from_dict(per_account[identity])
                                          if identity in per_account else self.coverage))
        self._posts = []
        for raw in self._list("posts"):
            stamp_raw = raw.get("created_at") or raw.get("timestamp")
            stamp = _normalize_datetime(stamp_raw)
            if stamp_raw and stamp is None:
                raise ValueError("Invalid post timestamp")
            author = str(raw.get("user_id") or raw.get("author_account_id") or owner)
            post = {"author_account_id": "current-user" if author == owner else author,
                    "timestamp": stamp.isoformat() if stamp else None, "text": str(raw.get("text") or raw.get("full_text") or "")}
            self._posts.append({"post_id": str(raw.get("id") or raw.get("post_id") or _stable_id(post)), **post})
        # The snapshot time is evidence-bound, never inferred as the current wall clock.
        self.as_of = self.coverage.observation_window_end or max((i.timestamp for i in self._interactions), default=None)

    def _coverage(self) -> AudienceDataCoverage:
        if "coverage" in self.archive:
            if not isinstance(self.archive["coverage"], dict):
                raise ValueError("coverage must be an object")
            return coverage_from_dict(self.archive["coverage"])
        # Presence of an explicitly normalized section (including []) means available.
        categories = {key + "_available": key in self.archive for key in
                      ("following", "followers", "replies", "mentions", "likes_received", "reposts")}
        categories.update(replies_outbound_available="replies" in self.archive,
                          mentions_outbound_available="mentions" in self.archive,
                          likes_performed_available="likes_performed" in self.archive,
                          quotes_available="quotes" in self.archive)
        # Nonempty observations alone never establish a complete observation window.
        return coverage_from_dict({**categories, "completeness": min(.5, sum(categories[k + "_available"] for k in
                                  ("following", "followers", "replies", "mentions", "likes_received", "reposts")) / 6)})

    def get_accounts(self) -> list[AudienceAccount]:
        return list(self._accounts)

    def get_interactions(self) -> list[Interaction]:
        return list(self._interactions)

    def get_posts(self) -> list[dict[str, Any]]:
        return list(self._posts)


class DatabaseXAudienceDataProvider(ProviderQueries):
    source = "X_ARCHIVE"

    def __init__(self, database: Database) -> None:
        self.database = database
        boundaries = [a.data_coverage.observation_window_end for a in self.get_accounts()
                      if a.data_coverage.observation_window_end]
        self.as_of = max(boundaries, default=None) or max((i.timestamp for i in self.get_interactions()), default=None)

    def get_accounts(self) -> list[AudienceAccount]:
        accounts = []
        for row in self.database.execute("SELECT * FROM audience_accounts WHERE source = ? AND account_id != 'current-user' ORDER BY username", (self.source,)):
            raw = dict(row)
            coverage = self.database.execute("SELECT * FROM audience_data_coverage WHERE account_id=? AND source=?", (row["account_id"], self.source)).fetchone()
            accounts.append(replace(normalize_account(raw, self.source),
                                    source_confidence=row["source_confidence"],
                                    data_coverage=coverage_from_dict(dict(coverage)) if coverage else AudienceDataCoverage()))
        return accounts

    def get_interactions(self) -> list[Interaction]:
        return [Interaction(row["interaction_id"], row["actor_account_id"], row["target_account_id"],
                            InteractionType(row["interaction_type"]), _normalize_datetime(row["timestamp"]),
                            row["post_id"], self.source, row["confidence"])
                for row in self.database.execute("SELECT * FROM audience_interactions WHERE source=?", (self.source,))]

    def get_posts(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.database.execute("SELECT * FROM audience_posts WHERE source=?", (self.source,))]


def upsert(database: Database, table: str, values: dict[str, Any], keys: tuple[str, ...]) -> None:
    """Internal SQL identifiers come exclusively from model/schema names."""
    columns = tuple(values)
    updates = [f"{c}=excluded.{c}" for c in columns if c not in keys]
    database.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
                     f"ON CONFLICT ({','.join(keys)}) DO UPDATE SET {','.join(updates)}", tuple(values.values()))


def persist_account(database: Database, account: AudienceAccount) -> None:
    raw = asdict(account)
    for key in ("data_coverage", "relationship_class", "unfollow_candidate"):
        raw.pop(key)
    for key in ("first_seen_at", "last_seen_at", "account_created_at"):
        raw[key] = raw[key].isoformat() if raw[key] else None
    upsert(database, "audience_accounts", raw, ("account_id", "source"))
    relationship = {key: raw[key] for key in ("account_id", "username", "user_follows", "mutual_follow", "first_seen_at", "last_seen_at", "source", "source_confidence")}
    relationship["account_follows_user"] = raw["follows_user"]
    upsert(database, "audience_relationships", relationship, ("account_id", "source"))
    coverage = asdict(account.data_coverage)
    for key in ("observation_window_start", "observation_window_end"):
        coverage[key] = coverage[key].isoformat() if coverage[key] else None
    upsert(database, "audience_data_coverage", {"account_id": account.account_id, "source": account.source, **coverage}, ("account_id", "source"))


class XArchiveImportService:
    def __init__(self, database: Database) -> None:
        self.database = database

    _normalize_account = staticmethod(normalize_account)

    def import_archive(self, archive_path: str | Path) -> ImportSummary:
        ensure_schema(self.database)
        # Schema setup commits before the import. Every import write, including scores,
        # links and source selection, belongs to this single rollback boundary.
        self.database.execute("BEGIN IMMEDIATE")
        try:
            provider = ArchiveXAudienceDataProvider(archive_path)
            cursor = self.database.execute(
                "INSERT INTO audience_import_runs(path,archive_hash,status,coverage_summary) VALUES(?,?,'IMPORTING',?)",
                (str(archive_path), _stable_id(provider.archive), json.dumps(asdict(provider.coverage), default=str)))
            run_id = int(cursor.lastrowid)
            accounts = provider.get_accounts()
            owner = AudienceAccount("current-user", "current-user", source="X_ARCHIVE", source_confidence=1,
                                    data_coverage=provider.coverage)
            # Preserve the existing empty-archive behavior without inventing relationships.
            for account in [owner, *accounts]:
                persist_account(self.database, account)
                if account.account_id == "current-user":
                    self.database.execute("DELETE FROM audience_relationships WHERE account_id='current-user' AND source='X_ARCHIVE'")
                self.database.execute("INSERT INTO audience_import_run_accounts(import_run_id,account_id) VALUES(?,?)", (run_id, account.account_id))
            inserted = 0
            for event in provider.get_interactions():
                prior = self.database.execute("SELECT actor_account_id,target_account_id,interaction_type,timestamp,post_id,source FROM audience_interactions WHERE interaction_id=?", (event.interaction_id,)).fetchone()
                canonical = (event.actor_account_id, event.target_account_id, event.interaction_type.value,
                             event.timestamp.isoformat(), event.post_id, event.source)
                if prior:
                    if tuple(prior) != canonical:
                        raise ValueError(f"Conflicting interaction identity: {event.interaction_id}")
                    continue
                self.database.execute("INSERT INTO audience_interactions(interaction_id,actor_account_id,target_account_id,interaction_type,timestamp,post_id,source,confidence,import_run_id) VALUES(?,?,?,?,?,?,?,?,?)",
                                      (event.interaction_id, *canonical, event.confidence, run_id))
                inserted += 1
            for post in provider.get_posts():
                upsert(self.database, "audience_posts", {**post, "source": "X_ARCHIVE", "import_run_id": run_id}, ("post_id", "source"))
            # Analyze persisted history, not just the newest import's interactions.
            AudienceQueryService(DatabaseXAudienceDataProvider(self.database), database=self.database).persist(commit=False)
            self.database.execute("UPDATE audience_import_runs SET status='OK' WHERE id=?", (run_id,))
            self.database.execute("INSERT INTO configuration(key,value) VALUES('audience_provider','database') ON CONFLICT(key) DO UPDATE SET value=excluded.value")
            self.database.commit()
            return ImportSummary(run_id, len(accounts) + 1, sum(a.user_follows for a in accounts),
                                 sum(a.follows_user for a in accounts), len(provider.get_posts()), inserted, provider.coverage)
        except Exception:
            self.database.execute("ROLLBACK")
            raise


class AudienceQueryService:
    """Structured read queries over mock, normalized archive, or persisted data.

    `all` uses the provider's evidence horizon. Explicit windows are anchored to
    as_of (injectable), intersect known coverage, and never extend it optimistically.
    """
    def __init__(self, provider: Any, *, window: str = "all", as_of: datetime | None = None,
                 database: Database | None = None, reciprocity_weights: dict[str, float] | None = None,
                 value_weights: dict[str, float] | None = None, unfollow_weights: dict[str, float] | None = None,
                 high_value_threshold: float = 40.0) -> None:
        if window not in {"30d", "90d", "180d", "365d", "all"}:
            raise ValueError("Window must be 30d, 90d, 180d, 365d or all")
        self.provider, self.window, self.database = provider, window, database
        self.high_value_threshold = high_value_threshold
        self.as_of = as_of or provider.as_of or datetime.now(timezone.utc)
        self.start = None if window == "all" else self.as_of - timedelta(days=int(window[:-1]))
        self.reciprocity_weights, self.value_weights, self.unfollow_weights = reciprocity_weights, value_weights, unfollow_weights

    def _analyze(self, account: AudienceAccount, events: list[Interaction]) -> dict[str, Any]:
        coverage = account.data_coverage
        evidence_end = min(self.as_of, coverage.observation_window_end) if coverage.observation_window_end else self.as_of
        evidence_start = max(self.start, coverage.observation_window_start) if self.start and coverage.observation_window_start else self.start or coverage.observation_window_start
        # A query cannot manufacture an unknown source observation boundary.
        if coverage.observation_window_start and coverage.observation_window_end:
            if evidence_start > evidence_end:
                coverage = replace(coverage, completeness=0, confidence="LOW", observation_window_start=None, observation_window_end=None)
            else:
                coverage = replace(coverage, observation_window_start=evidence_start, observation_window_end=evidence_end)
        if self.start and (not account.data_coverage.observation_window_start
                           or not account.data_coverage.observation_window_end
                           or self.start < account.data_coverage.observation_window_start
                           or self.as_of > account.data_coverage.observation_window_end):
            coverage = replace(coverage, completeness=min(coverage.completeness, .5), confidence="LOW")
        selected = [i for i in events if i.timestamp <= evidence_end and (evidence_start is None or i.timestamp >= evidence_start)]
        inbound = [i for i in selected if i.actor_account_id == account.account_id and i.target_account_id == "current-user"]
        outbound = [i for i in selected if i.target_account_id == account.account_id and i.actor_account_id == "current-user"]
        def count(items: list[Interaction], kinds: set[InteractionType], available: bool) -> int | None:
            found = sum(i.interaction_type in kinds for i in items)
            return found if available or found else None
        relation = AudienceRelationship(account.account_id, account.username, account.user_follows, account.follows_user,
                                        account.mutual_follow, account.first_seen_at, account.last_seen_at,
                                        account.source, account.source_confidence)
        metrics = RelationshipMetrics.from_account(
            relation, inbound=len(inbound), outbound=len(outbound),
            last_inbound=max((i.timestamp for i in inbound), default=None),
            last_outbound=max((i.timestamp for i in outbound), default=None), coverage=coverage, as_of=self.as_of,
            replies_to_user=count(inbound, {InteractionType.REPLY, InteractionType.ACCOUNT_REPLY_TO_USER}, coverage.replies_available),
            user_replies_to_them=count(outbound, {InteractionType.REPLY, InteractionType.USER_REPLY_TO_ACCOUNT}, coverage.replies_outbound_available),
            mentions_of_user=count(inbound, {InteractionType.MENTION, InteractionType.ACCOUNT_MENTION_OF_USER}, coverage.mentions_available),
            user_mentions_them=count(outbound, {InteractionType.MENTION, InteractionType.USER_MENTION_OF_ACCOUNT}, coverage.mentions_outbound_available),
            likes_of_user=count(inbound, {InteractionType.LIKE}, coverage.likes_received_available),
            user_likes_them=count(outbound, {InteractionType.LIKE}, coverage.likes_performed_available),
            reposts_of_user=count(inbound, {InteractionType.REPOST}, coverage.reposts_available),
            user_reposts_them=count(outbound, {InteractionType.REPOST}, coverage.reposts_available),
            quotes_of_user=count(inbound, {InteractionType.QUOTE}, coverage.quotes_available))
        reciprocity = compute_reciprocity(metrics, coverage, weights=self.reciprocity_weights)
        value = compute_relationship_value(metrics, coverage=coverage, weights=self.value_weights)
        candidate = score_unfollow_candidate(metrics, coverage=coverage, weights=self.unfollow_weights,
                                             reciprocity_weights=self.reciprocity_weights, value_weights=self.value_weights)
        high = score_high_value_connection(metrics, coverage=coverage,
                                           reciprocity_weights=self.reciprocity_weights, value_weights=self.value_weights)
        return {"account": replace(account, data_coverage=coverage, relationship_class=metrics.relationship_class),
                "metrics": metrics, "reciprocity": reciprocity, "relationship_value": value,
                "unfollow_candidate": candidate, "high_value_connection": high,
                "selected_window": self.window, "as_of": self.as_of}

    def overview(self) -> list[dict[str, Any]]:
        events = self.provider.get_interactions()
        return [self._analyze(account, events) for account in self.provider.get_accounts()]

    def account_detail(self, username: str) -> dict[str, Any]:
        key = username.lstrip("@").casefold()
        for row in self.overview():
            if key in {row["account"].account_id.casefold(), row["account"].username.casefold()}:
                return row
        raise ValueError(f"Account not found: {username}")

    def following_not_back(self) -> list[dict[str, Any]]:
        return [r for r in self.overview() if r["account"].user_follows and not r["account"].follows_user]

    def followers_not_followed(self) -> list[dict[str, Any]]:
        return [r for r in self.overview() if r["account"].follows_user and not r["account"].user_follows]

    def mutuals(self) -> list[dict[str, Any]]:
        return [r for r in self.overview() if r["account"].mutual_follow]

    def low_reciprocity(self) -> list[dict[str, Any]]:
        return sorted([r for r in self.overview() if r["reciprocity"].score < 30], key=lambda r: (r["reciprocity"].score, r["account"].username))

    def unfollow_candidates(self) -> list[dict[str, Any]]:
        return sorted([r for r in self.overview() if r["account"].user_follows
                       and r["relationship_value"].score < 70
                       and r["unfollow_candidate"].score > 0],
                      key=lambda r: (-r["unfollow_candidate"].score, r["account"].username))

    def high_value(self) -> list[dict[str, Any]]:
        return sorted([r for r in self.overview() if r["high_value_connection"].score >= self.high_value_threshold],
                      key=lambda r: (-r["high_value_connection"].score, r["account"].username))

    def never_interact(self) -> list[dict[str, Any]]:
        # This query concerns inbound engagement, even when the user has replied.
        results = []
        for row in self.overview():
            metrics, coverage = row["metrics"], row["metrics"].coverage
            if not row["account"].user_follows or metrics.inbound_interactions:
                continue
            confident = (coverage.completeness >= .8 and coverage.confidence == "HIGH" and coverage.replies_available and coverage.mentions_available
                         and coverage.observation_window_start is not None and coverage.observation_window_end is not None)
            results.append({"username": metrics.username, "observed_inbound_count": metrics.inbound_interactions,
                            "observed_outbound_count": metrics.outbound_interactions,
                            "observation_window_start": coverage.observation_window_start,
                            "observation_window_end": coverage.observation_window_end,
                            "selected_window": self.window, "data_coverage": coverage,
                            "confidence": "HIGH" if confident else "LOW", "unknown": not confident,
                            "explanation": ("No observed interaction in the selected period. This refers to inbound interaction in covered categories; unavailable categories remain unknown."
                                            if confident else "Insufficient coverage to determine whether this account interacted with you in the selected period; zero observed inbound interactions is not proof of absence.")})
        return results

    def persist(self, *, commit: bool = True) -> None:
        if self.database is None:
            raise ValueError("Persistence requires a database")
        db = self.database
        # Latest materialized scores are replaceable; raw source coverage stays intact.
        rows = self.overview()
        source = self.provider.source
        db.execute("SAVEPOINT audience_scores")
        try:
            for account in self.provider.get_accounts():
                persist_account(db, account)
            ids = [r["account"].account_id for r in rows]
            if ids:
                placeholders = ','.join('?' for _ in ids)
                for table in ("audience_unfollow_candidates", "audience_high_value_connections"):
                    db.execute(f"DELETE FROM {table} WHERE source=? AND account_id IN ({placeholders})", (source, *ids))
            for row in rows:
                account = row["account"]
                for table, score in [("audience_reciprocity_scores", row["reciprocity"]),
                                     ("audience_relationship_value_scores", row["relationship_value"])]:
                    raw = asdict(score); raw["reason_codes"] = json.dumps(raw["reason_codes"])
                    upsert(db, table, {"account_id": account.account_id, "source": source, **raw}, ("account_id", "source"))
                for table, score, eligible in [
                    ("audience_unfollow_candidates", row["unfollow_candidate"], account.user_follows and row["unfollow_candidate"].score > 0
                     and row["relationship_value"].score < 70),
                    ("audience_high_value_connections", row["high_value_connection"], row["high_value_connection"].score >= self.high_value_threshold)]:
                    if not eligible:
                        continue
                    raw = asdict(score); raw.pop("data_coverage")
                    raw["reason_codes"] = json.dumps(raw["reason_codes"])
                    raw["recommendation"] = raw.pop("recommendation_text")
                    raw["last_interaction_at"] = raw["last_interaction_at"].isoformat() if raw["last_interaction_at"] else None
                    upsert(db, table, {**raw, "source": source}, ("account_id", "source"))
            context = json.dumps({"window": self.window, "as_of": self.as_of.isoformat(),
                                  "account_coverage": {r["account"].account_id: asdict(r["metrics"].coverage) for r in rows}}, default=str)
            db.execute("INSERT INTO configuration(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       ("audience_snapshot_context:" + source, context))
            db.execute("RELEASE SAVEPOINT audience_scores")
            if commit:
                db.commit()
        except Exception:
            db.execute("ROLLBACK TO SAVEPOINT audience_scores")
            db.execute("RELEASE SAVEPOINT audience_scores")
            raise
