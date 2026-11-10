#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
from typing import Any, Callable
import urllib.error
import urllib.request


@dataclass
class Summary:
    root: Path
    days: int | None = None
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


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("days must be a positive integer")
    return parsed


def build_parser(default_root: Path, description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--dry-run", action="store_true", help="scan and parse without uploading")
    parser.add_argument("--limit", type=int, default=0, help="process at most N discovered sessions")
    parser.add_argument(
        "--days",
        type=positive_int,
        help="process only transcript files modified within the last N days",
    )
    parser.add_argument("--verbose", action="store_true", help="print per-file handling details")
    parser.add_argument(
        "--root",
        default=str(default_root),
        help=f"override the default scan root (default: {default_root})",
    )
    return parser


def ensure_upload_env() -> bool:
    return bool((os.getenv("TOKENLEAGUE_HOOK_KEY") or "").strip())


def _probe_url(url: str, timeout_seconds: float = 5.0) -> int:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return int(response.status)


def _format_probe_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    return str(exc)


def ensure_upload_ready(api_url: str, retry_url: str | None = None) -> tuple[bool, str | None]:
    candidate_urls: list[str] = []
    for url in (api_url, retry_url):
        normalized = str(url or "").rstrip("/")
        if normalized and normalized not in candidate_urls:
            candidate_urls.append(normalized)

    if not candidate_urls:
        return False, "Cannot reach TokenLeague API: missing API URL."

    last_error = "unknown error"
    for candidate_url in candidate_urls:
        health_url = f"{candidate_url}/health"
        try:
            status = _probe_url(health_url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = _format_probe_error(exc)
            continue
        if 200 <= status < 300:
            return True, None
        last_error = f"HTTP {status}"

    primary_url = candidate_urls[0]
    return (
        False,
        "Cannot reach TokenLeague API at "
        f"{primary_url}: {last_error}. Check TOKENLEAGUE_API_URL or start the service, then retry.",
    )


def modified_within_days(path: Path, *, days: int, now: datetime | None = None) -> bool:
    current_time = now or datetime.now(timezone.utc)
    threshold = current_time - timedelta(days=days)
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return modified_at >= threshold


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
    if summary.days is not None:
        print(f"Days filter: last {summary.days} day(s)")
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
