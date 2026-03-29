# Backfill Days Filter Design

## Goal

Add a shared `--days N` option to the manual Codex and Claude backfill scripts so users can replay only recently modified transcript files and avoid uploading an unnecessarily large history set.

## Scope

- Add one shared CLI flag for manual backfill scripts:
  - `scripts/backfill_codex.py`
  - `scripts/backfill_claude.py`
- Apply the filter by transcript file modification time (`mtime`).
- Keep existing upload payloads, upload ordering, and server ingestion APIs unchanged.
- Add tests and user-facing documentation for the new filter.

Out of scope:

- Filtering by timestamps inside transcript contents.
- Adding checkpoint or incremental sync state.
- Changing hook behavior or live upload behavior.
- Adding backfill support for agents beyond Codex and Claude Code.

## Existing Context

TokenLeague already provides manual historical replay through:

- `scripts/backfill_codex.py`
- `scripts/backfill_claude.py`

Those scripts share summary and argument parsing logic through:

- `scripts/backfill_common.py`

Current backfill behavior scans all matching `*.jsonl` files under the default root, builds prompt-event and task-run payloads, and either prints a dry-run summary or uploads those payloads through the existing ingestion endpoints.

Because the current implementation scans the full history tree by default, manual replay can include far more sessions than the user wants when they only need a recent subset.

## Design

### Command-line interface

Extend the shared parser in `scripts/backfill_common.py` with:

- `--days N`

Semantics:

- `N` is a positive integer.
- When provided, only transcript files whose filesystem modification time is within the last `N` days are eligible for processing.
- When omitted, behavior remains unchanged and all matching files under the selected root are considered.

This flag belongs in the shared parser so both Codex and Claude Code backfill scripts expose identical filtering behavior.

### Filter semantics

The filter is based on file modification time, not transcript payload timestamps.

Threshold calculation:

1. Determine the current wall-clock time when the script starts.
2. Compute `threshold = now - timedelta(days=N)`.
3. For each discovered `*.jsonl` file, read its `mtime`.
4. Only keep files whose `mtime >= threshold`.

This choice matches the intended operator workflow:

- the user thinks in terms of "logs touched in the last few days"
- filtering can happen before parsing
- fewer files are opened, parsed, and potentially uploaded

### Filtering point in the pipeline

Apply the `mtime` filter after path discovery and before transcript parsing.

Pipeline order:

1. Find candidate `*.jsonl` files under the selected root.
2. Apply existing path exclusions such as Claude `/subagents/`.
3. Apply the optional `--days` `mtime` filter.
4. Parse remaining files and build session payloads.
5. Apply existing `--limit` behavior to discovered sessions.
6. Dry-run or upload using the existing flow.

Filtering before parsing is important because the goal is not only to reduce uploads but also to reduce unnecessary work.

### Interaction with existing options

- `--root PATH`: still controls where files are discovered from.
- `--limit N`: still applies after session discovery, not before the `--days` filter.
- `--dry-run`: still parses eligible files and prints summary information without sending requests.
- `--verbose`: should include per-file information when a file is excluded by the `--days` filter.

This preserves the current mental model:

- root narrows the search tree
- days narrows recent files within that tree
- limit caps the resulting discovered sessions

### Summary and verbose output

Add optional summary output showing that a day filter was applied:

- `Days filter: last N day(s)`

This line appears only when `--days` is provided.

Filtered-out files should not be counted as skipped sessions because they were intentionally excluded before parsing. Existing skip accounting should remain focused on parsed files that produced no usable session payloads.

In `--verbose` mode, the script should print a clear line for files excluded by age, for example:

- `FILTERED /path/to/file.jsonl: older_than_days`

### Error handling

- Invalid `--days` values should be rejected by argument parsing with a clear error.
- Missing roots still exit cleanly with the existing summary behavior.
- Files that pass the day filter but fail to parse still count as failures as they do today.

No changes are needed to API authentication or upload ordering.

## Testing

Add focused coverage in `service/tests/test_backfill_scripts.py` for:

- Codex: `--days` includes only recently modified files and excludes older files before parsing.
- Claude Code: `--days` applies the same `mtime` logic while still excluding `/subagents/`.
- Summary output: dry-run includes the day-filter line when `--days` is provided.

Tests should set file modification times directly with `os.utime(...)` rather than relying on transcript content timestamps.

## Documentation

Update:

- `README.md`
- `docs/HOOKS.md`

Changes:

- include `--days N` in the shared backfill options list
- explain that the filter uses transcript file modification time
- show the option as a way to reduce the number of uploaded sessions

## Files

Modify:

- `scripts/backfill_common.py`
- `scripts/backfill_codex.py`
- `scripts/backfill_claude.py`
- `service/tests/test_backfill_scripts.py`
- `README.md`
- `docs/HOOKS.md`

Create:

- `docs/superpowers/specs/2026-03-29-backfill-days-filter-design.md`
