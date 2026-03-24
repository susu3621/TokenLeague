from datetime import datetime, timedelta, timezone


def _iso(dt):
    return dt.replace(microsecond=0).isoformat()


def _prompt_payload(event_id, started_at, *, task_id="task-1", input_tokens=10, output_tokens=5):
    return {
        "external_event_id": event_id,
        "task_id": task_id,
        "project_name": "TokenLeague",
        "prompt_started_at": _iso(started_at),
        "prompt_finished_at": _iso(started_at + timedelta(seconds=12)),
        "input_token_count": input_tokens,
        "output_token_count": output_tokens,
        "agent_type": "codex",
        "agent_version": "1.0.0",
        "model_name": "gpt-5.4",
        "status": "completed",
    }


def _task_payload(task_id, started_at, *, prompt_count=1, input_tokens=10, output_tokens=5):
    return {
        "external_task_id": task_id,
        "project_name": "TokenLeague",
        "started_at": _iso(started_at),
        "finished_at": _iso(started_at + timedelta(minutes=2)),
        "prompt_count": prompt_count,
        "input_token_count": input_tokens,
        "output_token_count": output_tokens,
        "agent_type": "codex",
        "agent_version": "1.0.0",
        "model_name": "gpt-5.4",
        "status": "completed",
    }


