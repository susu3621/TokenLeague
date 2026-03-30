#!/usr/bin/env python3

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_DIR = SCRIPT_DIR.parent / "service"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

import db


def _load_prompt_events() -> list[dict]:
    if db.use_in_memory_store():
        return list(db._memory_prompt_events)
    return db._fetch_prompt_events_from_db()


def _load_task_runs() -> list[dict]:
    if db.use_in_memory_store():
        return list(db._memory_task_runs)
    return db._fetch_task_runs_from_db()


def build_default_leaderboard_rows() -> list[dict]:
    prompt_events = _load_prompt_events()
    task_runs = _load_task_runs()
    users_by_id = {
        user["id"]: user
        for user in db.get_all_users()
        if user.get("status") == db.USER_ACTIVE
    }

    rows: dict[int, dict] = {}
    for event in prompt_events:
        user = users_by_id.get(event["user_id"])
        if not user:
            continue
        event_time = db._prompt_event_time(event)
        row = rows.setdefault(
            user["id"],
            {
                "user_id": user["id"],
                "username": user["username"],
                "display_name": user.get("display_name") or user["username"],
                "total_token_count": 0,
                "prompt_count": 0,
                "task_count": 0,
                "total_duration_ms": 0,
                "_last_active_dt": None,
            },
        )
        row["total_token_count"] += int(event.get("total_token_count") or 0)
        row["prompt_count"] += 1
        row["total_duration_ms"] += int(event.get("duration_ms") or 0)
        if row["_last_active_dt"] is None or (
            event_time is not None and event_time > row["_last_active_dt"]
        ):
            row["_last_active_dt"] = event_time

    task_counts: dict[int, int] = defaultdict(int)
    for task_run in task_runs:
        if task_run["user_id"] not in users_by_id:
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
        row["last_active_at"] = db._serialize_datetime(row.pop("_last_active_dt"))
    return ordered_rows


def refresh_default_leaderboard_snapshot() -> dict:
    rows = build_default_leaderboard_rows()
    generated_at = db._utcnow()
    return db.save_leaderboard_snapshot(db.DEFAULT_LEADERBOARD_SNAPSHOT_KEY, rows, generated_at)


def main() -> int:
    try:
        snapshot = refresh_default_leaderboard_snapshot()
    except Exception as exc:  # pragma: no cover - CLI reporting
        print(f"Failed to refresh leaderboard snapshot: {exc}", file=sys.stderr)
        return 1

    print(
        "Refreshed leaderboard snapshot "
        f"key={snapshot['snapshot_key']} "
        f"generated_at={db._serialize_datetime(snapshot['generated_at'])} "
        f"row_count={len(snapshot['rows'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
