#!/usr/bin/env python3
"""Backfill timing only. Stable turn identities make replays idempotent."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks" / "common"))
sys.path.insert(0, str(ROOT / "scripts"))
from tokenleague_timing import build_turn_timings
from backfill_common import modified_within_days, positive_int


def load_hook(source):
    spec = importlib.util.spec_from_file_location(f"timing_{source}_hook", ROOT / "hooks" / source / "tokenleague.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def session_timings(path, source, hook):
    entries = hook._load_transcript_entries(str(path))
    if source == "codex":
        meta = hook._extract_session_metadata(entries)
        session_id = meta.get("session_id") or path.stem
        cwd, version = meta.get("cwd"), meta.get("agent_version") or "unknown"
    else:
        meta = next((e for e in entries if e.get("sessionId") or e.get("cwd")), {})
        # Subagent transcripts can share their parent's sessionId; use file ID.
        session_id = path.stem if "subagents" in path.parts else meta.get("sessionId") or path.stem
        cwd, version = meta.get("cwd"), meta.get("version") or "unknown"
    return build_turn_timings(entries, source=source, session_id=session_id,
                              project_name=hook._detect_project_name(cwd), agent_version=version,
                              include_sidechain="subagents" in path.parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("codex", "claude", "all"), default="all")
    parser.add_argument("--codex-root", type=Path, default=Path.home() / ".codex" / "sessions")
    parser.add_argument("--claude-root", type=Path, default=Path(os.getenv("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects")
    parser.add_argument("--dry-run", action="store_true", help="parse locally without uploading")
    parser.add_argument("--days", type=positive_int, help="scan files modified within N days (does not truncate turns)")
    parser.add_argument("--limit", type=positive_int, help="maximum number of files per source")
    parser.add_argument("--project-name", help="process timing for one exact project name")
    args = parser.parse_args(argv)
    if not args.dry_run and not (os.getenv("TOKENLEAGUE_HOOK_KEY") or "").strip():
        parser.error("TOKENLEAGUE_HOOK_KEY is required for upload")
    summary = {"mode": "dry-run" if args.dry_run else "upload", "files": 0, "turns": 0, "uploaded": 0, "failures": 0}
    for source in ("codex", "claude") if args.source == "all" else (args.source,):
        hook = load_hook(source)
        root = getattr(args, f"{source}_root").expanduser()
        paths = (p for p in sorted(root.rglob("rollout-*.jsonl" if source == "codex" else "*.jsonl"))
                 if not args.days or modified_within_days(p, days=args.days))
        for index, path in enumerate(paths):
            if args.limit and index >= args.limit:
                break
            summary["files"] += 1
            try:
                rows = session_timings(path, source, hook)
                if args.project_name:
                    rows = [row for row in rows if row["project_name"] == args.project_name]
            except (OSError, ValueError, TypeError, OverflowError):
                summary["failures"] += 1
                continue
            summary["turns"] += len(rows)
            if not args.dry_run:
                for row in rows:
                    if not hook._send_api_request("/api/ingest/turn-timing", row):
                        summary["failures"] += 1
                        # Do not replay an uncertain write in this run.
                        print(json.dumps(summary))
                        return 1
                    summary["uploaded"] += 1
    print(json.dumps(summary))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
