#!/usr/bin/env python3
"""
TokenLeague Statistics Hook for Codex CLI.

This hook captures Codex session metadata on UserPromptSubmit and aggregates the
latest completed turn on Stop before upserting usage into TokenLeague.
"""

from __future__ import annotations

import contextlib
import fcntl
import ipaddress
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit


DEFAULT_API_URL = "http://localhost:5006"
HOOK_LOG_FILE_NAME = ".tokenleague_codex_hook.log"
AGENT_TYPE = "codex"
SESSION_LOCK_TIMEOUT_SECONDS = 0.5
SESSION_LOCK_RETRY_INTERVAL_SECONDS = 0.05


class _SessionLockTimeoutError(TimeoutError):
    pass


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


def _sanitize_session_id(session_id: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in session_id)


def _get_session_state_file(session_id: str) -> Path:
    return _get_temp_dir() / f".tokenleague_codex_session_{_sanitize_session_id(session_id)}.json"


def _get_session_lock_file(session_id: str) -> Path:
    return _get_temp_dir() / f".tokenleague_codex_session_{_sanitize_session_id(session_id)}.lock"


@contextlib.contextmanager
def _session_lock(session_id: str) -> Iterator[None]:
    lock_path = _get_session_lock_file(session_id)
    with lock_path.open("w", encoding="utf-8") as handle:
        deadline = time.monotonic() + SESSION_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise _SessionLockTimeoutError(session_id) from exc
                time.sleep(SESSION_LOCK_RETRY_INTERVAL_SECONDS)
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


def _empty_task_run_state() -> dict[str, Any]:
    return {
        "started_at": "",
        "finished_at": "",
        "prompt_count": 0,
        "input_token_count": 0,
        "output_token_count": 0,
        "cached_input_token_count": 0,
    }


def _normalize_task_run_state(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    return {
        "started_at": str(payload.get("started_at") or ""),
        "finished_at": str(payload.get("finished_at") or ""),
        "prompt_count": int(payload.get("prompt_count") or 0),
        "input_token_count": int(payload.get("input_token_count") or 0),
        "output_token_count": int(payload.get("output_token_count") or 0),
        "cached_input_token_count": int(payload.get("cached_input_token_count") or 0),
    }


def _normalize_session_state(session_state: dict[str, Any]) -> dict[str, Any]:
    payload = session_state if isinstance(session_state, dict) else {}
    processed_turn_ids = payload.get("processed_turn_ids")
    if not isinstance(processed_turn_ids, list):
        processed_turn_ids = []

    baseline_completed_turn_count = payload.get("baseline_completed_turn_count")
    if baseline_completed_turn_count is None:
        baseline_completed_turn_count = None
    else:
        baseline_completed_turn_count = int(baseline_completed_turn_count)

    return {
        "session_id": str(payload.get("session_id") or ""),
        "transcript_path": str(payload.get("transcript_path") or ""),
        "model_name": str(payload.get("model_name") or "unknown"),
        "cwd": str(payload.get("cwd") or ""),
        "project_name": str(payload.get("project_name") or ""),
        "baseline_completed_turn_count": baseline_completed_turn_count,
        "processed_turn_ids": [str(turn_id) for turn_id in processed_turn_ids if turn_id],
        "task_run": _normalize_task_run_state(payload.get("task_run")),
    }


def _load_session_state(session_id: str) -> dict[str, Any]:
    session_path = _get_session_state_file(session_id)
    if not session_path.exists():
        return _normalize_session_state({})
    try:
        with session_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return _normalize_session_state({})
    return _normalize_session_state(payload if isinstance(payload, dict) else {})


def _save_session_state(session_id: str, session_state: dict[str, Any]) -> None:
    session_path = _get_session_state_file(session_id)
    try:
        with session_path.open("w", encoding="utf-8") as handle:
            json.dump(_normalize_session_state(session_state), handle, ensure_ascii=False, indent=2, sort_keys=True)
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
            "cwd": str(payload.get("cwd") or ""),
            "agent_version": str(payload.get("cli_version") or payload.get("agent_version") or "unknown"),
        }
    return {
        "session_id": "",
        "started_at": "",
        "cwd": "",
        "agent_version": "unknown",
    }


