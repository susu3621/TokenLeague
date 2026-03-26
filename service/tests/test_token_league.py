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


def _seed_user_detail_window_data(monkeypatch):
    import db

    fixed_now = datetime(2026, 3, 24, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(db, "_utcnow", lambda: fixed_now)

    fixtures = [
        ("today-event", fixed_now, "today-task", "TokenLeague", "gpt-5.4", 20, 10),
        (
            "yesterday-event",
            fixed_now - timedelta(days=1),
            "yesterday-task",
            "SideQuest",
            "claude-sonnet-4",
            40,
            20,
        ),
        ("old-event", fixed_now - timedelta(days=8), "old-task", "Archive", "gpt-4.1", 70, 30),
    ]

    for event_id, started_at, task_id, project_name, model_name, input_tokens, output_tokens in fixtures:
        prompt_payload = _prompt_payload(
            event_id,
            started_at,
            task_id=task_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        prompt_payload["project_name"] = project_name
        prompt_payload["model_name"] = model_name
        db.upsert_prompt_event(1, prompt_payload)

        task_payload = _task_payload(
            task_id,
            started_at,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        task_payload["project_name"] = project_name
        task_payload["model_name"] = model_name
        db.upsert_task_run(1, task_payload)


def _seed_user_detail_filter_data(monkeypatch):
    import db

    fixed_now = datetime(2026, 3, 24, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(db, "_utcnow", lambda: fixed_now)

    fixtures = [
        ("codex-primary", fixed_now, "codex-primary-task", "TokenLeague", "codex", "1.0.0", "gpt-5.4", 20, 10),
        (
            "claude-side",
            fixed_now - timedelta(days=1),
            "claude-side-task",
            "SideQuest",
            "claude-code",
            "2.0.0",
            "claude-sonnet-4",
            40,
            20,
        ),
        ("codex-archive", fixed_now - timedelta(days=2), "codex-archive-task", "Archive", "codex", "1.0.0", "gpt-4.1", 70, 30),
    ]

    for event_id, started_at, task_id, project_name, agent_type, agent_version, model_name, input_tokens, output_tokens in fixtures:
        prompt_payload = _prompt_payload(
            event_id,
            started_at,
            task_id=task_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        prompt_payload["project_name"] = project_name
        prompt_payload["agent_type"] = agent_type
        prompt_payload["agent_version"] = agent_version
        prompt_payload["model_name"] = model_name
        db.upsert_prompt_event(1, prompt_payload)

        task_payload = _task_payload(
            task_id,
            started_at,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        task_payload["project_name"] = project_name
        task_payload["agent_type"] = agent_type
        task_payload["agent_version"] = agent_version
        task_payload["model_name"] = model_name
        db.upsert_task_run(1, task_payload)


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


def test_user_timeline_api_supports_today_hourly_range(auth_session, monkeypatch):
    """Test that today window returns hourly data with hour granularity."""
    import db
    from db import upsert_prompt_event

    fixed_now = datetime(2026, 3, 24, 14, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(db, "_utcnow", lambda: fixed_now)

    db.reset_in_memory_state()
    upsert_prompt_event(
        1,
        {
            **_prompt_payload(
                "today-hour-1",
                fixed_now.replace(hour=9, minute=0),
                input_tokens=100,
                output_tokens=50,
            ),
            "project_name": "TokenLeague",
        },
    )
    upsert_prompt_event(
        1,
        {
            **_prompt_payload(
                "today-hour-2",
                fixed_now.replace(hour=11, minute=0),
                input_tokens=200,
                output_tokens=100,
            ),
            "project_name": "SideQuest",
        },
    )

    response = auth_session.get("/api/users/1/timeline?window=today")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["window"] == "today"
    assert payload["granularity"] == "hour"
    # Should have buckets from 00:00 to 14:00 (15 buckets)
    assert len(payload["timeline"]) == 15
    assert payload["timeline"][0]["time_bucket"] == "2026-03-24 00:00"
    assert payload["timeline"][-1]["time_bucket"] == "2026-03-24 14:00"

    timeline = {row["time_bucket"]: row for row in payload["timeline"]}
    assert timeline["2026-03-24 09:00"]["total_token_count"] == 150
    assert timeline["2026-03-24 11:00"]["total_token_count"] == 300
    assert timeline["2026-03-24 10:00"]["total_token_count"] == 0


def test_user_detail_defaults_to_week_window(auth_session, monkeypatch):
    _seed_user_detail_window_data(monkeypatch)

    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "within the selected week window" in html
    assert "let currentWindow = 'week';" in html
    assert "today-event" in html
    assert "yesterday-event" in html
    assert "old-event" not in html
    assert "today-task" in html
    assert "yesterday-task" in html
    assert "old-task" not in html


def test_user_detail_page_uses_week_as_default_window(auth_session, monkeypatch):
    _seed_user_detail_window_data(monkeypatch)

    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "within the selected week window" in html
    assert "let currentWindow = 'week';" in html
    assert "const windowParam = 'week';" not in html


def test_user_detail_page_renders_refresh_targets_for_stats_sections(auth_session, monkeypatch):
    _seed_user_detail_window_data(monkeypatch)

    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-user-detail-summary-value="total-token-count"' in html
    assert 'data-user-detail-summary-value="prompt-count"' in html
    assert 'data-user-detail-summary-value="task-count"' in html
    assert 'data-user-detail-summary-value="avg-token-per-prompt"' in html
    assert 'data-user-detail-window-selector="week"' in html
    assert 'data-user-detail-window-option="today"' in html
    assert 'data-user-detail-window-option="week"' in html
    assert 'data-user-detail-window-option="month"' in html
    assert 'data-user-detail-agent-breakdown-body' in html
    assert 'data-user-detail-recent-prompt-events-body' in html


def test_user_detail_all_window_keeps_no_active_selector(auth_session, monkeypatch):
    _seed_user_detail_window_data(monkeypatch)

    response = auth_session.get("/users/1?window=all")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "let currentWindow = 'all';" in html
    assert 'data-user-detail-window-selector="all"' in html
    assert 'class="timeline-range-button is-active" data-user-detail-window-option="today"' not in html
    assert 'class="timeline-range-button is-active" data-user-detail-window-option="week"' not in html
    assert 'class="timeline-range-button is-active" data-user-detail-window-option="month"' not in html


def test_user_timeline_api_accepts_day_alias_as_today(auth_session, monkeypatch):
    import db
    from db import upsert_prompt_event

    fixed_now = datetime(2026, 3, 24, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(db, "_utcnow", lambda: fixed_now)

    db.reset_in_memory_state()
    upsert_prompt_event(
        1,
        _prompt_payload(
            "day-alias-event",
            fixed_now - timedelta(hours=1),
            input_tokens=20,
            output_tokens=10,
        ),
    )

    response = auth_session.get("/api/users/1/timeline?window=day")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["window"] == "today"
    assert payload["granularity"] == "hour"
    assert len(payload["timeline"]) == 13
    assert payload["timeline"][0]["time_bucket"] == "2026-03-24 00:00"
    assert payload["timeline"][-1]["time_bucket"] == "2026-03-24 12:00"
    timeline = {row["time_bucket"]: row for row in payload["timeline"]}
    assert timeline["2026-03-24 11:00"]["total_token_count"] == 30
    assert timeline["2026-03-24 12:00"]["total_token_count"] == 0


def test_user_timeline_api_accepts_all_window(auth_session, monkeypatch):
    _seed_user_detail_window_data(monkeypatch)

    response = auth_session.get("/api/users/1/timeline?window=all&granularity=day")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["window"] == "all"
    assert payload["granularity"] == "day"
    assert len(payload["timeline"]) == 3
    assert [row["time_bucket"] for row in payload["timeline"]] == [
        "2026-03-16",
        "2026-03-23",
        "2026-03-24",
    ]
    assert payload["timeline"][0]["total_token_count"] == 100
    assert payload["timeline"][1]["total_token_count"] == 60
    assert payload["timeline"][2]["total_token_count"] == 30


def test_user_detail_page_script_requests_all_sections_with_selected_window(auth_session, monkeypatch):
    _seed_user_detail_window_data(monkeypatch)

    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "function refreshUserDetail(windowValue)" in html
    assert "let refreshRequestId = 0;" in html
    assert "function buildRefreshUrl(pathname, windowValue, extraSearchParams = {})" in html
    assert "const url = new URL(pathname, window.location.origin);" in html
    assert "const params = new URLSearchParams(window.location.search);" in html
    assert "const requestId = ++refreshRequestId;" in html
    assert "const nextUrl = new URL(window.location.href);" in html
    assert "nextUrl.searchParams.set('window', windowValue);" in html
    assert "history.replaceState({}, '', `${nextUrl.pathname}${nextUrl.search}${nextUrl.hash}`);" in html
    assert "params.set('window', windowValue);" in html
    assert "Object.entries(extraSearchParams).forEach(([key, value]) => {" in html
    assert "params.set(key, value);" in html
    assert "url.search = params.toString();" in html
    assert "fetch(buildRefreshUrl(`/api/users/${userId}/stats`, windowValue))" in html
    assert "fetch(buildRefreshUrl(`/api/users/${userId}/projects`, windowValue))" in html
    assert "fetch(buildRefreshUrl(`/api/users/${userId}/models`, windowValue))" in html
    assert "fetch(buildRefreshUrl(`/api/users/${userId}/timeline`, windowValue, { granularity }))" in html
    assert html.count("if (requestId !== refreshRequestId) {") == 4
    assert "renderSummary(data.summary || {});" in html
    assert "renderProjects(data.projects || []);" in html
    assert "renderModels(data.models || []);" in html
    assert "renderTimeline(data.timeline || [], windowValue);" in html
    assert "refreshUserDetail(currentWindow);" in html


def test_user_detail_page_script_escapes_dynamic_refresh_fields_before_inner_html(auth_session):
    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "function escapeHtml(value)" in html
    assert "${escapeHtml(row.agent_type)}" in html
    assert "${escapeHtml(row.agent_version)}" in html
    assert "${escapeHtml(row.model_name)}" in html
    assert "${escapeHtml((row.external_event_id || '').slice(0, 16))}..." in html
    assert "${escapeHtml(row.project_name)}" in html
    assert "${escapeHtml((row.task_id || '').slice(0, 16))}..." in html
    assert 'data-utc-time="${escapeHtml(row.prompt_finished_at || \'\')}"' in html
    assert "${escapeHtml(project.project_name)}" in html
    assert "${escapeHtml(model.model_name)}" in html


def test_user_detail_day_window_aliases_to_today(auth_session, monkeypatch):
    _seed_user_detail_window_data(monkeypatch)

    day_response = auth_session.get("/users/1?window=day")
    today_response = auth_session.get("/users/1?window=today")

    assert day_response.status_code == 200
    assert today_response.status_code == 200

    day_html = day_response.get_data(as_text=True)
    today_html = today_response.get_data(as_text=True)
    assert day_html == today_html
    assert "within the selected today window" in day_html
    assert "let currentWindow = 'today';" in day_html
    assert "today-event" in day_html
    assert "yesterday-event" not in day_html
    assert "old-event" not in day_html


def test_user_detail_breakdown_apis_honor_month_window(auth_session, monkeypatch):
    _seed_user_detail_window_data(monkeypatch)

    stats_response = auth_session.get("/api/users/1/stats?window=month")
    projects_response = auth_session.get("/api/users/1/projects?window=month")
    models_response = auth_session.get("/api/users/1/models?window=month")

    assert stats_response.status_code == 200
    assert projects_response.status_code == 200
    assert models_response.status_code == 200

    stats = stats_response.get_json()
    assert stats["summary"]["total_token_count"] == 190
    assert stats["summary"]["prompt_count"] == 3
    assert stats["summary"]["task_count"] == 3
    assert {row["external_event_id"] for row in stats["recent_prompt_events"]} == {
        "today-event",
        "yesterday-event",
        "old-event",
    }

    projects = {row["project_name"]: row for row in projects_response.get_json()["projects"]}
    assert projects_response.get_json()["window"] == "month"
    assert projects["TokenLeague"]["total_token_count"] == 30
    assert projects["TokenLeague"]["task_count"] == 1
    assert projects["SideQuest"]["total_token_count"] == 60
    assert projects["SideQuest"]["task_count"] == 1
    assert projects["Archive"]["total_token_count"] == 100
    assert projects["Archive"]["task_count"] == 1

    models = {row["model_name"]: row for row in models_response.get_json()["models"]}
    assert models_response.get_json()["window"] == "month"
    assert models["gpt-5.4"]["total_token_count"] == 30
    assert models["claude-sonnet-4"]["total_token_count"] == 60
    assert models["gpt-4.1"]["total_token_count"] == 100


def test_user_detail_refresh_apis_honor_filters(auth_session, monkeypatch):
    _seed_user_detail_filter_data(monkeypatch)

    projects_response = auth_session.get("/api/users/1/projects?window=month&agent_type=codex")
    models_response = auth_session.get("/api/users/1/models?window=month&model_name=gpt-5.4")
    timeline_response = auth_session.get("/api/users/1/timeline?window=month&granularity=day&agent_type=codex")

    assert projects_response.status_code == 200
    assert models_response.status_code == 200
    assert timeline_response.status_code == 200

    projects = {row["project_name"]: row for row in projects_response.get_json()["projects"]}
    assert projects_response.get_json()["window"] == "month"
    assert set(projects) == {"Archive", "TokenLeague"}
    assert projects["TokenLeague"]["total_token_count"] == 30
    assert projects["TokenLeague"]["task_count"] == 1
    assert projects["Archive"]["total_token_count"] == 100
    assert projects["Archive"]["task_count"] == 1

    models = models_response.get_json()["models"]
    assert models_response.get_json()["window"] == "month"
    assert [row["model_name"] for row in models] == ["gpt-5.4"]
    assert models[0]["total_token_count"] == 30
    assert models[0]["task_count"] == 1

    timeline = timeline_response.get_json()
    nonzero_buckets = {
        bucket["time_bucket"]: bucket for bucket in timeline["timeline"] if bucket["total_token_count"] > 0
    }
    assert timeline["window"] == "month"
    assert timeline["granularity"] == "day"
    assert set(nonzero_buckets) == {"2026-03-22", "2026-03-24"}
    assert nonzero_buckets["2026-03-24"]["project_breakdown"] == [
        {"project_name": "TokenLeague", "total_token_count": 30}
    ]
    assert nonzero_buckets["2026-03-22"]["project_breakdown"] == [
        {"project_name": "Archive", "total_token_count": 100}
    ]


def test_user_detail_page_renders_timeline_range_selector(auth_session):
    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "今天" in html
    assert "过去7天" in html
    assert "过去30天" in html
    assert "granularity" in html
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
    assert "formatTokenCount(project.total_token_count)" in html
    assert "formatTokenCount(model.total_token_count)" in html
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
