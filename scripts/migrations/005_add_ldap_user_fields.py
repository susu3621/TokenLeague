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

    if not _column_exists(cursor, "users", "auth_source"):
        cursor.execute(
            "ALTER TABLE users ADD COLUMN auth_source VARCHAR(16) NOT NULL DEFAULT 'local' CHECK (auth_source IN ('local', 'ldap'))"
        )

    if not _column_exists(cursor, "users", "ldap_dn"):
        cursor.execute("ALTER TABLE users ADD COLUMN ldap_dn VARCHAR(255) NULL")

    if not _column_exists(cursor, "users", "last_synced_at"):
        cursor.execute("ALTER TABLE users ADD COLUMN last_synced_at TIMESTAMP NULL")

    conn.commit()
    cursor.close()
    conn.close()
    print("Ensured LDAP user fields")


if __name__ == "__main__":
    main()
