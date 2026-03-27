import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CODEX_SCRIPT_PATH = ROOT / "scripts" / "backfill_codex.py"
CLAUDE_SCRIPT_PATH = ROOT / "scripts" / "backfill_claude.py"
CURSOR_SCRIPT_PATH = ROOT / "scripts" / "backfill_cursor.py"


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(entry) for entry in entries),
        encoding="utf-8",
    )


def _codex_entries() -> list[dict]:
    return [
        {
            "timestamp": "2026-03-27T08:00:00.000Z",
            "type": "session_meta",
            "payload": {
                "id": "session-1",
                "timestamp": "2026-03-27T08:00:00.000Z",
                "cwd": "/Users/juns/project/TokenLeague",
                "cli_version": "0.116.0",
            },
        },
        {
            "timestamp": "2026-03-27T08:00:00.100Z",
            "type": "turn_context",
            "payload": {
                "model": "gpt-5.4",
            },
        },
        {
            "timestamp": "2026-03-27T08:00:01.000Z",
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": "turn-1",
            },
        },
        {
            "timestamp": "2026-03-27T08:00:05.000Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "cached_input_tokens": 2,
                    }
                },
            },
        },
        {
            "timestamp": "2026-03-27T08:00:06.000Z",
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-1",
            },
        },
    ]


def _claude_entries(session_id: str = "claude-session-1") -> list[dict]:
    return [
        {
            "uuid": "user-1",
            "type": "user",
            "timestamp": "2026-03-27T08:26:37.824Z",
            "cwd": "/Users/juns/project/TokenLeague",
            "sessionId": session_id,
            "message": {"role": "user", "content": "你好"},
        },
        {
            "uuid": "assistant-final",
            "parentUuid": "user-1",
            "type": "assistant",
            "timestamp": "2026-03-27T08:26:56.851Z",
            "cwd": "/Users/juns/project/TokenLeague",
            "sessionId": session_id,
            "version": "2.1.81",
            "message": {
                "id": "msg-1",
                "role": "assistant",
                "model": "claude-3.7-sonnet",
                "content": [{"type": "text", "text": "好的主人"}],
                "usage": {
                    "input_tokens": 34,
                    "output_tokens": 8,
                    "cache_read_input_tokens": 3,
                    "cache_creation_input_tokens": 0,
                },
            },
        },
    ]


def test_codex_dry_run_scans_default_root_and_counts_payloads(tmp_path, monkeypatch, capsys):
    home_dir = tmp_path / "home"
    transcript_path = (
        home_dir
        / ".codex"
        / "sessions"
        / "2026"
        / "03"
        / "27"
        / "rollout-2026-03-27T08-00-00-session-1.jsonl"
    )
    _write_jsonl(transcript_path, _codex_entries())
    monkeypatch.setenv("HOME", str(home_dir))

    module = _load_module("tokenleague_backfill_codex", CODEX_SCRIPT_PATH)

    exit_code = module.main(["--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Mode: dry-run" in captured.out
    assert "Scanned files: 1" in captured.out
    assert "Discovered sessions: 1" in captured.out
    assert "Generated prompt events: 1" in captured.out
    assert "Generated task runs: 1" in captured.out
    assert "session-1:turn:turn-1" in captured.out


def test_backfill_uploads_prompt_events_before_task_run(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    transcript_path = (
        home_dir
        / ".codex"
        / "sessions"
        / "2026"
        / "03"
        / "27"
        / "rollout-2026-03-27T08-00-00-session-1.jsonl"
    )
    _write_jsonl(transcript_path, _codex_entries())
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("TOKENLEAGUE_HOOK_KEY", "hook-key")

    module = _load_module("tokenleague_backfill_codex_upload", CODEX_SCRIPT_PATH)
    uploads: list[tuple[str, str]] = []

    def fake_send_request(endpoint: str, payload: dict) -> bool:
        payload_id = payload.get("external_event_id") or payload.get("external_task_id") or ""
        uploads.append((endpoint, str(payload_id)))
        return True

    monkeypatch.setattr(module, "send_request", fake_send_request)

    exit_code = module.main([])

    assert exit_code == 0
    assert uploads == [
        ("/api/ingest/prompt-event", "session-1:turn:turn-1"),
        ("/api/ingest/task-run", "session-1"),
    ]


def test_claude_backfill_skips_subagent_transcripts(tmp_path, monkeypatch):
    home_dir = tmp_path / "home"
    main_path = home_dir / ".claude" / "projects" / "project-a" / "session-1.jsonl"
    subagent_path = (
        home_dir
        / ".claude"
        / "projects"
        / "project-a"
        / "session-1"
        / "subagents"
        / "agent-a.jsonl"
    )
    _write_jsonl(main_path, _claude_entries("claude-session-main"))
    _write_jsonl(subagent_path, _claude_entries("claude-session-subagent"))
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("TOKENLEAGUE_HOOK_KEY", "hook-key")

    module = _load_module("tokenleague_backfill_claude", CLAUDE_SCRIPT_PATH)
    uploads: list[tuple[str, str]] = []

    def fake_send_request(endpoint: str, payload: dict) -> bool:
        payload_id = payload.get("external_event_id") or payload.get("external_task_id") or ""
        uploads.append((endpoint, str(payload_id)))
        return True

    monkeypatch.setattr(module, "send_request", fake_send_request)

    exit_code = module.main([])

    assert exit_code == 0
    assert uploads == [
        ("/api/ingest/prompt-event", "msg-1"),
        ("/api/ingest/task-run", "claude-session-main"),
    ]


def test_cursor_backfill_reports_missing_token_usage_for_text_only_history(tmp_path, monkeypatch, capsys):
    home_dir = tmp_path / "home"
    transcript_path = (
        home_dir
        / ".cursor"
        / "projects"
        / "Users-juns-project-TokenLeague"
        / "agent-transcripts"
        / "session-1.json"
    )
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        json.dumps(
            [
                {"role": "user", "text": "你好"},
                {"role": "assistant", "text": "好的"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home_dir))

    module = _load_module("tokenleague_backfill_cursor", CURSOR_SCRIPT_PATH)

    exit_code = module.main(["--dry-run"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Mode: dry-run" in captured.out
    assert "Scanned files: 1" in captured.out
    assert "Generated prompt events: 0" in captured.out
    assert "Generated task runs: 0" in captured.out
    assert "missing_token_usage=1" in captured.out
