"""Forward-only migration runner (M05).

Ref: phase-1/DATA_ARCHITECTURE_AND_DB_SCHEMA.md §16.

No down-migrations by design: rolling back a schema change on a database
holding derived data is more dangerous than rolling forward with a corrective
migration.

Run:  python -u -m scripts.migrate
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from src.foundation.config import PROJECT_ROOT, settings

MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def applied_versions(conn: psycopg.Connection) -> set[str]:
    """Versions already applied. Empty on a virgin database."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'meta' AND table_name = 'schema_migrations'
            )
        """)
        if not cur.fetchone()[0]:
            return set()
        cur.execute("SELECT version FROM meta.schema_migrations")
        return {row[0] for row in cur.fetchall()}


def main() -> int:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"no migrations found in {MIGRATIONS_DIR}")
        return 1

    print(f"connecting: {settings.db_dsn_display}")
    with psycopg.connect(settings.db_dsn) as conn:
        done = applied_versions(conn)
        print(f"already applied: {len(done)}")

        for path in files:
            version = path.stem
            if version in done:
                print(f"  skip    {version}")
                continue

            sql = path.read_text(encoding="utf-8")
            print(f"  apply   {version} ...", end=" ", flush=True)
            try:
                # Each migration is one transaction: it fully applies or not at all.
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(sql)
                        cur.execute(
                            "INSERT INTO meta.schema_migrations (version, description) "
                            "VALUES (%s, %s)",
                            (version, version.replace("_", " ")),
                        )
                print("OK")
            except psycopg.Error as exc:
                print("FAILED")
                print(f"\n{type(exc).__name__}: {exc}")
                return 1

    print("\nmigrations complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
