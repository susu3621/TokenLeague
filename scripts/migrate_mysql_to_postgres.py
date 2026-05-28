#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sys
from typing import Any

import mysql.connector
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json


DB_ENV_ALIASES = {
    "MY_APP_DB_HOST": ("MY_APP_DB_HOST", "MY_KMM_DB_HOST"),
    "MY_APP_DB_NAME": ("MY_APP_DB_NAME", "MY_KMM_DB_NAME"),
    "MY_APP_DB_USER": ("MY_APP_DB_USER", "MY_KMM_DB_USER"),
    "MY_APP_DB_PWD": ("MY_APP_DB_PWD", "MY_KMM_DB_PWD"),
    "MY_APP_DB_PORT": ("MY_APP_DB_PORT", "MY_KMM_DB_PORT"),
}


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[str, ...]
    json_defaults: dict[str, Any]


TABLES = [
    TableSpec(
        "schema_migrations",
        ("id", "migration_name", "applied_at"),
        {},
    ),
    TableSpec(
        "users",
        (
            "id",
            "username",
            "display_name",
            "password_hash",
            "role",
            "status",
            "auth_source",
            "ldap_dn",
            "last_synced_at",
            "hook_key",
            "hook_key_created_at",
            "created_at",
            "updated_at",
        ),
        {},
    ),
    TableSpec(
        "system_settings",
        ("id", "setting_key", "setting_value", "updated_at"),
        {},
    ),
    TableSpec(
        "prompt_events",
        (
            "id",
            "user_id",
            "task_id",
            "external_event_id",
            "project_name",
            "prompt_started_at",
            "prompt_finished_at",
            "input_token_count",
            "output_token_count",
            "cached_input_token_count",
            "total_token_count",
            "duration_ms",
            "agent_type",
            "agent_version",
            "model_name",
            "status",
            "metadata_json",
            "created_at",
            "updated_at",
        ),
        {"metadata_json": {}},
    ),
    TableSpec(
        "task_runs",
        (
            "id",
            "user_id",
            "task_id",
            "external_task_id",
            "project_name",
            "started_at",
            "finished_at",
            "prompt_count",
            "input_token_count",
            "output_token_count",
            "cached_input_token_count",
            "total_token_count",
            "total_duration_ms",
            "agent_type",
            "agent_version",
            "model_name",
            "status",
            "metadata_json",
            "created_at",
            "updated_at",
        ),
        {"metadata_json": {}},
    ),
    TableSpec(
        "leaderboard_snapshots",
        ("id", "snapshot_key", "generated_at", "rows_json", "created_at", "updated_at"),
        {"rows_json": []},
    ),
]


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    print(f"Missing required environment variable: {name}", file=sys.stderr)
    sys.exit(1)


def _required_target_env(name: str) -> str:
    for candidate in DB_ENV_ALIASES.get(name, (name,)):
        value = os.getenv(candidate)
        if value:
            return value
    print(f"Missing required environment variable: {name}", file=sys.stderr)
    sys.exit(1)


def _target_db_port() -> int:
    return int(
        _required_target_env("MY_APP_DB_PORT")
        if os.getenv("MY_APP_DB_PORT") or os.getenv("MY_KMM_DB_PORT")
        else "5432"
    )


def _source_db_port() -> int:
    return int(os.getenv("MYSQL_SOURCE_PORT") or "3306")


def _decode_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value)


def get_mysql_connection():
    return mysql.connector.connect(
        host=_required_env("MYSQL_SOURCE_HOST"),
        port=_source_db_port(),
        database=_required_env("MYSQL_SOURCE_DB"),
        user=_required_env("MYSQL_SOURCE_USER"),
        password=_required_env("MYSQL_SOURCE_PWD"),
        charset="utf8mb4",
    )


def get_postgres_connection():
    return psycopg.connect(
        host=_required_target_env("MY_APP_DB_HOST"),
        port=_target_db_port(),
        dbname=_required_target_env("MY_APP_DB_NAME"),
        user=_required_target_env("MY_APP_DB_USER"),
        password=_required_target_env("MY_APP_DB_PWD"),
        row_factory=dict_row,
    )


def fetch_source_rows(source_cursor, table: TableSpec) -> list[dict[str, Any]]:
    column_sql = ", ".join(table.columns)
    source_cursor.execute(f"SELECT {column_sql} FROM {table.name} ORDER BY id")
    return list(source_cursor.fetchall())


def source_count(source_cursor, table_name: str) -> int:
    source_cursor.execute(f"SELECT COUNT(*) AS count FROM {table_name}")
    row = source_cursor.fetchone()
    return int(row["count"])


def target_count(target_cursor, table_name: str) -> int:
    target_cursor.execute(sql.SQL("SELECT COUNT(*) AS count FROM {}").format(sql.Identifier(table_name)))
    row = target_cursor.fetchone()
    return int(row["count"])


def truncate_target_tables(target_cursor) -> None:
    table_identifiers = [sql.Identifier(table.name) for table in TABLES]
    target_cursor.execute(
        sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY").format(sql.SQL(", ").join(table_identifiers))
    )


def postgres_values(table: TableSpec, row: dict[str, Any]) -> list[Any]:
    values: list[Any] = []
    for column in table.columns:
        value = row.get(column)
        if column in table.json_defaults:
            values.append(Json(_decode_json(value, table.json_defaults[column])))
        else:
            values.append(value)
    return values


def insert_rows(target_cursor, table: TableSpec, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = sql.SQL(", ").join(sql.Identifier(column) for column in table.columns)
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in table.columns)
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table.name),
        columns,
        placeholders,
    )
    for row in rows:
        target_cursor.execute(statement, postgres_values(table, row))


def reset_sequence(target_cursor, table_name: str) -> None:
    target_cursor.execute(
        sql.SQL(
            """
            SELECT setval(
                pg_get_serial_sequence(%s, 'id'),
                COALESCE((SELECT MAX(id) FROM {}), 1),
                (SELECT COUNT(*) > 0 FROM {})
            )
            """
        ).format(sql.Identifier(table_name), sql.Identifier(table_name)),
        (table_name,),
    )


def migrate() -> None:
    source_conn = get_mysql_connection()
    target_conn = get_postgres_connection()
    try:
        source_cursor = source_conn.cursor(dictionary=True)
        target_cursor = target_conn.cursor()

        expected_counts = {table.name: source_count(source_cursor, table.name) for table in TABLES}
        truncate_target_tables(target_cursor)

        for table in TABLES:
            rows = fetch_source_rows(source_cursor, table)
            insert_rows(target_cursor, table, rows)
            reset_sequence(target_cursor, table.name)

            imported_count = target_count(target_cursor, table.name)
            expected_count = expected_counts[table.name]
            print(f"{table.name}: source={expected_count} target={imported_count}")
            if imported_count != expected_count:
                raise RuntimeError(
                    f"Row count mismatch for {table.name}: source={expected_count}, target={imported_count}"
                )

        target_conn.commit()
        source_cursor.close()
        target_cursor.close()
    except Exception:
        target_conn.rollback()
        raise
    finally:
        source_conn.close()
        target_conn.close()


def main():
    migrate()
    print("MySQL to PostgreSQL migration complete")


if __name__ == "__main__":
    main()
