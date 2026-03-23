from datetime import datetime, timedelta, timezone


def _iso(dt):
    return dt.replace(microsecond=0).isoformat()


def _prompt_payload(event_id, started_at, *, task_id="task-1", input_tokens=10, output_tokens=5):
    return {
        "external_event_id": event_id,
        "task_id": task_id,
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

    leaderboard_page = auth_session.get("/leaderboard")
    assert leaderboard_page.status_code == 200
    assert "Token Leaderboard" in leaderboard_page.get_data(as_text=True)

    agent_page = auth_session.get("/admin/agents")
    assert agent_page.status_code == 200
    agent_html = agent_page.get_data(as_text=True)
    assert "claude-code" in agent_html
    assert "claude-sonnet-4" in agent_html
