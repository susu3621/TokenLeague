import importlib.util
import json
from pathlib import Path
import urllib.request


HOOK_PATH = Path(__file__).resolve().parents[2] / "hooks" / "openclaw" / "tokenleague_collect.py"
INSTALL_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "install_hooks.sh"
SYSTEMD_SERVICE_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "hooks"
    / "openclaw"
    / "tokenleague-openclaw-collector.service"
)
SYSTEMD_TIMER_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "hooks"
    / "openclaw"
    / "tokenleague-openclaw-collector.timer"
)


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


def _write_openclaw_gateway_session(
    root: Path,
    *,
    agent_id: str = "main",
    session_id: str = "session-1",
    project_name: str = "TokenLeague",
) -> Path:
    repo_root = root / "repos" / project_name
    (repo_root / ".git").mkdir(parents=True)

    sessions_dir = root / "agents" / agent_id / "sessions"
    sessions_dir.mkdir(parents=True)
    transcript_path = sessions_dir / f"{session_id}.jsonl"
    transcript_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "session",
                        "version": 3,
                        "id": session_id,
                        "timestamp": "2026-03-24T09:00:00.000Z",
                        "cwd": str(repo_root),
                    }
                ),
                json.dumps(
                    {
                        "type": "model_change",
                        "id": "model-1",
                        "parentId": None,
                        "timestamp": "2026-03-24T09:00:00.100Z",
                        "provider": "zai",
                        "modelId": "glm-5",
                    }
                ),
                json.dumps(
                    {
                        "type": "message",
                        "id": "turn-1-user",
                        "parentId": "model-1",
                        "timestamp": "2026-03-24T09:00:01.000Z",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "帮我搜一下今天的热搜"}],
                            "timestamp": 1774342801000,
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "message",
                        "id": "turn-1-assistant",
                        "parentId": "turn-1-user",
                        "timestamp": "2026-03-24T09:00:15.000Z",
                        "message": {
                            "role": "assistant",
                            "model": "glm-5",
                            "content": [{"type": "text", "text": "我来帮你搜一下今天的热搜。"}],
                            "usage": {
                                "input": 5338,
                                "output": 187,
                                "cacheRead": 4096,
                                "cacheWrite": 0,
                                "totalTokens": 9621,
                            },
                            "timestamp": 1774342815000,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (sessions_dir / "sessions.json").write_text(
        json.dumps(
            {
                f"agent:{agent_id}:{agent_id}": {
                    "sessionId": session_id,
                    "updatedAt": 1774342815000,
                    "sessionFile": str(transcript_path),
                    "chatType": "direct",
                }
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return transcript_path


def test_install_script_supports_openclaw_assets():
    content = INSTALL_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "--openclaw" in content
    assert "install_openclaw_hooks" in content
    assert "uninstall_openclaw_hooks" in content
    assert ".openclaw/tokenleague_collect.py" in content
    assert "tokenleague-openclaw-collector.service" in content
    assert "tokenleague-openclaw-collector.timer" in content
    assert "systemctl daemon-reload" in content
    assert "systemctl enable --now tokenleague-openclaw-collector.timer" in content


def test_openclaw_systemd_templates_exist_and_poll_every_minute():
    service_template = SYSTEMD_SERVICE_TEMPLATE_PATH.read_text(encoding="utf-8")
    timer_template = SYSTEMD_TIMER_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert "User={{OPENCLAW_USER}}" in service_template
    assert "ExecStart={{PYTHON_BIN}} {{COLLECTOR_PATH}}" in service_template
    assert "Environment=HOME={{OPENCLAW_HOME}}" in service_template
    assert "OnUnitActiveSec=1min" in timer_template
    assert "WantedBy=timers.target" in timer_template


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
                "project_name": "OpenClaw",
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
                "project_name": "OpenClaw",
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


def test_collect_session_uploads_prompt_and_task_usage_from_gateway_schema(tmp_path, monkeypatch):
    hook = _load_hook_module()
    openclaw_root = tmp_path / ".openclaw"
    _write_openclaw_gateway_session(openclaw_root)
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
                "project_name": "OpenClaw",
                "prompt_started_at": "2026-03-24T09:00:01.000Z",
                "prompt_finished_at": "2026-03-24T09:00:15.000Z",
                "input_token_count": 5338,
                "output_token_count": 187,
                "agent_type": "openclaw",
                "agent_version": "unknown",
                "model_name": "glm-5",
            },
        ),
        (
            "/api/ingest/task-run",
            {
                "external_task_id": "session-1",
                "project_name": "OpenClaw",
                "started_at": "2026-03-24T09:00:00.000Z",
                "finished_at": "2026-03-24T09:00:15.000Z",
                "prompt_count": 1,
                "input_token_count": 5338,
                "output_token_count": 187,
                "agent_type": "openclaw",
                "agent_version": "unknown",
                "model_name": "glm-5",
            },
        ),
    ]


def test_collect_session_reads_openclaw_env_file_with_export_prefix(tmp_path, monkeypatch):
    hook = _load_hook_module()
    openclaw_root = tmp_path / ".openclaw"
    _write_openclaw_gateway_session(openclaw_root)
    (openclaw_root / ".env").write_text(
        "export TOKENLEAGUE_HOOK_KEY=test-hook-key\n"
        "export TOKENLEAGUE_API_URL=http://192.168.9.11:5006\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TOKENLEAGUE_OPENCLAW_ROOT", str(openclaw_root))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.delenv("TOKENLEAGUE_HOOK_KEY", raising=False)
    monkeypatch.delenv("TOKENLEAGUE_API_URL", raising=False)

    requests = []

    class _Response:
        def __init__(self, status: int):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request: urllib.request.Request, timeout: int = 5):
        headers = {key.lower(): value for key, value in request.header_items()}
        requests.append(
            {
                "url": request.full_url,
                "hook_key": headers.get("x-hook-key"),
            }
        )
        return _Response(200)

    monkeypatch.setattr(hook.urllib.request, "urlopen", fake_urlopen)

    assert hook.collect_and_upload() == 0
    assert requests
    assert requests[0]["url"].startswith("http://192.168.9.11:5006/")
    assert requests[0]["hook_key"] == "test-hook-key"


