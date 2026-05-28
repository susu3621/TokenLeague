#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from werkzeug.security import generate_password_hash


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


def _connect(database: str):
    return psycopg.connect(
        host=_required_env("MY_APP_DB_HOST"),
        port=_db_port(),
        dbname=database,
        user=_required_env("MY_APP_DB_USER"),
        password=_required_env("MY_APP_DB_PWD"),
    )


def ensure_database_exists(database: str) -> None:
    admin_database = os.getenv("MY_APP_DB_ADMIN_DB") or os.getenv("MY_KMM_DB_ADMIN_DB") or "postgres"
    conn = _connect(admin_database)
    conn.autocommit = True
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
        if cursor.fetchone():
            cursor.close()
            return
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        cursor.close()
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Initialize the TokenLeague PostgreSQL database")
    parser.add_argument("--admin-password", required=True, help="Initial admin password")
    args = parser.parse_args()

    database = _required_env("MY_APP_DB_NAME")
    ensure_database_exists(database)

    script_dir = Path(__file__).resolve().parent
    subprocess.run([sys.executable, str(script_dir / "run_migrations.py")], check=True)

    conn = _connect(database)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (username, display_name, password_hash, role, status, auth_source, hook_key, hook_key_created_at)
        VALUES (%s, %s, %s, 'admin', 'active', 'local', %s, NOW())
        ON CONFLICT (username) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            password_hash = EXCLUDED.password_hash,
            role = EXCLUDED.role,
            status = EXCLUDED.status,
            auth_source = EXCLUDED.auth_source,
            hook_key = COALESCE(users.hook_key, EXCLUDED.hook_key),
            hook_key_created_at = COALESCE(users.hook_key_created_at, EXCLUDED.hook_key_created_at)
        """,
        ("admin", "Admin", generate_password_hash(args.admin_password), secrets.token_hex(16)),
    )
    cursor.execute(
        """
        INSERT INTO system_settings (setting_key, setting_value)
        VALUES (%s, %s)
        ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value
        """,
        ("project_title", "TokenLeague"),
    )
    cursor.execute(
        """
        INSERT INTO system_settings (setting_key, setting_value)
        VALUES (%s, %s)
        ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value
        """,
        ("project_subtitle", "Rank users by token usage across agent runs"),
    )
    conn.commit()
    cursor.close()
    conn.close()

    print(f"Initialized database: {database}")


if __name__ == "__main__":
    main()
