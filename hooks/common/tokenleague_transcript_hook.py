#!/usr/bin/env python3
"""
Shared transcript-based TokenLeague hook helpers.

These helpers support agents that expose a transcript path at hook time and
report usage through assistant transcript entries.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import os
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit


DEFAULT_API_URL = "http://localhost:5006"
ANSI_GREEN = "\033[32m"
ANSI_RED = "\033[31m"
ANSI_BOLD = "\033[1m"
ANSI_RESET = "\033[0m"


@dataclass(frozen=True)
class TranscriptHookConfig:
    agent_type: str
    log_file_name: str
    transcript_env_vars: tuple[str, ...] = ()
    cwd_env_vars: tuple[str, ...] = ()
    version_env_vars: tuple[str, ...] = ()


def get_env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def get_api_url() -> str:
    return (get_env("TOKENLEAGUE_API_URL") or DEFAULT_API_URL).rstrip("/")


def get_hook_key() -> str | None:
    return get_env("TOKENLEAGUE_HOOK_KEY")


def get_hook_log_file(config: TranscriptHookConfig) -> Path:
    temp_dir = Path(os.getenv("TMPDIR", "/tmp"))
    return temp_dir / config.log_file_name


def resolve_worktree_repo_root(root: Path) -> Path | None:
    git_file = root / ".git"
    if not git_file.is_file():
        return None

    try:
        first_line = git_file.read_text(encoding="utf-8").splitlines()[0].strip()
    except (IndexError, OSError, UnicodeDecodeError):
        return None

    prefix = "gitdir:"
    if not first_line.startswith(prefix):
        return None

    gitdir_value = first_line[len(prefix):].strip()
    gitdir_path = Path(gitdir_value)
    if not gitdir_path.is_absolute():
        gitdir_path = (git_file.parent / gitdir_path).resolve()

    parts = gitdir_path.parts
    for index in range(len(parts) - 2):
        if parts[index] == ".git" and parts[index + 1] == "worktrees":
            repo_root = Path(*parts[:index])
            return repo_root if str(repo_root) else Path(parts[0])
    return None


def detect_project_name(cwd: str | None = None) -> str:
    raw_cwd = str(cwd or "").strip()
    candidate = Path(raw_cwd or os.getcwd()).expanduser()
    try:
        candidate = candidate.resolve()
    except OSError:
        pass

    if candidate.is_file():
        candidate = candidate.parent

    search_roots = [candidate, *candidate.parents]
    for root in search_roots:
        if (root / ".git").is_dir():
            return root.name

    for root in search_roots:
        repo_root = resolve_worktree_repo_root(root)
        if repo_root is not None:
            return repo_root.name

    normalized = str(candidate).rstrip("/\\")
    if not normalized:
        return ""
    return normalized.split("/")[-1].split("\\")[-1]


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_timestamp(dt: datetime | None = None) -> str:
    if dt is None:
        dt = utcnow()
    return dt.isoformat()


def write_hook_log(config: TranscriptHookConfig, event_type: str, **fields: Any) -> None:
    log_path = get_hook_log_file(config)
    record = {
        "timestamp": iso_timestamp(),
        "event": event_type,
        **fields,
    }
    try:
        with log_path.open("a", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    except OSError:
        pass


def payload_identifier(payload: dict[str, Any]) -> str:
    return str(
        payload.get("external_event_id")
        or payload.get("external_task_id")
        or payload.get("task_id")
        or payload.get("session_id")
        or "unknown"
    )


def format_request_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    return str(exc)


def build_private_ip_retry_url(url: str) -> str | None:
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


def should_retry_with_resolved_ip(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    if isinstance(exc, urllib.error.URLError):
        return True
    return False


def send_api_request(config: TranscriptHookConfig, endpoint: str, payload: dict[str, Any]) -> bool:
    hook_key = get_hook_key()
    if not hook_key:
        write_hook_log(
            config,
            "request_skipped",
            endpoint=endpoint,
            reason="missing_hook_key",
            payload_id=payload_identifier(payload),
        )
        return False

    primary_url = f"{get_api_url()}{endpoint}"
    retry_url = build_private_ip_retry_url(primary_url)
    attempt_urls = [primary_url]
    if retry_url and retry_url != primary_url:
        attempt_urls.append(retry_url)

    headers = {
        "Content-Type": "application/json",
        "X-Hook-Key": hook_key,
    }
    data = json.dumps(payload).encode("utf-8")
    payload_id = payload_identifier(payload)

    for index, url in enumerate(attempt_urls):
        try:
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=5) as response:
                write_hook_log(
                    config,
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
                and should_retry_with_resolved_ip(exc)
            )
            if should_retry:
                write_hook_log(
                    config,
                    "request_retrying_with_ip",
                    endpoint=endpoint,
                    payload_id=payload_id,
                    retry_url=attempt_urls[index + 1],
                    url=url,
                    error=format_request_error(exc),
                )
                continue
            write_hook_log(
                config,
                "request_failed",
                endpoint=endpoint,
                payload_id=payload_id,
                url=url,
                error=format_request_error(exc),
                agent_type=payload.get("agent_type"),
                agent_version=payload.get("agent_version"),
                model_name=payload.get("model_name"),
            )
            return False

    return False


def build_session_start_message(config: TranscriptHookConfig) -> str:
    del config
    api_url = get_api_url()
    hook_key = get_hook_key()

    if get_env("TOKENLEAGUE_API_URL"):
        api_url_status = f"{ANSI_GREEN}configured{ANSI_RESET} ({api_url})"
    else:
        api_url_status = f"{ANSI_RED}default{ANSI_RESET} ({api_url})"

    if hook_key:
        hook_key_status = f"{ANSI_GREEN}configured{ANSI_RESET}"
    else:
        hook_key_status = f"{ANSI_RED}missing{ANSI_RESET}"

    return f"{ANSI_BOLD}[TokenLeague]{ANSI_RESET} TOKENLEAGUE_API_URL={api_url_status}, TOKENLEAGUE_HOOK_KEY={hook_key_status}"


def build_session_start_json_payload(config: TranscriptHookConfig) -> dict[str, Any]:
    message = build_session_start_message(config)
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        },
        "systemMessage": message,
    }


def load_event_data_from_stdin() -> dict[str, Any]:
    try:
        raw = sys.stdin.read()
    except OSError:
        return {}

    if not raw.strip():
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    return payload if isinstance(payload, dict) else {}


def lookup_nested_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def first_string(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def resolve_transcript_path(config: TranscriptHookConfig, event_data: dict[str, Any]) -> str:
    candidates = [
        event_data.get("transcript_path"),
        event_data.get("agent_transcript_path"),
        event_data.get("transcriptPath"),
        event_data.get("agentTranscriptPath"),
        lookup_nested_value(event_data, ("payload", "transcript_path")),
        lookup_nested_value(event_data, ("payload", "agent_transcript_path")),
        lookup_nested_value(event_data, ("data", "transcript_path")),
        lookup_nested_value(event_data, ("data", "agent_transcript_path")),
    ]
    candidates.extend(get_env(name) for name in config.transcript_env_vars)
    return first_string(*candidates)


def resolve_cwd(config: TranscriptHookConfig, event_data: dict[str, Any]) -> str:
    candidates = [
        event_data.get("cwd"),
        event_data.get("project_dir"),
        event_data.get("workspace"),
        event_data.get("workspace_path"),
        lookup_nested_value(event_data, ("payload", "cwd")),
        lookup_nested_value(event_data, ("payload", "project_dir")),
        lookup_nested_value(event_data, ("data", "cwd")),
        lookup_nested_value(event_data, ("data", "project_dir")),
    ]
    candidates.extend(get_env(name) for name in config.cwd_env_vars)
    return first_string(*candidates)


def resolve_session_id(event_data: dict[str, Any]) -> str:
    return first_string(
        event_data.get("session_id"),
        event_data.get("sessionId"),
        event_data.get("task_id"),
        lookup_nested_value(event_data, ("payload", "session_id")),
        lookup_nested_value(event_data, ("payload", "sessionId")),
        lookup_nested_value(event_data, ("data", "session_id")),
        lookup_nested_value(event_data, ("data", "sessionId")),
    )


def extract_token_counts(event_data: dict[str, Any]) -> tuple[int, int, int]:
    usage = event_data.get("usage", {})
    if not usage:
        usage = event_data.get("message", {}).get("usage", {})
    if not usage:
        usage = event_data.get("response", {}).get("usage", {})

    input_tokens = usage.get("input_tokens", 0) or usage.get("input_token_count", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or usage.get("output_token_count", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
    cached_input_tokens = usage.get("cached_input_tokens", cache_read + cache_creation) or 0

    return int(input_tokens), int(output_tokens), int(cached_input_tokens)


def extract_model_info(config: TranscriptHookConfig, event_data: dict[str, Any]) -> tuple[str, str]:
    message = event_data.get("message")
    if not isinstance(message, dict):
        message = {}

    model_name = first_string(
        event_data.get("model"),
        event_data.get("model_name"),
        event_data.get("modelName"),
        message.get("model"),
        lookup_nested_value(event_data, ("payload", "model")),
    ) or "unknown"

    env_version = first_string(*(get_env(name) for name in config.version_env_vars))
    agent_version = (
        first_string(
            event_data.get("agent_version"),
            event_data.get("version"),
            event_data.get("agentVersion"),
            lookup_nested_value(event_data, ("payload", "version")),
            env_version,
        )
        or "unknown"
    )
    return str(model_name), str(agent_version)


def load_transcript_entries(config: TranscriptHookConfig, transcript_path: str | None) -> list[dict[str, Any]]:
    if not transcript_path:
        return []

    path = Path(transcript_path)
    if not path.exists():
        write_hook_log(config, "transcript_missing", transcript_path=str(path))
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
                    write_hook_log(
                        config,
                        "transcript_invalid_json",
                        transcript_path=str(path),
                        line_number=line_number,
                        error=str(exc),
                    )
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
    except OSError as exc:
        write_hook_log(
            config,
            "transcript_read_failed",
            transcript_path=str(path),
            error=str(exc),
        )
        return []

    return entries


def is_primary_user_entry(entry: dict[str, Any]) -> bool:
    return (
        entry.get("type") == "user"
        and not entry.get("isSidechain")
        and not entry.get("isMeta")
    )


def is_primary_assistant_entry(entry: dict[str, Any]) -> bool:
    return (
        entry.get("type") == "assistant"
        and not entry.get("isSidechain")
        and isinstance(entry.get("message"), dict)
        and entry["message"].get("role") == "assistant"
    )


def find_prompt_start_entry(
    assistant_entry: dict[str, Any],
    entries_by_uuid: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
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
        if is_primary_user_entry(parent):
            return parent
        current = parent


def entry_timestamp(entry: dict[str, Any] | None) -> str | None:
    if not isinstance(entry, dict):
        return None
    timestamp = entry.get("timestamp")
    if timestamp is None:
        return None
    return str(timestamp)


def group_assistant_entries(entries: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for index, entry in enumerate(entries):
        if not is_primary_assistant_entry(entry):
            continue
        message = entry.get("message", {})
        group_key = message.get("id") or entry.get("uuid") or f"assistant-{index}"
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


def build_usage_payloads_from_transcript(
    config: TranscriptHookConfig,
    event_data: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    transcript_path = resolve_transcript_path(config, event_data)
    entries = load_transcript_entries(config, transcript_path)
    if not entries:
        return [], None

    entries_by_uuid = {
        str(entry["uuid"]): entry
        for entry in entries
        if isinstance(entry.get("uuid"), str)
    }
    session_id = resolve_session_id(event_data) or str(uuid.uuid4())
    project_name = detect_project_name(resolve_cwd(config, event_data))
    fallback_model_name, fallback_agent_version = extract_model_info(config, event_data)
    prompt_events: list[dict[str, Any]] = []

    for first_entry, final_entry in group_assistant_entries(entries):
        message = final_entry.get("message", {})
        external_event_id = message.get("id") or final_entry.get("uuid")
        if not external_event_id:
            continue

        start_entry = find_prompt_start_entry(first_entry, entries_by_uuid) or first_entry
        prompt_started_at = entry_timestamp(start_entry)
        prompt_finished_at = entry_timestamp(final_entry)
        if not prompt_started_at or not prompt_finished_at:
            continue

        input_tokens, output_tokens, cached_tokens = extract_token_counts(final_entry)
        model_name, agent_version = extract_model_info(config, final_entry)
        if model_name == "unknown":
            model_name = fallback_model_name
        if agent_version == "unknown":
            agent_version = fallback_agent_version

        prompt_events.append(
            {
                "external_event_id": str(external_event_id),
                "task_id": session_id,
                "project_name": project_name,
                "prompt_started_at": prompt_started_at,
                "prompt_finished_at": prompt_finished_at,
                "input_token_count": input_tokens,
                "output_token_count": output_tokens,
                "cached_input_token_count": cached_tokens,
                "agent_type": config.agent_type,
                "agent_version": agent_version,
                "model_name": model_name,
            }
        )

    if not prompt_events:
        return [], None

    task_run = {
        "external_task_id": session_id,
        "project_name": project_name,
        "started_at": prompt_events[0]["prompt_started_at"],
        "finished_at": prompt_events[-1]["prompt_finished_at"],
        "prompt_count": len(prompt_events),
        "input_token_count": sum(event["input_token_count"] for event in prompt_events),
        "output_token_count": sum(event["output_token_count"] for event in prompt_events),
        "cached_input_token_count": sum(event["cached_input_token_count"] for event in prompt_events),
        "agent_type": config.agent_type,
        "agent_version": prompt_events[-1]["agent_version"],
        "model_name": prompt_events[-1]["model_name"],
    }
    return prompt_events, task_run


def handle_stop(config: TranscriptHookConfig, event_data: dict[str, Any]) -> None:
    prompt_events, task_run = build_usage_payloads_from_transcript(config, event_data)
    if not prompt_events or not task_run:
        write_hook_log(
            config,
            "stop_skipped",
            reason="no_prompt_events",
            session_id=resolve_session_id(event_data),
            transcript_path=resolve_transcript_path(config, event_data),
        )
        return

    write_hook_log(
        config,
        "transcript_parsed",
        session_id=resolve_session_id(event_data),
        transcript_path=resolve_transcript_path(config, event_data),
        prompt_count=len(prompt_events),
        input_token_count=task_run["input_token_count"],
        output_token_count=task_run["output_token_count"],
        cached_input_token_count=task_run["cached_input_token_count"],
    )

    for prompt_event in prompt_events:
        send_api_request(config, "/api/ingest/prompt-event", prompt_event)
    send_api_request(config, "/api/ingest/task-run", task_run)
