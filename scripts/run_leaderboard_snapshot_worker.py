#!/usr/bin/env python3

from __future__ import annotations

import sys
import time

from refresh_leaderboard_snapshot import refresh_default_leaderboard_snapshot


def run_forever(
    refresh_func=refresh_default_leaderboard_snapshot,
    sleep_func=time.sleep,
    interval_seconds: int = 3600,
    retry_interval_seconds: int = 60,
) -> None:
    while True:
        try:
            snapshot = refresh_func()
            print(
                "Leaderboard snapshot refresh succeeded "
                f"key={snapshot['snapshot_key']} rows={len(snapshot['rows'])}"
            )
        except Exception as exc:  # pragma: no cover - operational logging
            print(f"Leaderboard snapshot refresh failed: {exc}", file=sys.stderr)
            sleep_func(retry_interval_seconds)
            continue
        sleep_func(interval_seconds)


def main() -> int:
    try:
        run_forever()
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        print("Leaderboard snapshot worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
