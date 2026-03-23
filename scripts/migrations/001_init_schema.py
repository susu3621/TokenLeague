#!/usr/bin/env python3

from __future__ import annotations

import os
import sys
import secrets

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


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
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
    return cursor.fetchone() is not None


def _index_exists(cursor, table_name: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        """,
        (table_name, index_name),
    )
    return cursor.fetchone() is not None


def _add_column_if_missing(cursor, table_name: str, column_name: str, ddl: str) -> None:
    if _column_exists(cursor, table_name, column_name):
        return
    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl}")


def _add_unique_key_if_missing(cursor, table_name: str, index_name: str, column_name: str) -> None:
    if _index_exists(cursor, table_name, index_name):
        return
    cursor.execute(f"ALTER TABLE {table_name} ADD UNIQUE KEY {index_name} ({column_name})")


def main():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(64) NOT NULL UNIQUE,
            display_name VARCHAR(128) NULL,
            password_hash VARCHAR(255) NOT NULL,
            role ENUM('admin', 'user') NOT NULL DEFAULT 'user',
            status ENUM('active', 'disabled') NOT NULL DEFAULT 'active',
            hook_key VARCHAR(64) NULL,
            hook_key_created_at DATETIME NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uniq_users_hook_key (hook_key)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS system_settings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            setting_key VARCHAR(128) NOT NULL UNIQUE,
            setting_value TEXT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    _add_column_if_missing(cursor, "users", "display_name", "display_name VARCHAR(128) NULL AFTER username")
    _add_column_if_missing(
        cursor,
        "users",
        "status",
        "status ENUM('active', 'disabled') NOT NULL DEFAULT 'active' AFTER role",
    )
    _add_column_if_missing(cursor, "users", "hook_key", "hook_key VARCHAR(64) NULL AFTER status")
    _add_column_if_missing(
        cursor,
        "users",
        "hook_key_created_at",
        "hook_key_created_at DATETIME NULL AFTER hook_key",
    )
    _add_unique_key_if_missing(cursor, "users", "uniq_users_hook_key", "hook_key")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_events (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            task_id VARCHAR(128) NOT NULL,
            external_event_id VARCHAR(128) NOT NULL,
            project_name VARCHAR(255) NOT NULL DEFAULT '',
            prompt_started_at DATETIME NOT NULL,
            prompt_finished_at DATETIME NOT NULL,
            input_token_count INT NOT NULL DEFAULT 0,
            output_token_count INT NOT NULL DEFAULT 0,
            total_token_count INT NOT NULL DEFAULT 0,
            duration_ms INT NOT NULL DEFAULT 0,
            agent_type VARCHAR(128) NOT NULL,
            agent_version VARCHAR(128) NOT NULL,
            model_name VARCHAR(128) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'completed',
            metadata_json JSON NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uniq_prompt_event_user_external (user_id, external_event_id),
            KEY idx_prompt_finished_at (prompt_finished_at),
            KEY idx_prompt_agent (agent_type, agent_version, model_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS task_runs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            task_id VARCHAR(128) NOT NULL,
            external_task_id VARCHAR(128) NOT NULL,
            project_name VARCHAR(255) NOT NULL DEFAULT '',
            started_at DATETIME NOT NULL,
            finished_at DATETIME NOT NULL,
            prompt_count INT NOT NULL DEFAULT 0,
            input_token_count INT NOT NULL DEFAULT 0,
            output_token_count INT NOT NULL DEFAULT 0,
            total_token_count INT NOT NULL DEFAULT 0,
            total_duration_ms INT NOT NULL DEFAULT 0,
            agent_type VARCHAR(128) NOT NULL,
            agent_version VARCHAR(128) NOT NULL,
            model_name VARCHAR(128) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'completed',
            metadata_json JSON NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uniq_task_run_user_external (user_id, external_task_id),
            KEY idx_task_finished_at (finished_at),
            KEY idx_task_agent (agent_type, agent_version, model_name)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
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
