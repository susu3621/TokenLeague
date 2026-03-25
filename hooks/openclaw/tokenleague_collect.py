#!/usr/bin/env python3
"""
TokenLeague statistics collector for OpenClaw.

This collector reads OpenClaw Gateway session artifacts, converts them to
TokenLeague prompt and task payloads, and uploads newly observed usage.
"""

from __future__ import annotations

import contextlib
import fcntl
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit


DEFAULT_API_URL = "http://localhost:5006"
HOOK_LOG_FILE_NAME = ".tokenleague_openclaw_hook.log"
CURSOR_FILE_NAME = ".tokenleague_openclaw_cursor.json"
CURSOR_LOCK_FILE_NAME = ".tokenleague_openclaw_cursor.lock"
AGENT_TYPE = "openclaw"
_OPENCLAW_ENV_CACHE: dict[str, str] | None = None
_OPENCLAW_VERSION_CACHE: str | None = None


def _get_process_env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def _get_openclaw_env_file() -> Path:
    configured = _get_process_env("TOKENLEAGUE_OPENCLAW_ENV_FILE")
    if configured:
        return Path(configured).expanduser()
    return _get_openclaw_root() / ".env"


def _parse_dotenv_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):].strip()
    if "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def _load_openclaw_env_values() -> dict[str, str]:
    global _OPENCLAW_ENV_CACHE
    if _OPENCLAW_ENV_CACHE is not None:
        return _OPENCLAW_ENV_CACHE

    env_file = _get_openclaw_env_file()
    values: dict[str, str] = {}
    if env_file.exists():
        try:
            for raw_line in env_file.read_text(encoding="utf-8").splitlines():
                parsed = _parse_dotenv_line(raw_line)
                if parsed is None:
                    continue
                key, value = parsed
                values[key] = value
        except OSError:
            values = {}

    _OPENCLAW_ENV_CACHE = values
    return values


def _get_env(key: str, default: str | None = None) -> str | None:
    process_value = _get_process_env(key)
    if process_value is not None:
        return process_value
    return _load_openclaw_env_values().get(key, default)


def _get_api_url() -> str:
    return (_get_env("TOKENLEAGUE_API_URL") or DEFAULT_API_URL).rstrip("/")


def _get_hook_key() -> str | None:
    return _get_env("TOKENLEAGUE_HOOK_KEY")


def _get_openclaw_root() -> Path:
    configured = _get_process_env("TOKENLEAGUE_OPENCLAW_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".openclaw"


def _get_temp_dir() -> Path:
    return Path(_get_process_env("TMPDIR", "/tmp") or "/tmp")


def _get_hook_log_file() -> Path:
    return _get_temp_dir() / HOOK_LOG_FILE_NAME


def _get_cursor_state_file() -> Path:
    return _get_temp_dir() / CURSOR_FILE_NAME


def _get_cursor_lock_file() -> Path:
    return _get_temp_dir() / CURSOR_LOCK_FILE_NAME


@contextlib.contextmanager
def _cursor_lock() -> Iterator[None]:
    lock_path = _get_cursor_lock_file()
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
        or payload.get("task_id")
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
                    payload_id=_payload_identifier(payload),
                    status=response.status,
                    url=url,
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
                    payload_id=_payload_identifier(payload),
                    retry_url=attempt_urls[index + 1],
                    url=url,
                    error=_format_request_error(exc),
                )
                continue
            _write_hook_log(
                "request_failed",
                endpoint=endpoint,
                payload_id=_payload_identifier(payload),
                url=url,
                error=_format_request_error(exc),
            )
            return False

    return False


def _resolve_worktree_repo_root(root: Path) -> Path | None:
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


def _get_project_name() -> str:
    return "OpenClaw"


def _extract_semver(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"\b\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?\b", text)
    if not match:
        return None
    return match.group(0)


