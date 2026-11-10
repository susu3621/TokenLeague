from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys

import pytest

import db
import timing

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hooks" / "common"))
from tokenleague_timing import build_turn_timings

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


def iso(seconds):
    return (NOW + timedelta(seconds=seconds)).isoformat()


def payload(turn="t1", *, start=-100, end=-80, session="s1", project="TokenLeague", **extras):
    return {"session_id": session, "turn_id": turn, "project_name": project, "agent_type": "codex",
            "agent_version": "1.0", "model_name": "model-a", "started_at": iso(start), "finished_at": iso(end),
            "duration_ms": round((end - start) * 1000), "time_to_first_token_ms": None,
            "timing_source": "timestamps", "tool_status": "unavailable", "tools": [], "model_blocks": [], **extras}


def span(kind, start, end, **extra):
    return {"kind": kind, "started_at": iso(start), "finished_at": iso(end), **extra}


def event(kind, seconds, **data):
    return {"type": "event_msg", "timestamp": iso(seconds), "payload": {"type": kind, **data}}


def test_codex_prefers_recorded_latency_and_does_not_invent_tool_time_or_ttft():
    entries = [event("task_started", -100, turn_id="a"),
               {"type": "turn_context", "payload": {"model": "new-model"}},
               event("task_complete", -50, turn_id="a", duration_ms=30000, time_to_first_token_ms=500),
               event("task_complete", -40, turn_id="b", duration_ms=0),
               event("task_started", -30, turn_id="unfinished")]
    rows = build_turn_timings(entries, source="codex", session_id="s", project_name="p")
    assert len(rows) == 2
    assert rows[0]["started_at"] == iso(-80)
    assert rows[0]["duration_ms"] == 30000
    assert rows[0]["model_name"] == "new-model"
    assert rows[0]["time_to_first_token_ms"] == 500
    assert rows[0]["tool_status"] == "unavailable" and rows[0]["tools"] == []
    assert rows[1]["duration_ms"] == 0 and rows[1]["time_to_first_token_ms"] is None


def native_item(item_type, start, end, *, turn_id="a", item_id="item-1", **extra):
    return event("item_completed", end, turn_id=turn_id,
                 started_at_ms=round((NOW + timedelta(seconds=start)).timestamp() * 1000),
                 completed_at_ms=round((NOW + timedelta(seconds=end)).timestamp() * 1000),
                 item={"type": item_type, "id": item_id, **extra})


def response_item(kind, at, **extra):
    return {"type": "response_item", "timestamp": iso(at), "payload": {"type": kind, **extra}}


def test_codex_native_activity_fills_the_breakdown_without_double_counting_wrappers():
    command = native_item("CommandExecution", -96, -90, item_id="cmd",
                          command=["bash", "-lc", "pytest /secret/path"], status="Completed")
    entries = [event("task_started", -100, turn_id="a"),
               native_item("UserMessage", -100, -100, item_id="user", content="private prompt"),
               native_item("AgentMessage", -99, -98, item_id="msg", content="private text"),
               response_item("custom_tool_call", -97, call_id="wrapper", name="exec", input="private command"),
               command, command,
               native_item("Reasoning", -89, -89, item_id="reason", raw_content="private thought"),
               native_item("Extension", -95, -85, item_id="sleep", kind="clock.sleep"),
               response_item("custom_tool_call_output", -84, call_id="wrapper", output="private output"),
               native_item("AgentMessage", -83, -80, item_id="final", content="private answer"),
               native_item("ContextCompaction", -80, -79, item_id="compact"),
               event("task_complete", -78, turn_id="a", duration_ms=22000)]
    rows = build_turn_timings(entries, source="codex", session_id="s", project_name="p")
    assert len(rows) == 1 and rows[0]["parser_version"] == 2
    assert rows[0]["tool_status"] == "measured"
    assert len(rows[0]["tools"]) == 3
    assert all(word not in json.dumps(rows) for word in ("private", "/secret", "pytest"))
    report = timing.build_report([{"user_id": 1, **timing.normalize(rows[0])}], upper=NOW)
    summary = report["summary"]
    assert summary["tool_observed_turns"] == 1 and summary["legacy_codex_turns"] == 0
    assert sum(s["duration_ms"] for s in summary["breakdown"]) == 22000
    tools = {tool["tool"]: tool for tool in report["tools"]}
    assert tools["exec_command"]["call_count"] == 1
    assert tools["exec_command"]["exclusive_ms"] == 3500
    assert tools["clock.sleep"]["exclusive_ms"] == 7500
    assert tools["exec"]["exclusive_ms"] == 2000
    assert next(s for s in summary["breakdown"] if s["kind"] == "compaction")["duration_ms"] == 1000
    assert next(s for s in summary["breakdown"] if s["kind"] == "unobserved")["duration_ms"] == 1000


