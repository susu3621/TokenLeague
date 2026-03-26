from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import os
import secrets
from typing import Any

import mysql.connector
from werkzeug.security import generate_password_hash


UTC = timezone.utc
USER_ACTIVE = "active"
USER_DISABLED = "disabled"
DEFAULT_PROJECT_TITLE = "TokenLeague"
DEFAULT_PROJECT_SUBTITLE = "Rank users by token usage across agent runs"
DB_ENV_ALIASES = {
    "MY_APP_DB_HOST": ("MY_APP_DB_HOST", "MY_KMM_DB_HOST"),
    "MY_APP_DB_NAME": ("MY_APP_DB_NAME", "MY_KMM_DB_NAME"),
    "MY_APP_DB_USER": ("MY_APP_DB_USER", "MY_KMM_DB_USER"),
    "MY_APP_DB_PWD": ("MY_APP_DB_PWD", "MY_KMM_DB_PWD"),
    "MY_APP_DB_PORT": ("MY_APP_DB_PORT", "MY_KMM_DB_PORT"),
}


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def use_in_memory_store() -> bool:
    return _is_truthy(os.getenv("MY_TEMPLATE_USE_IN_MEMORY_STORE"))


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _generate_hook_key() -> str:
    return secrets.token_hex(16)


def _to_storage_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _to_storage_datetime(value).isoformat()


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _to_storage_datetime(value)
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    return _to_storage_datetime(parsed)


def _normalize_metadata(metadata: Any) -> dict[str, Any]:
    if isinstance(metadata, dict):
        return metadata
    return {}


def _normalize_project_name(value: Any) -> str:
    return str(value or "").strip()


def _non_negative_duration_ms(started_at: datetime | None, finished_at: datetime | None) -> int:
    if not started_at or not finished_at:
        return 0
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


def _normalize_datetime_fields(record: dict[str, Any], *fields: str) -> dict[str, Any]:
    for field in fields:
        record[field] = _parse_datetime(record.get(field))
    return record


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "role": user["role"],
        "status": user.get("status", USER_ACTIVE),
        "hook_key": user.get("hook_key"),
        "hook_key_created_at": _serialize_datetime(user.get("hook_key_created_at")),
        "created_at": _serialize_datetime(user.get("created_at")),
        "updated_at": _serialize_datetime(user.get("updated_at")),
    }


def _full_user(user: dict[str, Any]) -> dict[str, Any]:
    data = _public_user(user)
    data["password_hash"] = user["password_hash"]
    return data


def _build_default_users() -> list[dict[str, Any]]:
    now = _utcnow()
    return [
        {
            "id": 1,
            "username": "admin",
            "display_name": "Admin",
            "password_hash": generate_password_hash("admin123"),
            "role": "admin",
            "status": USER_ACTIVE,
            "hook_key": _generate_hook_key(),
            "hook_key_created_at": now,
            "created_at": now,
            "updated_at": now,
        }
    ]


_memory_users: list[dict[str, Any]] = []
_memory_settings: dict[str, str] = {}
_memory_prompt_events: list[dict[str, Any]] = []
_memory_task_runs: list[dict[str, Any]] = []


def reset_in_memory_state() -> None:
    global _memory_users, _memory_settings, _memory_prompt_events, _memory_task_runs
    _memory_users = [dict(user) for user in _build_default_users()]
    _memory_settings = {
        "project_title": DEFAULT_PROJECT_TITLE,
        "project_subtitle": DEFAULT_PROJECT_SUBTITLE,
    }
    _memory_prompt_events = []
    _memory_task_runs = []


reset_in_memory_state()


def _required_env(name: str) -> str:
    for candidate in DB_ENV_ALIASES.get(name, (name,)):
        value = os.getenv(candidate)
        if value:
            return value
    raise RuntimeError(f"Missing required environment variable: {name}")


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


def _find_memory_user(predicate):
    for user in _memory_users:
        if predicate(user):
            return user
    return None


