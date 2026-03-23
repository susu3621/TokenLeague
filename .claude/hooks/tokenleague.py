#!/usr/bin/env python3
"""
TokenLeague Statistics Hook for Claude Code

This hook collects token usage statistics from the Claude transcript on Stop
and sends them to the TokenLeague API.

Environment Variables:
    TOKENLEAGUE_API_URL: TokenLeague API endpoint (default: http://localhost:5006)
    TOKENLEAGUE_HOOK_KEY: Authentication key (required)

Supported Hook Events:
    - SessionStart: Show TokenLeague environment configuration
    - Stop: Parse transcript usage and upsert prompt/task statistics
    - SessionEnd: Re-run transcript parsing as an exit-time fallback
"""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from datetime import datetime, timezone
import ipaddress
from pathlib import Path
from typing import Any
import urllib.request
import urllib.error
from urllib.parse import urlsplit, urlunsplit

# Default configuration
DEFAULT_API_URL = "http://localhost:5006"
HOOK_LOG_FILE_NAME = ".tokenleague_hook.log"
END_HOOK_EVENTS = {"Stop", "SessionEnd"}

# Agent metadata
AGENT_TYPE = "claude-code"


def _get_env(key: str, default: str | None = None) -> str | None:
    """Get environment variable value."""
    return os.getenv(key, default)


def _get_api_url() -> str:
    """Get TokenLeague API URL."""
    return (_get_env("TOKENLEAGUE_API_URL") or DEFAULT_API_URL).rstrip("/")


def _get_hook_key() -> str | None:
    """Get authentication hook key."""
    return _get_env("TOKENLEAGUE_HOOK_KEY")


def _get_hook_log_file() -> Path:
    """Get path to hook log file."""
    temp_dir = Path(os.getenv("TMPDIR", "/tmp"))
    return temp_dir / HOOK_LOG_FILE_NAME


def _utcnow() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso_timestamp(dt: datetime | None = None) -> str:
    """Generate ISO format timestamp."""
    if dt is None:
        dt = _utcnow()
    return dt.isoformat()


def _write_hook_log(event_type: str, **fields: Any) -> None:
    """Write a structured hook log record to the temp directory."""
    log_path = _get_hook_log_file()
    record = {
        "timestamp": _iso_timestamp(),
        "event": event_type,
        **fields,
    }
    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    except IOError:
        pass


def _payload_identifier(payload: dict[str, Any]) -> str:
    """Return the most useful identifier for a payload."""
    return str(
        payload.get("external_event_id")
        or payload.get("external_task_id")
        or payload.get("task_id")
        or "unknown"
    )


