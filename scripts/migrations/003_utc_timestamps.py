#!/usr/bin/env python3
"""
Migration: preserve the historical UTC migration marker for PostgreSQL.

The old MySQL migration converted existing rows from Shanghai local time
to UTC. PostgreSQL deployments are initialized after the Python code
already writes UTC timestamps, so there is no data rewrite to perform.
"""

from __future__ import annotations


def main():
    print("PostgreSQL timestamps are written in UTC by application code; no rewrite needed")


if __name__ == "__main__":
    main()
