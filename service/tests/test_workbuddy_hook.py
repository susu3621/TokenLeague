import json
import importlib.util
from pathlib import Path

import pytest


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


def _write_workbuddy_transcript(
    path: Path,
    requests: list[dict] | None = None,
    messages: list[dict] | None = None,
) -> Path:
    if requests is None:
        requests = []
    if messages is None:
        messages = []
    data = {"messages": messages, "requests": requests}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


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
    assert ".workbuddy/settings.json" in content


def test_docs_describe_workbuddy_hooks_installation():
    content = DOCS_PATH.read_text(encoding="utf-8")

    assert "Workbuddy" in content or "WorkBuddy" in content
    assert "CodeBuddy" in content
    assert ".workbuddy/settings.json" in content


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


def test_parse_workbuddy_transcript_extracts_usage_from_complete_requests(tmp_path):
    hook = _load_hook_module()

    transcript_path = _write_workbuddy_transcript(
        tmp_path / "session" / "index.json",
        requests=[
            {
                "id": "req-001",
                "type": "craft",
                "messages": ["msg-user-1", "msg-assistant-1"],
                "state": "complete",
                "startedAt": 1774936850964,
                "usage": {
                    "inputTokens": 23247,
                    "outputTokens": 27,
                    "totalTokens": 23274,
                },
            },
        ],
        messages=[
            {"id": "msg-user-1", "type": "text", "role": "user", "isComplete": True},
            {"id": "msg-assistant-1", "type": "text", "role": "assistant", "isComplete": True},
        ],
    )

    prompt_events, task_run = hook._parse_workbuddy_transcript(
        str(transcript_path),
        "session-1",
        "TestProject",
        "1.0.0",
    )

    assert len(prompt_events) == 1
    assert prompt_events[0]["external_event_id"] == "req-001"
    assert prompt_events[0]["task_id"] == "session-1"
    assert prompt_events[0]["project_name"] == "TestProject"
    assert prompt_events[0]["input_token_count"] == 23247
    assert prompt_events[0]["output_token_count"] == 27
    assert prompt_events[0]["cached_input_token_count"] == 0
    assert prompt_events[0]["agent_type"] == "workbuddy"
    assert prompt_events[0]["agent_version"] == "1.0.0"
    assert prompt_events[0]["model_name"] == "unknown"

    assert task_run is not None
    assert task_run["external_task_id"] == "session-1"
    assert task_run["prompt_count"] == 1
    assert task_run["input_token_count"] == 23247
    assert task_run["output_token_count"] == 27


def test_parse_workbuddy_transcript_skips_incomplete_requests(tmp_path):
    hook = _load_hook_module()

    transcript_path = _write_workbuddy_transcript(
        tmp_path / "session" / "index.json",
        requests=[
            {
                "id": "req-pending",
                "type": "craft",
                "messages": ["m1"],
                "state": "pending",
                "startedAt": 1774936850964,
                "usage": {"inputTokens": 100, "outputTokens": 50, "totalTokens": 150},
            },
            {
                "id": "req-complete",
                "type": "craft",
                "messages": ["m2", "m3"],
                "state": "complete",
                "startedAt": 1774936860000,
                "usage": {"inputTokens": 500, "outputTokens": 100, "totalTokens": 600},
            },
        ],
    )

    prompt_events, task_run = hook._parse_workbuddy_transcript(
        str(transcript_path),
        "session-2",
        "TestProject",
        "1.0.0",
    )

    assert len(prompt_events) == 1
    assert prompt_events[0]["external_event_id"] == "req-complete"
    assert task_run is not None
    assert task_run["prompt_count"] == 1


def test_parse_workbuddy_transcript_handles_multiple_requests(tmp_path):
    hook = _load_hook_module()

    transcript_path = _write_workbuddy_transcript(
        tmp_path / "session" / "index.json",
        requests=[
            {
                "id": "req-1",
                "type": "craft",
                "messages": ["m1", "m2"],
                "state": "complete",
                "startedAt": 1774936850000,
                "usage": {"inputTokens": 100, "outputTokens": 50, "totalTokens": 150},
            },
            {
                "id": "req-2",
                "type": "craft",
                "messages": ["m3", "m4"],
                "state": "complete",
                "startedAt": 1774936860000,
                "usage": {"inputTokens": 200, "outputTokens": 80, "totalTokens": 280},
            },
        ],
    )

    prompt_events, task_run = hook._parse_workbuddy_transcript(
        str(transcript_path),
        "session-3",
        "TestProject",
        "1.0.0",
    )

    assert len(prompt_events) == 2
    assert task_run is not None
    assert task_run["prompt_count"] == 2
    assert task_run["input_token_count"] == 300
    assert task_run["output_token_count"] == 130


def test_parse_workbuddy_transcript_returns_empty_for_missing_file():
    hook = _load_hook_module()

    prompt_events, task_run = hook._parse_workbuddy_transcript(
        "/nonexistent/path/index.json",
        "session-x",
        "TestProject",
        "1.0.0",
    )

    assert prompt_events == []
    assert task_run is None


def test_parse_workbuddy_transcript_returns_empty_for_empty_requests(tmp_path):
    hook = _load_hook_module()

    transcript_path = _write_workbuddy_transcript(tmp_path / "session" / "index.json")

    prompt_events, task_run = hook._parse_workbuddy_transcript(
        str(transcript_path),
        "session-x",
        "TestProject",
        "1.0.0",
    )

    assert prompt_events == []
    assert task_run is None


def test_handle_stop_uploads_prompt_and_task_usage(tmp_path, monkeypatch):
    hook = _load_hook_module()

    transcript_path = _write_workbuddy_transcript(
        tmp_path / "session" / "index.json",
        requests=[
            {
                "id": "req-001",
                "type": "craft",
                "messages": ["m1", "m2"],
                "state": "complete",
                "startedAt": 1774936850964,
                "usage": {
                    "inputTokens": 23247,
                    "outputTokens": 27,
                    "totalTokens": 23274,
                },
            },
        ],
        messages=[
            {"id": "m1", "type": "text", "role": "user", "isComplete": True},
            {"id": "m2", "type": "text", "role": "assistant", "isComplete": True},
        ],
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

    prompt_events = [u for u in uploads if u[0] == "/api/ingest/prompt-event"]
    task_runs = [u for u in uploads if u[0] == "/api/ingest/task-run"]

    assert len(prompt_events) == 1
    assert prompt_events[0][1]["external_event_id"] == "req-001"
    assert prompt_events[0][1]["input_token_count"] == 23247
    assert prompt_events[0][1]["output_token_count"] == 27
    assert prompt_events[0][1]["agent_type"] == "workbuddy"

    assert len(task_runs) == 1
    assert task_runs[0][1]["external_task_id"] == "session-1"
    assert task_runs[0][1]["prompt_count"] == 1
    assert task_runs[0][1]["input_token_count"] == 23247
    assert task_runs[0][1]["output_token_count"] == 27
