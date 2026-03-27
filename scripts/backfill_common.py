#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import os
from typing import Any, Callable


@dataclass
class Summary:
    root: Path
    scanned_files: int = 0
    discovered_sessions: int = 0
    processed_sessions: int = 0
    generated_prompt_events: int = 0
    generated_task_runs: int = 0
    skipped_items: int = 0
    failed_items: int = 0
    skip_reasons: Counter[str] = field(default_factory=Counter)
    sample_payload_ids: list[str] = field(default_factory=list)

    def add_skip(self, reason: str) -> None:
        self.skipped_items += 1
        self.skip_reasons[reason] += 1

    def add_failure(self) -> None:
        self.failed_items += 1

    def add_samples(self, prompt_events: list[dict[str, Any]], task_run: dict[str, Any] | None) -> None:
        for prompt_event in prompt_events:
            payload_id = str(prompt_event.get("external_event_id") or "").strip()
            if payload_id and payload_id not in self.sample_payload_ids:
                self.sample_payload_ids.append(payload_id)
            if len(self.sample_payload_ids) >= 3:
                return

        if task_run is not None and len(self.sample_payload_ids) < 3:
            payload_id = str(task_run.get("external_task_id") or "").strip()
            if payload_id and payload_id not in self.sample_payload_ids:
                self.sample_payload_ids.append(payload_id)


def build_parser(default_root: Path, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--dry-run", action="store_true", help="scan and parse without uploading")
    parser.add_argument("--limit", type=int, default=0, help="process at most N discovered sessions")
    parser.add_argument("--verbose", action="store_true", help="print per-file handling details")
    parser.add_argument(
        "--root",
        default=str(default_root),
        help=f"override the default scan root (default: {default_root})",
    )
    return parser


def ensure_upload_env() -> bool:
    return bool((os.getenv("TOKENLEAGUE_HOOK_KEY") or "").strip())


def upload_session(
    send_request: Callable[[str, dict[str, Any]], bool],
    prompt_events: list[dict[str, Any]],
    task_run: dict[str, Any],
) -> bool:
    for prompt_event in prompt_events:
        if not send_request("/api/ingest/prompt-event", prompt_event):
            return False
    return send_request("/api/ingest/task-run", task_run)


def print_summary(summary: Summary, *, dry_run: bool) -> None:
    print(f"Mode: {'dry-run' if dry_run else 'upload'}")
    print(f"Root: {summary.root}")
    print(f"Scanned files: {summary.scanned_files}")
    print(f"Discovered sessions: {summary.discovered_sessions}")
    print(f"Processed sessions: {summary.processed_sessions}")
    print(f"Generated prompt events: {summary.generated_prompt_events}")
    print(f"Generated task runs: {summary.generated_task_runs}")
    print(f"Skipped items: {summary.skipped_items}")
    print(f"Failures: {summary.failed_items}")
    if summary.skip_reasons:
        reasons = ", ".join(f"{key}={value}" for key, value in sorted(summary.skip_reasons.items()))
        print(f"Skip reasons: {reasons}")
    if summary.sample_payload_ids:
        print(f"Sample payload ids: {', '.join(summary.sample_payload_ids[:3])}")
