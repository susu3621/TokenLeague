# Project and session time analysis

Open `/timing` for completed-turn duration distributions and bottleneck analysis. Admins see all members; other users see their own records. `/users/<id>/timing` provides a user-specific view. Filter by range, UTC dates, project, session, agent, or model, then drill into projects and sessions. All four tables support column sorting, page guidance, previous/next, and direct page jumps. URL state supports sharing and browser back/forward.

## Measurement rules

- Turn latency measures a completed turn, not the entire session span. Claude tool results are not new prompts. Missing measurements are excluded rather than replaced with zero.
- P50/P95 use nearest rank and only turns fully inside the range. Activity intervals are clipped at range boundaries.
- Agent time sums turn intervals; active wall time merges overlaps once. Their ratio is effective parallelism, not verified human time saved or hardware parallelism.
- Session gaps are the uncovered intervals between recorded turns. They are separate from agent time and do not establish human waiting time.
- Codex prefers recorded completion duration, with matched start/completion timestamps as a fallback. Native `item_completed` start/end timestamps record commands, MCP calls, file changes, waits, web activity, and compaction. Older logs can pair call/result IDs. TTFT requires an explicit field.
- Model gaps are estimates that can include request, network, and scheduling latency. Recorded tools take priority over these estimates and wrapper calls. Unattributable gaps remain unknown.
- Claude matches tool calls to results and estimates thinking/text/tool-call-writing time from transcript block timestamps. This estimate includes request latency and is not TTFT. Unfinished turns are excluded.
- Exclusive time slices prioritize model intervals and split overlapping tools equally. Raw tool-call latency is reported separately and may include approval waits.
- Coverage includes existing token-only sessions. Other agents retain their token analytics; detailed timing currently supports Codex and Claude.

The measurement approach references [agent-usage-analyzer](https://github.com/daguix/agent-usage-analyzer). The CLI is not a runtime dependency.

## Enable collection and backfill

Deploy the service and run migrations before upgrading each developer machine's hooks:

```bash
python3 scripts/run_migrations.py
bash scripts/install_hooks.sh --codex --claude --global
```

Migration `007_add_turn_timings.py` adds a separate timing table and indexes. The installer copies the shared timing module alongside each hook.

With `TOKENLEAGUE_API_URL` and the user's `TOKENLEAGUE_HOOK_KEY` in the environment:

```bash
python3 scripts/backfill_timing.py --source all --dry-run
python3 scripts/backfill_timing.py --source all
```

Options include `--source codex|claude|all`, `--days N` (file modification time), `--limit N` (files per source), `--codex-root PATH`, and `--claude-root PATH`. Claude also respects `CLAUDE_CONFIG_DIR`; subagent files use their own file IDs as session identities.

Timing backfill never replays token usage. Records upsert by user/agent/session/turn, so replay does not inflate counts. Re-run the updated script to enrich Codex records imported by the older parser, or use `--source codex --project-name NAME` for one project. Parser versions prevent old clients from overwriting richer data. Upload failure stops the current run without an automatic resend. Payloads contain identifiers, timestamps, tool names and fixed categories only: no prompts, responses, shell commands, arguments, file paths, or tool outputs.

## API

- `POST /api/ingest/turn-timing` uses `X-Hook-Key` and validates timestamps, durations, and interval bounds.
- `GET /api/timing` and `/api/users/<id>/timing` require login and enforce ownership.
- `view=projects|sessions|tools|turns` adds a paginated table. Use `sort`, `order=asc|desc`, `page`, and `page_size` (maximum 100).
- Use `window=today|week|month|quarter|all` or paired ISO `from` / `to` timestamps for a half-open interval. The UI converts an inclusive end date to the next UTC midnight.
- Filter with `project_name`, `session_id`, `agent_type`, `agent_version`, or `model_name`; admins may also scope by `user_id`.

Slow-turn rows retain full recorded latency while their in-window activity is clipped. Tool counts include calls started in the range; latency samples require calls fully inside it.
