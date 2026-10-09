import sqlite3

with sqlite3.connect("data/exitvector.db") as database:
    for table in (
        "social_observations",
        "trend_score_snapshots",
        "regivion_enrichment_snapshots",
        "opportunities",
        "content_candidates",
    ):
        count = database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(table, count)
