import json
import importlib.util
from pathlib import Path


HOOK_PATH = Path(__file__).resolve().parents[2] / "hooks" / "kiro" / "tokenleague.py"
ENV_EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "hooks" / "kiro" / "tokenleague.env.example"
INSTALL_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "install_hooks.sh"
DOCS_PATH = Path(__file__).resolve().parents[2] / "docs" / "HOOKS.md"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("tokenleague_kiro_hook", HOOK_PATH)
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


def test_kiro_assets_and_installer_stage_manual_hook_files():
    assert HOOK_PATH.exists()
    assert ENV_EXAMPLE_PATH.exists()

    content = INSTALL_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "--kiro" in content
    assert "install_kiro_hooks" in content
    assert "uninstall_kiro_hooks" in content
    assert ".kiro/hooks/tokenleague.py" in content
    assert ".kiro/hooks/tokenleague.env.example" in content


def test_docs_do_not_expose_kiro_hook_setup():
    content = DOCS_PATH.read_text(encoding="utf-8")

    assert "Kiro" not in content
    assert "Agent Hooks" not in content
    assert "Prompt Submit" not in content
    assert "Agent Stop" not in content
    assert ".kiro/hooks/tokenleague.py" not in content


def test_detect_project_name_uses_repo_root_for_git_worktree(tmp_path):
    hook = _load_hook_module()
    worktree_dir = _make_git_worktree_path(tmp_path, "TokenLeague", "kiro-hook-support")

    assert hook._detect_project_name(str(worktree_dir)) == "TokenLeague"


def test_handle_prompt_submit_returns_env_configuration_message(monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TOKENLEAGUE_API_URL", "http://192.168.9.11:5006")
    monkeypatch.setenv("TOKENLEAGUE_HOOK_KEY", "a" * 32)

    message = hook._handle_prompt_submit({"hook_event_name": "PromptSubmit"})

    assert "TOKENLEAGUE_API_URL" in message
    assert "http://192.168.9.11:5006" in message
    assert "TOKENLEAGUE_HOOK_KEY" in message


def test_handle_agent_stop_parses_transcript_and_uploads_prompt_and_task_usage(tmp_path, monkeypatch):
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
                        "version": "0.9.0",
                        "message": {
                            "id": "msg-1",
                            "role": "assistant",
                            "model": "kiro-agent",
                            "content": [{"type": "text", "text": "好的主人"}],
                            "usage": {
                                "input_tokens": 2048,
                                "output_tokens": 144,
                                "cache_read_input_tokens": 64,
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

    hook._handle_agent_stop(
        {
            "session_id": "session-1",
            "transcript_path": str(transcript_path),
            "hook_event_name": "AgentStop",
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
                "input_token_count": 2048,
                "output_token_count": 144,
                "cached_input_token_count": 64,
                "agent_type": "kiro",
                "agent_version": "0.9.0",
                "model_name": "kiro-agent",
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
                "input_token_count": 2048,
                "output_token_count": 144,
                "cached_input_token_count": 64,
                "agent_type": "kiro",
                "agent_version": "0.9.0",
                "model_name": "kiro-agent",
            },
        ),
    ]
