#!/usr/bin/env python3
"""Store timing independently of token accounting; safe to run repeatedly."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_migrations import get_connection


def main():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS turn_timings (
                    id BIGSERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    session_id VARCHAR(255) NOT NULL,
                    turn_id VARCHAR(255) NOT NULL,
                    project_name VARCHAR(255) NOT NULL,
                    agent_type VARCHAR(64) NOT NULL,
                    agent_version VARCHAR(128) NOT NULL,
                    model_name VARCHAR(128) NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    finished_at TIMESTAMPTZ NOT NULL,
                    duration_ms BIGINT NOT NULL CHECK (duration_ms >= 0),
                    time_to_first_token_ms BIGINT NULL CHECK (time_to_first_token_ms >= 0),
                    timing_source VARCHAR(16) NOT NULL CHECK (timing_source IN ('recorded', 'timestamps')),
                    tool_status VARCHAR(16) NOT NULL CHECK (tool_status IN ('measured', 'unavailable', 'incomplete')),
                    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (user_id, agent_type, session_id, turn_id),
                    CHECK (finished_at >= started_at)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_turn_timings_user_time ON turn_timings (user_id, finished_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_turn_timings_project_time ON turn_timings (project_name, finished_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_turn_timings_time ON turn_timings (finished_at)")
    print("Ensured turn timings table and indexes")


if __name__ == "__main__":
    main()
