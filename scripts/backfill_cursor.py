#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import backfill_common


HOOK_PATH = Path(__file__).resolve().parents[1] / "hooks" / "cursor" / "tokenleague.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("tokenleague_cursor_hook_backfill", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


hook = _load_hook_module()
send_request = hook._send_api_request


def _default_root() -> Path:
    return Path.home() / ".cursor" / "projects"


def _extract_usage(item: dict[str, Any]) -> tuple[int, int, int, bool]:
    usage = item.get("usage")
    if not isinstance(usage, dict):
        return 0, 0, 0, False

    input_tokens = int(usage.get("input_tokens") or usage.get("input_token_count") or 0)
    output_tokens = int(usage.get("output_tokens") or usage.get("output_token_count") or 0)
    cached_tokens = int(
        usage.get("cached_input_tokens")
        or usage.get("cache_read_input_tokens")
        or 0
    )
    return input_tokens, output_tokens, cached_tokens, True


def _project_name(path: Path, item: dict[str, Any]) -> str:
    cwd = str(item.get("cwd") or "").strip()
    if cwd:
        return hook._detect_project_name(cwd)
    try:
        return path.parents[1].name
    except IndexError:
        return path.parent.name


def _build_session_from_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return None, "unsupported_cursor_format"

    prompt_events: list[dict[str, Any]] = []
    session_id = path.stem
    saw_assistant = False
    pending_user: dict[str, Any] | None = None

    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role == "user":
            pending_user = item
            continue
        if role != "assistant":
            continue

        saw_assistant = True
        input_tokens, output_tokens, cached_tokens, has_usage = _extract_usage(item)
        if not has_usage:
            continue

        started_at = str((pending_user or {}).get("timestamp") or "").strip()
        finished_at = str(item.get("timestamp") or "").strip()
        if not started_at or not finished_at:
            return None, "missing_timestamps"

        prompt_events.append(
            {
                "external_event_id": str(item.get("id") or item.get("uuid") or f"{session_id}:message:{index}"),
                "task_id": session_id,
                "project_name": _project_name(path, item),
                "prompt_started_at": started_at,
                "prompt_finished_at": finished_at,
                "input_token_count": input_tokens,
                "output_token_count": output_tokens,
                "cached_input_token_count": cached_tokens,
                "agent_type": "cursor",
                "agent_version": str(item.get("version") or "unknown"),
                "model_name": str(item.get("model") or "unknown"),
            }
        )

    if not prompt_events:
        return None, "missing_token_usage" if saw_assistant else "no_assistant_messages"

    task_run = {
        "external_task_id": session_id,
        "project_name": prompt_events[0]["project_name"],
        "started_at": prompt_events[0]["prompt_started_at"],
        "finished_at": prompt_events[-1]["prompt_finished_at"],
        "prompt_count": len(prompt_events),
        "input_token_count": sum(event["input_token_count"] for event in prompt_events),
        "output_token_count": sum(event["output_token_count"] for event in prompt_events),
        "cached_input_token_count": sum(event["cached_input_token_count"] for event in prompt_events),
        "agent_type": "cursor",
        "agent_version": prompt_events[-1]["agent_version"],
        "model_name": prompt_events[-1]["model_name"],
    }
    return {
        "path": path,
        "session_id": session_id,
        "prompt_events": prompt_events,
        "task_run": task_run,
    }, None


def main(argv: list[str] | None = None) -> int:
    parser = backfill_common.build_parser(_default_root(), "Backfill Cursor transcript usage")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser()
    summary = backfill_common.Summary(root=root)

    if not args.dry_run and not backfill_common.ensure_upload_env():
        print("Missing TOKENLEAGUE_HOOK_KEY")
        return 1

    if not root.exists():
        backfill_common.print_summary(summary, dry_run=args.dry_run)
        return 0

    sessions: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/agent-transcripts/*.json")):
        summary.scanned_files += 1
        try:
            session, skip_reason = _build_session_from_json(path)
        except Exception:
            summary.add_failure()
            if args.verbose:
                print(f"FAILED {path}")
            continue

        if session is None:
            summary.add_skip(skip_reason or "skipped")
            if args.verbose:
                print(f"SKIPPED {path}: {skip_reason}")
            continue
        sessions.append(session)

    summary.discovered_sessions = len(sessions)
    if args.limit > 0:
        sessions = sessions[:args.limit]

    for session in sessions:
        summary.processed_sessions += 1
        summary.generated_prompt_events += len(session["prompt_events"])
        summary.generated_task_runs += 1
        summary.add_samples(session["prompt_events"], session["task_run"])
        if args.verbose:
            print(f"SESSION {session['session_id']} from {session['path']}")
        if args.dry_run:
            continue
        if not backfill_common.upload_session(send_request, session["prompt_events"], session["task_run"]):
            summary.add_failure()

    backfill_common.print_summary(summary, dry_run=args.dry_run)
    return 1 if summary.failed_items else 0


if __name__ == "__main__":
    raise SystemExit(main())