def test_codex_native_mcp_and_raw_call_are_one_call():
    entries = [event("task_started", -100, turn_id="a"),
               response_item("function_call", -98, call_id="call-1", name="js", namespace="mcp__browser", arguments='{"private":"arguments"}'),
               native_item("McpToolCall", -97, -93, item_id="call-1", server="browser", tool="js", arguments={"private": "arguments"}),
               response_item("function_call_output", -92, call_id="call-1", output="private output"),
               event("task_complete", -90, turn_id="a")]
    row = build_turn_timings(entries, source="codex", session_id="s", project_name="p")[0]
    assert len(row["tools"]) == 1
    assert row["tools"][0]["source"] == "recorded" and row["tools"][0]["tool"] == "browser.js"


def test_codex_legacy_pairs_call_ids_without_reading_tool_output_text():
    entries = [event("task_started", -100, turn_id="a"),
               response_item("reasoning", -98, id="r", summary="private thought"),
               response_item("function_call", -97, call_id="call-1", name="exec_command", arguments='{"cmd":"cargo test /secret/path"}'),
               response_item("function_call_output", -90, call_id="call-1", output=[{"text": "Wall time: 999999 seconds. private output"}]),
               response_item("message", -85, role="assistant", content="private answer"),
               event("task_complete", -84, turn_id="a")]
    row = build_turn_timings(entries, source="codex", session_id="s", project_name="p")[0]
    assert row["tools"][0]["source"] == "paired"
    assert row["tools"][0]["started_at"] == iso(-97)
    assert row["tools"][0]["finished_at"] == iso(-90)
    assert row["tools"][0]["kind"] == "test"
    assert all(span["source"] == "estimated" for span in row["model_blocks"])
    assert "private" not in json.dumps(row)


def test_codex_unmatched_call_is_partial_and_unfinished_turn_is_excluded():
    entries = [event("task_started", -100, turn_id="a"),
               response_item("function_call", -95, call_id="missing", name="exec_command", arguments="{}"),
               event("task_complete", -90, turn_id="a"),
               event("task_started", -85, turn_id="unfinished"),
               native_item("Extension", -80, -70, turn_id="unfinished", kind="clock.sleep")]
    rows = build_turn_timings(entries, source="codex", session_id="s", project_name="p")
    assert len(rows) == 1 and rows[0]["tool_status"] == "incomplete"
    assert rows[0]["tools"] == []


def test_codex_native_rust_duration_fallback_and_clipping():
    item = event("item_completed", -90, turn_id="a", item={"type": "CommandExecution", "id": "cmd", "command": ["rg", "test"],
                 "parsed_cmd": [{"type": "Search"}], "duration": {"secs": 20, "nanos": 500000000}})
    row = build_turn_timings([event("task_started", -100, turn_id="a"), item, event("task_complete", -80, turn_id="a")],
                            source="codex", session_id="s", project_name="p")[0]
    assert row["tools"][0]["started_at"] == iso(-100)
    assert row["tools"][0]["kind"] == "search_read"
    timing.normalize(row)


def test_estimated_model_gaps_cannot_take_time_away_from_measured_tools():
    row = {"user_id": 1, **timing.normalize(payload(
        tools=[{**span("build", -100, -80, tool="native"), "source": "recorded"},
               {**span("orchestration", -100, -80, tool="wrapper"), "source": "paired"}],
        model_blocks=[{**span("thinking", -100, -80), "source": "estimated"}],
    ))}
    report = timing.build_report([row], upper=NOW)
    assert next(t for t in report["tools"] if t["tool"] == "native")["exclusive_ms"] == 20000
    assert next(t for t in report["tools"] if t["tool"] == "wrapper")["exclusive_ms"] == 0
    assert report["summary"]["agent_ms"] == 20000


def test_old_parser_replay_cannot_erase_enriched_timing():
    enriched = payload(parser_version=2, tool_status="measured", tools=[{**span("build", -100, -80, tool="native"), "source": "recorded"}])
    db.upsert_turn_timing(1, enriched)
    db.upsert_turn_timing(1, payload())
    rows, _ = db.get_timing_data(upper=NOW)
    assert len(rows) == 1 and rows[0]["parser_version"] == 2 and len(rows[0]["tools"]) == 1


