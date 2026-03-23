#!/usr/bin/env python3
"""
Migration: Convert all DATETIME columns to use UTC consistently.

This migration removes DEFAULT CURRENT_TIMESTAMP which uses MySQL server's
local timezone, and ensures all timestamps are explicitly set in UTC from Python.
"""

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


def get_connection():
    return mysql.connector.connect(
        host=_required_env("MY_APP_DB_HOST"),
        port=_db_port(),
        database=_required_env("MY_APP_DB_NAME"),
        user=_required_env("MY_APP_DB_USER"),
        password=_required_env("MY_APP_DB_PWD"),
        charset="utf8mb4",
    )


def _convert_shanghai_to_utc(cursor, table_name: str, column_name: str) -> None:
    """Convert Shanghai time (UTC+8) to UTC time by subtracting 8 hours."""
    # Check if column exists
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table_name, column_name),
    )
    if not cursor.fetchone():
        print(f"  Skipping {table_name}.{column_name} (column does not exist)")
        return

    # Convert existing data: subtract 8 hours to convert Shanghai time to UTC
    print(f"  Converting {table_name}.{column_name} from Shanghai (UTC+8) to UTC...")
    cursor.execute(
        f"UPDATE {table_name} SET {column_name} = DATE_SUB({column_name}, INTERVAL 8 HOUR) WHERE {column_name} IS NOT NULL"
    )
    affected = cursor.rowcount
    print(f"    Converted {affected} rows")


def main():
    conn = get_connection()
    cursor = conn.cursor()

    print("Migrating timestamps to UTC...")

    # Convert existing data in users table
    _convert_shanghai_to_utc(cursor, "users", "created_at")
    _convert_shanghai_to_utc(cursor, "users", "updated_at")
    _convert_shanghai_to_utc(cursor, "users", "hook_key_created_at")

    # Convert existing data in prompt_events table
    _convert_shanghai_to_utc(cursor, "prompt_events", "created_at")
    _convert_shanghai_to_utc(cursor, "prompt_events", "updated_at")

    # Convert existing data in task_runs table
    _convert_shanghai_to_utc(cursor, "task_runs", "created_at")
    _convert_shanghai_to_utc(cursor, "task_runs", "updated_at")

    # Convert existing data in system_settings table
    _convert_shanghai_to_utc(cursor, "system_settings", "updated_at")

    conn.commit()

    # Modify column definitions to remove DEFAULT CURRENT_TIMESTAMP
    # Note: We keep the columns but remove the automatic defaults
    # Python code will now explicitly set these values in UTC

    print("\nModifying column definitions...")

    # Users table
    cursor.execute("""
        ALTER TABLE users
        MODIFY COLUMN created_at DATETIME NULL,
        MODIFY COLUMN updated_at DATETIME NULL,
        MODIFY COLUMN hook_key_created_at DATETIME NULL
    """)
    print("  Modified users table")

    # Prompt_events table
    cursor.execute("""
        ALTER TABLE prompt_events
        MODIFY COLUMN created_at DATETIME NULL,
        MODIFY COLUMN updated_at DATETIME NULL
    """)
    print("  Modified prompt_events table")

    # Task_runs table
    cursor.execute("""
        ALTER TABLE task_runs
        MODIFY COLUMN created_at DATETIME NULL,
        MODIFY COLUMN updated_at DATETIME NULL
    """)
    print("  Modified task_runs table")

    # System_settings table
    cursor.execute("""
        ALTER TABLE system_settings
        MODIFY COLUMN updated_at DATETIME NULL
    """)
    print("  Modified system_settings table")

    conn.commit()

    cursor.close()
    conn.close()
    print("\nMigration complete: All timestamps converted to UTC")


if __name__ == "__main__":
    main()
