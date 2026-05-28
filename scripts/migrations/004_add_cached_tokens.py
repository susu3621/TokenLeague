#!/usr/bin/env python3

from __future__ import annotations

import os
import sys

import psycopg


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


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = %s
          AND column_name = %s
        LIMIT 1
        """,
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def main():
    conn = psycopg.connect(
        host=_required_env("MY_APP_DB_HOST"),
        port=_db_port(),
        dbname=_required_env("MY_APP_DB_NAME"),
        user=_required_env("MY_APP_DB_USER"),
        password=_required_env("MY_APP_DB_PWD"),
    )
    cursor = conn.cursor()

    if not _column_exists(cursor, "prompt_events", "cached_input_token_count"):
        cursor.execute(
            "ALTER TABLE prompt_events ADD COLUMN cached_input_token_count INTEGER NOT NULL DEFAULT 0"
        )

    if not _column_exists(cursor, "task_runs", "cached_input_token_count"):
        cursor.execute(
            "ALTER TABLE task_runs ADD COLUMN cached_input_token_count INTEGER NOT NULL DEFAULT 0"
        )

    conn.commit()
    cursor.close()
    conn.close()
    print("Ensured cached_input_token_count columns")


if __name__ == "__main__":
    main()