def test_later_human_message_does_not_become_estimated_model_time():
    entries = [event("task_started", -100, turn_id="a"),
               native_item("UserMessage", -100, -100, item_id="u1"),
               native_item("AgentMessage", -99, -98, item_id="m1"),
               native_item("UserMessage", -10, -10, item_id="u2"),
               native_item("Reasoning", -9, -9, item_id="r"),
               event("task_complete", -8, turn_id="a")]
    row = build_turn_timings(entries, source="codex", session_id="s", project_name="p")[0]
    report = timing.build_report([{"user_id": 1, **timing.normalize(row)}], upper=NOW)
    unknown = next(s for s in report["summary"]["breakdown"] if s["kind"] == "unobserved")
    assert unknown["duration_ms"] == 89000  # human gap plus the final unrecorded second


@pytest.mark.parametrize("change", [{"parser_version": True}, {"parser_version": 0}, {"tools": [{**span("build", -100, -90, tool="x"), "source": "invented"}]}])
def test_invalid_activity_metadata_is_rejected(change):
    with pytest.raises(ValueError):
        timing.normalize(payload(**change))


def claude_fixture():
    return [
        {"type": "user", "uuid": "prompt-1", "timestamp": iso(-100), "message": {"content": "private prompt"}},
        {"type": "assistant", "timestamp": iso(-95), "message": {"model": "claude-test", "content": [
            {"type": "tool_use", "id": "c1", "name": "Bash", "input": {"command": "pytest /secret/path"}},
            {"type": "tool_use", "id": "c2", "name": "Read", "input": {"file_path": "/secret/path"}}]}},
        {"type": "user", "timestamp": iso(-85), "message": {"content": [{"type": "tool_result", "tool_use_id": "c1", "content": "private result"}]}},
        {"type": "user", "timestamp": iso(-80), "message": {"content": [{"type": "tool_result", "tool_use_id": "c2", "content": "private result"}]}},
        {"type": "assistant", "timestamp": iso(-75), "message": {"model": "claude-test", "stop_reason": "end_turn", "content": [{"type": "text", "text": "private answer"}]}},
        {"type": "user", "uuid": "unfinished", "timestamp": iso(-5), "message": {"content": "next prompt"}},
    ]


def test_claude_tool_results_are_not_prompts_and_payload_contains_no_content():
    rows = build_turn_timings(claude_fixture(), source="claude", session_id="s", project_name="p")
    assert len(rows) == 1
    row = rows[0]
    assert row["turn_id"] == "prompt-1" and row["duration_ms"] == 25000
    assert row["time_to_first_token_ms"] is None
    assert [call["kind"] for call in row["tools"]] == ["test", "search_read"]
    assert all(word not in json.dumps(rows) for word in ("private", "/secret", "pytest"))
    normalized = {"user_id": 1, **timing.normalize(row)}
    report = timing.build_report([normalized], upper=NOW)
    assert sum(x["duration_ms"] for x in report["summary"]["breakdown"]) == 25000
    assert sum(t["exclusive_ms"] for t in report["tools"]) == 15000
    assert sum(t["duration"]["average_ms"] for t in report["tools"]) == 25000


def test_claude_unfinished_tools_and_sidechain_do_not_become_completed_primary_turns():
    entries = claude_fixture()[:2]
    assert build_turn_timings(entries, source="claude", session_id="s", project_name="p") == []
    entries = [{**e, "isSidechain": True} for e in claude_fixture()]
    assert build_turn_timings(entries, source="claude", session_id="s", project_name="p") == []
    assert len(build_turn_timings(entries, source="claude", session_id="sub", project_name="p", include_sidechain=True)) == 1


def test_parallel_turns_gaps_clipping_and_latency_sample_counts():
    rows = [
        {"user_id": 1, **timing.normalize(payload("t1", start=-100, end=-80, time_to_first_token_ms=0))},
        {"user_id": 1, **timing.normalize(payload("t2", start=-90, end=-60, session="s2"))},
        {"user_id": 1, **timing.normalize(payload("t3", start=-40, end=-30))},
    ]
    result = timing.build_report(rows, lower=NOW - timedelta(seconds=95), upper=NOW)
    assert result["summary"]["agent_ms"] == 55000
    assert result["summary"]["active_wall_ms"] == 45000
    assert result["summary"]["duration"] == {"samples": 2, "average_ms": 20000, "p50_ms": 10000, "p95_ms": 30000, "max_ms": 30000}
    assert result["summary"]["ttft"]["samples"] == 0  # clipped first turn excluded
    assert sum(b["count"] for b in result["histogram"]) == 2
    first = next(s for s in result["sessions"] if s["session_id"] == "s1")
    assert first["gap_ms"] == 40000
    all_time = timing.build_report(rows, upper=NOW)
    assert all_time["summary"]["ttft"]["samples"] == 1
    assert all_time["summary"]["ttft"]["p50_ms"] == 0
    assert all_time["summary"]["parallelism"] == pytest.approx(1.2)


