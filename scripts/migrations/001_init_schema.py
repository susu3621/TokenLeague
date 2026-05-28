#!/usr/bin/env python3

from __future__ import annotations

import os
import secrets
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


def get_connection():
    return psycopg.connect(
        host=_required_env("MY_APP_DB_HOST"),
        port=_db_port(),
        dbname=_required_env("MY_APP_DB_NAME"),
        user=_required_env("MY_APP_DB_USER"),
        password=_required_env("MY_APP_DB_PWD"),
    )


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = %s
          AND column_name = %s
        """,
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def _add_column_if_missing(cursor, table_name: str, column_name: str, ddl: str) -> None:
    if _column_exists(cursor, table_name, column_name):
        return
    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def main():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(64) NOT NULL UNIQUE,
            display_name VARCHAR(128) NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(16) NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
            status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
            auth_source VARCHAR(16) NOT NULL DEFAULT 'local' CHECK (auth_source IN ('local', 'ldap')),
            ldap_dn VARCHAR(255) NULL,
            last_synced_at TIMESTAMP NULL,
            hook_key VARCHAR(64) NULL,
            hook_key_created_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uniq_users_hook_key ON users (hook_key)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS system_settings (
            id SERIAL PRIMARY KEY,
            setting_key VARCHAR(128) NOT NULL UNIQUE,
            setting_value TEXT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    _add_column_if_missing(cursor, "users", "display_name", "display_name VARCHAR(128) NULL")
    _add_column_if_missing(
        cursor,
        "users",
        "status",
        "status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled'))",
    )
    _add_column_if_missing(cursor, "users", "hook_key", "hook_key VARCHAR(64) NULL")
    _add_column_if_missing(
        cursor,
        "users",
        "hook_key_created_at",
        "hook_key_created_at TIMESTAMP NULL",
    )
    _add_column_if_missing(
        cursor,
        "users",
        "auth_source",
        "auth_source VARCHAR(16) NOT NULL DEFAULT 'local' CHECK (auth_source IN ('local', 'ldap'))",
    )
    _add_column_if_missing(cursor, "users", "ldap_dn", "ldap_dn VARCHAR(255) NULL")
    _add_column_if_missing(cursor, "users", "last_synced_at", "last_synced_at TIMESTAMP NULL")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_events (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            task_id VARCHAR(128) NOT NULL,
            external_event_id VARCHAR(128) NOT NULL,
            project_name VARCHAR(255) NOT NULL DEFAULT '',
            prompt_started_at TIMESTAMP NOT NULL,
            prompt_finished_at TIMESTAMP NOT NULL,
            input_token_count INTEGER NOT NULL DEFAULT 0,
            output_token_count INTEGER NOT NULL DEFAULT 0,
            cached_input_token_count INTEGER NOT NULL DEFAULT 0,
            total_token_count INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            agent_type VARCHAR(128) NOT NULL,
            agent_version VARCHAR(128) NOT NULL,
            model_name VARCHAR(128) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'completed',
            metadata_json JSONB NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uniq_prompt_event_user_external UNIQUE (user_id, external_event_id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prompt_finished_at ON prompt_events (prompt_finished_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prompt_agent ON prompt_events (agent_type, agent_version, model_name)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS task_runs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            task_id VARCHAR(128) NOT NULL,
            external_task_id VARCHAR(128) NOT NULL,
            project_name VARCHAR(255) NOT NULL DEFAULT '',
            started_at TIMESTAMP NOT NULL,
            finished_at TIMESTAMP NOT NULL,
            prompt_count INTEGER NOT NULL DEFAULT 0,
            input_token_count INTEGER NOT NULL DEFAULT 0,
            output_token_count INTEGER NOT NULL DEFAULT 0,
            cached_input_token_count INTEGER NOT NULL DEFAULT 0,
            total_token_count INTEGER NOT NULL DEFAULT 0,
            total_duration_ms INTEGER NOT NULL DEFAULT 0,
            agent_type VARCHAR(128) NOT NULL,
            agent_version VARCHAR(128) NOT NULL,
            model_name VARCHAR(128) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'completed',
            metadata_json JSONB NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uniq_task_run_user_external UNIQUE (user_id, external_task_id)
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_finished_at ON task_runs (finished_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_agent ON task_runs (agent_type, agent_version, model_name)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
            id SERIAL PRIMARY KEY,
            snapshot_key VARCHAR(128) NOT NULL UNIQUE,
            generated_at TIMESTAMP NULL,
            rows_json JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.commit()

    cursor.execute("SELECT id, hook_key FROM users WHERE username = 'admin' LIMIT 1")
    admin_row = cursor.fetchone()
    if admin_row and not admin_row[1]:
        cursor.execute(
            "UPDATE users SET hook_key = %s, hook_key_created_at = NOW() WHERE id = %s",
            (secrets.token_hex(16), admin_row[0]),
        )
        conn.commit()

    cursor.close()
    conn.close()
    print("Initialized base schema")


if __name__ == "__main__":
    main()