def test_get_openclaw_version_detects_installed_cli_from_binary_package_json(tmp_path, monkeypatch):
    hook = _load_hook_module()
    package_root = tmp_path / "lib" / "node_modules" / "openclaw"
    binary_dir = package_root / "bin"
    binary_dir.mkdir(parents=True)
    (package_root / "package.json").write_text(
        json.dumps({"name": "openclaw", "version": "2026.3.13"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    binary_path = binary_dir / "openclaw"
    binary_path.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    monkeypatch.delenv("TOKENLEAGUE_OPENCLAW_VERSION", raising=False)
    monkeypatch.setattr(hook.shutil, "which", lambda name: str(binary_path) if name == "openclaw" else None)
    if hasattr(hook, "_OPENCLAW_VERSION_CACHE"):
        monkeypatch.setattr(hook, "_OPENCLAW_VERSION_CACHE", None)

    assert hook._get_openclaw_version() == "2026.3.13"


def test_get_openclaw_version_prefers_openclaw_command_output(monkeypatch):
    hook = _load_hook_module()
    monkeypatch.delenv("TOKENLEAGUE_OPENCLAW_VERSION", raising=False)
    monkeypatch.setattr(hook.shutil, "which", lambda name: "/usr/local/bin/openclaw" if name == "openclaw" else None)
    if hasattr(hook, "_OPENCLAW_VERSION_CACHE"):
        monkeypatch.setattr(hook, "_OPENCLAW_VERSION_CACHE", None)

    calls = []

    class _CompletedProcess:
        stdout = "OpenClaw 2026.3.13 (61d171a)\n"

    def fake_run(args, capture_output, text, timeout, check):
        calls.append(args)
        return _CompletedProcess()

    monkeypatch.setattr(hook, "subprocess", type("_SubprocessModule", (), {"run": staticmethod(fake_run)}), raising=False)
    monkeypatch.setattr(hook, "_detect_openclaw_version_from_binary", lambda binary_path: "2025.1.1")

    assert hook._get_openclaw_version() == "2026.3.13"
    assert calls == [["/usr/local/bin/openclaw", "--version"]]


def test_collect_session_writes_summary_log_when_no_sessions_found(tmp_path, monkeypatch):
    hook = _load_hook_module()
    openclaw_root = tmp_path / ".openclaw"
    openclaw_root.mkdir()
    monkeypatch.setenv("TOKENLEAGUE_OPENCLAW_ROOT", str(openclaw_root))
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    assert hook.collect_and_upload() == 0

    log_path = tmp_path / hook.HOOK_LOG_FILE_NAME
    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "collector_started" in log_text
    assert "collector_finished" in log_text
    assert '"discovered_session_count": 0' in log_text