def test_leaderboard_requires_login(client):
    response = client.get("/leaderboard")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_can_create_user_with_hook_key(auth_session):
    response = auth_session.post(
        "/admin/users",
        data={
            "username": "alice",
            "display_name": "Alice",
            "password": "secret123",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200

    from db import get_user_by_username

    user = get_user_by_username("alice")
    assert user["display_name"] == "Alice"
    assert user["status"] == "active"
    assert user["hook_key"]

    html = response.get_data(as_text=True)
    assert "Alice" in html
    assert user["hook_key"] in html


def test_prompt_ingest_requires_valid_hook_key(client):
    now = datetime.now(timezone.utc)

    response = client.post(
        "/api/ingest/prompt-event",
        json=_prompt_payload("event-1", now),
    )

    assert response.status_code == 401


def test_prompt_ingest_logs_rejection_reason(client, capsys):
    now = datetime.now(timezone.utc)

    response = client.post(
        "/api/ingest/prompt-event",
        json=_prompt_payload("event-log-reject", now),
    )

    assert response.status_code == 401
    stderr = capsys.readouterr().err
    assert "ingest/prompt-event rejected" in stderr
    assert "reason=invalid_hook_key" in stderr


def test_prompt_ingest_logs_success(auth_session, capsys):
    from db import create_user

    alice = create_user("alice", "secret123", display_name="Alice")
    now = datetime.now(timezone.utc)

    response = auth_session.post(
        "/api/ingest/prompt-event",
        headers={"X-Hook-Key": alice["hook_key"]},
        json=_prompt_payload("event-log-success", now),
    )

    assert response.status_code == 200
    stderr = capsys.readouterr().err
    assert "ingest/prompt-event accepted" in stderr
    assert "username=alice" in stderr
    assert "external_event_id=event-log-success" in stderr


def test_task_run_ingest_logs_success(auth_session, capsys):
    from db import create_user

    alice = create_user("alice", "secret123", display_name="Alice")
    now = datetime.now(timezone.utc)

    response = auth_session.post(
        "/api/ingest/task-run",
        headers={"X-Hook-Key": alice["hook_key"]},
        json=_task_payload("task-log-success", now),
    )

    assert response.status_code == 200
    stderr = capsys.readouterr().err
    assert "ingest/task-run accepted" in stderr
    assert "username=alice" in stderr
    assert "external_task_id=task-log-success" in stderr


def test_leaderboard_handles_naive_datetimes_from_db(monkeypatch):
    import db

    now = datetime.now(timezone.utc).replace(microsecond=0)
    naive_now = now.replace(tzinfo=None)

    monkeypatch.setattr(db, "use_in_memory_store", lambda: False)
    monkeypatch.setattr(
        db,
        "_fetch_prompt_events_from_db",
        lambda: [
            {
                "user_id": 1,
                "task_id": "task-1",
                "external_event_id": "event-1",
                "prompt_started_at": naive_now,
                "prompt_finished_at": naive_now,
                "input_token_count": 10,
                "output_token_count": 5,
                "total_token_count": 15,
                "duration_ms": 0,
                "agent_type": "claude-code",
                "agent_version": "2.1.81",
                "model_name": "glm-5",
                "project_name": "TokenLeague",
                "status": "completed",
                "metadata": {},
            }
        ],
    )
    monkeypatch.setattr(db, "_fetch_task_runs_from_db", lambda: [])
    monkeypatch.setattr(
        db,
        "get_user_by_id",
        lambda user_id: {
            "id": user_id,
            "username": "admin",
            "display_name": "Admin",
            "status": db.USER_ACTIVE,
        },
    )

    rows = db.get_leaderboard(window="all")

    assert rows[0]["username"] == "admin"
    assert rows[0]["total_token_count"] == 15


def test_ingest_events_feed_leaderboard_filters_and_user_stats(auth_session):
    from db import create_user

    alice = create_user("alice", "secret123", display_name="Alice")
    bob = create_user("bob", "secret123", display_name="Bob")
    now = datetime.now(timezone.utc)

    response = auth_session.post(
        "/api/ingest/prompt-event",
        headers={"X-Hook-Key": alice["hook_key"]},
        json=_prompt_payload("alice-today", now, input_tokens=100, output_tokens=40),
    )
    assert response.status_code == 200

    response = auth_session.post(
        "/api/ingest/prompt-event",
        headers={"X-Hook-Key": alice["hook_key"]},
        json=_prompt_payload("alice-old", now - timedelta(days=10), input_tokens=20, output_tokens=10),
    )
    assert response.status_code == 200

    bob_payload = _prompt_payload("bob-today", now, input_tokens=70, output_tokens=20)
    bob_payload["agent_type"] = "claude-code"
    bob_payload["agent_version"] = "2.1.0"
    bob_payload["model_name"] = "claude-sonnet-4"
    response = auth_session.post(
        "/api/ingest/prompt-event",
        headers={"X-Hook-Key": bob["hook_key"]},
        json=bob_payload,
    )
    assert response.status_code == 200

    response = auth_session.post(
        "/api/ingest/task-run",
        headers={"X-Hook-Key": alice["hook_key"]},
        json=_task_payload("task-alice", now, prompt_count=2, input_tokens=100, output_tokens=40),
    )
    assert response.status_code == 200

    response = auth_session.post(
        "/api/ingest/prompt-event",
        headers={"X-Hook-Key": alice["hook_key"]},
        json=_prompt_payload("alice-today", now, input_tokens=100, output_tokens=60),
    )
    assert response.status_code == 200

    all_board = auth_session.get("/api/leaderboard?window=all")
    assert all_board.status_code == 200
    all_rows = all_board.get_json()["rows"]
    assert [row["username"] for row in all_rows] == ["alice", "bob"]
    assert all_rows[0]["total_token_count"] == 190
    assert all_rows[0]["task_count"] == 1
    assert all_rows[1]["total_token_count"] == 90

    day_board = auth_session.get("/api/leaderboard?window=day")
    assert day_board.status_code == 200
    day_rows = day_board.get_json()["rows"]
    assert day_rows[0]["username"] == "alice"
    assert day_rows[0]["total_token_count"] == 160

    filtered_board = auth_session.get("/api/leaderboard?window=all&agent_type=codex")
    assert filtered_board.status_code == 200
    filtered_rows = filtered_board.get_json()["rows"]
    assert [row["username"] for row in filtered_rows] == ["alice"]

    stats = auth_session.get(f"/api/users/{alice['id']}/stats?window=all")
    assert stats.status_code == 200
    payload = stats.get_json()
    assert payload["summary"]["total_token_count"] == 190
    assert payload["summary"]["task_count"] == 1
    assert payload["agent_breakdown"][0]["agent_type"] == "codex"
    assert payload["agent_breakdown"][0]["model_name"] == "gpt-5.4"
    assert any(
        row["project_name"] == "TokenLeague"
        for row in payload["recent_prompt_events"]
    )
    assert any(
        row["project_name"] == "TokenLeague"
        for row in payload["recent_task_runs"]
    )

    leaderboard_page = auth_session.get("/leaderboard")
    assert leaderboard_page.status_code == 200
    assert "Token Leaderboard" in leaderboard_page.get_data(as_text=True)

    agent_page = auth_session.get("/admin/agents")
    assert agent_page.status_code == 200
    agent_html = agent_page.get_data(as_text=True)
    assert "claude-code" in agent_html
    assert "claude-sonnet-4" in agent_html


def test_user_timeline_api_supports_month_daily_range(auth_session, monkeypatch):
    import db
    from db import upsert_prompt_event

    fixed_now = datetime(2026, 3, 24, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(db, "_utcnow", lambda: fixed_now)

    upsert_prompt_event(
        1,
        _prompt_payload(
            "timeline-month-1",
            fixed_now - timedelta(days=4),
            task_id="task-alpha",
            input_tokens=30,
            output_tokens=10,
        ),
    )
    upsert_prompt_event(
        1,
        {
            **_prompt_payload(
                "timeline-month-1b",
                fixed_now - timedelta(days=4),
                task_id="task-beta",
                input_tokens=8,
                output_tokens=7,
            ),
            "project_name": "SideQuest",
        },
    )
    upsert_prompt_event(
        1,
        {
            **_prompt_payload(
                "timeline-month-2",
                fixed_now,
                input_tokens=20,
                output_tokens=5,
            ),
            "project_name": "TokenLeague",
        },
    )

    response = auth_session.get("/api/users/1/timeline?window=month&granularity=day")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["window"] == "month"
    assert payload["granularity"] == "day"
    assert len(payload["timeline"]) == 30
    assert payload["timeline"][0]["time_bucket"] == "2026-02-23"
    assert payload["timeline"][-1]["time_bucket"] == "2026-03-24"

    timeline = {row["time_bucket"]: row for row in payload["timeline"]}
    assert timeline["2026-03-20"]["total_token_count"] == 55
    assert timeline["2026-03-24"]["total_token_count"] == 25
    assert timeline["2026-03-19"]["total_token_count"] == 0
    assert timeline["2026-03-19"]["project_breakdown"] == []
    assert timeline["2026-03-20"]["project_breakdown"] == [
        {"project_name": "TokenLeague", "total_token_count": 40},
        {"project_name": "SideQuest", "total_token_count": 15},
    ]
    assert timeline["2026-03-24"]["project_breakdown"] == [
        {"project_name": "TokenLeague", "total_token_count": 25},
    ]


def test_user_detail_page_renders_timeline_range_selector(auth_session):
    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "过去7天" in html
    assert "过去30天" in html
    assert "granularity=day" in html
    assert "project_breakdown" in html
    assert "stacked: true" in html


def test_compact_token_count_formats_human_readable_suffixes():
    from app import format_token_count

    assert format_token_count(950) == "950"
    assert format_token_count(1250) == "1.3K"
    assert format_token_count(15000) == "15K"
    assert format_token_count(2300000) == "2.3M"
    assert format_token_count(1000000000) == "1B"
    assert format_token_count(123.4) == "123.4"


def test_user_detail_page_renders_compact_token_counts(auth_session):
    from db import upsert_prompt_event

    upsert_prompt_event(
        1,
        _prompt_payload(
            "compact-user-detail",
            datetime(2026, 3, 24, 12, 0, 0, tzinfo=timezone.utc),
            input_tokens=1200,
            output_tokens=50,
        ),
    )

    response = auth_session.get("/users/1?window=all")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "1.3K" in html
    assert "1,250" not in html
    assert "function formatTokenCount(value)" in html
    assert "formatTokenCount(p.total_token_count)" in html
    assert "formatTokenCount(m.total_token_count)" in html
    assert "callback: value => formatTokenCount(value)" in html


def test_ingest_clamps_negative_prompt_and_task_durations(auth_session):
    from db import create_user, upsert_prompt_event, upsert_task_run

    alice = create_user("alice-negative", "secret123", display_name="Alice Negative")
    started_at = datetime(2026, 3, 23, 9, 18, 0, tzinfo=timezone.utc)
    finished_at = datetime(2026, 3, 23, 9, 2, 36, tzinfo=timezone.utc)

    prompt = upsert_prompt_event(
        alice["id"],
        {
            "external_event_id": "negative-prompt",
            "task_id": "negative-task",
            "prompt_started_at": _iso(started_at),
            "prompt_finished_at": _iso(finished_at),
            "input_token_count": 10,
            "output_token_count": 5,
            "project_name": "TokenLeague",
            "agent_type": "codex",
            "agent_version": "0.116.0",
            "model_name": "gpt-5.4",
        },
    )
    task = upsert_task_run(
        alice["id"],
        {
            "external_task_id": "negative-task",
            "started_at": _iso(started_at),
            "finished_at": _iso(finished_at),
            "prompt_count": 1,
            "input_token_count": 10,
            "output_token_count": 5,
            "project_name": "TokenLeague",
            "agent_type": "codex",
            "agent_version": "0.116.0",
            "model_name": "gpt-5.4",
        },
    )

    assert prompt["duration_ms"] == 0
    assert task["total_duration_ms"] == 0
    assert prompt["project_name"] == "TokenLeague"
    assert task["project_name"] == "TokenLeague"