def test_model_time_takes_priority_and_exclusive_slices_sum_to_turn_time():
    row = {"user_id": 1, **timing.normalize(payload(
        tool_status="measured", tools=[span("test", -100, -85, tool="Bash"), span("build", -95, -80, tool="Bash")],
        model_blocks=[span("thinking", -90, -85)],
    ))}
    result = timing.build_report([row], upper=NOW)
    assert sum(x["duration_ms"] for x in result["summary"]["breakdown"]) == 20000
    assert sum(x["exclusive_ms"] for x in result["tools"]) == 15000


@pytest.mark.parametrize("changes", [
    {"duration_ms": -1}, {"duration_ms": 20}, {"time_to_first_token_ms": True},
    {"time_to_first_token_ms": 30000}, {"finished_at": "bad"}, {"agent_type": ""},
    {"session_id": []}, {"tools": [span("test", -150, -90, tool="Bash")]},
    {"tools": {}}, {"model_blocks": [span("invalid", -100, -90)]},
])
def test_invalid_measurements_are_rejected_without_writing(client, changes):
    headers = {"X-Hook-Key": db.get_user_by_id(1)["hook_key"]}
    response = client.post("/api/ingest/turn-timing", json=payload(**changes), headers=headers)
    assert response.status_code == 400
    assert db._memory_turn_timings == {}


def test_ingest_requires_hook_key_and_upserts_without_changing_usage(client, auth_session, monkeypatch):
    monkeypatch.setattr(db, "_utcnow", lambda: NOW)
    assert client.post("/api/ingest/turn-timing", json=payload()).status_code == 401
    headers = {"X-Hook-Key": db.get_user_by_id(1)["hook_key"]}
    for _ in range(2):
        assert client.post("/api/ingest/turn-timing", json={**payload(), "prompt": "not stored"}, headers=headers).status_code == 200
    result = auth_session.get("/api/timing?window=all&view=turns").get_json()
    assert result["table"]["total"] == 1
    assert result["summary"]["ttft"]["p50_ms"] is None
    assert db._memory_prompt_events == [] and db._memory_task_runs == []
    assert "not stored" not in repr(db._memory_turn_timings)


def test_user_scoping_applies_to_summary_and_session_lists(user_session, monkeypatch):
    monkeypatch.setattr(db, "_utcnow", lambda: NOW)
    db.upsert_turn_timing(1, payload(project="admin-private"))
    with user_session.session_transaction() as session:
        user_id = session["user_id"]
    db.upsert_turn_timing(user_id, payload(project="alice-project"))
    result = user_session.get("/api/timing?window=all&view=projects").get_json()
    assert [r["project_name"] for r in result["table"]["rows"]] == ["alice-project"]
    assert user_session.get("/api/timing?user_id=1").status_code == 403
    assert user_session.get("/api/users/1/timing").status_code == 403
    assert user_session.get("/users/1/timing").status_code == 403


def test_admin_filters_sort_and_pagination_are_applied_before_paging(auth_session, monkeypatch):
    monkeypatch.setattr(db, "_utcnow", lambda: NOW)
    for i in range(36):
        db.upsert_turn_timing(1, payload(f"t{i}", start=-100, end=-99 + i, session=f"s{i}", project="p"))
    result = auth_session.get("/api/timing?window=all&view=turns&project_name=p&page=2&page_size=10&sort=duration_ms&order=asc").get_json()
    assert result["table"]["pages"] == 4 and result["table"]["page"] == 2
    assert result["table"]["rows"][0]["duration_ms"] == 11000
    assert auth_session.get("/api/timing?window=all&view=turns&page=999").get_json()["table"]["page"] == 3
    assert auth_session.get("/api/timing?window=all&session_id=s0").get_json()["summary"]["turn_count"] == 1
    assert auth_session.get("/api/timing?window=all&model_name=missing").get_json()["summary"]["turn_count"] == 0


def test_nulls_sort_last_in_both_directions():
    rows = [{"duration_ms": value} for value in (None, 10, 1)]
    for order in ("asc", "desc"):
        result = timing.paginate(rows, "turns", sort="duration_ms", order=order)
        assert result["rows"][-1]["duration_ms"] is None


