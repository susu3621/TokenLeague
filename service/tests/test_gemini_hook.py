import json
import importlib.util
import os
from pathlib import Path


HOOK_PATH = Path(__file__).resolve().parents[2] / "hooks" / "gemini" / "tokenleague.py"
SETTINGS_PATH = Path(__file__).resolve().parents[2] / "hooks" / "gemini" / "settings.json"
INSTALL_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "install_hooks.sh"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("tokenleague_gemini_hook", HOOK_PATH)
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


def _write_gemini_chat_session(
    root: Path,
    *,
    session_id: str,
    started_at: str,
    prompt: str,
    finished_at: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int,
    model: str = "gemini-3-flash-preview",
) -> Path:
    session_path = root / ".gemini" / "tmp" / "tokenleague" / "chats" / "session-2026-03-26T00-00-test.json"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        json.dumps(
            {
                "sessionId": session_id,
                "startTime": started_at,
                "lastUpdated": finished_at,
                "messages": [
                    {
                        "id": "user-1",
                        "timestamp": started_at,
                        "type": "user",
                        "content": [{"text": prompt}],
                    },
                    {
                        "id": "gemini-1",
                        "timestamp": finished_at,
                        "type": "gemini",
                        "content": "done",
                        "tokens": {
                            "input": input_tokens,
                            "output": output_tokens,
                            "cached": cached_tokens,
                            "thoughts": 0,
                            "tool": 0,
                            "total": input_tokens + output_tokens,
                        },
                        "model": model,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return session_path


def test_gemini_settings_register_expected_hooks():
    payload = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))

    assert set(payload["hooks"]) == {
        "SessionStart",
        "BeforeAgent",
        "AfterModel",
        "AfterAgent",
        "SessionEnd",
    }
    assert payload["hooks"]["SessionStart"][0]["matcher"] == "startup"
    assert payload["hooks"]["BeforeAgent"][0]["matcher"] == "*"
    assert payload["hooks"]["SessionEnd"][0]["matcher"] == "exit"
    assert payload["hooks"]["AfterAgent"][0]["hooks"][0]["timeout"] == 5000


def test_install_script_supports_gemini_settings():
    content = INSTALL_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "--gemini" in content
    assert "install_gemini_hooks" in content
    assert "uninstall_gemini_hooks" in content
    assert ".gemini/settings.json" in content


def test_detect_project_name_uses_repo_root_for_git_worktree(tmp_path):
    hook = _load_hook_module()
    worktree_dir = _make_git_worktree_path(tmp_path, "TokenLeague", "openclaw-hook-support")

    assert hook._detect_project_name(str(worktree_dir)) == "TokenLeague"


def test_handle_session_start_returns_env_configuration_message(monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TOKENLEAGUE_API_URL", "http://192.168.9.11:5006")
    monkeypatch.setenv("TOKENLEAGUE_HOOK_KEY", "a" * 32)

    payload = hook._handle_session_start(
        {
            "session_id": "session-1",
            "hook_event_name": "SessionStart",
            "source": "startup",
        }
    )

    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    # Check for the presence of configuration info (may include ANSI color codes)
    assert "TOKENLEAGUE_API_URL" in payload["systemMessage"]
    assert "http://192.168.9.11:5006" in payload["systemMessage"]
    assert "TOKENLEAGUE_HOOK_KEY" in payload["systemMessage"]
    assert "configured" in payload["systemMessage"]


def test_handle_before_agent_initializes_pending_turn_state(tmp_path, monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    hook._handle_before_agent(
        {
            "session_id": "session-1",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": "2026-03-24T08:00:01.000Z",
            "prompt": "track this turn",
            "hook_event_name": "BeforeAgent",
        }
    )

    state = hook._load_session_state("session-1")
    assert state["session_id"] == "session-1"
    assert state["cwd"] == "/Users/juns/project/TokenLeague"
    assert state["project_name"] == "TokenLeague"
    assert state["task_run"]["prompt_count"] == 0
    assert state["pending_turn"]["prompt"] == "track this turn"
    assert state["pending_turn"]["started_at"] == "2026-03-24T08:00:01.000Z"
    assert state["pending_turn"]["latest_usage"] == {}


def test_handle_after_agent_uploads_prompt_and_task_usage(tmp_path, monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("TOKENLEAGUE_GEMINI_CLI_VERSION", "0.34.0")
    monkeypatch.setattr(hook, "_write_hook_log", lambda *args, **kwargs: None)

    hook._handle_before_agent(
        {
            "session_id": "session-1",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": "2026-03-24T08:01:00.000Z",
            "prompt": "summarize the repo",
            "hook_event_name": "BeforeAgent",
        }
    )
    hook._handle_after_model(
        {
            "session_id": "session-1",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": "2026-03-24T08:01:05.000Z",
            "hook_event_name": "AfterModel",
            "llm_request": {
                "model": "gemini-2.5-pro",
                "messages": [{"role": "user", "content": "summarize the repo"}],
            },
            "llm_response": {
                "responseId": "resp-1",
                "modelVersion": "gemini-2.5-pro-001",
                "usageMetadata": {
                    "promptTokenCount": 120,
                    "candidatesTokenCount": 45,
                    "totalTokenCount": 165,
                },
            },
        }
    )

    uploads = []

    def fake_send_api_request(endpoint, payload):
        uploads.append((endpoint, payload))
        return True

    monkeypatch.setattr(hook, "_send_api_request", fake_send_api_request)

    hook._handle_after_agent(
        {
            "session_id": "session-1",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": "2026-03-24T08:01:08.000Z",
            "prompt": "summarize the repo",
            "prompt_response": "done",
            "hook_event_name": "AfterAgent",
        }
    )

    assert uploads == [
        (
            "/api/ingest/prompt-event",
            {
                "external_event_id": "resp-1",
                "task_id": "session-1",
                "project_name": "TokenLeague",
                "prompt_started_at": "2026-03-24T08:01:00.000Z",
                "prompt_finished_at": "2026-03-24T08:01:08.000Z",
                "input_token_count": 120,
                "output_token_count": 45,
                "cached_input_token_count": 0,
                "agent_type": "gemini-cli",
                "agent_version": "0.34.0",
                "model_name": "gemini-2.5-pro",
            },
        ),
        (
            "/api/ingest/task-run",
            {
                "external_task_id": "session-1",
                "project_name": "TokenLeague",
                "started_at": "2026-03-24T08:01:00.000Z",
                "finished_at": "2026-03-24T08:01:08.000Z",
                "prompt_count": 1,
                "input_token_count": 120,
                "output_token_count": 45,
                "cached_input_token_count": 0,
                "agent_type": "gemini-cli",
                "agent_version": "0.34.0",
                "model_name": "gemini-2.5-pro",
            },
        ),
    ]

    state = hook._load_session_state("session-1")
    assert state["task_run"]["prompt_count"] == 1
    assert state["task_run"]["input_token_count"] == 120
    assert state["task_run"]["output_token_count"] == 45
    assert state["task_run"]["cached_input_token_count"] == 0
    assert state["pending_turn"] == {}


def test_handle_after_agent_falls_back_to_total_token_count(tmp_path, monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(hook, "_write_hook_log", lambda *args, **kwargs: None)

    hook._handle_before_agent(
        {
            "session_id": "session-2",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": "2026-03-24T08:02:00.000Z",
            "prompt": "fallback tokens",
            "hook_event_name": "BeforeAgent",
        }
    )
    hook._handle_after_model(
        {
            "session_id": "session-2",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": "2026-03-24T08:02:04.000Z",
            "hook_event_name": "AfterModel",
            "llm_request": {
                "model": "gemini-2.5-flash",
                "messages": [{"role": "user", "content": "fallback tokens"}],
            },
            "llm_response": {
                "usageMetadata": {
                    "totalTokenCount": 77,
                },
            },
        }
    )

    uploads = []

    def fake_send_api_request(endpoint, payload):
        uploads.append((endpoint, payload))
        return True

    monkeypatch.setattr(hook, "_send_api_request", fake_send_api_request)

    hook._handle_after_agent(
        {
            "session_id": "session-2",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": "2026-03-24T08:02:06.000Z",
            "prompt": "fallback tokens",
            "prompt_response": "done",
            "hook_event_name": "AfterAgent",
        }
    )

    assert uploads[0][1]["input_token_count"] == 77
    assert uploads[0][1]["output_token_count"] == 0
    assert uploads[1][1]["input_token_count"] == 77
    assert uploads[1][1]["output_token_count"] == 0


def test_handle_after_agent_falls_back_to_local_chat_cache_tokens(tmp_path, monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TOKENLEAGUE_GEMINI_CLI_VERSION", "0.35.0")
    monkeypatch.setattr(hook, "_write_hook_log", lambda *args, **kwargs: None)

    started_at = "2026-03-25T23:26:00.415Z"
    finished_at = "2026-03-25T23:26:52.315Z"
    _write_gemini_chat_session(
        tmp_path,
        session_id="session-cache-1",
        started_at=started_at,
        prompt="你好",
        finished_at=finished_at,
        input_tokens=8157,
        output_tokens=21,
        cached_tokens=6045,
    )

    hook._handle_before_agent(
        {
            "session_id": "session-cache-1",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": started_at,
            "prompt": "你好",
            "hook_event_name": "BeforeAgent",
        }
    )
    hook._handle_after_model(
        {
            "session_id": "session-cache-1",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": "2026-03-25T23:26:51.000Z",
            "hook_event_name": "AfterModel",
            "llm_request": {
                "model": "gemini-3-flash-preview",
                "messages": [{"role": "user", "content": "你好"}],
            },
            "llm_response": {
                "usageMetadata": {
                    "promptTokenCount": 8157,
                    "candidatesTokenCount": 21,
                    "totalTokenCount": 8178,
                },
            },
        }
    )

    uploads = []

    def fake_send_api_request(endpoint, payload):
        uploads.append((endpoint, payload))
        return True

    monkeypatch.setattr(hook, "_send_api_request", fake_send_api_request)

    hook._handle_after_agent(
        {
            "session_id": "session-cache-1",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": finished_at,
            "prompt": "你好",
            "prompt_response": "done",
            "hook_event_name": "AfterAgent",
        }
    )

    assert uploads[0][1]["cached_input_token_count"] == 6045
    assert uploads[1][1]["cached_input_token_count"] == 6045
    state = hook._load_session_state("session-cache-1")
    assert state["task_run"]["cached_input_token_count"] == 6045


def test_handle_after_agent_detects_gemini_cli_version_from_binary_path(tmp_path, monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("TOKENLEAGUE_GEMINI_CLI_VERSION", raising=False)
    monkeypatch.setattr(hook, "_write_hook_log", lambda *args, **kwargs: None)

    cellar_bin = tmp_path / "Cellar" / "gemini-cli" / "0.34.0" / "bin"
    cellar_bin.mkdir(parents=True)
    real_binary = cellar_bin / "gemini"
    real_binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    real_binary.chmod(0o755)

    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir()
    shim_binary = shim_dir / "gemini"
    shim_binary.symlink_to(real_binary)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    hook._handle_before_agent(
        {
            "session_id": "session-3",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": "2026-03-24T08:03:00.000Z",
            "prompt": "detect cli version",
            "hook_event_name": "BeforeAgent",
        }
    )
    hook._handle_after_model(
        {
            "session_id": "session-3",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": "2026-03-24T08:03:04.000Z",
            "hook_event_name": "AfterModel",
            "llm_request": {
                "model": "gemini-2.5-pro",
                "messages": [{"role": "user", "content": "detect cli version"}],
            },
            "llm_response": {
                "responseId": "resp-3",
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 4,
                    "totalTokenCount": 14,
                },
            },
        }
    )

    uploads = []

    def fake_send_api_request(endpoint, payload):
        uploads.append((endpoint, payload))
        return True

    monkeypatch.setattr(hook, "_send_api_request", fake_send_api_request)

    hook._handle_after_agent(
        {
            "session_id": "session-3",
            "cwd": "/Users/juns/project/TokenLeague",
            "timestamp": "2026-03-24T08:03:06.000Z",
            "prompt": "detect cli version",
            "prompt_response": "done",
            "hook_event_name": "AfterAgent",
        }
    )

    assert uploads[0][1]["agent_version"] == "0.34.0"
    assert uploads[1][1]["agent_version"] == "0.34.0"
