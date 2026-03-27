import io
import json
import importlib.util
from pathlib import Path

import pytest


HOOK_PATH = Path(__file__).resolve().parents[2] / "hooks" / "cursor" / "tokenleague.py"
HOOKS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "hooks" / "cursor" / "hooks.json"
INSTALL_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "install_hooks.sh"
DOCS_PATH = Path(__file__).resolve().parents[2] / "docs" / "HOOKS.md"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("tokenleague_cursor_hook", HOOK_PATH)
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


def test_cursor_hooks_json_registers_session_start_stop_and_session_end_hooks():
    payload = json.loads(HOOKS_CONFIG_PATH.read_text(encoding="utf-8"))

    assert payload["version"] == 1
    assert set(payload["hooks"]) == {"sessionStart", "stop", "sessionEnd"}
    assert payload["hooks"]["sessionStart"][0]["command"].endswith("tokenleague.py sessionStart")
    assert payload["hooks"]["stop"][0]["command"].endswith("tokenleague.py stop")
    assert payload["hooks"]["sessionEnd"][0]["command"].endswith("tokenleague.py sessionEnd")


def test_install_script_supports_cursor_hooks_json():
    content = INSTALL_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "--cursor" in content
    assert "install_cursor_hooks" in content
    assert "uninstall_cursor_hooks" in content
    assert ".cursor/hooks.json" in content


def test_docs_describe_cursor_hooks_installation():
    content = DOCS_PATH.read_text(encoding="utf-8")

    assert "Cursor" in content
    assert ".cursor/hooks.json" in content
    assert ".cursor/hooks/tokenleague.py" in content


def test_detect_project_name_uses_repo_root_for_git_worktree(tmp_path):
    hook = _load_hook_module()
    worktree_dir = _make_git_worktree_path(tmp_path, "TokenLeague", "cursor-hook-support")

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
                        "timestamp": "2026-03-27T08:26:37.824Z",
                        "message": {"role": "user", "content": "你好"},
                    }
                ),
                json.dumps(
                    {
                        "uuid": "assistant-1",
                        "parentUuid": "user-1",
                        "type": "assistant",
                        "timestamp": "2026-03-27T08:26:56.851Z",
                        "version": "1.0.0",
                        "message": {
                            "id": "msg-1",
                            "role": "assistant",
                            "model": "cursor-fast",
                            "content": [{"type": "text", "text": "好的主人"}],
                            "usage": {
                                "input_tokens": 34521,
                                "output_tokens": 85,
                                "cache_read_input_tokens": 1024,
                                "cache_creation_input_tokens": 0,
                            },
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
            "hook_event_name": "stop",
        }
    )

    assert uploads == [
        (
            "/api/ingest/prompt-event",
            {
                "external_event_id": "msg-1",
                "task_id": "session-1",
                "project_name": "TokenLeague",
                "prompt_started_at": "2026-03-27T08:26:37.824Z",
                "prompt_finished_at": "2026-03-27T08:26:56.851Z",
                "input_token_count": 34521,
                "output_token_count": 85,
                "cached_input_token_count": 1024,
                "agent_type": "cursor",
                "agent_version": "1.0.0",
                "model_name": "cursor-fast",
            },
        ),
        (
            "/api/ingest/task-run",
            {
                "external_task_id": "session-1",
                "project_name": "TokenLeague",
                "started_at": "2026-03-27T08:26:37.824Z",
                "finished_at": "2026-03-27T08:26:56.851Z",
                "prompt_count": 1,
                "input_token_count": 34521,
                "output_token_count": 85,
                "cached_input_token_count": 1024,
                "agent_type": "cursor",
                "agent_version": "1.0.0",
                "model_name": "cursor-fast",
            },
        ),
    ]


def test_main_routes_cli_session_end_to_stop(monkeypatch):
    hook = _load_hook_module()
    calls = []
    event_data = {
        "session_id": "session-1",
        "transcript_path": "/tmp/transcript.jsonl",
    }

    monkeypatch.setattr(hook, "_handle_stop", lambda payload: calls.append(payload))
    monkeypatch.setattr(hook.sys, "stdin", io.StringIO(json.dumps(event_data)))
    monkeypatch.setattr(hook.sys, "argv", ["tokenleague.py", "sessionEnd"])

    with pytest.raises(SystemExit) as exc_info:
        hook.main()

    assert exc_info.value.code == 0
    assert calls == [event_data]
