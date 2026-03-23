#!/usr/bin/env python3

from __future__ import annotations

import os
import sys

import mysql.connector


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
    return int(_required_env("MY_APP_DB_PORT") if os.getenv("MY_APP_DB_PORT") or os.getenv("MY_KMM_DB_PORT") else "3306")


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        LIMIT 1
        """,
        (_required_env("MY_APP_DB_NAME"), table_name, column_name),
    )
    return cursor.fetchone() is not None


def main():
    conn = mysql.connector.connect(
        host=_required_env("MY_APP_DB_HOST"),
        port=_db_port(),
        database=_required_env("MY_APP_DB_NAME"),
        user=_required_env("MY_APP_DB_USER"),
        password=_required_env("MY_APP_DB_PWD"),
        charset="utf8mb4",
    )
    cursor = conn.cursor()

    if not _column_exists(cursor, "prompt_events", "project_name"):
        cursor.execute(
            """
            ALTER TABLE prompt_events
            ADD COLUMN project_name VARCHAR(255) NOT NULL DEFAULT '' AFTER external_event_id
            """
        )

    if not _column_exists(cursor, "task_runs", "project_name"):
        cursor.execute(
            """
            ALTER TABLE task_runs
            ADD COLUMN project_name VARCHAR(255) NOT NULL DEFAULT '' AFTER external_task_id
            """
        )

    conn.commit()
    cursor.close()
    conn.close()
    print("Added project_name columns")


if __name__ == "__main__":
    main()
