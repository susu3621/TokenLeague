#!/usr/bin/env python3
"""
TokenLeague Statistics Hook for Codex CLI.

This hook captures Codex session metadata on UserPromptSubmit and parses the
session transcript on Stop to upsert prompt and task usage into TokenLeague.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit


DEFAULT_API_URL = "http://localhost:5006"
HOOK_LOG_FILE_NAME = ".tokenleague_codex_hook.log"
AGENT_TYPE = "codex"


def _get_env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def _get_api_url() -> str:
    return (_get_env("TOKENLEAGUE_API_URL") or DEFAULT_API_URL).rstrip("/")


def _get_hook_key() -> str | None:
    return _get_env("TOKENLEAGUE_HOOK_KEY")


def _get_temp_dir() -> Path:
    return Path(os.getenv("TMPDIR", "/tmp"))


def _get_hook_log_file() -> Path:
    return _get_temp_dir() / HOOK_LOG_FILE_NAME


def _get_session_state_file(session_id: str) -> Path:
    safe_session_id = "".join(char if char.isalnum() or char in "-_" else "_" for char in session_id)
    return _get_temp_dir() / f".tokenleague_codex_session_{safe_session_id}.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso_timestamp(dt: datetime | None = None) -> str:
    if dt is None:
        dt = _utcnow()
    return dt.isoformat()


def _write_hook_log(event_type: str, **fields: Any) -> None:
    log_path = _get_hook_log_file()
    record = {
        "timestamp": _iso_timestamp(),
        "event": event_type,
        **fields,
    }
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    except OSError:
        pass


def _payload_identifier(payload: dict[str, Any]) -> str:
    return str(
        payload.get("external_event_id")
        or payload.get("external_task_id")
        or payload.get("session_id")
        or "unknown"
    )


def _format_request_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    return str(exc)


def _build_private_ip_retry_url(url: str) -> str | None:
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
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    if isinstance(exc, urllib.error.URLError):
        return True
    return False


def _send_api_request(endpoint: str, payload: dict[str, Any]) -> bool:
    hook_key = _get_hook_key()
    if not hook_key:
        _write_hook_log(
            "request_skipped",
            endpoint=endpoint,
            reason="missing_hook_key",
            payload_id=_payload_identifier(payload),
        )
        return False

    primary_url = f"{_get_api_url()}{endpoint}"
    retry_url = _build_private_ip_retry_url(primary_url)
    attempt_urls = [primary_url]
    if retry_url and retry_url != primary_url:
        attempt_urls.append(retry_url)

    data = json.dumps(payload).encode("utf-8")
    payload_id = _payload_identifier(payload)
    headers = {
        "Content-Type": "application/json",
        "X-Hook-Key": hook_key,
    }

    for index, url in enumerate(attempt_urls):
        try:
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=5) as response:
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


def _load_session_state(session_id: str) -> dict[str, Any]:
    session_path = _get_session_state_file(session_id)
    if not session_path.exists():
        return {}
    try:
        with session_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_session_state(session_id: str, session_state: dict[str, Any]) -> None:
    session_path = _get_session_state_file(session_id)
    try:
        with session_path.open("w", encoding="utf-8") as handle:
            json.dump(session_state, handle, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError:
        pass


def _clear_session_state(session_id: str) -> None:
    session_path = _get_session_state_file(session_id)
    if not session_path.exists():
        return
    try:
        session_path.unlink()
    except OSError:
        pass


def _load_transcript_entries(transcript_path: str | None) -> list[dict[str, Any]]:
    if not transcript_path:
        return []

    path = Path(transcript_path)
    if not path.exists():
        _write_hook_log("transcript_missing", transcript_path=str(path))
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
        _write_hook_log("transcript_read_failed", transcript_path=str(path), error=str(exc))
        return []

    return entries


def _extract_session_metadata(entries: list[dict[str, Any]]) -> dict[str, str]:
    for entry in entries:
        if entry.get("type") != "session_meta":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        return {
            "session_id": str(payload.get("id") or ""),
            "started_at": str(payload.get("timestamp") or entry.get("timestamp") or ""),
            "agent_version": str(payload.get("cli_version") or payload.get("agent_version") or "unknown"),
        }
    return {
        "session_id": "",
        "started_at": "",
        "agent_version": "unknown",
    }


def _extract_token_usage_events(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usage_events: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("type") != "event_msg":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        if not isinstance(info, dict):
            continue
        last_usage = info.get("last_token_usage")
        if not isinstance(last_usage, dict):
            continue
        finished_at = str(entry.get("timestamp") or "")
        if not finished_at:
            continue
        usage_events.append(
            {
                "finished_at": finished_at,
                "input_token_count": int(last_usage.get("input_tokens") or 0),
                "output_token_count": int(last_usage.get("output_tokens") or 0),
            }
        )
    return usage_events


def _build_usage_payloads_from_transcript(
    *,
    session_id: str | None,
    transcript_path: str,
    model_name: str,
    prompt_started_ats: list[str],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    entries = _load_transcript_entries(transcript_path)
    if not entries:
        return [], None

    session_metadata = _extract_session_metadata(entries)
    usage_events = _extract_token_usage_events(entries)
    if not usage_events:
        return [], None

    external_session_id = str(session_id or session_metadata["session_id"] or "unknown-session")
    transcript_started_at = session_metadata["started_at"] or usage_events[0]["finished_at"]
    agent_version = session_metadata["agent_version"] or "unknown"

    prompt_events: list[dict[str, Any]] = []
    for index, usage_event in enumerate(usage_events, start=1):
        prompt_started_at = (
            prompt_started_ats[index - 1]
            if index - 1 < len(prompt_started_ats)
            else transcript_started_at
        )
        prompt_events.append(
            {
                "external_event_id": f"{external_session_id}:prompt:{index}",
                "task_id": external_session_id,
                "prompt_started_at": prompt_started_at,
                "prompt_finished_at": usage_event["finished_at"],
                "input_token_count": usage_event["input_token_count"],
                "output_token_count": usage_event["output_token_count"],
                "agent_type": AGENT_TYPE,
                "agent_version": agent_version,
                "model_name": model_name,
            }
        )

    task_run = {
        "external_task_id": external_session_id,
        "started_at": prompt_events[0]["prompt_started_at"],
        "finished_at": prompt_events[-1]["prompt_finished_at"],
        "prompt_count": len(prompt_events),
        "input_token_count": sum(event["input_token_count"] for event in prompt_events),
        "output_token_count": sum(event["output_token_count"] for event in prompt_events),
        "agent_type": AGENT_TYPE,
        "agent_version": agent_version,
        "model_name": model_name,
    }
    return prompt_events, task_run


def _handle_user_prompt_submit(event_data: dict[str, Any]) -> None:
    session_id = str(event_data.get("session_id") or "")
    transcript_path = str(event_data.get("transcript_path") or "")
    if not session_id or not transcript_path:
        _write_hook_log(
            "user_prompt_submit_skipped",
            reason="missing_session_or_transcript",
            session_id=session_id or None,
            transcript_path=transcript_path or None,
        )
        return

    session_state = _load_session_state(session_id)
    prompt_started_ats = session_state.get("prompt_started_ats")
    if not isinstance(prompt_started_ats, list):
        prompt_started_ats = []

    prompt_started_ats.append(_iso_timestamp())
    updated_state = {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "model_name": str(event_data.get("model") or session_state.get("model_name") or "unknown"),
        "cwd": str(event_data.get("cwd") or session_state.get("cwd") or ""),
        "prompt_started_ats": prompt_started_ats,
    }
    _save_session_state(session_id, updated_state)
    _write_hook_log(
        "user_prompt_submit_recorded",
        session_id=session_id,
        transcript_path=transcript_path,
        prompt_count=len(prompt_started_ats),
        model_name=updated_state["model_name"],
    )


def _handle_stop(event_data: dict[str, Any]) -> None:
    session_id = str(event_data.get("session_id") or "")
    session_state = _load_session_state(session_id) if session_id else {}

    transcript_path = str(event_data.get("transcript_path") or session_state.get("transcript_path") or "")
    if not transcript_path:
        _write_hook_log(
            "stop_skipped",
            reason="missing_transcript_path",
            session_id=session_id or None,
        )
        return

    prompt_started_ats = session_state.get("prompt_started_ats")
    if not isinstance(prompt_started_ats, list):
        prompt_started_ats = []

    model_name = str(event_data.get("model") or session_state.get("model_name") or "unknown")
    prompt_events, task_run = _build_usage_payloads_from_transcript(
        session_id=session_id or None,
        transcript_path=transcript_path,
        model_name=model_name,
        prompt_started_ats=prompt_started_ats,
    )
    if not prompt_events or not task_run:
        _write_hook_log(
            "stop_skipped",
            reason="no_prompt_events",
            session_id=session_id or None,
            transcript_path=transcript_path,
        )
        if session_id:
            _clear_session_state(session_id)
        return

    _write_hook_log(
        "transcript_parsed",
        session_id=task_run["external_task_id"],
        transcript_path=transcript_path,
        prompt_count=len(prompt_events),
        input_token_count=task_run["input_token_count"],
        output_token_count=task_run["output_token_count"],
    )

    for prompt_event in prompt_events:
        _send_api_request("/api/ingest/prompt-event", prompt_event)
    _send_api_request("/api/ingest/task-run", task_run)

    if session_id:
        _clear_session_state(session_id)


def main() -> None:
    try:
        event_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    hook_event = os.getenv("CODEX_HOOK_EVENT_NAME", "")
    if not hook_event:
        hook_event = str(event_data.get("hook_event_name") or "")

    if hook_event == "UserPromptSubmit":
        _handle_user_prompt_submit(event_data)
    elif hook_event == "Stop":
        _handle_stop(event_data)
    else:
        _write_hook_log("hook_event_ignored", hook_event=hook_event or "unknown")

    sys.exit(0)


if __name__ == "__main__":
    main()
