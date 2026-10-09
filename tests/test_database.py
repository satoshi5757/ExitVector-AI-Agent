from pathlib import Path

import pytest

from exitvector_agent.database import Database, ensure_schema


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "exitvector.db")
    ensure_schema(db)
    return db


def test_database_initializes_expected_tables(database: Database) -> None:
    tables = database.list_tables()

    assert {
        "social_observations",
        "ticker_velocity",
        "opportunities",
        "generated_posts",
        "notifications",
        "post_performance",
        "configuration",
    }.issubset(tables)


def test_database_can_store_and_query_key_value_configuration(database: Database) -> None:
    database.set_config("scan_interval_seconds", "600")

    assert database.get_config("scan_interval_seconds") == "600"
    assert database.get_config("missing_key") is None
