#!/usr/bin/env python3
"""
TokenLeague Statistics Hook for Gemini CLI.

This hook records Gemini turn usage across BeforeAgent, AfterModel, and
AfterAgent, then uploads prompt and task usage to TokenLeague.
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
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit


DEFAULT_API_URL = "http://localhost:5006"
HOOK_LOG_FILE_NAME = ".tokenleague_gemini_hook.log"
AGENT_TYPE = "gemini-cli"
_GEMINI_CLI_VERSION_CACHE: str | None = None

# ANSI color codes disabled for Gemini CLI (does not support ANSI escape codes)
ANSI_GREEN = ""
ANSI_RED = ""
ANSI_BOLD = ""
ANSI_RESET = ""


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
    return _get_temp_dir() / f".tokenleague_gemini_session_{_sanitize_session_id(session_id)}.json"


def _get_session_lock_file(session_id: str) -> Path:
    return _get_temp_dir() / f".tokenleague_gemini_session_{_sanitize_session_id(session_id)}.lock"


@contextlib.contextmanager
def _session_lock(session_id: str) -> Iterator[None]:
    lock_path = _get_session_lock_file(session_id)
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


def _normalize_pending_turn_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        return {}

    latest_usage = value.get("latest_usage")
    if not isinstance(latest_usage, dict):
        latest_usage = {}

    return {
        "prompt": str(value.get("prompt") or ""),
        "started_at": str(value.get("started_at") or ""),
        "latest_usage": latest_usage,
        "latest_response_id": str(value.get("latest_response_id") or ""),
        "latest_model_name": str(value.get("latest_model_name") or ""),
        "latest_agent_version": str(
            value.get("latest_agent_version")
            or value.get("latest_model_version")
            or "unknown"
        ),
        "latest_model_version": str(value.get("latest_model_version") or "unknown"),
    }


def _normalize_session_state(session_state: dict[str, Any]) -> dict[str, Any]:
    payload = session_state if isinstance(session_state, dict) else {}
    return {
        "session_id": str(payload.get("session_id") or ""),
        "cwd": str(payload.get("cwd") or ""),
        "project_name": str(payload.get("project_name") or ""),
        "agent_version": str(payload.get("agent_version") or "unknown"),
        "model_name": str(payload.get("model_name") or "unknown"),
        "task_run": _normalize_task_run_state(payload.get("task_run")),
        "pending_turn": _normalize_pending_turn_state(payload.get("pending_turn")),
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


def _delete_session_state(session_id: str) -> None:
    session_path = _get_session_state_file(session_id)
    try:
        session_path.unlink(missing_ok=True)
    except OSError:
        pass


def _get_session_id(event_data: dict[str, Any]) -> str:
    return str(event_data.get("session_id") or _get_env("GEMINI_SESSION_ID") or "")


def _build_session_start_message() -> str:
    api_url = _get_api_url()
    hook_key = _get_hook_key()

    if _get_env("TOKENLEAGUE_API_URL"):
        api_url_status = f"{ANSI_GREEN}configured{ANSI_RESET} ({api_url})"
    else:
        api_url_status = f"{ANSI_RED}default{ANSI_RESET} ({api_url})"

    if hook_key:
        hook_key_status = f"{ANSI_GREEN}configured{ANSI_RESET}"
    else:
        hook_key_status = f"{ANSI_RED}missing{ANSI_RESET}"

    return f"{ANSI_BOLD}[TokenLeague]{ANSI_RESET} TOKENLEAGUE_API_URL={api_url_status}, TOKENLEAGUE_HOOK_KEY={hook_key_status}"


def _handle_session_start(event_data: dict[str, Any]) -> dict[str, Any]:
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


def _extract_usage_counts(usage_metadata: dict[str, Any]) -> tuple[int, int, int] | None:
    """Extract input, output, and cached token counts from usage metadata."""
    if not isinstance(usage_metadata, dict) or not usage_metadata:
        return None

    prompt_tokens = usage_metadata.get("promptTokenCount")
    candidate_tokens = usage_metadata.get("candidatesTokenCount")
    total_tokens = usage_metadata.get("totalTokenCount")
    # Gemini API uses cachedContentTokenCount for cached tokens
    cached_tokens = usage_metadata.get("cachedContentTokenCount")

    if prompt_tokens is None and candidate_tokens is None and total_tokens is None:
        return None

    if prompt_tokens is None:
        if total_tokens is not None and candidate_tokens is not None:
            prompt_tokens = max(int(total_tokens) - int(candidate_tokens), 0)
        elif total_tokens is not None:
            prompt_tokens = int(total_tokens)
        else:
            prompt_tokens = 0

    if candidate_tokens is None:
        if total_tokens is not None and usage_metadata.get("promptTokenCount") is not None:
            candidate_tokens = max(int(total_tokens) - int(usage_metadata.get("promptTokenCount") or 0), 0)
        elif total_tokens is not None and prompt_tokens == int(total_tokens):
            candidate_tokens = 0
        else:
            candidate_tokens = 0

    return int(prompt_tokens or 0), int(candidate_tokens or 0), int(cached_tokens or 0)


def _extract_response_id(llm_response: dict[str, Any]) -> str:
    return str(
        llm_response.get("responseId")
        or llm_response.get("response_id")
        or llm_response.get("id")
        or ""
    )


def _extract_semver(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"\b\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?\b", text)
    if not match:
        return None
    return match.group(0)


def _detect_gemini_cli_version_from_binary(binary_path: str | None) -> str | None:
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
        if parts[index + 1] != "gemini-cli":
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
        if "gemini-cli" not in package_name:
            continue

        version = _extract_semver(str(payload.get("version") or ""))
        if version:
            return version

    return None


def _detect_installed_gemini_cli_version() -> str | None:
    global _GEMINI_CLI_VERSION_CACHE

    if _GEMINI_CLI_VERSION_CACHE is not None:
        return _GEMINI_CLI_VERSION_CACHE

    for env_name in ("TOKENLEAGUE_GEMINI_CLI_VERSION", "GEMINI_CLI_VERSION"):
        version = _extract_semver(_get_env(env_name))
        if version:
            _GEMINI_CLI_VERSION_CACHE = version
            return version

    version = _detect_gemini_cli_version_from_binary(shutil.which("gemini"))
    _GEMINI_CLI_VERSION_CACHE = version or ""
    return version


def _extract_agent_version(event_data: dict[str, Any], pending_turn: dict[str, Any]) -> str:
    for candidate in (
        event_data.get("gemini_cli_version"),
        event_data.get("cli_version"),
        event_data.get("agent_version"),
        pending_turn.get("latest_agent_version"),
        _detect_installed_gemini_cli_version(),
    ):
        version = _extract_semver(str(candidate or ""))
        if version:
            return version
    return "unknown"


def _build_prompt_event(
    *,
    session_id: str,
    pending_turn: dict[str, Any],
    project_name: str,
    prompt_finished_at: str,
) -> dict[str, Any] | None:
    token_counts = _extract_usage_counts(pending_turn.get("latest_usage", {}))
    if token_counts is None:
        return None

    input_tokens, output_tokens, cached_tokens = token_counts
    external_event_id = str(
        pending_turn.get("latest_response_id")
        or f"{session_id}:turn:{pending_turn.get('started_at') or prompt_finished_at}"
    )
    return {
        "external_event_id": external_event_id,
        "task_id": session_id,
        "project_name": project_name,
        "prompt_started_at": str(pending_turn.get("started_at") or ""),
        "prompt_finished_at": prompt_finished_at,
        "input_token_count": input_tokens,
        "output_token_count": output_tokens,
        "cached_input_token_count": cached_tokens,
        "agent_type": AGENT_TYPE,
        "agent_version": str(pending_turn.get("latest_agent_version") or "unknown"),
        "model_name": str(pending_turn.get("latest_model_name") or "unknown"),
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
    next_state["cached_input_token_count"] += int(prompt_event.get("cached_input_token_count") or 0)
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


def _handle_before_agent(event_data: dict[str, Any]) -> None:
    session_id = _get_session_id(event_data)
    if not session_id:
        _write_hook_log("before_agent_skipped", reason="missing_session_id")
        return

    with _session_lock(session_id):
        session_state = _load_session_state(session_id)
        cwd = str(event_data.get("cwd") or session_state.get("cwd") or _get_env("GEMINI_CWD") or "")
        model_name = str(session_state.get("model_name") or "unknown")
        agent_version = str(session_state.get("agent_version") or _detect_installed_gemini_cli_version() or "unknown")
        updated_state = {
            **session_state,
            "session_id": session_id,
            "cwd": cwd,
            "project_name": _detect_project_name(cwd),
            "agent_version": agent_version,
            "model_name": model_name,
            "pending_turn": {
                "prompt": str(event_data.get("prompt") or ""),
                "started_at": str(event_data.get("timestamp") or _iso_timestamp()),
                "latest_usage": {},
                "latest_response_id": "",
                "latest_model_name": model_name,
                "latest_agent_version": agent_version,
                "latest_model_version": "unknown",
            },
        }
        _save_session_state(session_id, updated_state)

    _write_hook_log(
        "before_agent_recorded",
        session_id=session_id,
        prompt=event_data.get("prompt"),
        timestamp=updated_state["pending_turn"]["started_at"],
    )


def _handle_after_model(event_data: dict[str, Any]) -> None:
    session_id = _get_session_id(event_data)
    if not session_id:
        _write_hook_log("after_model_skipped", reason="missing_session_id")
        return

    llm_request = event_data.get("llm_request")
    if not isinstance(llm_request, dict):
        llm_request = {}
    llm_response = event_data.get("llm_response")
    if not isinstance(llm_response, dict):
        llm_response = {}

    with _session_lock(session_id):
        session_state = _load_session_state(session_id)
        pending_turn = _normalize_pending_turn_state(session_state.get("pending_turn"))
        if not pending_turn:
            _write_hook_log("after_model_skipped", reason="missing_pending_turn", session_id=session_id)
            return

        # Try usageMetadata first (standard Gemini API format)
        latest_usage = llm_response.get("usageMetadata")
        # Also check for tokens object (Gemini CLI format with cached support)
        tokens_obj = llm_response.get("tokens")
        if isinstance(tokens_obj, dict) and not isinstance(latest_usage, dict):
            # Convert tokens format to usageMetadata format for consistency
            latest_usage = {
                "promptTokenCount": tokens_obj.get("input"),
                "candidatesTokenCount": tokens_obj.get("output"),
                "cachedContentTokenCount": tokens_obj.get("cached"),
                "totalTokenCount": tokens_obj.get("total"),
            }
        if not isinstance(latest_usage, dict):
            latest_usage = pending_turn.get("latest_usage", {})

        latest_model_name = str(
            llm_request.get("model")
            or pending_turn.get("latest_model_name")
            or session_state.get("model_name")
            or "unknown"
        )
        latest_agent_version = _extract_agent_version(event_data, pending_turn)
        latest_model_version = str(
            llm_response.get("modelVersion")
            or pending_turn.get("latest_model_version")
            or "unknown"
        )

        pending_turn.update(
            {
                "latest_usage": latest_usage,
                "latest_response_id": _extract_response_id(llm_response) or pending_turn.get("latest_response_id", ""),
                "latest_model_name": latest_model_name,
                "latest_agent_version": latest_agent_version,
                "latest_model_version": latest_model_version,
            }
        )
        session_state["pending_turn"] = pending_turn
        session_state["agent_version"] = latest_agent_version
        session_state["model_name"] = latest_model_name
        _save_session_state(session_id, session_state)

    _write_hook_log(
        "after_model_recorded",
        session_id=session_id,
        model_name=latest_model_name,
        agent_version=latest_agent_version,
        response_id=pending_turn.get("latest_response_id"),
    )


def _handle_after_agent(event_data: dict[str, Any]) -> None:
    session_id = _get_session_id(event_data)
    if not session_id:
        _write_hook_log("after_agent_skipped", reason="missing_session_id")
        return

    with _session_lock(session_id):
        session_state = _load_session_state(session_id)
        pending_turn = _normalize_pending_turn_state(session_state.get("pending_turn"))
        if not pending_turn:
            _write_hook_log("after_agent_skipped", reason="missing_pending_turn", session_id=session_id)
            return

        cwd = str(event_data.get("cwd") or session_state.get("cwd") or _get_env("GEMINI_CWD") or "")
        project_name = str(session_state.get("project_name") or _detect_project_name(cwd))
        prompt_finished_at = str(event_data.get("timestamp") or _iso_timestamp())
        prompt_event = _build_prompt_event(
            session_id=session_id,
            pending_turn=pending_turn,
            project_name=project_name,
            prompt_finished_at=prompt_finished_at,
        )
        if prompt_event is None:
            _write_hook_log(
                "after_agent_skipped",
                reason="missing_usage_metadata",
                session_id=session_id,
            )
            return

        next_task_run_state = _accumulate_task_run_state(
            _normalize_task_run_state(session_state.get("task_run")),
            prompt_event,
        )
        task_run = _build_task_run_payload(
            session_id=session_id,
            task_run_state=next_task_run_state,
            project_name=project_name,
            model_name=str(prompt_event["model_name"]),
            agent_version=str(prompt_event["agent_version"]),
        )
        if task_run is None:
            _write_hook_log("after_agent_skipped", reason="missing_task_run", session_id=session_id)
            return

        if not _send_api_request("/api/ingest/prompt-event", prompt_event):
            return
        if not _send_api_request("/api/ingest/task-run", task_run):
            return

        session_state["cwd"] = cwd
        session_state["project_name"] = project_name
        session_state["model_name"] = str(prompt_event["model_name"])
        session_state["task_run"] = next_task_run_state
        session_state["pending_turn"] = {}
        _save_session_state(session_id, session_state)

    _write_hook_log(
        "after_agent_uploaded",
        session_id=session_id,
        prompt_count=task_run["prompt_count"],
        input_token_count=task_run["input_token_count"],
        output_token_count=task_run["output_token_count"],
        cached_input_token_count=task_run["cached_input_token_count"],
    )


def _handle_session_end(event_data: dict[str, Any]) -> None:
    session_id = _get_session_id(event_data)
    if not session_id:
        _write_hook_log("session_end_skipped", reason="missing_session_id")
        return

    _delete_session_state(session_id)
    _write_hook_log("session_end_cleaned", session_id=session_id, reason=event_data.get("reason"))


def main() -> None:
    try:
        event_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    hook_event = str(event_data.get("hook_event_name") or "")
    response_payload: dict[str, Any] | None = None

    if hook_event == "SessionStart":
        response_payload = _handle_session_start(event_data)
    elif hook_event == "BeforeAgent":
        _handle_before_agent(event_data)
    elif hook_event == "AfterModel":
        _handle_after_model(event_data)
    elif hook_event == "AfterAgent":
        _handle_after_agent(event_data)
    elif hook_event == "SessionEnd":
        _handle_session_end(event_data)
    else:
        _write_hook_log("hook_event_ignored", hook_event=hook_event or "unknown")

    if response_payload is not None:
        json.dump(response_payload, sys.stdout)
        sys.stdout.write("\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
