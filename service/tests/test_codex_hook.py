import fcntl
import json
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


HOOK_PATH = Path(__file__).resolve().parents[2] / "hooks" / "codex" / "tokenleague.py"
HOOKS_CONFIG_PATH = Path(__file__).resolve().parents[2] / "hooks" / "codex" / "hooks.json"
INSTALL_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "install_hooks.sh"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("tokenleague_codex_hook", HOOK_PATH)
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


def _task_started(timestamp: str, turn_id: str) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "task_started",
            "turn_id": turn_id,
        },
    }


def _token_count(timestamp: str, input_tokens: int, output_tokens: int) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": input_tokens,
                    "cached_input_tokens": 0,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                }
            },
        },
    }


def _task_complete(timestamp: str, turn_id: str) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "task_complete",
            "turn_id": turn_id,
        },
    }


def test_codex_hooks_json_registers_user_prompt_submit_and_stop_hooks():
    payload = json.loads(HOOKS_CONFIG_PATH.read_text(encoding="utf-8"))

    assert set(payload["hooks"]) == {"UserPromptSubmit", "Stop"}
    assert payload["hooks"]["UserPromptSubmit"][0]["hooks"][0]["timeoutSec"] == 10
    assert payload["hooks"]["Stop"][0]["hooks"][0]["timeoutSec"] == 30


def test_install_script_uses_codex_hooks_json_and_enables_feature_flag():
    content = INSTALL_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "write_codex_hooks_config" in content
    assert 'hooks.json"' in content
    assert "config.toml" in content
    assert "codex_hooks = true" in content
    assert ".codex/settings.json" not in content


