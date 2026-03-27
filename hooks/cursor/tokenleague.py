#!/usr/bin/env python3
"""
TokenLeague Statistics Hook for Cursor.

This hook consumes Cursor transcript paths on stop-like events and uploads
aggregated usage statistics to TokenLeague.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any


def _load_common_module() -> None:
    search_dirs = [
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parents[1] / "common",
    ]
    for directory in search_dirs:
        candidate = directory / "tokenleague_transcript_hook.py"
        if candidate.exists():
            sys.path.insert(0, str(directory))
            return


_load_common_module()

from tokenleague_transcript_hook import TranscriptHookConfig  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import build_session_start_message  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import build_usage_payloads_from_transcript  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import detect_project_name  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import load_event_data_from_stdin  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import resolve_session_id  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import resolve_transcript_path  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import send_api_request as shared_send_api_request  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import write_hook_log  # type: ignore  # noqa: E402


CONFIG = TranscriptHookConfig(
    agent_type="cursor",
    log_file_name=".tokenleague_cursor_hook.log",
    transcript_env_vars=("CURSOR_TRANSCRIPT_PATH",),
    cwd_env_vars=("CLAUDE_PROJECT_DIR",),
    version_env_vars=("CURSOR_VERSION",),
)
END_HOOK_EVENTS = {"stop", "sessionEnd", "Stop", "SessionEnd"}


def _detect_project_name(cwd: str | None = None) -> str:
    return detect_project_name(cwd)


def _handle_session_start(event_data: dict[str, Any]) -> None:
    del event_data
    write_hook_log(CONFIG, "session_start_message", message=build_session_start_message(CONFIG))


def _send_api_request(endpoint: str, payload: dict[str, Any]) -> bool:
    return shared_send_api_request(CONFIG, endpoint, payload)


def _handle_stop(event_data: dict[str, Any]) -> None:
    prompt_events, task_run = build_usage_payloads_from_transcript(CONFIG, event_data)
    if not prompt_events or not task_run:
        write_hook_log(
            CONFIG,
            "stop_skipped",
            reason="no_prompt_events",
            session_id=resolve_session_id(event_data),
            transcript_path=resolve_transcript_path(CONFIG, event_data),
        )
        return

    write_hook_log(
        CONFIG,
        "transcript_parsed",
        session_id=resolve_session_id(event_data),
        transcript_path=resolve_transcript_path(CONFIG, event_data),
        prompt_count=len(prompt_events),
        input_token_count=task_run["input_token_count"],
        output_token_count=task_run["output_token_count"],
        cached_input_token_count=task_run["cached_input_token_count"],
    )

    for prompt_event in prompt_events:
        _send_api_request("/api/ingest/prompt-event", prompt_event)
    _send_api_request("/api/ingest/task-run", task_run)


def _resolve_hook_event(event_data: dict[str, Any]) -> str:
    cli_event = sys.argv[1] if len(sys.argv) > 1 else ""
    return str(
        cli_event
        or os.getenv("CURSOR_HOOK_EVENT_NAME", "")
        or event_data.get("hook_event_name", "")
        or event_data.get("event", "")
    )


def main() -> None:
    event_data = load_event_data_from_stdin()
    hook_event = _resolve_hook_event(event_data)

    if hook_event == "sessionStart":
        _handle_session_start(event_data)
    elif hook_event in END_HOOK_EVENTS:
        _handle_stop(event_data)
    else:
        write_hook_log(CONFIG, "hook_event_ignored", hook_event=hook_event or "unknown")

    sys.exit(0)


if __name__ == "__main__":
    main()
