"""Apply local PostgreSQL migrations and remember which ones ran.

The migration files predate the migration ledger.  When an existing database is
encountered, the schema is inspected and migrations whose changes are already
present are bootstrapped into the ledger before newer migrations are applied.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((ROOT / "migrations").glob("*.sql"))


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _already_applied(inspector, migration_number: int) -> bool:
    tables = set(inspector.get_table_names())

    def columns(table: str) -> set[str]:
        return _columns(inspector, table)

    requirements = {
        1: ("research_projects",),
        2: ("research_projects", "papers", "search_runs", "project_papers"),
        3: ("project_papers", "search_runs"),
        4: ("papers", "project_papers", "search_runs"),
        5: ("subtopics", "search_runs"),
        6: ("search_runs",),
        7: ("project_papers",),
        8: ("project_papers", "subtopics"),
        9: ("papers", "project_papers"),
        10: ("search_runs",),
        11: ("search_queries",),
        12: ("search_runs",),
        13: ("search_queries",),
    }
    required_tables = requirements[migration_number]
    if not all(table in tables for table in required_tables):
        return False

    required_columns = {
        3: {
            "project_papers": {"relevanceScore"},
            "search_runs": {"duplicateCount"},
        },
        4: {
            "papers": {"embedding", "embeddingModel"},
            "project_papers": {"clusterId"},
            "search_runs": {"clusterCount"},
        },
        5: {"search_runs": {"namingError"}},
        6: {"search_runs": {"stage"}},
        7: {"project_papers": {"classificationExplanation"}},
        8: {
            "project_papers": {"isRelevant", "userModified"},
            "subtopics": {"userModified"},
        },
        9: {
            "papers": {"embeddingProvider", "embeddingDimension", "embeddingInputHash"},
            "project_papers": {"explanationContextHash"},
        },
        10: {"search_runs": {"generatedQueries"}},
        12: {"search_runs": {"filteredCount"}},
        13: {"search_queries": {"userAdded"}},
    }
    return all(
        expected <= columns(table)
        for table, expected in required_columns.get(migration_number, {}).items()
    )


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set. Copy .env.example to .env and try again.")

    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version VARCHAR(255) PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )

        inspector = inspect(engine)
        with engine.begin() as connection:
            applied = {
                row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))
            }
            for path in MIGRATIONS:
                version = path.name
                if version in applied:
                    continue
                number = int(path.name.split("_", 1)[0])
                if _already_applied(inspector, number):
                    connection.execute(
                        text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                        {"version": version},
                    )
                    print(f"✓ {version} (already applied)")
                    continue

                connection.exec_driver_sql(path.read_text())
                connection.execute(
                    text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                    {"version": version},
                )
                print(f"✓ {version}")
                inspector = inspect(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