def test_install_script_can_install_codex_hooks_globally(tmp_path):
    home_dir = tmp_path / "home"
    home_dir.mkdir()

    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT_PATH), "--codex", "--global"],
        cwd=INSTALL_SCRIPT_PATH.parent.parent,
        env={"HOME": str(home_dir)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    hooks_config_path = home_dir / ".codex" / "hooks.json"
    payload = json.loads(hooks_config_path.read_text(encoding="utf-8"))

    assert set(payload["hooks"]) == {"UserPromptSubmit", "Stop"}
    assert payload["hooks"]["UserPromptSubmit"][0]["hooks"][0]["timeoutSec"] == 10
    assert payload["hooks"]["Stop"][0]["hooks"][0]["timeoutSec"] == 30


def test_detect_project_name_uses_repo_root_for_git_worktree(tmp_path):
    hook = _load_hook_module()
    worktree_dir = _make_git_worktree_path(tmp_path, "TokenLeague", "openclaw-hook-support")

    assert hook._detect_project_name(str(worktree_dir)) == "TokenLeague"


def test_handle_user_prompt_submit_persists_session_state(tmp_path, monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    hook._handle_user_prompt_submit(
        {
            "session_id": "session-1",
            "transcript_path": "/tmp/session-1.jsonl",
            "cwd": "/Users/juns/project/TokenLeague",
            "hook_event_name": "UserPromptSubmit",
            "model": "gpt-5.4",
        }
    )

    state = hook._load_session_state("session-1")
    assert state["session_id"] == "session-1"
    assert state["transcript_path"] == "/tmp/session-1.jsonl"
    assert state["model_name"] == "gpt-5.4"
    assert state["cwd"] == "/Users/juns/project/TokenLeague"
    assert state["project_name"] == "TokenLeague"
    assert state["processed_turn_ids"] == []
    assert state["task_run"]["prompt_count"] == 0
    assert state["task_run"]["input_token_count"] == 0
    assert state["task_run"]["output_token_count"] == 0


def test_handle_stop_uploads_latest_completed_turn_and_accumulates_task_run(tmp_path, monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    monkeypatch.setattr(hook, "_write_hook_log", lambda *args, **kwargs: None)

    transcript_path = tmp_path / "session.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-23T08:00:00.000Z",
                        "type": "session_meta",
                        "payload": {
                            "id": "session-1",
                            "timestamp": "2026-03-23T08:00:00.000Z",
                            "cwd": "/Users/juns/project/TokenLeague",
                            "cli_version": "0.116.0",
                        },
                    }
                ),
                json.dumps(_task_started("2026-03-23T08:00:01.000Z", "turn-1")),
                json.dumps(_token_count("2026-03-23T08:00:05.000Z", 100, 40)),
                json.dumps(_token_count("2026-03-23T08:00:08.000Z", 20, 10)),
                json.dumps(_task_complete("2026-03-23T08:00:09.000Z", "turn-1")),
            ]
        ),
        encoding="utf-8",
    )

    hook._handle_user_prompt_submit(
        {
            "session_id": "session-1",
            "transcript_path": str(transcript_path),
            "cwd": "/Users/juns/project/TokenLeague",
            "hook_event_name": "UserPromptSubmit",
            "model": "gpt-5.4",
        }
    )

    uploads = []

    def fake_send_api_request(endpoint, payload):
        uploads.append((endpoint, payload))
        return True

    monkeypatch.setattr(hook, "_send_api_request", fake_send_api_request)

    transcript_path.write_text(
        transcript_path.read_text(encoding="utf-8")
        + "\n"
        + "\n".join(
            [
                json.dumps(_task_started("2026-03-23T08:01:01.000Z", "turn-2")),
                json.dumps(_token_count("2026-03-23T08:01:05.000Z", 80, 30)),
                json.dumps(_token_count("2026-03-23T08:01:10.000Z", 5, 2)),
                json.dumps(_task_complete("2026-03-23T08:01:15.000Z", "turn-2")),
            ]
        ),
        encoding="utf-8",
    )

    hook._handle_stop(
        {
            "session_id": "session-1",
            "hook_event_name": "Stop",
        }
    )

    assert uploads == [
        (
            "/api/ingest/prompt-event",
            {
                "external_event_id": "session-1:turn:turn-2",
                "task_id": "session-1",
                "project_name": "TokenLeague",
                "prompt_started_at": "2026-03-23T08:01:01.000Z",
                "prompt_finished_at": "2026-03-23T08:01:15.000Z",
                "input_token_count": 85,
                "output_token_count": 32,
                "cached_input_token_count": 0,
                "agent_type": "codex",
                "agent_version": "0.116.0",
                "model_name": "gpt-5.4",
            },
        ),
        (
            "/api/ingest/task-run",
            {
                "external_task_id": "session-1",
                "project_name": "TokenLeague",
                "started_at": "2026-03-23T08:01:01.000Z",
                "finished_at": "2026-03-23T08:01:15.000Z",
                "prompt_count": 1,
                "input_token_count": 85,
                "output_token_count": 32,
                "cached_input_token_count": 0,
                "agent_type": "codex",
                "agent_version": "0.116.0",
                "model_name": "gpt-5.4",
            },
        ),
    ]
    state = hook._load_session_state("session-1")
    assert state["processed_turn_ids"] == ["turn-2"]
    assert state["task_run"]["prompt_count"] == 1
    assert state["task_run"]["input_token_count"] == 85
    assert state["task_run"]["output_token_count"] == 32

    uploads.clear()
    hook._handle_stop(
        {
            "session_id": "session-1",
            "hook_event_name": "Stop",
        }
    )
    assert uploads == []

    transcript_path.write_text(
        transcript_path.read_text(encoding="utf-8")
        + "\n"
        + "\n".join(
            [
                json.dumps(_task_started("2026-03-23T08:02:01.000Z", "turn-3")),
                json.dumps(_token_count("2026-03-23T08:02:05.000Z", 30, 12)),
                json.dumps(_task_complete("2026-03-23T08:02:07.000Z", "turn-3")),
            ]
        ),
        encoding="utf-8",
    )

    hook._handle_user_prompt_submit(
        {
            "session_id": "session-1",
            "transcript_path": str(transcript_path),
            "cwd": "/Users/juns/project/TokenLeague",
            "hook_event_name": "UserPromptSubmit",
            "model": "gpt-5.4",
        }
    )
    hook._handle_stop(
        {
            "session_id": "session-1",
            "hook_event_name": "Stop",
        }
    )

    assert uploads == [
        (
            "/api/ingest/prompt-event",
            {
                "external_event_id": "session-1:turn:turn-3",
                "task_id": "session-1",
                "project_name": "TokenLeague",
                "prompt_started_at": "2026-03-23T08:02:01.000Z",
                "prompt_finished_at": "2026-03-23T08:02:07.000Z",
                "input_token_count": 30,
                "output_token_count": 12,
                "cached_input_token_count": 0,
                "agent_type": "codex",
                "agent_version": "0.116.0",
                "model_name": "gpt-5.4",
            },
        ),
        (
            "/api/ingest/task-run",
            {
                "external_task_id": "session-1",
                "project_name": "TokenLeague",
                "started_at": "2026-03-23T08:01:01.000Z",
                "finished_at": "2026-03-23T08:02:07.000Z",
                "prompt_count": 2,
                "input_token_count": 115,
                "output_token_count": 44,
                "cached_input_token_count": 0,
                "agent_type": "codex",
                "agent_version": "0.116.0",
                "model_name": "gpt-5.4",
            },
        ),
    ]


def test_codex_hook_exits_quickly_when_session_lock_is_held(tmp_path):
    lock_path = tmp_path / ".tokenleague_codex_session_lock-test-session.lock"
    payload = json.dumps(
        {
            "session_id": "lock-test-session",
            "transcript_path": "/tmp/lock-test-session.jsonl",
            "hook_event_name": "UserPromptSubmit",
        }
    )
    env = {**os.environ, "TMPDIR": str(tmp_path)}

    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        result = subprocess.run(
            [sys.executable, str(HOOK_PATH)],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=1,
        )

    assert result.returncode == 0, result.stderr

    log_text = (tmp_path / ".tokenleague_codex_hook.log").read_text(encoding="utf-8")
    assert '"event": "session_lock_timeout"' in log_text
