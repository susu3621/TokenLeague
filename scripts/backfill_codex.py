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


HOOK_PATH = Path(__file__).resolve().parents[1] / "hooks" / "codex" / "tokenleague.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("tokenleague_codex_hook_backfill", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


hook = _load_hook_module()
send_request = hook._send_api_request


def _default_root() -> Path:
    return Path.home() / ".codex" / "sessions"


def _extract_model_name(entries: list[dict[str, Any]]) -> str:
    for entry in entries:
        if entry.get("type") != "turn_context":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        model = str(payload.get("model") or "").strip()
        if model:
            return model
    return "unknown"


def _build_session(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    entries = hook._load_transcript_entries(str(path))
    if not entries:
        return None, "empty_transcript"

    session_metadata = hook._extract_session_metadata(entries)
    completed_turns = hook._extract_completed_turns(entries)
    if not completed_turns:
        return None, "no_completed_turns"

    session_id = str(session_metadata.get("session_id") or path.stem)
    project_name = hook._detect_project_name(session_metadata.get("cwd"))
    model_name = _extract_model_name(entries)
    agent_version = str(session_metadata.get("agent_version") or "unknown")

    prompt_events: list[dict[str, Any]] = []
    task_run_state = hook._empty_task_run_state()
    for turn in completed_turns:
        prompt_event = hook._build_prompt_event(
            session_id=session_id,
            turn=turn,
            project_name=project_name,
            model_name=model_name,
            agent_version=agent_version,
        )
        prompt_events.append(prompt_event)
        task_run_state = hook._accumulate_task_run_state(task_run_state, prompt_event)

    task_run = hook._build_task_run_payload(
        session_id=session_id,
        task_run_state=task_run_state,
        project_name=project_name,
        model_name=model_name,
        agent_version=agent_version,
    )
    if task_run is None:
        return None, "missing_task_run"

    return {
        "path": path,
        "session_id": session_id,
        "prompt_events": prompt_events,
        "task_run": task_run,
    }, None


def main(argv: list[str] | None = None) -> int:
    parser = backfill_common.build_parser(_default_root(), "Backfill Codex transcript usage")
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
    for path in sorted(root.glob("**/*.jsonl")):
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