def _format_request_error(exc: Exception) -> str:
    """Format a request exception for logs."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    return str(exc)


def _build_private_ip_retry_url(url: str) -> str | None:
    """Resolve a hostname and build an IP-based retry URL for private networks."""
    parsed = urlsplit(url)
    hostname = parsed.hostname
    if not hostname or hostname in {"localhost", "127.0.0.1"}:
        return None

    try:
        ipaddress.ip_address(hostname)
        return None
    except ValueError:
        pass

    try:
        resolved_ip = socket.gethostbyname(hostname)
        if not ipaddress.ip_address(resolved_ip).is_private:
            return None
    except (OSError, ValueError):
        return None

    netloc = resolved_ip
    if parsed.port:
        netloc = f"{resolved_ip}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _should_retry_with_resolved_ip(exc: Exception) -> bool:
    """Return whether a failed request should retry through a resolved IP."""
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    if isinstance(exc, urllib.error.URLError):
        return True
    return False


def _send_api_request(endpoint: str, payload: dict[str, Any]) -> bool:
    """Send request to TokenLeague API."""
    hook_key = _get_hook_key()
    if not hook_key:
        _write_hook_log(
            "request_skipped",
            endpoint=endpoint,
            reason="missing_hook_key",
            payload_id=_payload_identifier(payload),
        )
        return False

    api_url = _get_api_url()
    primary_url = f"{api_url}{endpoint}"
    retry_url = _build_private_ip_retry_url(primary_url)
    attempt_urls = [primary_url]
    if retry_url and retry_url != primary_url:
        attempt_urls.append(retry_url)

    headers = {
        "Content-Type": "application/json",
        "X-Hook-Key": hook_key,
    }

    data = json.dumps(payload).encode("utf-8")
    payload_id = _payload_identifier(payload)

    for index, url in enumerate(attempt_urls):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=5) as response:
                _write_hook_log(
                    "request_succeeded",
                    endpoint=endpoint,
                    payload_id=payload_id,
                    status=response.status,
                    url=url,
                    agent_type=payload.get("agent_type"),
                    agent_version=payload.get("agent_version"),
                    model_name=payload.get("model_name"),
                )
                return response.status == 200
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            is_last_attempt = index == len(attempt_urls) - 1
            should_retry = (
                not is_last_attempt
                and index == 0
                and _should_retry_with_resolved_ip(exc)
            )
            if should_retry:
                _write_hook_log(
                    "request_retrying_with_ip",
                    endpoint=endpoint,
                    payload_id=payload_id,
                    retry_url=attempt_urls[index + 1],
                    url=url,
                    error=_format_request_error(exc),
                )
                continue
            _write_hook_log(
                "request_failed",
                endpoint=endpoint,
                payload_id=payload_id,
                url=url,
                error=_format_request_error(exc),
                agent_type=payload.get("agent_type"),
                agent_version=payload.get("agent_version"),
                model_name=payload.get("model_name"),
            )
            return False

    return False


def _extract_token_counts(event_data: dict[str, Any]) -> tuple[int, int]:
    """Extract input and output token counts from event data."""
    # Try different possible locations for token counts
    usage = event_data.get("usage", {})
    if not usage:
        usage = event_data.get("message", {}).get("usage", {})
    if not usage:
        usage = event_data.get("response", {}).get("usage", {})

    input_tokens = usage.get("input_tokens", 0) or usage.get("input_token_count", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or usage.get("output_token_count", 0) or 0

    return int(input_tokens), int(output_tokens)


def _extract_model_info(event_data: dict[str, Any]) -> tuple[str, str]:
    """Extract model name and version from event data."""
    message = event_data.get("message")
    if not isinstance(message, dict):
        message = {}
    model_name = (
        event_data.get("model")
        or event_data.get("model_name")
        or message.get("model")
        or "unknown"
    )
    # Claude Code version (if available)
    agent_version = (
        event_data.get("claude_code_version")
        or event_data.get("agent_version")
        or event_data.get("version")
        or "unknown"
    )
    return str(model_name), str(agent_version)


def _build_session_start_message() -> str:
    """Build a startup message showing TokenLeague environment configuration."""
    api_url = _get_api_url()
    hook_key = _get_hook_key()

    if _get_env("TOKENLEAGUE_API_URL"):
        api_url_status = f"configured ({api_url})"
    else:
        api_url_status = f"default ({api_url})"

    hook_key_status = "configured" if hook_key else "missing"
    return f"[TokenLeague] TOKENLEAGUE_API_URL={api_url_status}, TOKENLEAGUE_HOOK_KEY={hook_key_status}"


def _handle_session_start(event_data: dict[str, Any]) -> dict[str, Any]:
    """Handle SessionStart hook event."""
    del event_data
    message = _build_session_start_message()
    _write_hook_log("session_start_message", message=message)
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        },
        "systemMessage": message,
    }


def _load_transcript_entries(transcript_path: str | None) -> list[dict[str, Any]]:
    """Load JSONL transcript entries from disk."""
    if not transcript_path:
        return []

    path = Path(transcript_path)
    if not path.exists():
        _write_hook_log(
            "transcript_missing",
            transcript_path=str(path),
        )
        return []

    entries: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    entry = json.loads(text)
                except json.JSONDecodeError as exc:
                    _write_hook_log(
                        "transcript_invalid_json",
                        transcript_path=str(path),
                        line_number=line_number,
                        error=str(exc),
                    )
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError as exc:
        _write_hook_log(
            "transcript_read_failed",
            transcript_path=str(path),
            error=str(exc),
        )
        return []

    return entries


def _is_primary_user_entry(entry: dict[str, Any]) -> bool:
    return (
        entry.get("type") == "user"
        and not entry.get("isSidechain")
        and not entry.get("isMeta")
    )


def _is_primary_assistant_entry(entry: dict[str, Any]) -> bool:
    return (
        entry.get("type") == "assistant"
        and not entry.get("isSidechain")
        and isinstance(entry.get("message"), dict)
        and entry["message"].get("role") == "assistant"
    )


def _find_prompt_start_entry(
    assistant_entry: dict[str, Any],
    entries_by_uuid: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Walk the parent chain to find the initiating user prompt."""
    current = assistant_entry
    visited: set[str] = set()

    while True:
        parent_uuid = current.get("parentUuid")
        if not parent_uuid or parent_uuid in visited:
            return None
        visited.add(parent_uuid)
        parent = entries_by_uuid.get(parent_uuid)
        if not isinstance(parent, dict):
            return None
        if _is_primary_user_entry(parent):
            return parent
        current = parent


def _entry_timestamp(entry: dict[str, Any] | None) -> str | None:
    if not isinstance(entry, dict):
        return None
    timestamp = entry.get("timestamp")
    if timestamp is None:
        return None
    return str(timestamp)


