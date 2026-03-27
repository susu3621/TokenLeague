import json
import importlib.util
from pathlib import Path


HOOK_PATH = Path(__file__).resolve().parents[2] / "hooks" / "workbuddy" / "tokenleague.py"
SETTINGS_PATH = Path(__file__).resolve().parents[2] / "hooks" / "workbuddy" / "settings.json"
INSTALL_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "install_hooks.sh"
DOCS_PATH = Path(__file__).resolve().parents[2] / "docs" / "HOOKS.md"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("tokenleague_workbuddy_hook", HOOK_PATH)
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


def test_workbuddy_settings_register_stop_and_session_lifecycle_hooks():
    payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

    assert set(payload["hooks"]) == {"SessionStart", "Stop", "SessionEnd"}
    assert payload["hooks"]["SessionStart"][0]["hooks"][0]["command"].endswith("tokenleague.py SessionStart")
    assert payload["hooks"]["Stop"][0]["hooks"][0]["command"].endswith("tokenleague.py Stop")
    assert payload["hooks"]["SessionEnd"][0]["hooks"][0]["command"].endswith("tokenleague.py SessionEnd")


def test_install_script_supports_workbuddy_settings():
    content = INSTALL_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "--workbuddy" in content
    assert "install_workbuddy_hooks" in content
    assert "uninstall_workbuddy_hooks" in content
    assert ".codebuddy/settings.json" in content


def test_docs_describe_workbuddy_hooks_installation():
    content = DOCS_PATH.read_text(encoding="utf-8")

    assert "Workbuddy" in content
    assert "CodeBuddy" in content
    assert ".codebuddy/settings.json" in content


def test_detect_project_name_uses_repo_root_for_git_worktree(tmp_path):
    hook = _load_hook_module()
    worktree_dir = _make_git_worktree_path(tmp_path, "TokenLeague", "workbuddy-hook-support")

    assert hook._detect_project_name(str(worktree_dir)) == "TokenLeague"


def test_handle_session_start_returns_env_configuration_message(monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TOKENLEAGUE_API_URL", "http://192.168.9.11:5006")
    monkeypatch.setenv("TOKENLEAGUE_HOOK_KEY", "a" * 32)

    payload = hook._handle_session_start({"session_id": "session-1"})

    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "TOKENLEAGUE_API_URL" in payload["hookSpecificOutput"]["additionalContext"]
    assert "http://192.168.9.11:5006" in payload["hookSpecificOutput"]["additionalContext"]
    assert "TOKENLEAGUE_HOOK_KEY" in payload["systemMessage"]


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
                        "version": "1.2.3",
                        "message": {
                            "id": "msg-1",
                            "role": "assistant",
                            "model": "hunyuan-turbo",
                            "content": [{"type": "text", "text": "好的主人"}],
                            "usage": {
                                "input_tokens": 4096,
                                "output_tokens": 256,
                                "cache_read_input_tokens": 128,
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
                "prompt_started_at": "2026-03-27T08:26:37.824Z",
                "prompt_finished_at": "2026-03-27T08:26:56.851Z",
                "input_token_count": 4096,
                "output_token_count": 256,
                "cached_input_token_count": 128,
                "agent_type": "workbuddy",
                "agent_version": "1.2.3",
                "model_name": "hunyuan-turbo",
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
                "input_token_count": 4096,
                "output_token_count": 256,
                "cached_input_token_count": 128,
                "agent_type": "workbuddy",
                "agent_version": "1.2.3",
                "model_name": "hunyuan-turbo",
            },
        ),
    ]
