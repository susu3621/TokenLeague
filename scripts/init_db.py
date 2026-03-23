#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from pathlib import Path

import mysql.connector
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
    return int(_required_env("MY_APP_DB_PORT") if os.getenv("MY_APP_DB_PORT") or os.getenv("MY_KMM_DB_PORT") else "3306")


def main():
    parser = argparse.ArgumentParser(description="Initialize the template project database")
    parser.add_argument("--admin-password", required=True, help="Initial admin password")
    args = parser.parse_args()

    host = _required_env("MY_APP_DB_HOST")
    port = _db_port()
    database = _required_env("MY_APP_DB_NAME")
    user = _required_env("MY_APP_DB_USER")
    password = _required_env("MY_APP_DB_PWD")

    conn = mysql.connector.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        charset="utf8mb4",
    )
    cursor = conn.cursor()
    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS `{database}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    cursor.close()
    conn.close()

    script_dir = Path(__file__).resolve().parent
    subprocess.run([sys.executable, str(script_dir / "run_migrations.py")], check=True)

    conn = mysql.connector.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        charset="utf8mb4",
    )
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (username, display_name, password_hash, role, status, hook_key, hook_key_created_at)
        VALUES (%s, %s, %s, 'admin', 'active', %s, NOW())
        ON DUPLICATE KEY UPDATE
            display_name = VALUES(display_name),
            password_hash = VALUES(password_hash),
            role = VALUES(role),
            status = VALUES(status),
            hook_key = COALESCE(users.hook_key, VALUES(hook_key)),
            hook_key_created_at = COALESCE(users.hook_key_created_at, VALUES(hook_key_created_at))
        """,
        ("admin", "Admin", generate_password_hash(args.admin_password), secrets.token_hex(16)),
    )
    cursor.execute(
        """
        INSERT INTO system_settings (setting_key, setting_value)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
        """,
        ("project_title", "TokenLeague"),
    )
    cursor.execute(
        """
        INSERT INTO system_settings (setting_key, setting_value)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)
        """,
        ("project_subtitle", "Rank users by token usage across agent runs"),
    )
    conn.commit()
    cursor.close()
    conn.close()

    print(f"Initialized database: {database}")


if __name__ == "__main__":
    main()
