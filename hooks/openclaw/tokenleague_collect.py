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
import socket
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


def _get_env(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def _get_api_url() -> str:
    return (_get_env("TOKENLEAGUE_API_URL") or DEFAULT_API_URL).rstrip("/")


def _get_hook_key() -> str | None:
    return _get_env("TOKENLEAGUE_HOOK_KEY")


def _get_openclaw_root() -> Path:
    configured = _get_env("TOKENLEAGUE_OPENCLAW_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".openclaw"


def _get_temp_dir() -> Path:
    return Path(_get_env("TMPDIR", "/tmp") or "/tmp")


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


def _detect_project_name(cwd: str | None = None) -> str:
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
        repo_root = _resolve_worktree_repo_root(root)
        if repo_root is not None:
            return repo_root.name

    normalized = str(candidate).rstrip("/\\")
    if not normalized:
        return ""
    return normalized.split("/")[-1].split("\\")[-1]


def _coerce_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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

        for session in _coerce_list(payload.get("sessions")):
            record = _coerce_dict(session)
            if not record:
                continue
            enriched = dict(record)
            enriched.setdefault("agentId", agent_dir.name)
            sessions.append(enriched)

    return sessions


def _load_session_transcript(root: Path, agent_id: str, session_id: str) -> list[dict[str, Any]]:
    transcript_path = root / "agents" / agent_id / "sessions" / f"{session_id}.jsonl"
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
    return str(_get_env("TOKENLEAGUE_OPENCLAW_VERSION") or "unknown")


def _build_prompt_event_payload(
    *,
    session_record: dict[str, Any],
    assistant_record: dict[str, Any],
    user_record: dict[str, Any],
    project_name: str,
) -> dict[str, Any]:
    usage = _coerce_dict(assistant_record.get("usage"))
    return {
        "external_event_id": str(assistant_record.get("id") or ""),
        "task_id": str(session_record.get("id") or ""),
        "project_name": project_name,
        "prompt_started_at": str(user_record.get("timestamp") or ""),
        "prompt_finished_at": str(assistant_record.get("timestamp") or ""),
        "input_token_count": int(usage.get("inputTokens") or 0),
        "output_token_count": int(usage.get("outputTokens") or 0),
        "agent_type": AGENT_TYPE,
        "agent_version": _get_openclaw_version(),
        "model_name": str(session_record.get("model") or "unknown"),
    }


def _extract_prompt_events(
    session_record: dict[str, Any], transcript_records: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    records_by_id = {
        str(record.get("id") or ""): record
        for record in transcript_records
        if isinstance(record, dict) and record.get("id")
    }
    project_name = _detect_project_name(session_record.get("cwd"))
    prompt_events: list[dict[str, Any]] = []
    for record in transcript_records:
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        assistant_id = str(record.get("id") or "")
        parent_id = str(record.get("parentId") or "")
        user_record = records_by_id.get(parent_id, {})
        if not assistant_id or user_record.get("type") != "user":
            continue
        prompt_events.append(
            _build_prompt_event_payload(
                session_record=session_record,
                assistant_record=record,
                user_record=user_record,
                project_name=project_name,
            )
        )
    return prompt_events


def _build_task_run_payload(session_record: dict[str, Any], project_name: str) -> dict[str, Any]:
    usage = _coerce_dict(session_record.get("usage"))
    prompt_count = 0
    transcript_records = _load_session_transcript(
        _get_openclaw_root(),
        str(session_record.get("agentId") or ""),
        str(session_record.get("id") or ""),
    )
    for record in transcript_records:
        if isinstance(record, dict) and record.get("type") == "assistant":
            prompt_count += 1

    return {
        "external_task_id": str(session_record.get("id") or ""),
        "project_name": project_name,
        "started_at": str(session_record.get("startedAt") or ""),
        "finished_at": str(session_record.get("updatedAt") or session_record.get("finishedAt") or ""),
        "prompt_count": prompt_count,
        "input_token_count": int(usage.get("inputTokens") or 0),
        "output_token_count": int(usage.get("outputTokens") or 0),
        "agent_type": AGENT_TYPE,
        "agent_version": _get_openclaw_version(),
        "model_name": str(session_record.get("model") or "unknown"),
    }


def collect_and_upload() -> int:
    root = _get_openclaw_root()
    with _cursor_lock():
        state = _load_cursor_state()
        session_state = _coerce_dict(state.get("sessions"))

        for session_record in _load_sessions_index(root):
            session_id = str(session_record.get("id") or "")
            agent_id = str(session_record.get("agentId") or "")
            if not session_id or not agent_id:
                continue

            project_name = _detect_project_name(session_record.get("cwd"))
            transcript_records = _load_session_transcript(root, agent_id, session_id)
            prompt_events = _extract_prompt_events(session_record, transcript_records)
            current_session_state = _coerce_dict(session_state.get(session_id))
            processed_event_ids = {
                str(value)
                for value in _coerce_list(current_session_state.get("processed_event_ids"))
                if str(value)
            }

            new_processed_ids = set(processed_event_ids)
            prompt_uploads_succeeded = True
            for payload in prompt_events:
                event_id = str(payload.get("external_event_id") or "")
                if not event_id or event_id in processed_event_ids:
                    continue
                if not _send_api_request("/api/ingest/prompt-event", payload):
                    prompt_uploads_succeeded = False
                    break
                new_processed_ids.add(event_id)

            if not prompt_uploads_succeeded:
                session_state[session_id] = current_session_state
                continue

            aggregate_timestamp = str(
                session_record.get("updatedAt") or session_record.get("finishedAt") or ""
            )
            if aggregate_timestamp and aggregate_timestamp != str(
                current_session_state.get("last_task_finished_at") or ""
            ):
                task_payload = _build_task_run_payload(session_record, project_name)
                if _send_api_request("/api/ingest/task-run", task_payload):
                    current_session_state["last_task_finished_at"] = aggregate_timestamp

            current_session_state["processed_event_ids"] = sorted(new_processed_ids)
            session_state[session_id] = current_session_state

        state["sessions"] = session_state
        _save_cursor_state(state)

    return 0


def main() -> None:
    raise SystemExit(collect_and_upload())


if __name__ == "__main__":
    main()
