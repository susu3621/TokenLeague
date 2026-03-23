import json
import importlib.util
from pathlib import Path


HOOK_PATH = Path(__file__).resolve().parents[2] / ".codex" / "hooks" / "tokenleague.py"
HOOKS_CONFIG_PATH = Path(__file__).resolve().parents[2] / ".codex" / "hooks.json"
INSTALL_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "install_hooks.sh"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("tokenleague_codex_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_codex_hooks_json_registers_user_prompt_submit_and_stop_hooks():
    payload = json.loads(HOOKS_CONFIG_PATH.read_text(encoding="utf-8"))

    assert set(payload["hooks"]) == {"UserPromptSubmit", "Stop"}
    assert payload["hooks"]["UserPromptSubmit"][0]["hooks"][0]["timeoutSec"] == 10
    assert payload["hooks"]["Stop"][0]["hooks"][0]["timeoutSec"] == 10


def test_install_script_uses_codex_hooks_json_and_enables_feature_flag():
    content = INSTALL_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "write_codex_hooks_config" in content
    assert 'hooks.json"' in content
    assert "config.toml" in content
    assert "codex_hooks = true" in content
    assert ".codex/settings.json" not in content


def test_handle_user_prompt_submit_persists_session_state(tmp_path, monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(hook, "_iso_timestamp", lambda dt=None: "2026-03-23T08:00:00+00:00")

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
    assert state == {
        "session_id": "session-1",
        "transcript_path": "/tmp/session-1.jsonl",
        "model_name": "gpt-5.4",
        "cwd": "/Users/juns/project/TokenLeague",
        "prompt_started_ats": ["2026-03-23T08:00:00+00:00"],
    }


def test_handle_stop_parses_transcript_and_uploads_prompt_and_task_usage(tmp_path, monkeypatch):
    hook = _load_hook_module()
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    monkeypatch.setattr(hook, "_write_hook_log", lambda *args, **kwargs: None)
    timestamps = iter(
        [
            "2026-03-23T08:00:00+00:00",
            "2026-03-23T08:01:00+00:00",
        ]
    )
    monkeypatch.setattr(hook, "_iso_timestamp", lambda dt=None: next(timestamps))

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
                json.dumps(
                    {
                        "timestamp": "2026-03-23T08:00:01.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": None,
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-23T08:00:05.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "last_token_usage": {
                                    "input_tokens": 100,
                                    "cached_input_tokens": 20,
                                    "output_tokens": 40,
                                    "total_tokens": 140,
                                }
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-23T08:01:15.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "last_token_usage": {
                                    "input_tokens": 80,
                                    "cached_input_tokens": 10,
                                    "output_tokens": 30,
                                    "total_tokens": 110,
                                }
                            },
                        },
                    }
                ),
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
                "external_event_id": "session-1:prompt:1",
                "task_id": "session-1",
                "prompt_started_at": "2026-03-23T08:00:00+00:00",
                "prompt_finished_at": "2026-03-23T08:00:05.000Z",
                "input_token_count": 100,
                "output_token_count": 40,
                "agent_type": "codex",
                "agent_version": "0.116.0",
                "model_name": "gpt-5.4",
            },
        ),
        (
            "/api/ingest/prompt-event",
            {
                "external_event_id": "session-1:prompt:2",
                "task_id": "session-1",
                "prompt_started_at": "2026-03-23T08:01:00+00:00",
                "prompt_finished_at": "2026-03-23T08:01:15.000Z",
                "input_token_count": 80,
                "output_token_count": 30,
                "agent_type": "codex",
                "agent_version": "0.116.0",
                "model_name": "gpt-5.4",
            },
        ),
        (
            "/api/ingest/task-run",
            {
                "external_task_id": "session-1",
                "started_at": "2026-03-23T08:00:00+00:00",
                "finished_at": "2026-03-23T08:01:15.000Z",
                "prompt_count": 2,
                "input_token_count": 180,
                "output_token_count": 70,
                "agent_type": "codex",
                "agent_version": "0.116.0",
                "model_name": "gpt-5.4",
            },
        ),
    ]
    assert hook._load_session_state("session-1") == {}