def get_user_by_id(user_id: int | None):
    if not user_id:
        return None

    if use_in_memory_store():
        user = _find_memory_user(lambda item: item["id"] == user_id)
        return _full_user(user) if user else None

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT id, username, display_name, password_hash, role, status, hook_key,
               hook_key_created_at, created_at, updated_at
        FROM users WHERE id = %s
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_user_by_username(username: str):
    if use_in_memory_store():
        user = _find_memory_user(lambda item: item["username"] == username)
        return _full_user(user) if user else None

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT id, username, display_name, password_hash, role, status, hook_key,
               hook_key_created_at, created_at, updated_at
        FROM users WHERE username = %s
        """,
        (username,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_user_by_hook_key(hook_key: str | None):
    if not hook_key:
        return None

    if use_in_memory_store():
        user = _find_memory_user(
            lambda item: item.get("hook_key") == hook_key and item.get("status") == USER_ACTIVE
        )
        return _full_user(user) if user else None

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT id, username, display_name, password_hash, role, status, hook_key,
               hook_key_created_at, created_at, updated_at
        FROM users WHERE hook_key = %s AND status = %s
        """,
        (hook_key, USER_ACTIVE),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def get_all_users() -> list[dict[str, Any]]:
    if use_in_memory_store():
        return [_public_user(user) for user in sorted(_memory_users, key=lambda item: item["id"])]

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT id, username, display_name, role, status, hook_key, hook_key_created_at,
               created_at, updated_at
        FROM users ORDER BY id ASC
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def create_user(
    username: str,
    password: str,
    *,
    display_name: str | None = None,
    role: str = "user",
    status: str = USER_ACTIVE,
):
    now = _utcnow()
    password_hash = generate_password_hash(password)
    hook_key = _generate_hook_key()
    display_name = (display_name or username).strip()

    if use_in_memory_store():
        if _find_memory_user(lambda item: item["username"] == username):
            raise ValueError("Username already exists")
        user = {
            "id": max((user["id"] for user in _memory_users), default=0) + 1,
            "username": username,
            "display_name": display_name,
            "password_hash": password_hash,
            "role": role,
            "status": status,
            "hook_key": hook_key,
            "hook_key_created_at": now,
            "created_at": now,
            "updated_at": now,
        }
        _memory_users.append(user)
        return _full_user(user)

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        INSERT INTO users (
            username, display_name, password_hash, role, status, hook_key,
            hook_key_created_at, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (username, display_name, password_hash, role, status, hook_key,
         now.replace(tzinfo=None), now.replace(tzinfo=None), now.replace(tzinfo=None)),
    )
    conn.commit()
    user_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return get_user_by_id(user_id)


def update_user_password(user_id: int, new_password: str) -> None:
    password_hash = generate_password_hash(new_password)
    now = _utcnow()

    if use_in_memory_store():
        user = _find_memory_user(lambda item: item["id"] == user_id)
        if not user:
            raise ValueError("User not found")
        user["password_hash"] = password_hash
        user["updated_at"] = now
        return

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET password_hash = %s, updated_at = %s WHERE id = %s",
        (password_hash, now.replace(tzinfo=None), user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def rotate_user_hook_key(user_id: int) -> str:
    new_key = _generate_hook_key()
    now = _utcnow()

    if use_in_memory_store():
        user = _find_memory_user(lambda item: item["id"] == user_id)
        if not user:
            raise ValueError("User not found")
        user["hook_key"] = new_key
        user["hook_key_created_at"] = now
        user["updated_at"] = now
        return new_key

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE users
        SET hook_key = %s, hook_key_created_at = %s
        WHERE id = %s
        """,
        (new_key, now.replace(tzinfo=None), user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return new_key


def set_user_status(user_id: int, status: str) -> None:
    if status not in {USER_ACTIVE, USER_DISABLED}:
        raise ValueError("Invalid status")

    now = _utcnow()

    if use_in_memory_store():
        user = _find_memory_user(lambda item: item["id"] == user_id)
        if not user:
            raise ValueError("User not found")
        user["status"] = status
        user["updated_at"] = now
        return

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET status = %s, updated_at = %s WHERE id = %s",
        (status, now.replace(tzinfo=None), user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_setting(key: str):
    if use_in_memory_store():
        return _memory_settings.get(key)

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT setting_value FROM system_settings WHERE setting_key = %s",
        (key,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row["setting_value"] if row else None


def set_setting(key: str, value: str) -> None:
    if use_in_memory_store():
        _memory_settings[key] = value
        return

    now = _utcnow()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO system_settings (setting_key, setting_value, updated_at)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value), updated_at = VALUES(updated_at)
        """,
        (key, value, now.replace(tzinfo=None)),
    )
    conn.commit()
    cursor.close()
    conn.close()