def _extract_completed_turns(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    completed_turns: list[dict[str, Any]] = []
    current_turn: dict[str, Any] | None = None

    for entry in entries:
        if entry.get("type") != "event_msg":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue

        event_type = str(payload.get("type") or "")
        if event_type == "task_started":
            turn_id = str(payload.get("turn_id") or "")
            if not turn_id:
                continue
            current_turn = {
                "turn_id": turn_id,
                "started_at": str(entry.get("timestamp") or ""),
                "finished_at": "",
                "input_token_count": 0,
                "output_token_count": 0,
                "cached_input_token_count": 0,
            }
            continue

        if event_type == "token_count":
            if current_turn is None:
                continue
            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            last_usage = info.get("last_token_usage")
            if not isinstance(last_usage, dict):
                continue
            current_turn["input_token_count"] += int(last_usage.get("input_tokens") or 0)
            current_turn["output_token_count"] += int(last_usage.get("output_tokens") or 0)
            current_turn["cached_input_token_count"] += int(last_usage.get("cached_input_tokens") or 0)
            continue

        if event_type == "task_complete":
            turn_id = str(payload.get("turn_id") or "")
            if current_turn is None or current_turn.get("turn_id") != turn_id:
                continue
            current_turn["finished_at"] = str(entry.get("timestamp") or "")
            completed_turns.append(dict(current_turn))
            current_turn = None

    return completed_turns


def _build_prompt_event(
    *,
    session_id: str,
    turn: dict[str, Any],
    project_name: str,
    model_name: str,
    agent_version: str,
) -> dict[str, Any]:
    turn_id = str(turn["turn_id"])
    return {
        "external_event_id": f"{session_id}:turn:{turn_id}",
        "task_id": session_id,
        "project_name": project_name,
        "prompt_started_at": str(turn["started_at"]),
        "prompt_finished_at": str(turn["finished_at"]),
        "input_token_count": int(turn["input_token_count"]),
        "output_token_count": int(turn["output_token_count"]),
        "cached_input_token_count": int(turn["cached_input_token_count"]),
        "agent_type": AGENT_TYPE,
        "agent_version": agent_version,
        "model_name": model_name,
    }


def _accumulate_task_run_state(
    task_run_state: dict[str, Any],
    prompt_event: dict[str, Any],
) -> dict[str, Any]:
    next_state = dict(task_run_state)
    started_at = str(prompt_event["prompt_started_at"])
    finished_at = str(prompt_event["prompt_finished_at"])
    if not next_state["started_at"]:
        next_state["started_at"] = started_at
    next_state["finished_at"] = finished_at
    next_state["prompt_count"] += 1
    next_state["input_token_count"] += int(prompt_event["input_token_count"])
    next_state["output_token_count"] += int(prompt_event["output_token_count"])
    next_state["cached_input_token_count"] += int(prompt_event["cached_input_token_count"])
    return next_state


def _build_task_run_payload(
    *,
    session_id: str,
    task_run_state: dict[str, Any],
    project_name: str,
    model_name: str,
    agent_version: str,
) -> dict[str, Any] | None:
    if not task_run_state["started_at"] or not task_run_state["finished_at"]:
        return None
    return {
        "external_task_id": session_id,
        "project_name": project_name,
        "started_at": task_run_state["started_at"],
        "finished_at": task_run_state["finished_at"],
        "prompt_count": int(task_run_state["prompt_count"]),
        "input_token_count": int(task_run_state["input_token_count"]),
        "output_token_count": int(task_run_state["output_token_count"]),
        "cached_input_token_count": int(task_run_state["cached_input_token_count"]),
        "agent_type": AGENT_TYPE,
        "agent_version": agent_version,
        "model_name": model_name,
    }


def _completed_turn_count(transcript_path: str) -> int:
    return len(_extract_completed_turns(_load_transcript_entries(transcript_path)))


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

    try:
        with _session_lock(session_id):
            session_state = _load_session_state(session_id)
            baseline_completed_turn_count = session_state["baseline_completed_turn_count"]
            if baseline_completed_turn_count is None:
                baseline_completed_turn_count = _completed_turn_count(transcript_path)

            updated_state = {
                **session_state,
                "session_id": session_id,
                "transcript_path": transcript_path,
                "model_name": str(event_data.get("model") or session_state.get("model_name") or "unknown"),
                "cwd": str(event_data.get("cwd") or session_state.get("cwd") or ""),
                "project_name": _detect_project_name(event_data.get("cwd") or session_state.get("cwd")),
                "baseline_completed_turn_count": baseline_completed_turn_count,
            }
            _save_session_state(session_id, updated_state)
    except _SessionLockTimeoutError:
        _write_hook_log(
            "session_lock_timeout",
            session_id=session_id,
            hook_event_name="UserPromptSubmit",
            timeout_seconds=SESSION_LOCK_TIMEOUT_SECONDS,
        )
        return

    _write_hook_log(
        "user_prompt_submit_recorded",
        session_id=session_id,
        transcript_path=transcript_path,
        baseline_completed_turn_count=baseline_completed_turn_count,
        model_name=updated_state["model_name"],
    )


def _handle_stop(event_data: dict[str, Any]) -> None:
    session_id = str(event_data.get("session_id") or "")
    if not session_id:
        _write_hook_log("stop_skipped", reason="missing_session_id")
        return

    try:
        with _session_lock(session_id):
            session_state = _load_session_state(session_id)
            transcript_path = str(event_data.get("transcript_path") or session_state.get("transcript_path") or "")
            if not transcript_path:
                _write_hook_log(
                    "stop_skipped",
                    reason="missing_transcript_path",
                    session_id=session_id,
                )
                return

            entries = _load_transcript_entries(transcript_path)
            if not entries:
                _write_hook_log(
                    "stop_skipped",
                    reason="empty_transcript",
                    session_id=session_id,
                    transcript_path=transcript_path,
                )
                return

            session_metadata = _extract_session_metadata(entries)
            completed_turns = _extract_completed_turns(entries)
            if not completed_turns:
                _write_hook_log(
                    "stop_skipped",
                    reason="no_completed_turns",
                    session_id=session_id,
                    transcript_path=transcript_path,
                )
                return

            baseline_completed_turn_count = session_state["baseline_completed_turn_count"]
            if baseline_completed_turn_count is None:
                baseline_completed_turn_count = max(len(completed_turns) - 1, 0)
                session_state["baseline_completed_turn_count"] = baseline_completed_turn_count

            tracked_turns = completed_turns[baseline_completed_turn_count:]
            processed_turn_ids = set(session_state["processed_turn_ids"])
            unprocessed_turns = [
                turn for turn in tracked_turns if str(turn.get("turn_id") or "") not in processed_turn_ids
            ]
            if not unprocessed_turns:
                _write_hook_log(
                    "stop_skipped",
                    reason="no_unprocessed_turns",
                    session_id=session_id,
                    transcript_path=transcript_path,
                    baseline_completed_turn_count=baseline_completed_turn_count,
                )
                return

            model_name = str(event_data.get("model") or session_state.get("model_name") or "unknown")
            agent_version = session_metadata["agent_version"] or "unknown"
            project_name = (
                str(session_state.get("project_name") or "")
                or _detect_project_name(session_metadata.get("cwd"))
                or _detect_project_name(event_data.get("cwd"))
            )
            prompt_events = [
                _build_prompt_event(
                    session_id=session_id,
                    turn=turn,
                    project_name=project_name,
                    model_name=model_name,
                    agent_version=agent_version,
                )
                for turn in unprocessed_turns
            ]

            next_task_run_state = _normalize_task_run_state(session_state.get("task_run"))
            for prompt_event in prompt_events:
                next_task_run_state = _accumulate_task_run_state(next_task_run_state, prompt_event)

            task_run = _build_task_run_payload(
                session_id=session_id,
                task_run_state=next_task_run_state,
                project_name=project_name,
                model_name=model_name,
                agent_version=agent_version,
            )
            if task_run is None:
                _write_hook_log(
                    "stop_skipped",
                    reason="missing_task_run",
                    session_id=session_id,
                    transcript_path=transcript_path,
                )
                return

            _write_hook_log(
                "transcript_parsed",
                session_id=session_id,
                transcript_path=transcript_path,
                tracked_turn_count=len(tracked_turns),
                unprocessed_turn_count=len(unprocessed_turns),
                latest_turn_id=str(unprocessed_turns[-1]["turn_id"]),
                input_token_count=task_run["input_token_count"],
                output_token_count=task_run["output_token_count"],
            )

            prompt_upload_succeeded = True
            for prompt_event in prompt_events:
                if not _send_api_request("/api/ingest/prompt-event", prompt_event):
                    prompt_upload_succeeded = False
                    break

            if not prompt_upload_succeeded:
                return

            if not _send_api_request("/api/ingest/task-run", task_run):
                return

            session_state["processed_turn_ids"] = [
                *session_state["processed_turn_ids"],
                *[str(turn["turn_id"]) for turn in unprocessed_turns],
            ]
            session_state["task_run"] = next_task_run_state
            session_state["transcript_path"] = transcript_path
            session_state["model_name"] = model_name
            session_state["project_name"] = project_name
            _save_session_state(session_id, session_state)
    except _SessionLockTimeoutError:
        _write_hook_log(
            "session_lock_timeout",
            session_id=session_id,
            hook_event_name="Stop",
            timeout_seconds=SESSION_LOCK_TIMEOUT_SECONDS,
        )
        return


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
