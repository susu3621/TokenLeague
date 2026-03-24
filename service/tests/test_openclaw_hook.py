import importlib.util
import json
from pathlib import Path


HOOK_PATH = Path(__file__).resolve().parents[2] / "hooks" / "openclaw" / "tokenleague_collect.py"
INSTALL_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "install_hooks.sh"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("tokenleague_openclaw_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_openclaw_session(
    root: Path,
    *,
    agent_id: str = "agent-1",
    session_id: str = "session-1",
    project_name: str = "TokenLeague",
) -> None:
    repo_root = root / "repos" / project_name
    (repo_root / ".git").mkdir(parents=True)

    sessions_dir = root / "agents" / agent_id / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "sessions.json").write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "id": session_id,
                        "agentId": agent_id,
                        "cwd": str(repo_root),
                        "model": "claude-3-7-sonnet",
                        "startedAt": "2026-03-24T09:00:00.000Z",
                        "updatedAt": "2026-03-24T09:00:15.000Z",
                        "usage": {
                            "inputTokens": 120,
                            "outputTokens": 45,
                        },
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (sessions_dir / f"{session_id}.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "turn-1-user",
                        "type": "user",
                        "timestamp": "2026-03-24T09:00:01.000Z",
                        "content": "Summarize the repo",
                    }
                ),
                json.dumps(
                    {
                        "id": "turn-1-assistant",
                        "type": "assistant",
                        "parentId": "turn-1-user",
                        "timestamp": "2026-03-24T09:00:15.000Z",
                        "usage": {
                            "inputTokens": 120,
                            "outputTokens": 45,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_install_script_supports_openclaw_assets():
    content = INSTALL_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "--openclaw" in content
    assert "install_openclaw_hooks" in content
    assert "uninstall_openclaw_hooks" in content
    assert ".openclaw/tokenleague_collect.py" in content


def test_collect_session_uploads_prompt_and_task_usage(tmp_path, monkeypatch):
    hook = _load_hook_module()
    openclaw_root = tmp_path / ".openclaw"
    _write_openclaw_session(openclaw_root)
    monkeypatch.setenv("TOKENLEAGUE_OPENCLAW_ROOT", str(openclaw_root))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(hook, "_write_hook_log", lambda *args, **kwargs: None)

    uploads = []

    def fake_send_api_request(endpoint, payload):
        uploads.append((endpoint, payload))
        return True

    monkeypatch.setattr(hook, "_send_api_request", fake_send_api_request)

    assert hook.collect_and_upload() == 0
    assert uploads == [
        (
            "/api/ingest/prompt-event",
            {
                "external_event_id": "turn-1-assistant",
                "task_id": "session-1",
                "project_name": "TokenLeague",
                "prompt_started_at": "2026-03-24T09:00:01.000Z",
                "prompt_finished_at": "2026-03-24T09:00:15.000Z",
                "input_token_count": 120,
                "output_token_count": 45,
                "agent_type": "openclaw",
                "agent_version": "unknown",
                "model_name": "claude-3-7-sonnet",
            },
        ),
        (
            "/api/ingest/task-run",
            {
                "external_task_id": "session-1",
                "project_name": "TokenLeague",
                "started_at": "2026-03-24T09:00:00.000Z",
                "finished_at": "2026-03-24T09:00:15.000Z",
                "prompt_count": 1,
                "input_token_count": 120,
                "output_token_count": 45,
                "agent_type": "openclaw",
                "agent_version": "unknown",
                "model_name": "claude-3-7-sonnet",
            },
        ),
    ]


def test_collect_session_skips_previously_processed_turns(tmp_path, monkeypatch):
    hook = _load_hook_module()
    openclaw_root = tmp_path / ".openclaw"
    _write_openclaw_session(openclaw_root)
    monkeypatch.setenv("TOKENLEAGUE_OPENCLAW_ROOT", str(openclaw_root))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(hook, "_write_hook_log", lambda *args, **kwargs: None)

    uploads = []

    def fake_send_api_request(endpoint, payload):
        uploads.append((endpoint, payload))
        return True

    monkeypatch.setattr(hook, "_send_api_request", fake_send_api_request)

    assert hook.collect_and_upload() == 0
    assert len(uploads) == 2

    uploads.clear()
    assert hook.collect_and_upload() == 0
    assert uploads == []