def _normalize_prompt_event(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    started_at = _parse_datetime(payload.get("prompt_started_at"))
    finished_at = _parse_datetime(payload.get("prompt_finished_at"))
    input_token_count = int(payload.get("input_token_count") or 0)
    output_token_count = int(payload.get("output_token_count") or 0)
    cached_input_token_count = int(payload.get("cached_input_token_count") or 0)
    duration_ms = int(
        payload.get("duration_ms")
        or _non_negative_duration_ms(started_at, finished_at)
    )
    return {
        "user_id": user_id,
        "task_id": (payload.get("task_id") or "").strip(),
        "external_event_id": (payload.get("external_event_id") or "").strip(),
        "project_name": _normalize_project_name(payload.get("project_name")),
        "prompt_started_at": started_at,
        "prompt_finished_at": finished_at,
        "input_token_count": input_token_count,
        "output_token_count": output_token_count,
        "cached_input_token_count": cached_input_token_count,
        "total_token_count": input_token_count + output_token_count + cached_input_token_count,
        "duration_ms": duration_ms,
        "agent_type": (payload.get("agent_type") or "").strip(),
        "agent_version": (payload.get("agent_version") or "").strip(),
        "model_name": (payload.get("model_name") or "").strip(),
        "status": (payload.get("status") or "completed").strip(),
        "metadata": _normalize_metadata(payload.get("metadata")),
        "updated_at": _utcnow(),
    }


def _normalize_task_run(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    started_at = _parse_datetime(payload.get("started_at"))
    finished_at = _parse_datetime(payload.get("finished_at"))
    input_token_count = int(payload.get("input_token_count") or 0)
    output_token_count = int(payload.get("output_token_count") or 0)
    cached_input_token_count = int(payload.get("cached_input_token_count") or 0)
    total_duration_ms = int(
        payload.get("total_duration_ms")
        or _non_negative_duration_ms(started_at, finished_at)
    )
    return {
        "user_id": user_id,
        "task_id": (payload.get("task_id") or payload.get("external_task_id") or "").strip(),
        "external_task_id": (payload.get("external_task_id") or "").strip(),
        "project_name": _normalize_project_name(payload.get("project_name")),
        "started_at": started_at,
        "finished_at": finished_at,
        "prompt_count": int(payload.get("prompt_count") or 0),
        "input_token_count": input_token_count,
        "output_token_count": output_token_count,
        "cached_input_token_count": cached_input_token_count,
        "total_token_count": input_token_count + output_token_count + cached_input_token_count,
        "total_duration_ms": total_duration_ms,
        "agent_type": (payload.get("agent_type") or "").strip(),
        "agent_version": (payload.get("agent_version") or "").strip(),
        "model_name": (payload.get("model_name") or "").strip(),
        "status": (payload.get("status") or "completed").strip(),
        "metadata": _normalize_metadata(payload.get("metadata")),
        "updated_at": _utcnow(),
    }


def upsert_prompt_event(user_id: int, payload: dict[str, Any]):
    event = _normalize_prompt_event(user_id, payload)
    now = _utcnow()

    if use_in_memory_store():
        for index, existing in enumerate(_memory_prompt_events):
            if (
                existing["user_id"] == user_id
                and existing["external_event_id"] == event["external_event_id"]
            ):
                event["created_at"] = existing["created_at"]
                event["updated_at"] = now
                _memory_prompt_events[index] = {**existing, **event}
                return dict(_memory_prompt_events[index])
        event["created_at"] = now
        event["updated_at"] = now
        _memory_prompt_events.append(event)
        return dict(event)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO prompt_events (
            user_id, task_id, external_event_id, project_name, prompt_started_at, prompt_finished_at,
            input_token_count, output_token_count, cached_input_token_count, total_token_count, duration_ms,
            agent_type, agent_version, model_name, status, metadata_json, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            task_id = VALUES(task_id),
            project_name = VALUES(project_name),
            prompt_started_at = VALUES(prompt_started_at),
            prompt_finished_at = VALUES(prompt_finished_at),
            input_token_count = VALUES(input_token_count),
            output_token_count = VALUES(output_token_count),
            cached_input_token_count = VALUES(cached_input_token_count),
            total_token_count = VALUES(total_token_count),
            duration_ms = VALUES(duration_ms),
            agent_type = VALUES(agent_type),
            agent_version = VALUES(agent_version),
            model_name = VALUES(model_name),
            status = VALUES(status),
            metadata_json = VALUES(metadata_json),
            updated_at = VALUES(updated_at)
        """,
        (
            user_id,
            event["task_id"],
            event["external_event_id"],
            event["project_name"],
            event["prompt_started_at"].replace(tzinfo=None) if event["prompt_started_at"] else None,
            event["prompt_finished_at"].replace(tzinfo=None) if event["prompt_finished_at"] else None,
            event["input_token_count"],
            event["output_token_count"],
            event["cached_input_token_count"],
            event["total_token_count"],
            event["duration_ms"],
            event["agent_type"],
            event["agent_version"],
            event["model_name"],
            event["status"],
            json.dumps(event["metadata"]),
            now.replace(tzinfo=None),
            now.replace(tzinfo=None),
        ),
    )
    conn.commit()
    cursor.close()
    conn.close()
    event["created_at"] = now
    return event


def upsert_task_run(user_id: int, payload: dict[str, Any]):
    task_run = _normalize_task_run(user_id, payload)
    now = _utcnow()

    if use_in_memory_store():
        for index, existing in enumerate(_memory_task_runs):
            if (
                existing["user_id"] == user_id
                and existing["external_task_id"] == task_run["external_task_id"]
            ):
                task_run["created_at"] = existing["created_at"]
                task_run["updated_at"] = now
                _memory_task_runs[index] = {**existing, **task_run}
                return dict(_memory_task_runs[index])
        task_run["created_at"] = now
        task_run["updated_at"] = now
        _memory_task_runs.append(task_run)
        return dict(task_run)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO task_runs (
            user_id, task_id, external_task_id, project_name, started_at, finished_at, prompt_count,
            input_token_count, output_token_count, cached_input_token_count, total_token_count, total_duration_ms,
            agent_type, agent_version, model_name, status, metadata_json, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            task_id = VALUES(task_id),
            project_name = VALUES(project_name),
            started_at = VALUES(started_at),
            finished_at = VALUES(finished_at),
            prompt_count = VALUES(prompt_count),
            input_token_count = VALUES(input_token_count),
            output_token_count = VALUES(output_token_count),
            cached_input_token_count = VALUES(cached_input_token_count),
            total_token_count = VALUES(total_token_count),
            total_duration_ms = VALUES(total_duration_ms),
            agent_type = VALUES(agent_type),
            agent_version = VALUES(agent_version),
            model_name = VALUES(model_name),
            status = VALUES(status),
            metadata_json = VALUES(metadata_json),
            updated_at = VALUES(updated_at)
        """,
        (
            user_id,
            task_run["task_id"],
            task_run["external_task_id"],
            task_run["project_name"],
            task_run["started_at"].replace(tzinfo=None) if task_run["started_at"] else None,
            task_run["finished_at"].replace(tzinfo=None) if task_run["finished_at"] else None,
            task_run["prompt_count"],
            task_run["input_token_count"],
            task_run["output_token_count"],
            task_run["cached_input_token_count"],
            task_run["total_token_count"],
            task_run["total_duration_ms"],
            task_run["agent_type"],
            task_run["agent_version"],
            task_run["model_name"],
            task_run["status"],
            json.dumps(task_run["metadata"]),
            now.replace(tzinfo=None),
            now.replace(tzinfo=None),
        ),
    )
    conn.commit()
    cursor.close()
    conn.close()
    task_run["created_at"] = now
    return task_run


def _record_matches_filters(record: dict[str, Any], filters: dict[str, str]) -> bool:
    for field in ("agent_type", "agent_version", "model_name"):
        expected = (filters.get(field) or "").strip()
        if expected and record.get(field) != expected:
            return False
    return True


def _within_window(event_time: datetime | None, window: str, now: datetime) -> bool:
    if event_time is None:
        return False
    event_time = _to_storage_datetime(event_time)
    if window == "all":
        return True
    if window in {"day", "today"}:
        start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return event_time >= start
    if window == "week":
        return event_time >= now.astimezone(UTC) - timedelta(days=7)
    if window == "month":
        return event_time >= now.astimezone(UTC) - timedelta(days=30)
    raise ValueError("Unsupported window")


def _prompt_event_time(event: dict[str, Any]) -> datetime | None:
    return _parse_datetime(event.get("prompt_finished_at") or event.get("prompt_started_at"))


def _task_run_time(task_run: dict[str, Any]) -> datetime | None:
    return _parse_datetime(task_run.get("finished_at") or task_run.get("started_at"))


def _build_leaderboard_rows(
    prompt_events: list[dict[str, Any]],
    task_runs: list[dict[str, Any]],
    window: str,
    filters: dict[str, str],
):
    now = _utcnow()
    rows: dict[int, dict[str, Any]] = {}

    for event in prompt_events:
        event_time = _prompt_event_time(event)
        if not _within_window(event_time, window, now):
            continue
        if not _record_matches_filters(event, filters):
            continue
        user = get_user_by_id(event["user_id"])
        if not user or user["status"] != USER_ACTIVE:
            continue
        row = rows.setdefault(
            user["id"],
            {
                "user_id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
                "total_token_count": 0,
                "prompt_count": 0,
                "task_count": 0,
                "total_duration_ms": 0,
                "last_active_at": None,
            },
        )
        row["total_token_count"] += event["total_token_count"]
        row["prompt_count"] += 1
        row["total_duration_ms"] += event["duration_ms"]
        if not row["last_active_at"] or event_time > _parse_datetime(row["last_active_at"]):
            row["last_active_at"] = _serialize_datetime(event_time)

    task_counts = defaultdict(int)
    for task_run in task_runs:
        task_time = _task_run_time(task_run)
        if not _within_window(task_time, window, now):
            continue
        if not _record_matches_filters(task_run, filters):
            continue
        task_counts[task_run["user_id"]] += 1

    for user_id, count in task_counts.items():
        if user_id in rows:
            rows[user_id]["task_count"] = count

    ordered_rows = list(rows.values())
    ordered_rows.sort(
        key=lambda item: (
            -item["total_token_count"],
            -item["prompt_count"],
            item["username"],
        )
    )
    for index, row in enumerate(ordered_rows, start=1):
        row["rank"] = index
        row["avg_token_per_prompt"] = (
            row["total_token_count"] / row["prompt_count"] if row["prompt_count"] else 0
        )
    return ordered_rows


def _fetch_prompt_events_from_db() -> list[dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT user_id, task_id, external_event_id, prompt_started_at, prompt_finished_at,
               input_token_count, output_token_count, total_token_count, duration_ms, project_name,
               agent_type, agent_version, model_name, status, metadata_json
        FROM prompt_events
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    for row in rows:
        _normalize_datetime_fields(row, "prompt_started_at", "prompt_finished_at")
        row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
    return rows


def _fetch_task_runs_from_db() -> list[dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT user_id, task_id, external_task_id, started_at, finished_at, prompt_count,
               input_token_count, output_token_count, total_token_count, total_duration_ms, project_name,
               agent_type, agent_version, model_name, status, metadata_json
        FROM task_runs
        """
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    for row in rows:
        _normalize_datetime_fields(row, "started_at", "finished_at")
        row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
    return rows


def get_leaderboard(window: str = "all", filters: dict[str, str] | None = None):
    filters = filters or {}
    if use_in_memory_store():
        return _build_leaderboard_rows(_memory_prompt_events, _memory_task_runs, window, filters)

    return _build_leaderboard_rows(
        _fetch_prompt_events_from_db(),
        _fetch_task_runs_from_db(),
        window,
        filters,
    )


def get_user_stats(user_id: int, window: str = "all", filters: dict[str, str] | None = None):
    filters = filters or {}
    now = _utcnow()
    user = get_user_by_id(user_id)
    if not user:
        return None

    if use_in_memory_store():
        prompt_events = list(_memory_prompt_events)
        task_runs = list(_memory_task_runs)
    else:
        prompt_events = _fetch_prompt_events_from_db()
        task_runs = _fetch_task_runs_from_db()

    matching_events = [
        event
        for event in prompt_events
        if event["user_id"] == user_id
        and _within_window(_prompt_event_time(event), window, now)
        and _record_matches_filters(event, filters)
    ]
    matching_tasks = [
        task_run
        for task_run in task_runs
        if task_run["user_id"] == user_id
        and _within_window(_task_run_time(task_run), window, now)
        and _record_matches_filters(task_run, filters)
    ]

    total_token_count = sum(event["total_token_count"] for event in matching_events)
    prompt_count = len(matching_events)
    task_count = len(matching_tasks)
    total_duration_ms = sum(event["duration_ms"] for event in matching_events)
    last_active = max((_prompt_event_time(event) for event in matching_events), default=None)

    agent_groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in matching_events:
        key = (event["agent_type"], event["agent_version"], event["model_name"])
        group = agent_groups.setdefault(
            key,
            {
                "agent_type": event["agent_type"],
                "agent_version": event["agent_version"],
                "model_name": event["model_name"],
                "total_token_count": 0,
                "prompt_count": 0,
                "task_count": 0,
            },
        )
        group["total_token_count"] += event["total_token_count"]
        group["prompt_count"] += 1
    for task_run in matching_tasks:
        key = (task_run["agent_type"], task_run["agent_version"], task_run["model_name"])
        group = agent_groups.setdefault(
            key,
            {
                "agent_type": task_run["agent_type"],
                "agent_version": task_run["agent_version"],
                "model_name": task_run["model_name"],
                "total_token_count": 0,
                "prompt_count": 0,
                "task_count": 0,
            },
        )
        group["task_count"] += 1

    agent_breakdown = list(agent_groups.values())
    agent_breakdown.sort(
        key=lambda item: (-item["total_token_count"], -item["prompt_count"], item["agent_type"])
    )

    recent_prompt_events = sorted(
        matching_events,
        key=lambda item: _prompt_event_time(item) or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )[:20]
    recent_task_runs = sorted(
        matching_tasks,
        key=lambda item: _task_run_time(item) or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )[:20]

    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
            "status": user["status"],
        },
        "summary": {
            "total_token_count": total_token_count,
            "prompt_count": prompt_count,
            "task_count": task_count,
            "total_duration_ms": total_duration_ms,
            "last_active_at": _serialize_datetime(last_active),
            "avg_token_per_prompt": total_token_count / prompt_count if prompt_count else 0,
        },
        "agent_breakdown": agent_breakdown,
        "recent_prompt_events": [
            {
                "external_event_id": event["external_event_id"],
                "task_id": event["task_id"],
                "total_token_count": event["total_token_count"],
                "input_token_count": event["input_token_count"],
                "output_token_count": event["output_token_count"],
                "duration_ms": event["duration_ms"],
                "project_name": event["project_name"],
                "agent_type": event["agent_type"],
                "agent_version": event["agent_version"],
                "model_name": event["model_name"],
                "status": event["status"],
                "prompt_finished_at": _serialize_datetime(_prompt_event_time(event)),
            }
            for event in recent_prompt_events
        ],
        "recent_task_runs": [
            {
                "external_task_id": task_run["external_task_id"],
                "task_id": task_run["task_id"],
                "total_token_count": task_run["total_token_count"],
                "prompt_count": task_run["prompt_count"],
                "total_duration_ms": task_run["total_duration_ms"],
                "project_name": task_run["project_name"],
                "agent_type": task_run["agent_type"],
                "agent_version": task_run["agent_version"],
                "model_name": task_run["model_name"],
                "status": task_run["status"],
                "finished_at": _serialize_datetime(_task_run_time(task_run)),
            }
            for task_run in recent_task_runs
        ],
    }


def list_agent_catalog() -> list[dict[str, Any]]:
    if use_in_memory_store():
        prompt_events = list(_memory_prompt_events)
        task_runs = list(_memory_task_runs)
    else:
        prompt_events = _fetch_prompt_events_from_db()
        task_runs = _fetch_task_runs_from_db()

    catalog: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in [*prompt_events, *task_runs]:
        key = (record["agent_type"], record["agent_version"], record["model_name"])
        if key not in catalog:
            catalog[key] = {
                "agent_type": record["agent_type"],
                "agent_version": record["agent_version"],
                "model_name": record["model_name"],
                "prompt_event_count": 0,
                "task_run_count": 0,
            }
        if "external_event_id" in record:
            catalog[key]["prompt_event_count"] += 1
        else:
            catalog[key]["task_run_count"] += 1
    rows = list(catalog.values())
    rows.sort(key=lambda item: (item["agent_type"], item["agent_version"], item["model_name"]))
    return rows


def get_user_project_breakdown(
    user_id: int,
    window: str = "all",
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Get user token statistics grouped by project."""
    now = _utcnow()
    filters = filters or {}

    if use_in_memory_store():
        prompt_events = list(_memory_prompt_events)
        task_runs = list(_memory_task_runs)
    else:
        prompt_events = _fetch_prompt_events_from_db()
        task_runs = _fetch_task_runs_from_db()

    matching_events = [
        event
        for event in prompt_events
        if event["user_id"] == user_id
        and _within_window(_prompt_event_time(event), window, now)
        and _record_matches_filters(event, filters)
    ]

    task_counts: dict[str, int] = defaultdict(int)
    for task_run in task_runs:
        if task_run["user_id"] != user_id:
            continue
        if not _within_window(_task_run_time(task_run), window, now):
            continue
        if not _record_matches_filters(task_run, filters):
            continue
        project = task_run.get("project_name") or ""
        task_counts[project] += 1

    project_groups: dict[str, dict[str, Any]] = {}
    for event in matching_events:
        project = event.get("project_name") or ""
        group = project_groups.setdefault(
            project,
            {
                "project_name": project or "(unknown)",
                "total_token_count": 0,
                "input_token_count": 0,
                "output_token_count": 0,
                "prompt_count": 0,
                "task_count": 0,
            },
        )
        group["total_token_count"] += event["total_token_count"]
        group["input_token_count"] += event["input_token_count"]
        group["output_token_count"] += event["output_token_count"]
        group["prompt_count"] += 1

    for project, count in task_counts.items():
        if project in project_groups:
            project_groups[project]["task_count"] = count
        else:
            project_groups[project] = {
                "project_name": project or "(unknown)",
                "total_token_count": 0,
                "input_token_count": 0,
                "output_token_count": 0,
                "prompt_count": 0,
                "task_count": count,
            }

    result = list(project_groups.values())
    result.sort(key=lambda item: (-item["total_token_count"], item["project_name"]))
    return result


def get_user_model_breakdown(
    user_id: int,
    window: str = "all",
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Get user token statistics grouped by model."""
    now = _utcnow()
    filters = filters or {}

    if use_in_memory_store():
        prompt_events = list(_memory_prompt_events)
        task_runs = list(_memory_task_runs)
    else:
        prompt_events = _fetch_prompt_events_from_db()
        task_runs = _fetch_task_runs_from_db()

    matching_events = [
        event
        for event in prompt_events
        if event["user_id"] == user_id
        and _within_window(_prompt_event_time(event), window, now)
        and _record_matches_filters(event, filters)
    ]

    task_counts: dict[str, int] = defaultdict(int)
    for task_run in task_runs:
        if task_run["user_id"] != user_id:
            continue
        if not _within_window(_task_run_time(task_run), window, now):
            continue
        if not _record_matches_filters(task_run, filters):
            continue
        model = task_run.get("model_name") or ""
        task_counts[model] += 1

    model_groups: dict[str, dict[str, Any]] = {}
    for event in matching_events:
        model = event.get("model_name") or ""
        group = model_groups.setdefault(
            model,
            {
                "model_name": model or "(unknown)",
                "total_token_count": 0,
                "input_token_count": 0,
                "output_token_count": 0,
                "prompt_count": 0,
                "task_count": 0,
            },
        )
        group["total_token_count"] += event["total_token_count"]
        group["input_token_count"] += event["input_token_count"]
        group["output_token_count"] += event["output_token_count"]
        group["prompt_count"] += 1

    for model, count in task_counts.items():
        if model in model_groups:
            model_groups[model]["task_count"] = count
        else:
            model_groups[model] = {
                "model_name": model or "(unknown)",
                "total_token_count": 0,
                "input_token_count": 0,
                "output_token_count": 0,
                "prompt_count": 0,
                "task_count": count,
            }

    result = list(model_groups.values())
    result.sort(key=lambda item: (-item["total_token_count"], item["model_name"]))
    return result


def get_user_time_series(
    user_id: int,
    window: str = "all",
    granularity: str = "hour",
    filters: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Get user token usage timeline grouped by time bucket."""
    now = _utcnow()
    filters = filters or {}

    if granularity not in ("hour", "day", "week"):
        granularity = "hour"

    if use_in_memory_store():
        prompt_events = list(_memory_prompt_events)
    else:
        prompt_events = _fetch_prompt_events_from_db()

    daily_bucket_range: tuple[date, date] | None = None
    if granularity == "day" and window in ("week", "month"):
        end_date = now.astimezone(UTC).date()
        day_count = 7 if window == "week" else 30
        start_date = end_date - timedelta(days=day_count - 1)
        daily_bucket_range = (start_date, end_date)

    hourly_bucket_range: tuple[datetime, datetime] | None = None
    if window == "today":
        end_time = now.astimezone(UTC)
        start_time = end_time.replace(hour=0, minute=0, second=0, microsecond=0)
        hourly_bucket_range = (start_time, end_time)

    matching_events = []
    for event in prompt_events:
        if event["user_id"] != user_id:
            continue
        if not _record_matches_filters(event, filters):
            continue
        event_time = _prompt_event_time(event)
        if hourly_bucket_range is not None:
            if event_time is None:
                continue
            event_dt = _to_storage_datetime(event_time)
            if hourly_bucket_range[0] <= event_dt <= hourly_bucket_range[1]:
                matching_events.append(event)
            continue
        if daily_bucket_range is not None:
            if event_time is None:
                continue
            event_date = _to_storage_datetime(event_time).date()
            if daily_bucket_range[0] <= event_date <= daily_bucket_range[1]:
                matching_events.append(event)
            continue
        if _within_window(event_time, window, now):
            matching_events.append(event)

    def _bucket_key(event_time: datetime | None) -> str:
        if event_time is None:
            return "unknown"
        if granularity == "hour":
            return event_time.strftime("%Y-%m-%d %H:00")
        elif granularity == "day":
            return event_time.strftime("%Y-%m-%d")
        else:  # week
            iso = event_time.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"

    time_buckets: dict[str, dict[str, Any]] = {}
    for event in matching_events:
        event_time = _prompt_event_time(event)
        bucket = _bucket_key(event_time)
        group = time_buckets.setdefault(
            bucket,
            {
                "time_bucket": bucket,
                "total_token_count": 0,
                "input_token_count": 0,
                "output_token_count": 0,
                "prompt_count": 0,
                "project_breakdown": [],
                "_project_totals": {},
            },
        )
        group["total_token_count"] += event["total_token_count"]
        group["input_token_count"] += event["input_token_count"]
        group["output_token_count"] += event["output_token_count"]
        group["prompt_count"] += 1
        project_name = (event.get("project_name") or "").strip() or "(unknown)"
        project_totals = group["_project_totals"]
        project_totals[project_name] = project_totals.get(project_name, 0) + event["total_token_count"]

    result = list(time_buckets.values())
    if daily_bucket_range is not None:
        current_date = daily_bucket_range[0]
        while current_date <= daily_bucket_range[1]:
            bucket = current_date.strftime("%Y-%m-%d")
            time_buckets.setdefault(
                bucket,
                {
                    "time_bucket": bucket,
                    "total_token_count": 0,
                    "input_token_count": 0,
                    "output_token_count": 0,
                    "prompt_count": 0,
                    "project_breakdown": [],
                    "_project_totals": {},
                },
            )
            current_date += timedelta(days=1)
        result = list(time_buckets.values())

    if hourly_bucket_range is not None:
        current_hour = hourly_bucket_range[0]
        while current_hour <= hourly_bucket_range[1]:
            bucket = current_hour.strftime("%Y-%m-%d %H:00")
            time_buckets.setdefault(
                bucket,
                {
                    "time_bucket": bucket,
                    "total_token_count": 0,
                    "input_token_count": 0,
                    "output_token_count": 0,
                    "prompt_count": 0,
                    "project_breakdown": [],
                    "_project_totals": {},
                },
            )
            current_hour += timedelta(hours=1)
        result = list(time_buckets.values())

    for item in result:
        project_totals = item.pop("_project_totals", {})
        item["project_breakdown"] = [
            {
                "project_name": project_name,
                "total_token_count": total_token_count,
            }
            for project_name, total_token_count in sorted(
                project_totals.items(),
                key=lambda project: (-project[1], project[0]),
            )
        ]
    result.sort(key=lambda item: item["time_bucket"])
    return result
