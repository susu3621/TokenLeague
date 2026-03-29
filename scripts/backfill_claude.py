#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import backfill_common


HOOK_PATH = Path(__file__).resolve().parents[1] / "hooks" / "claude" / "tokenleague.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("tokenleague_claude_hook_backfill", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


hook = _load_hook_module()
send_request = hook._send_api_request


def _default_root() -> Path:
    return Path.home() / ".claude" / "projects"


def _contains_subagent_path(path: Path) -> bool:
    return "subagents" in path.parts


def _extract_event_context(entries: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    for entry in entries:
        session_id = str(entry.get("sessionId") or "").strip()
        cwd = str(entry.get("cwd") or "").strip()
        if session_id or cwd:
            return {
                "session_id": session_id or path.stem,
                "cwd": cwd,
            }
    return {"session_id": path.stem, "cwd": ""}


def _build_session(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    entries = hook._load_transcript_entries(str(path))
    if not entries:
        return None, "empty_transcript"

    event_context = _extract_event_context(entries, path)
    prompt_events, task_run = hook._build_usage_payloads_from_transcript(
        {
            "session_id": event_context["session_id"],
            "transcript_path": str(path),
            "cwd": event_context["cwd"],
        }
    )
    if not prompt_events or task_run is None:
        return None, "no_prompt_events"

    return {
        "path": path,
        "session_id": event_context["session_id"],
        "prompt_events": prompt_events,
        "task_run": task_run,
    }, None


def main(argv: list[str] | None = None) -> int:
    parser = backfill_common.build_parser(_default_root(), "Backfill Claude Code transcript usage")
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser()
    summary = backfill_common.Summary(root=root, days=args.days)

    if not args.dry_run and not backfill_common.ensure_upload_env():
        print("Missing TOKENLEAGUE_HOOK_KEY")
        return 1

    if not root.exists():
        backfill_common.print_summary(summary, dry_run=args.dry_run)
        return 0

    sessions: list[dict[str, Any]] = []
    for path in sorted(root.glob("**/*.jsonl")):
        if _contains_subagent_path(path):
            continue
        if args.days and not backfill_common.modified_within_days(path, days=args.days):
            if args.verbose:
                print(f"FILTERED {path}: older_than_days")
            continue
        summary.scanned_files += 1
        try:
            session, skip_reason = _build_session(path)
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
