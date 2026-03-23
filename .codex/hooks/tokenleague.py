#!/usr/bin/env python3
"""
TokenLeague Statistics Hook for Codex CLI

This hook collects token usage statistics and sends them to the TokenLeague API.

Environment Variables:
    TOKENLEAGUE_API_URL: TokenLeague API endpoint (default: http://localhost:5006)
    TOKENLEAGUE_HOOK_KEY: Authentication key (required)

Supported Hook Events:
    - SessionStart: Initialize session tracking
    - UserPromptSubmit: Record prompt usage
    - Stop: Finalize session and send aggregated data
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.request
import urllib.error

# Default configuration
DEFAULT_API_URL = "http://localhost:5006"
SESSION_FILE_NAME = ".tokenleague_codex_session.json"

# Agent metadata
AGENT_TYPE = "codex-cli"


def _get_env(key: str, default: str | None = None) -> str | None:
    """Get environment variable value."""
    return os.getenv(key, default)


def _get_api_url() -> str:
    """Get TokenLeague API URL."""
    return (_get_env("TOKENLEAGUE_API_URL") or DEFAULT_API_URL).rstrip("/")


def _get_hook_key() -> str | None:
    """Get authentication hook key."""
    return _get_env("TOKENLEAGUE_HOOK_KEY")


def _get_session_file() -> Path:
    """Get path to session state file."""
    temp_dir = Path(os.getenv("TMPDIR", "/tmp"))
    return temp_dir / SESSION_FILE_NAME


def _utcnow() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso_timestamp(dt: datetime | None = None) -> str:
    """Generate ISO format timestamp."""
    if dt is None:
        dt = _utcnow()
    return dt.isoformat()


def _load_session() -> dict[str, Any]:
    """Load session state from file."""
    session_file = _get_session_file()
    if session_file.exists():
        try:
            with open(session_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_session(session: dict[str, Any]) -> None:
    """Save session state to file."""
    session_file = _get_session_file()
    try:
        with open(session_file, "w") as f:
            json.dump(session, f, indent=2)
    except IOError:
        pass


def _clear_session() -> None:
    """Clear session state file."""
    session_file = _get_session_file()
    if session_file.exists():
        try:
            session_file.unlink()
        except IOError:
            pass


def _send_api_request(endpoint: str, payload: dict[str, Any]) -> bool:
    """Send request to TokenLeague API."""
    hook_key = _get_hook_key()
    if not hook_key:
        return False

    api_url = _get_api_url()
    url = f"{api_url}{endpoint}"

    headers = {
        "Content-Type": "application/json",
        "X-Hook-Key": hook_key,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return False


def _extract_token_counts(event_data: dict[str, Any]) -> tuple[int, int]:
    """Extract input and output token counts from event data."""
    usage = event_data.get("usage", {})
    if not usage:
        usage = event_data.get("response", {}).get("usage", {})

    input_tokens = usage.get("input_tokens", 0) or usage.get("input_token_count", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or usage.get("output_token_count", 0) or 0

    return int(input_tokens), int(output_tokens)


def _extract_model_info(event_data: dict[str, Any]) -> tuple[str, str]:
    """Extract model name and version from event data."""
    model_name = event_data.get("model") or event_data.get("model_name") or "unknown"
    agent_version = event_data.get("codex_version") or event_data.get("agent_version") or "unknown"
    return str(model_name), str(agent_version)


def _handle_session_start(event_data: dict[str, Any]) -> None:
    """Handle SessionStart hook event."""
    session_id = event_data.get("session_id") or str(uuid.uuid4())
    model_name, agent_version = _extract_model_info(event_data)

    session = {
        "session_id": session_id,
        "started_at": _iso_timestamp(),
        "model_name": model_name,
        "agent_version": agent_version,
        "prompt_count": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "prompt_events": [],
    }

    _save_session(session)


def _handle_user_prompt_submit(event_data: dict[str, Any]) -> None:
    """Handle UserPromptSubmit hook event."""
    session = _load_session()
    if not session:
        _handle_session_start(event_data)
        session = _load_session()

    if not session:
        return

    input_tokens, output_tokens = _extract_token_counts(event_data)
    model_name, agent_version = _extract_model_info(event_data)

    if model_name and model_name != "unknown":
        session["model_name"] = model_name
    if agent_version and agent_version != "unknown":
        session["agent_version"] = agent_version

    event_id = event_data.get("event_id") or event_data.get("request_id") or str(uuid.uuid4())
    now = _iso_timestamp()

    prompt_event = {
        "external_event_id": event_id,
        "task_id": session.get("session_id", str(uuid.uuid4())),
        "prompt_started_at": now,
        "prompt_finished_at": now,
        "input_token_count": input_tokens,
        "output_token_count": output_tokens,
        "agent_type": AGENT_TYPE,
        "agent_version": session.get("agent_version", "unknown"),
        "model_name": session.get("model_name", "unknown"),
    }

    _send_api_request("/api/ingest/prompt-event", prompt_event)

    session["prompt_count"] = session.get("prompt_count", 0) + 1
    session["total_input_tokens"] = session.get("total_input_tokens", 0) + input_tokens
    session["total_output_tokens"] = session.get("total_output_tokens", 0) + output_tokens
    session["prompt_events"].append(prompt_event)

    _save_session(session)


def _handle_stop(event_data: dict[str, Any]) -> None:
    """Handle Stop hook event."""
    session = _load_session()
    if not session:
        return

    now = _iso_timestamp()
    started_at = session.get("started_at", now)

    task_run = {
        "external_task_id": session.get("session_id", str(uuid.uuid4())),
        "started_at": started_at,
        "finished_at": now,
        "prompt_count": session.get("prompt_count", 0),
        "input_token_count": session.get("total_input_tokens", 0),
        "output_token_count": session.get("total_output_tokens", 0),
        "agent_type": AGENT_TYPE,
        "agent_version": session.get("agent_version", "unknown"),
        "model_name": session.get("model_name", "unknown"),
    }

    _send_api_request("/api/ingest/task-run", task_run)
    _clear_session()


def main() -> None:
    """Main entry point for the hook script."""
    try:
        event_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    hook_event = os.getenv("CODEX_HOOK_EVENT_NAME", "")
    if not hook_event:
        hook_event = event_data.get("hook_event_name", "")

    if hook_event == "SessionStart":
        _handle_session_start(event_data)
    elif hook_event == "UserPromptSubmit":
        _handle_user_prompt_submit(event_data)
    elif hook_event == "Stop":
        _handle_stop(event_data)

    sys.exit(0)


if __name__ == "__main__":
    main()