def test_empty_coverage_never_turns_old_session_span_into_agent_time(auth_session, monkeypatch):
    monkeypatch.setattr(db, "_utcnow", lambda: NOW)
    db.upsert_task_run(1, {"external_task_id": "old", "started_at": iso(-10000), "finished_at": iso(-10), "agent_type": "claude-code"})
    result = auth_session.get("/api/timing?window=all").get_json()["summary"]
    assert result["unmeasured_session_count"] == 1
    assert result["agent_ms"] == 0 and result["duration"]["p50_ms"] is None


def test_custom_range_and_invalid_queries(auth_session, monkeypatch):
    monkeypatch.setattr(db, "_utcnow", lambda: NOW)
    db.upsert_turn_timing(1, payload())
    result = auth_session.get("/api/timing", query_string={"from": iso(-95), "to": iso(-85)}).get_json()
    assert result["summary"]["agent_ms"] == 10000
    assert result["summary"]["duration"]["samples"] == 0
    for query in ("view=invalid", "page=bad", "order=bad", "from=invalid", "from=2026-11-11&to=2026-11-10"):
        assert auth_session.get(f"/api/timing?{query}").status_code == 400


def test_window_boundaries_keep_zero_latency_but_exclude_prior_turns(auth_session, monkeypatch):
    monkeypatch.setattr(db, "_utcnow", lambda: NOW)
    db.upsert_turn_timing(1, payload("prior", start=-100, end=-80))
    db.upsert_turn_timing(1, payload("zero", start=-80, end=-80))
    result = auth_session.get("/api/timing", query_string={"from": iso(-80), "to": iso(0)}).get_json()
    assert result["summary"]["turn_count"] == 1
    assert result["summary"]["duration"]["p50_ms"] == 0
    assert result["summary"]["duration"]["samples"] == 1


def test_reversed_submillisecond_intervals_and_future_windows_are_rejected():
    with pytest.raises(ValueError, match="precede"):
        timing.normalize(payload(start=-80, end=-80.0001, duration_ms=0))
    with pytest.raises(ValueError, match="current time"):
        timing.window_bounds("all", NOW, NOW + timedelta(days=1), NOW + timedelta(days=2))


def test_timing_pages_have_auth_and_bilingual_labels(client, auth_session):
    response = auth_session.get("/timing", headers={"Accept-Language": "zh-CN"})
    assert response.status_code == 200 and "耗时分析" in response.get_data(as_text=True)
    assert b"timing-config" in response.data and b"timing-page-input" in response.data
    assert auth_session.get("/users/99999/timing").status_code == 404


def test_timing_backfill_uses_stable_ids_and_touches_no_usage(tmp_path, monkeypatch, client, auth_session):
    spec = importlib.util.spec_from_file_location("backfill_timing", ROOT / "scripts" / "backfill_timing.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / "session.jsonl").write_text("\n".join(json.dumps(e) for e in claude_fixture()))
    monkeypatch.setattr(db, "_utcnow", lambda: NOW)
    monkeypatch.setenv("TOKENLEAGUE_HOOK_KEY", db.get_user_by_id(1)["hook_key"])
    hook = module.load_hook("claude")
    monkeypatch.setattr(hook, "_send_api_request", lambda endpoint, data: client.post(endpoint, json=data, headers={"X-Hook-Key": db.get_user_by_id(1)["hook_key"]}).status_code == 200)
    monkeypatch.setattr(module, "load_hook", lambda source: hook)
    for _ in range(2):
        assert module.main(["--source", "claude", "--claude-root", str(tmp_path)]) == 0
    assert len(db._memory_turn_timings) == 1
    assert db._memory_prompt_events == [] and db._memory_task_runs == []


def test_timing_backfill_project_filter_does_not_upload_other_projects(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("backfill_timing_filtered", ROOT / "scripts" / "backfill_timing.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("target", "unrelated"):
        (tmp_path / f"{name}.jsonl").write_text("{}")
    monkeypatch.setenv("TOKENLEAGUE_HOOK_KEY", "test-only")
    uploads = []
    hook = type("Hook", (), {"_send_api_request": staticmethod(lambda endpoint, row: uploads.append(row) or True)})()
    monkeypatch.setattr(module, "load_hook", lambda source: hook)
    monkeypatch.setattr(module, "session_timings", lambda path, source, hook: [payload(project=path.stem)])
    assert module.main(["--source", "claude", "--claude-root", str(tmp_path), "--project-name", "target"]) == 0
    assert [row["project_name"] for row in uploads] == ["target"]
