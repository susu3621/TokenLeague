#!/usr/bin/env python3
"""
TokenLeague Statistics Hook for Workbuddy (CodeBuddy CLI).

This hook parses transcript usage on Stop or SessionEnd and returns a startup
message on SessionStart using the Claude-compatible hook payload format.

WorkBuddy stores transcripts as index.json with the following structure:
{
  "messages": [{"id": "...", "type": "text", "role": "user|assistant", "isComplete": true}],
  "requests": [{
    "id": "...", "type": "craft", "messages": ["msg-id-1", "msg-id-2"],
    "state": "complete", "startedAt": 1774936850964,
    "usage": {"inputTokens": 23247, "outputTokens": 27, "totalTokens": 23274, "lastTokens": 23274}
  }]
}
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any
import uuid
from datetime import datetime, timezone


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
from tokenleague_transcript_hook import build_session_start_json_payload  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import first_string  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import get_env  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import load_event_data_from_stdin  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import resolve_session_id  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import resolve_transcript_path  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import send_api_request as shared_send_api_request  # type: ignore  # noqa: E402
from tokenleague_transcript_hook import write_hook_log  # type: ignore  # noqa: E402


CONFIG = TranscriptHookConfig(
    agent_type="workbuddy",
    log_file_name=".tokenleague_workbuddy_hook.log",
    version_env_vars=("WORKBUDDY_VERSION", "CODEBUDDY_VERSION"),
)
END_HOOK_EVENTS = {"Stop", "SessionEnd"}


def _detect_project_name(cwd: str | None = None) -> str:
    from tokenleague_transcript_hook import detect_project_name  # type: ignore  # noqa: E402
    return detect_project_name(cwd)


def _detect_workbuddy_version() -> str:
    env_version = first_string(*(get_env(name) for name in CONFIG.version_env_vars))
    if env_version:
        return env_version

    for plist_path in [
        Path("/Applications/WorkBuddy.app/Contents/Info.plist"),
        Path(os.path.expanduser("~/Applications/WorkBuddy.app/Contents/Info.plist")),
    ]:
        if plist_path.exists():
            try:
                import plistlib
                with plist_path.open("rb") as f:
                    plist = plistlib.load(f)
                version = plist.get("CFBundleShortVersionString")
                if version:
                    return str(version)
            except (OSError, ValueError):
                pass

    return "unknown"


def _ms_to_iso(ms_value: Any) -> str:
    if not ms_value:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        dt = datetime.fromtimestamp(int(ms_value) / 1000, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, OSError):
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_workbuddy_transcript(
    transcript_path: str,
    session_id: str,
    project_name: str,
    agent_version: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not transcript_path:
        return [], None

    path = Path(transcript_path)
    if not path.exists():
        write_hook_log(CONFIG, "transcript_missing", transcript_path=str(path))
        return [], None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        write_hook_log(CONFIG, "transcript_read_failed", transcript_path=str(path), error=str(exc))
        return [], None

    if not isinstance(data, dict):
        write_hook_log(CONFIG, "transcript_unexpected_format", transcript_path=str(path))
        return [], None

    requests = data.get("requests", [])
    if not requests:
        write_hook_log(CONFIG, "transcript_no_requests", transcript_path=str(path))
        return [], None

    prompt_events: list[dict[str, Any]] = []
    for req in requests:
        if not isinstance(req, dict):
            continue
        if req.get("state") != "complete":
            continue

        usage = req.get("usage", {})
        if not usage:
            continue

        input_tokens = int(usage.get("inputTokens", 0) or 0)
        output_tokens = int(usage.get("outputTokens", 0) or 0)
        if input_tokens == 0 and output_tokens == 0:
            continue

        req_id = req.get("id", str(uuid.uuid4()))
        timestamp_str = _ms_to_iso(req.get("startedAt"))

        prompt_events.append({
            "external_event_id": req_id,
            "task_id": session_id,
            "project_name": project_name,
            "prompt_started_at": timestamp_str,
            "prompt_finished_at": timestamp_str,
            "input_token_count": input_tokens,
            "output_token_count": output_tokens,
            "cached_input_token_count": 0,
            "agent_type": CONFIG.agent_type,
            "agent_version": agent_version,
            "model_name": "unknown",
        })

    if not prompt_events:
        return [], None

    task_run = {
        "external_task_id": session_id,
        "project_name": project_name,
        "started_at": prompt_events[0]["prompt_started_at"],
        "finished_at": prompt_events[-1]["prompt_finished_at"],
        "prompt_count": len(prompt_events),
        "input_token_count": sum(e["input_token_count"] for e in prompt_events),
        "output_token_count": sum(e["output_token_count"] for e in prompt_events),
        "cached_input_token_count": 0,
        "agent_type": CONFIG.agent_type,
        "agent_version": agent_version,
        "model_name": "unknown",
    }

    return prompt_events, task_run


def _handle_session_start(event_data: dict[str, Any]) -> dict[str, Any]:
    del event_data
    payload = build_session_start_json_payload(CONFIG)
    write_hook_log(CONFIG, "session_start_message", message=payload["systemMessage"])
    return payload


def _send_api_request(endpoint: str, payload: dict[str, Any]) -> bool:
    return shared_send_api_request(CONFIG, endpoint, payload)


def _handle_stop(event_data: dict[str, Any]) -> None:
    session_id = resolve_session_id(event_data)
    transcript_path = resolve_transcript_path(CONFIG, event_data)
    project_name = _detect_project_name(event_data.get("cwd"))
    agent_version = _detect_workbuddy_version()

    prompt_events, task_run = _parse_workbuddy_transcript(
        transcript_path, session_id, project_name, agent_version,
    )

    if not prompt_events or not task_run:
        write_hook_log(
            CONFIG,
            "stop_skipped",
            reason="no_prompt_events",
            session_id=session_id,
            transcript_path=transcript_path,
        )
        return

    write_hook_log(
        CONFIG,
        "transcript_parsed",
        session_id=session_id,
        transcript_path=transcript_path,
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
        or os.getenv("WORKBUDDY_HOOK_EVENT_NAME", "")
        or os.getenv("CODEBUDDY_HOOK_EVENT_NAME", "")
        or event_data.get("hook_event_name", "")
        or event_data.get("event", "")
    )


def main() -> None:
    event_data = load_event_data_from_stdin()
    hook_event = _resolve_hook_event(event_data)
    response_payload: dict[str, Any] | None = None

    if hook_event == "SessionStart":
        response_payload = _handle_session_start(event_data)
    elif hook_event in END_HOOK_EVENTS:
        _handle_stop(event_data)
    else:
        write_hook_log(CONFIG, "hook_event_ignored", hook_event=hook_event or "unknown")

    if response_payload is not None:
        json.dump(response_payload, sys.stdout)
        sys.stdout.write("\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
