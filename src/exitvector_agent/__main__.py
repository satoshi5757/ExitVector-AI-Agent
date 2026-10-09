"""Command-line entry point for ExitVector Agent."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone

from exitvector_agent.audience import (
    ArchiveXAudienceDataProvider, AudienceQueryService, DatabaseXAudienceDataProvider,
    MockXAudienceDataProvider, XArchiveImportService,
)
from exitvector_agent.audience_archive import XArchiveAdapter
from exitvector_agent.config import load_settings
from exitvector_agent.content import RuleBasedContentGenerator
from exitvector_agent.database import Database, ensure_schema
from exitvector_agent.logging import setup_logging
from exitvector_agent.opportunity_service import OpportunityService
from exitvector_agent.regivion import MockRegivionClient
from exitvector_agent.social.scan import SocialScanService


def main() -> int:
    """Run the application commands."""

    parser = argparse.ArgumentParser(description="ExitVector Agent")
    parser.add_argument("--env-file", help="Optional local environment file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="collect and persist mock/social observations")
    scan_parser.add_argument("--limit", type=int, default=20)

    trends_parser = subparsers.add_parser("trends", help="display ranked social trends")
    trends_parser.add_argument("--limit", type=int, default=20)

    opportunities_parser = subparsers.add_parser("opportunities", help="scan social trends and rank post opportunities")
    opportunities_parser.add_argument("--limit", type=int, default=20)

    opportunity_parser = subparsers.add_parser("opportunity", help="display the latest opportunity for one ticker")
    opportunity_parser.add_argument("ticker", type=str)

    content_parser = subparsers.add_parser("content", help="generate and list content candidates")
    content_parser.add_argument("ticker", nargs="?", default=None)
    content_parser.add_argument("--limit", type=int, default=20)

    audience_parser = subparsers.add_parser("audience", help="offline audience intelligence")
    audience_parser.add_argument("action", nargs="?", default="overview", choices=[
        "import", "inspect-archive", "overview", "never-interact", "low-reciprocity", "unfollow-candidates",
        "high-value", "following-not-back", "followers-not-followed", "mutuals", "account"])
    audience_parser.add_argument("target", nargs="?")
    audience_parser.add_argument("--archive", type=str, default=None)
    audience_parser.add_argument("--account", type=str, default=None)
    audience_parser.add_argument("--source", choices=["mock", "database", "archive"], default=None)
    audience_parser.add_argument("--window", choices=["30d", "90d", "180d", "365d", "all"], default="all")
    audience_parser.add_argument("--as-of", help="UTC/ISO reference time; defaults to source evidence horizon")
    audience_parser.add_argument("--limit", type=int, default=20)

    from exitvector_agent.operations import COMMANDS, add_parsers, execute
    add_parsers(subparsers)
    args = parser.parse_args()
    try:
        settings = load_settings(args.env_file)
    except ValueError as exc:
        fields = ", ".join(".".join(map(str, e['loc'])) for e in exc.errors()) if hasattr(exc, 'errors') else 'settings'
        print("ERROR: Invalid configuration fields: " + fields)
        return 2
    if args.command in COMMANDS:
        return execute(args, settings)
    try:
        settings.validate_operation()
    except ValueError as exc:
        print("ERROR: " + str(exc))
        return 2
    if args.command in {'scan', 'trends', 'opportunities', 'content'} and (
        settings.agent_social_provider != 'mock' or settings.agent_regivion_provider != 'mock' or settings.ai_provider == 'openai'):
        print('ERROR: Legacy generation commands are fixture-only; use run or run --symbol TICKER for configured live providers')
        return 2
    logger = setup_logging("exitvector.agent", level="INFO")
    logger.info("exitvector_startup", extra={"event": "startup", "context": {"environment": settings.environment, "command": args.command}})

    with Database(settings.database_path) as database:
        ensure_schema(database)
        database.set_config("scan_interval_seconds", str(settings.scan_interval_seconds))
        database.set_config("notify_threshold", str(settings.notify_threshold))

        if args.command == "scan":
            service = SocialScanService(database=database)
            service.run_sync(limit=args.limit)
            observation_count = database.execute("SELECT COUNT(*) AS count FROM social_observations").fetchone()["count"]
            print(f"Observation count: {observation_count}")
            return 0

        if args.command == "trends":
            service = SocialScanService(database=database)
            results = service.run_sync(limit=args.limit)
            observation_count = database.execute("SELECT COUNT(*) AS count FROM social_observations").fetchone()["count"]
            print(f"Observation count: {observation_count}")
            for index, result in enumerate(results, start=1):
                print(
                    f"{index}. {result.ticker:<5} {result.score:>5.1f}   "
                    f"+{result.velocity_ratio * 100:.0f}% mention acceleration"
                )
            summary = database.get_social_summary()
            print("Main sources:")
            for row in summary:
                print(f"- {row['source']}: {row['observation_count']} observations, {row['unique_authors']} unique authors")
            return 0

        if args.command == "opportunities":
            social_service = SocialScanService(database=database)
            social_service.run_sync(limit=20)
            opportunity_service = OpportunityService(
                database=database,
                regivion_client=MockRegivionClient(),
                threshold=settings.notify_threshold,
            )
            results = opportunity_service.scan(limit=args.limit)
            generator = RuleBasedContentGenerator(database=database)
            for opportunity in results:
                for candidate in generator.generate_for_opportunity(opportunity):
                    if generator.is_duplicate(candidate):
                        continue
                    generator._persist(candidate, opportunity)
            if not results:
                print("No opportunities above the configured threshold.")
                return 0
            for index, result in enumerate(results, start=1):
                print(
                    f"{index}. {result.symbol:<5} {result.total_score:>5.1f}  {result.confidence:<6}"
                )
                print(f"   Social: {result.social_trend_score:.1f}")
                print(f"   Regivion: {result.regivion_score:.1f}")
                print(f"   Angle: {result.suggested_content_angle}")
                print(f"   Reason: {' + '.join(result.trigger_reasons)}")
            return 0

        if args.command == "opportunity":
            opportunity_service = OpportunityService(
                database=database,
                regivion_client=MockRegivionClient(),
                threshold=settings.notify_threshold,
            )
            row = database.get_recent_opportunity(args.ticker)
            if row is None:
                print(f"No recent opportunity for {args.ticker.upper()}.")
                return 0
            print(
                f"{row['ticker']:<5} {float(row['score']):>5.1f}  {row['confidence']:<6}"
            )
            print(f"   Social: {float(row['social_trend_score']):.1f}")
            print(f"   Regivion: {float(row['regivion_score']):.1f}")
            print(f"   Angle: {row['suggested_content_angle']}")
            print(f"   Reason: {row['trigger_reasons']}")
            return 0

        if args.command == "content":
            generator = RuleBasedContentGenerator(database=database)
            rows = database.execute(
                "SELECT * FROM opportunities ORDER BY created_at DESC LIMIT ?",
                (args.limit,),
            ).fetchall()
            for row in rows:
                opportunity = __import__("types").SimpleNamespace(
                    symbol=row["ticker"],
                    total_score=float(row["score"]),
                    confidence=row["confidence"],
                    social_trend_score=float(row["social_trend_score"]),
                    regivion_score=float(row["regivion_score"]),
                    market_score=row["market_score"],
                    freshness_score=float(row["freshness_score"]),
                    novelty_score=float(row["novelty_score"]),
                    engagement_potential_score=float(row["engagement_potential_score"]),
                    trigger_reasons=json.loads(row["trigger_reasons"]),
                    social_summary=row["social_summary"],
                    regivion_summary=row["regivion_summary"],
                    strongest_fact=row["strongest_fact"],
                    supporting_facts=json.loads(row["supporting_facts"]),
                    urgency=row["urgency"],
                    suggested_content_angle=row["suggested_content_angle"],
                    suggested_visual_type=row["suggested_visual_type"],
                    content_angles=json.loads(row["content_angles"]),
                    history_confidence=1.0,
                    notification_eligible=bool(row["notification_eligible"]),
                )
                for candidate in generator.generate_for_opportunity(opportunity):
                    if not generator.is_duplicate(candidate):
                        generator._persist(candidate, opportunity)
            rows = database.execute(
                "SELECT * FROM content_candidates ORDER BY generated_at DESC LIMIT ?",
                (args.limit,),
            ).fetchall()
            if not rows:
                print("No content candidates available.")
                return 0
            if args.ticker:
                rows = [row for row in rows if row["ticker"] == args.ticker.upper()]
            for row in rows:
                print(f"{row['ticker']:<5} {row['format']:<18} {row['review_status']:<8} {row['estimated_engagement_score']}")
                print(f"   {row['hook']}")
                print(f"   {row['full_text']}")
            return 0

        if args.command == "audience":
            def json_default(value):
                if is_dataclass(value):
                    return asdict(value)
                if isinstance(value, datetime):
                    return value.isoformat()
                raise TypeError(f"Unsupported JSON value: {type(value).__name__}")

            try:
                if args.limit < 1:
                    raise ValueError("--limit must be positive")
                if args.action in {"import", "inspect-archive"}:
                    path = args.target or args.archive or settings.audience_archive_path
                    if not path:
                        raise ValueError("An archive path is required")
                    result = (XArchiveAdapter().inspect(path) if args.action == "inspect-archive"
                              else XArchiveImportService(database).import_archive(path))
                    print(json.dumps(result, default=json_default, indent=2))
                    return 0 if args.action == "import" or not result["errors"] else 2
                if args.target and args.action != "account":
                    raise ValueError("Only account, import and inspect-archive accept a positional target")
                source = args.source or settings.audience_provider
                if source == "auto":
                    source = database.get_config("audience_provider") or (
                        "database" if database.execute("SELECT 1 FROM audience_accounts WHERE source='X_ARCHIVE' LIMIT 1").fetchone()
                        else "mock")
                if source == "mock":
                    provider = MockXAudienceDataProvider()
                elif source == "database":
                    provider = DatabaseXAudienceDataProvider(database)
                else:
                    path = args.archive or settings.audience_archive_path
                    if not path:
                        raise ValueError("Archive source requires --archive or AUDIENCE_ARCHIVE_PATH")
                    provider = ArchiveXAudienceDataProvider(path)
                as_of = None
                if args.as_of:
                    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
                    as_of = as_of.replace(tzinfo=timezone.utc) if as_of.tzinfo is None else as_of.astimezone(timezone.utc)
                service = AudienceQueryService(provider, window=args.window, as_of=as_of,
                                               database=database if source != "archive" else None)
                if args.action == "account":
                    target = args.target or args.account
                    if not target:
                        raise ValueError("An account username is required")
                    result = service.account_detail(target)
                else:
                    method = args.action.replace("-", "_")
                    result = getattr(service, method)()[:args.limit]
                if source != "archive":
                    service.persist()
                print(json.dumps({"source": source, "window": args.window, "as_of": service.as_of,
                                  "results": result}, default=json_default, indent=2))
                return 0
            except (ValueError, OSError) as exc:
                print(json.dumps({"error": str(exc)}))
                return 2

    logger.info("exitvector_shutdown", context={"database": settings.database_url})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