def _detect_openclaw_version_from_binary(binary_path: str | None) -> str | None:
    if not binary_path:
        return None

    try:
        resolved = Path(binary_path).expanduser().resolve()
    except OSError:
        return None

    parts = resolved.parts
    for index, part in enumerate(parts):
        if part != "Cellar" or index + 2 >= len(parts):
            continue
        if parts[index + 1] != "openclaw":
            continue
        return _extract_semver(parts[index + 2])

    for directory in [resolved.parent, *resolved.parents]:
        package_json = directory / "package.json"
        if not package_json.exists():
            continue
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        package_name = str(payload.get("name") or "")
        if "openclaw" not in package_name:
            continue

        version = _extract_semver(str(payload.get("version") or ""))
        if version:
            return version

    return None


def _detect_openclaw_version_from_command(binary_path: str | None) -> str | None:
    if not binary_path:
        return None

    try:
        completed = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    for candidate in (completed.stdout, getattr(completed, "stderr", "")):
        version = _extract_semver(candidate)
        if version:
            return version
    return None


def _get_openclaw_binary_path() -> str | None:
    explicit = _get_env("OPENCLAW_BIN_PATH")
    if explicit:
        return explicit
    return shutil.which("openclaw")


def _detect_installed_openclaw_version() -> str | None:
    global _OPENCLAW_VERSION_CACHE

    if _OPENCLAW_VERSION_CACHE is not None:
        return _OPENCLAW_VERSION_CACHE or None

    for env_name in ("TOKENLEAGUE_OPENCLAW_VERSION", "OPENCLAW_VERSION"):
        version = _extract_semver(_get_env(env_name))
        if version:
            _OPENCLAW_VERSION_CACHE = version
            return version

    binary_path = _get_openclaw_binary_path()
    version = _detect_openclaw_version_from_command(binary_path)
    if not version:
        version = _detect_openclaw_version_from_binary(binary_path)
    _OPENCLAW_VERSION_CACHE = version or ""
    return version


