import json
import importlib.util
import io
import os
from pathlib import Path
import urllib.error

import pytest


HOOK_PATH = Path(__file__).resolve().parents[2] / "hooks" / "claude" / "tokenleague.py"
CLAUDE_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "hooks" / "claude" / "settings.json"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("tokenleague_claude_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_git_worktree_path(tmp_path: Path, project_name: str, worktree_name: str) -> Path:
    repo_root = tmp_path / project_name
    (repo_root / ".git").mkdir(parents=True)
    worktree_dir = repo_root / ".worktrees" / worktree_name
    worktree_dir.mkdir(parents=True)
    (worktree_dir / ".git").write_text(
        f"gitdir: {repo_root / '.git' / 'worktrees' / worktree_name}\n",
        encoding="utf-8",
    )
    return worktree_dir


def test_claude_settings_register_stop_and_session_end_hooks():
    payload = json.loads(CLAUDE_SETTINGS_PATH.read_text(encoding="utf-8"))

    assert set(payload["hooks"]) == {"SessionStart", "Stop", "SessionEnd"}


def test_handle_session_start_returns_env_configuration_message(monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TOKENLEAGUE_API_URL", "http://192.168.9.11:5006")
    monkeypatch.setenv("TOKENLEAGUE_HOOK_KEY", "a" * 32)

    payload = hook._handle_session_start({"session_id": "session-1"})

    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "TOKENLEAGUE_API_URL=configured (http://192.168.9.11:5006)" in payload["hookSpecificOutput"]["additionalContext"]
    assert "TOKENLEAGUE_HOOK_KEY=configured" in payload["hookSpecificOutput"]["additionalContext"]
    assert "TOKENLEAGUE_API_URL=configured (http://192.168.9.11:5006)" in payload["systemMessage"]
    assert "TOKENLEAGUE_HOOK_KEY=configured" in payload["systemMessage"]


def test_detect_project_name_uses_repo_root_for_git_worktree(tmp_path):
    hook = _load_hook_module()
    worktree_dir = _make_git_worktree_path(tmp_path, "TokenLeague", "openclaw-hook-support")

    assert hook._detect_project_name(str(worktree_dir)) == "TokenLeague"


def test_handle_stop_parses_transcript_and_uploads_prompt_and_task_usage(tmp_path, monkeypatch):
    hook = _load_hook_module()
    transcript_path = tmp_path / "session.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "uuid": "user-1",
                        "type": "user",
                        "timestamp": "2026-03-23T08:26:37.824Z",
                        "message": {"role": "user", "content": "你好"},
                    }
                ),
                json.dumps(
                    {
                        "uuid": "assistant-thinking",
                        "parentUuid": "user-1",
                        "type": "assistant",
                        "timestamp": "2026-03-23T08:26:54.642Z",
                        "version": "2.1.81",
                        "message": {
                            "id": "msg-1",
                            "role": "assistant",
                            "model": "glm-5",
                            "content": [{"type": "thinking", "thinking": "..."}],
                            "usage": {"input_tokens": 0, "output_tokens": 0},
                        },
                    }
                ),
                json.dumps(
                    {
                        "uuid": "assistant-final",
                        "parentUuid": "assistant-thinking",
                        "type": "assistant",
                        "timestamp": "2026-03-23T08:26:56.851Z",
                        "version": "2.1.81",
                        "message": {
                            "id": "msg-1",
                            "role": "assistant",
                            "model": "glm-5",
                            "content": [{"type": "text", "text": "好的主人"}],
                            "usage": {"input_tokens": 34521, "output_tokens": 85},
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    uploads = []

    def fake_send_api_request(endpoint, payload):
        uploads.append((endpoint, payload))
        return True

    monkeypatch.setattr(hook, "_send_api_request", fake_send_api_request)

    hook._handle_stop(
        {
            "session_id": "session-1",
            "transcript_path": str(transcript_path),
            "hook_event_name": "Stop",
        }
    )

    assert uploads == [
        (
            "/api/ingest/prompt-event",
            {
                "external_event_id": "msg-1",
                "task_id": "session-1",
                "project_name": "TokenLeague",
                "prompt_started_at": "2026-03-23T08:26:37.824Z",
                "prompt_finished_at": "2026-03-23T08:26:56.851Z",
                "input_token_count": 34521,
                "output_token_count": 85,
                "agent_type": "claude-code",
                "agent_version": "2.1.81",
                "model_name": "glm-5",
            },
        ),
        (
            "/api/ingest/task-run",
            {
                "external_task_id": "session-1",
                "project_name": "TokenLeague",
                "started_at": "2026-03-23T08:26:37.824Z",
                "finished_at": "2026-03-23T08:26:56.851Z",
                "prompt_count": 1,
                "input_token_count": 34521,
                "output_token_count": 85,
                "agent_type": "claude-code",
                "agent_version": "2.1.81",
                "model_name": "glm-5",
            },
        ),
    ]


def test_main_routes_session_end_to_stop(monkeypatch):
    hook = _load_hook_module()
    calls = []
    event_data = {
        "session_id": "session-1",
        "transcript_path": "/tmp/transcript.jsonl",
    }

    monkeypatch.setattr(hook, "_handle_stop", lambda payload: calls.append(payload))
    monkeypatch.setattr(hook.sys, "stdin", io.StringIO(json.dumps(event_data)))
    monkeypatch.setenv("CLAUDE_HOOK_EVENT_NAME", "SessionEnd")

    with pytest.raises(SystemExit) as exc_info:
        hook.main()

    assert exc_info.value.code == 0
    assert calls == [event_data]


def test_send_api_request_retries_private_hostname_via_ip(monkeypatch, tmp_path):
    hook = _load_hook_module()
    monkeypatch.setenv("TOKENLEAGUE_API_URL", "http://homegpu1:5006")
    monkeypatch.setenv("TOKENLEAGUE_HOOK_KEY", "a" * 32)
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    attempts = []

    class _Response:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout=5):
        attempts.append(req.full_url)
        if req.full_url.startswith("http://homegpu1:5006"):
            raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, io.BytesIO(b""))
        return _Response(200)

    monkeypatch.setattr(hook.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(hook.socket, "gethostbyname", lambda host: "192.168.9.11")

    assert hook._send_api_request("/api/ingest/prompt-event", {"external_event_id": "evt-1"}) is True
    assert attempts == [
        "http://homegpu1:5006/api/ingest/prompt-event",
        "http://192.168.9.11:5006/api/ingest/prompt-event",
    ]


def test_send_api_request_writes_failure_log(monkeypatch, tmp_path):
    hook = _load_hook_module()
    monkeypatch.setenv("TOKENLEAGUE_API_URL", "http://homegpu1:5006")
    monkeypatch.setenv("TOKENLEAGUE_HOOK_KEY", "a" * 32)
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    def fake_urlopen(req, timeout=5):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(hook.urllib.request, "urlopen", fake_urlopen)

    assert hook._send_api_request("/api/ingest/task-run", {"external_task_id": "task-1"}) is False

    log_path = tmp_path / hook.HOOK_LOG_FILE_NAME
    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "request_failed" in log_text
    assert "/api/ingest/task-run" in log_text
    assert "network down" in log_text


def test_extract_model_info_uses_generic_version_field():
    hook = _load_hook_module()

    model_name, agent_version = hook._extract_model_info(
        {
            "model": "glm-5",
            "version": "2.1.81",
        }
    )

    assert model_name == "glm-5"
    assert agent_version == "2.1.81"
