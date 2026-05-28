#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


MIGRATION_FILE_PATTERN = re.compile(r"^(\d+)_.*\.py$")
MIGRATION_TABLE = "schema_migrations"
DB_ENV_ALIASES = {
    "MY_APP_DB_HOST": ("MY_APP_DB_HOST", "MY_KMM_DB_HOST"),
    "MY_APP_DB_NAME": ("MY_APP_DB_NAME", "MY_KMM_DB_NAME"),
    "MY_APP_DB_USER": ("MY_APP_DB_USER", "MY_KMM_DB_USER"),
    "MY_APP_DB_PWD": ("MY_APP_DB_PWD", "MY_KMM_DB_PWD"),
    "MY_APP_DB_PORT": ("MY_APP_DB_PORT", "MY_KMM_DB_PORT"),
}


def _required_env(name: str) -> str:
    for candidate in DB_ENV_ALIASES.get(name, (name,)):
        value = os.getenv(candidate)
        if value:
            return value
    print(f"Missing required environment variable: {name}", file=sys.stderr)
    sys.exit(1)


def _db_port() -> int:
    return int(_required_env("MY_APP_DB_PORT") if os.getenv("MY_APP_DB_PORT") or os.getenv("MY_KMM_DB_PORT") else "5432")


def get_connection():
    return psycopg.connect(
        host=_required_env("MY_APP_DB_HOST"),
        port=_db_port(),
        dbname=_required_env("MY_APP_DB_NAME"),
        user=_required_env("MY_APP_DB_USER"),
        password=_required_env("MY_APP_DB_PWD"),
        row_factory=dict_row,
    )


def ensure_migration_table(conn):
    cursor = conn.cursor()
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
            id SERIAL PRIMARY KEY,
            migration_name VARCHAR(255) NOT NULL UNIQUE,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    cursor.close()


def get_applied_migrations(conn) -> set[str]:
    cursor = conn.cursor()
    cursor.execute(f"SELECT migration_name FROM {MIGRATION_TABLE}")
    rows = cursor.fetchall()
    cursor.close()
    return {row["migration_name"] for row in rows}


def list_migration_files(migrations_dir: Path) -> list[Path]:
    files = []
    for path in migrations_dir.iterdir():
        if path.is_file() and MIGRATION_FILE_PATTERN.match(path.name):
            files.append(path)
    files.sort(key=lambda item: (int(MIGRATION_FILE_PATTERN.match(item.name).group(1)), item.name))
    return files


def mark_migration_applied(conn, migration_name: str):
    cursor = conn.cursor()
    cursor.execute(
        f"INSERT INTO {MIGRATION_TABLE} (migration_name) VALUES (%s)",
        (migration_name,),
    )
    conn.commit()
    cursor.close()


def run_single_migration(path: Path):
    print(f"[migration] running {path.name}")
    result = subprocess.run([sys.executable, str(path)], text=True, capture_output=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"{path.name} failed with exit code {result.returncode}")


def main():
    parser = argparse.ArgumentParser(description="Run pending TokenLeague migrations")
    parser.add_argument("--dry-run", action="store_true", help="List pending migrations without running them")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    migrations_dir = script_dir / "migrations"
    conn = get_connection()
    try:
        ensure_migration_table(conn)
        applied = get_applied_migrations(conn)
        pending = [path for path in list_migration_files(migrations_dir) if path.name not in applied]
        if not pending:
            print("[migration] no pending migrations")
            return
        for path in pending:
            print(f"- {path.name}")
        if args.dry_run:
            return
        for path in pending:
            run_single_migration(path)
            mark_migration_applied(conn, path.name)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