def _coerce_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_timestamp(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1_000_000_000_000:
            timestamp /= 1000.0
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return str(value)


def _extract_usage(value: Any) -> dict[str, int]:
    usage = _coerce_dict(value)
    input_count = (
        usage.get("inputTokens")
        or usage.get("input_tokens")
        or usage.get("promptTokenCount")
        or usage.get("input")
        or 0
    )
    output_count = (
        usage.get("outputTokens")
        or usage.get("output_tokens")
        or usage.get("candidatesTokenCount")
        or usage.get("output")
        or 0
    )
    cache_read_count = usage.get("cacheRead") or 0
    cache_write_count = usage.get("cacheWrite") or 0
    return {
        "input_token_count": int(input_count),
        "output_token_count": int(output_count),
        "cached_input_token_count": int(cache_read_count + cache_write_count),
    }


def _extract_message(record: dict[str, Any]) -> dict[str, Any]:
    return _coerce_dict(record.get("message"))


def _extract_record_role(record: dict[str, Any]) -> str:
    record_type = str(record.get("type") or "")
    if record_type in {"user", "assistant"}:
        return record_type
    if record_type == "message":
        return str(_extract_message(record).get("role") or "")
    return ""


def _extract_record_usage(record: dict[str, Any]) -> dict[str, int]:
    direct_usage = _coerce_dict(record.get("usage"))
    if direct_usage:
        return _extract_usage(direct_usage)
    return _extract_usage(_extract_message(record).get("usage"))


def _extract_record_model_name(record: dict[str, Any]) -> str:
    message = _extract_message(record)
    return str(
        message.get("model")
        or record.get("model")
        or record.get("modelId")
        or _coerce_dict(record.get("data")).get("modelId")
        or ""
    )


def _canonical_session_record(
    value: Any,
    *,
    agent_id: str,
    session_key: str = "",
) -> dict[str, Any]:
    record = _coerce_dict(value)
    if not record:
        return {}

    enriched = dict(record)
    enriched.setdefault("agentId", agent_id)
    enriched.setdefault("sessionKey", session_key)
    enriched["id"] = str(enriched.get("id") or enriched.get("sessionId") or "")
    if not enriched.get("sessionFile"):
        session_file = enriched.get("session_path") or enriched.get("transcriptPath")
        if session_file:
            enriched["sessionFile"] = str(session_file)
    return enriched


def _load_sessions_index(root: Path) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    agents_root = root / "agents"
    if not agents_root.exists():
        return sessions

    for agent_dir in sorted(path for path in agents_root.iterdir() if path.is_dir()):
        sessions_dir = agent_dir / "sessions"
        sessions_path = sessions_dir / "sessions.json"
        if not sessions_path.exists():
            continue

        try:
            payload = json.loads(sessions_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            _write_hook_log("sessions_parse_failed", path=str(sessions_path), error=str(exc))
            continue

        sessions_value = payload.get("sessions") if isinstance(payload, dict) else None
        if isinstance(sessions_value, list):
            for session in sessions_value:
                enriched = _canonical_session_record(session, agent_id=agent_dir.name)
                if enriched:
                    sessions.append(enriched)
            continue

        if isinstance(payload, dict):
            for session_key, session in payload.items():
                enriched = _canonical_session_record(
                    session,
                    agent_id=agent_dir.name,
                    session_key=str(session_key),
                )
                if enriched:
                    sessions.append(enriched)

    return sessions


def _resolve_session_transcript_path(root: Path, session_record: dict[str, Any]) -> Path:
    session_file = str(session_record.get("sessionFile") or "")
    if session_file:
        transcript_path = Path(session_file).expanduser()
        if not transcript_path.is_absolute():
            transcript_path = (root / transcript_path).resolve()
        return transcript_path

    agent_id = str(session_record.get("agentId") or "")
    session_id = str(session_record.get("id") or "")
    return root / "agents" / agent_id / "sessions" / f"{session_id}.jsonl"


def _load_session_transcript(root: Path, session_record: dict[str, Any]) -> list[dict[str, Any]]:
    transcript_path = _resolve_session_transcript_path(root, session_record)
    if not transcript_path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        for raw_line in transcript_path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            record = json.loads(stripped)
            if isinstance(record, dict):
                records.append(record)
    except (OSError, json.JSONDecodeError) as exc:
        _write_hook_log("transcript_parse_failed", path=str(transcript_path), error=str(exc))
        return []

    return records


def _load_cursor_state() -> dict[str, Any]:
    state_path = _get_cursor_state_file()
    if not state_path.exists():
        return {"sessions": {}}

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sessions": {}}

    sessions = _coerce_dict(payload.get("sessions"))
    return {"sessions": sessions}


def _save_cursor_state(state: dict[str, Any]) -> None:
    state_path = _get_cursor_state_file()
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _get_openclaw_version() -> str:
    return str(_detect_installed_openclaw_version() or "unknown")


def _build_prompt_event_payload(
    *,
    session_record: dict[str, Any],
    assistant_record: dict[str, Any],
    user_record: dict[str, Any],
    project_name: str,
    model_name: str,
) -> dict[str, Any]:
    usage = _extract_record_usage(assistant_record)
    return {
        "external_event_id": str(assistant_record.get("id") or ""),
        "task_id": str(session_record.get("id") or ""),
        "project_name": project_name,
        "prompt_started_at": _normalize_timestamp(user_record.get("timestamp") or _extract_message(user_record).get("timestamp")),
        "prompt_finished_at": _normalize_timestamp(assistant_record.get("timestamp") or _extract_message(assistant_record).get("timestamp")),
        "input_token_count": usage["input_token_count"],
        "output_token_count": usage["output_token_count"],
        "cached_input_token_count": usage["cached_input_token_count"],
        "agent_type": AGENT_TYPE,
        "agent_version": _get_openclaw_version(),
        "model_name": model_name or str(session_record.get("model") or "unknown"),
    }


def _summarize_transcript(
    session_record: dict[str, Any], transcript_records: list[dict[str, Any]]
) -> dict[str, Any]:
    records_by_id = {
        str(record.get("id") or ""): record
        for record in transcript_records
        if isinstance(record, dict) and record.get("id")
    }
    cwd = str(session_record.get("cwd") or "")
    started_at = _normalize_timestamp(session_record.get("startedAt"))
    finished_at = _normalize_timestamp(session_record.get("finishedAt") or session_record.get("updatedAt"))
    current_model = str(session_record.get("model") or "")
    discovered_model_name = current_model
    last_user_record: dict[str, Any] = {}
    project_name = _get_project_name()
    prompt_events: list[dict[str, Any]] = []
    first_record_timestamp = ""

    for record in transcript_records:
        if not isinstance(record, dict):
            continue
        record_type = str(record.get("type") or "")
        record_timestamp = _normalize_timestamp(record.get("timestamp") or _extract_message(record).get("timestamp"))
        # Capture first timestamp as fallback for started_at
        if not first_record_timestamp and record_timestamp:
            first_record_timestamp = record_timestamp
        if record_type == "session":
            if not started_at and record_timestamp:
                started_at = record_timestamp
            if not cwd:
                cwd = str(record.get("cwd") or "")
        if record_type == "model_change":
            current_model = str(record.get("modelId") or current_model)
        if record_type == "custom":
            current_model = str(_coerce_dict(record.get("data")).get("modelId") or current_model)

        role = _extract_record_role(record)
        if role == "user":
            last_user_record = record
        elif role == "assistant":
            model_name = _extract_record_model_name(record) or current_model or discovered_model_name or "unknown"
            discovered_model_name = model_name
            assistant_id = str(record.get("id") or "")
            parent_id = str(record.get("parentId") or "")
            user_record = records_by_id.get(parent_id) or last_user_record
            if not assistant_id or _extract_record_role(user_record) != "user":
                continue
            prompt_events.append(
                _build_prompt_event_payload(
                    session_record=session_record,
                    assistant_record=record,
                    user_record=user_record,
                    project_name=project_name,
                    model_name=model_name,
                )
            )

        if record_timestamp:
            finished_at = record_timestamp

    # Fallback: use first record timestamp if started_at is still empty
    if not started_at and first_record_timestamp:
        started_at = first_record_timestamp

    return {
        "cwd": cwd,
        "project_name": project_name,
        "started_at": started_at,
        "finished_at": finished_at,
        "model_name": discovered_model_name or current_model or "unknown",
        "prompt_events": prompt_events,
    }


def _build_task_run_payload(
    session_record: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    usage = _coerce_dict(session_record.get("usage"))
    prompt_events = _coerce_list(summary.get("prompt_events"))
    usage_info = _extract_usage(usage) if usage else None
    if usage_info:
        usage_input = usage_info["input_token_count"]
        usage_output = usage_info["output_token_count"]
        usage_cached_input = usage_info["cached_input_token_count"]
    else:
        usage_input = sum(int(event.get("input_token_count") or 0) for event in prompt_events)
        usage_output = sum(int(event.get("output_token_count") or 0) for event in prompt_events)
        usage_cached_input = sum(int(event.get("cached_input_token_count") or 0) for event in prompt_events)

    return {
        "external_task_id": str(session_record.get("id") or ""),
        "project_name": str(summary.get("project_name") or _get_project_name()),
        "started_at": str(summary.get("started_at") or _normalize_timestamp(session_record.get("startedAt"))),
        "finished_at": str(
            summary.get("finished_at")
            or _normalize_timestamp(session_record.get("updatedAt") or session_record.get("finishedAt"))
        ),
        "prompt_count": len(prompt_events),
        "input_token_count": usage_input,
        "output_token_count": usage_output,
        "cached_input_token_count": usage_cached_input,
        "agent_type": AGENT_TYPE,
        "agent_version": _get_openclaw_version(),
        "model_name": str(summary.get("model_name") or session_record.get("model") or "unknown"),
    }


def collect_and_upload() -> int:
    root = _get_openclaw_root()
    _write_hook_log("collector_started", openclaw_root=str(root))
    with _cursor_lock():
        state = _load_cursor_state()
        session_state = _coerce_dict(state.get("sessions"))
        session_records = _load_sessions_index(root)
        _write_hook_log(
            "collector_sessions_discovered",
            openclaw_root=str(root),
            discovered_session_count=len(session_records),
        )
        processed_session_count = 0
        uploaded_prompt_event_count = 0
        uploaded_task_run_count = 0

        for session_record in session_records:
            session_id = str(session_record.get("id") or "")
            agent_id = str(session_record.get("agentId") or "")
            if not session_id or not agent_id:
                _write_hook_log(
                    "session_skipped",
                    reason="missing_identifiers",
                    session_key=str(session_record.get("sessionKey") or ""),
                )
                continue

            transcript_records = _load_session_transcript(root, session_record)
            summary = _summarize_transcript(session_record, transcript_records)
            prompt_events = _coerce_list(summary.get("prompt_events"))
            current_session_state = _coerce_dict(session_state.get(session_id))
            processed_event_ids = {
                str(value)
                for value in _coerce_list(current_session_state.get("processed_event_ids"))
                if str(value)
            }

            new_processed_ids = set(processed_event_ids)
            prompt_uploads_succeeded = True
            session_uploaded_prompt_event_count = 0
            for payload in prompt_events:
                event_id = str(payload.get("external_event_id") or "")
                if not event_id or event_id in processed_event_ids:
                    continue
                if not _send_api_request("/api/ingest/prompt-event", payload):
                    prompt_uploads_succeeded = False
                    break
                new_processed_ids.add(event_id)
                session_uploaded_prompt_event_count += 1
                uploaded_prompt_event_count += 1

            if not prompt_uploads_succeeded:
                session_state[session_id] = current_session_state
                _write_hook_log(
                    "session_processed",
                    session_id=session_id,
                    transcript_record_count=len(transcript_records),
                    discovered_prompt_event_count=len(prompt_events),
                    uploaded_prompt_event_count=session_uploaded_prompt_event_count,
                    task_run_uploaded=False,
                    status="prompt_upload_failed",
                )
                continue

            aggregate_timestamp = str(
                summary.get("finished_at")
                or _normalize_timestamp(session_record.get("updatedAt") or session_record.get("finishedAt"))
            )
            task_run_uploaded = False
            if aggregate_timestamp and aggregate_timestamp != str(
                current_session_state.get("last_task_finished_at") or ""
            ):
                task_payload = _build_task_run_payload(session_record, summary)
                if _send_api_request("/api/ingest/task-run", task_payload):
                    current_session_state["last_task_finished_at"] = aggregate_timestamp
                    uploaded_task_run_count += 1
                    task_run_uploaded = True

            current_session_state["processed_event_ids"] = sorted(new_processed_ids)
            session_state[session_id] = current_session_state
            processed_session_count += 1
            _write_hook_log(
                "session_processed",
                session_id=session_id,
                transcript_record_count=len(transcript_records),
                discovered_prompt_event_count=len(prompt_events),
                uploaded_prompt_event_count=session_uploaded_prompt_event_count,
                task_run_uploaded=task_run_uploaded,
                model_name=str(summary.get("model_name") or "unknown"),
            )

        state["sessions"] = session_state
        _save_cursor_state(state)

    _write_hook_log(
        "collector_finished",
        openclaw_root=str(root),
        discovered_session_count=len(session_records),
        processed_session_count=processed_session_count,
        uploaded_prompt_event_count=uploaded_prompt_event_count,
        uploaded_task_run_count=uploaded_task_run_count,
    )
    return 0


def main() -> None:
    raise SystemExit(collect_and_upload())


if __name__ == "__main__":
    main()