def _group_assistant_entries(
    entries: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return assistant message groups as (first_entry, final_entry)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for index, entry in enumerate(entries):
        if not _is_primary_assistant_entry(entry):
            continue
        message = entry.get("message", {})
        group_key = (
            message.get("id")
            or entry.get("uuid")
            or f"assistant-{index}"
        )
        groups.setdefault(str(group_key), []).append(entry)

    grouped_entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for group_entries in groups.values():
        first_entry = group_entries[0]
        final_entry = group_entries[-1]
        for candidate in reversed(group_entries):
            usage = candidate.get("message", {}).get("usage")
            if isinstance(usage, dict):
                final_entry = candidate
                break
        grouped_entries.append((first_entry, final_entry))
    return grouped_entries


def _build_usage_payloads_from_transcript(
    event_data: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Build prompt-event and task-run payloads from a Stop transcript."""
    entries = _load_transcript_entries(event_data.get("transcript_path"))
    if not entries:
        return [], None

    entries_by_uuid = {
        str(entry["uuid"]): entry
        for entry in entries
        if isinstance(entry.get("uuid"), str)
    }
    session_id = str(event_data.get("session_id") or uuid.uuid4())
    fallback_model_name, fallback_agent_version = _extract_model_info(event_data)
    prompt_events: list[dict[str, Any]] = []

    for first_entry, final_entry in _group_assistant_entries(entries):
        message = final_entry.get("message", {})
        external_event_id = message.get("id") or final_entry.get("uuid")
        if not external_event_id:
            continue

        start_entry = _find_prompt_start_entry(first_entry, entries_by_uuid) or first_entry
        prompt_started_at = _entry_timestamp(start_entry)
        prompt_finished_at = _entry_timestamp(final_entry)
        if not prompt_started_at or not prompt_finished_at:
            continue

        input_tokens, output_tokens = _extract_token_counts(final_entry)
        model_name, agent_version = _extract_model_info(final_entry)
        if model_name == "unknown":
            model_name = fallback_model_name
        if agent_version == "unknown":
            agent_version = fallback_agent_version

        prompt_events.append(
            {
                "external_event_id": str(external_event_id),
                "task_id": session_id,
                "prompt_started_at": prompt_started_at,
                "prompt_finished_at": prompt_finished_at,
                "input_token_count": input_tokens,
                "output_token_count": output_tokens,
                "agent_type": AGENT_TYPE,
                "agent_version": agent_version,
                "model_name": model_name,
            }
        )

    if not prompt_events:
        return [], None

    task_run = {
        "external_task_id": session_id,
        "started_at": prompt_events[0]["prompt_started_at"],
        "finished_at": prompt_events[-1]["prompt_finished_at"],
        "prompt_count": len(prompt_events),
        "input_token_count": sum(event["input_token_count"] for event in prompt_events),
        "output_token_count": sum(event["output_token_count"] for event in prompt_events),
        "agent_type": AGENT_TYPE,
        "agent_version": prompt_events[-1]["agent_version"],
        "model_name": prompt_events[-1]["model_name"],
    }
    return prompt_events, task_run


def _handle_stop(event_data: dict[str, Any]) -> None:
    """Handle Stop hook event."""
    prompt_events, task_run = _build_usage_payloads_from_transcript(event_data)
    if not prompt_events or not task_run:
        _write_hook_log(
            "stop_skipped",
            reason="no_prompt_events",
            session_id=event_data.get("session_id"),
            transcript_path=event_data.get("transcript_path"),
        )
        return

    _write_hook_log(
        "transcript_parsed",
        session_id=event_data.get("session_id"),
        transcript_path=event_data.get("transcript_path"),
        prompt_count=len(prompt_events),
        input_token_count=task_run["input_token_count"],
        output_token_count=task_run["output_token_count"],
    )

    for prompt_event in prompt_events:
        _send_api_request("/api/ingest/prompt-event", prompt_event)
    _send_api_request("/api/ingest/task-run", task_run)


def main() -> None:
    """Main entry point for the hook script."""
    # Read hook event data from stdin
    try:
        event_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # No valid JSON input, exit silently
        sys.exit(0)

    # Get hook event type from environment or data
    hook_event = os.getenv("CLAUDE_HOOK_EVENT_NAME", "")

    # If not in env, try to get from event data
    if not hook_event:
        hook_event = event_data.get("hook_event_name", "")

    response_payload: dict[str, Any] | None = None

    if hook_event == "SessionStart":
        response_payload = _handle_session_start(event_data)
    elif hook_event in END_HOOK_EVENTS:
        _handle_stop(event_data)
    else:
        _write_hook_log(
            "hook_event_ignored",
            hook_event=hook_event or "unknown",
        )

    if response_payload is not None:
        json.dump(response_payload, sys.stdout)
        sys.stdout.write("\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
