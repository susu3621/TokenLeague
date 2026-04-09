# TokenLeague Hooks

TokenLeague collects token usage statistics from documented AI coding assistants and sends them to the dashboard. The goal is not just accounting. The dashboard is meant to help teams review usage patterns, spot prompt-efficiency changes, and improve how they work over time.

## Supported Sources

- Claude Code
- Codex CLI
- Workbuddy / CodeBuddy CLI
- Gemini CLI
- OpenClaw

## Quick Start

### Install Hooks

Built-in templates live under `hooks/` inside this repository. The repository checkout itself does not auto-enable hooks; installation is explicit.

Install every documented integration globally:

```bash
cd /path/to/TokenLeague
./scripts/install_hooks.sh --claude --codex --workbuddy --gemini --openclaw --global
```

Installer options:

| Option | Description |
| --- | --- |
| `--claude` | Install only Claude Code hooks |
| `--codex` | Install only Codex CLI hooks |
| `--workbuddy` | Install only Workbuddy / CodeBuddy CLI hooks |
| `--gemini` | Install only Gemini CLI hooks |
| `--openclaw` | Install only OpenClaw collector assets |
| `--global` | Install to the user profile |
| `--local` | Install to the current project directory |
| `--uninstall` | Remove TokenLeague hooks |

Installer note:

- `--all` currently enables Claude Code and Codex CLI only
- use explicit flags when you also want Workbuddy, Gemini CLI, or OpenClaw

Examples:

```bash
# Install all documented integrations globally
./scripts/install_hooks.sh --claude --codex --workbuddy --gemini --openclaw --global

# Install selected integrations globally
./scripts/install_hooks.sh --claude --global
./scripts/install_hooks.sh --codex --global
./scripts/install_hooks.sh --workbuddy --global
./scripts/install_hooks.sh --gemini --global
./scripts/install_hooks.sh --openclaw --global

# Install documented integrations into the current project
./scripts/install_hooks.sh --claude --codex --workbuddy --gemini --openclaw --local
```

### Uninstall Hooks

```bash
./scripts/install_hooks.sh --claude --codex --workbuddy --gemini --openclaw --global --uninstall
```

Or uninstall individual integrations:

```bash
./scripts/install_hooks.sh --claude --global --uninstall
./scripts/install_hooks.sh --codex --global --uninstall
./scripts/install_hooks.sh --workbuddy --global --uninstall
./scripts/install_hooks.sh --gemini --global --uninstall
./scripts/install_hooks.sh --openclaw --global --uninstall
```

### Configure Environment Variables

For Claude Code, Codex CLI, Workbuddy, and Gemini CLI, add these to your shell profile such as `~/.bashrc` or `~/.zshrc`:

```bash
export TOKENLEAGUE_HOOK_KEY="your-hook-key-here"
export TOKENLEAGUE_API_URL="http://localhost:5006"
export TOKENLEAGUE_GEMINI_CLI_VERSION="0.34.0"
export TOKENLEAGUE_OPENCLAW_VERSION="0.1.0"
```

For OpenClaw service deployments, prefer putting these variables in `~/.openclaw/.env` and restarting the service. The collector reads this file directly and accepts both plain `.env` lines and `export KEY=VALUE` lines.

When you run `./scripts/install_hooks.sh --openclaw --global`, the installer also installs and enables a system-level `systemd` timer named `tokenleague-openclaw-collector.timer`. It runs the collector every minute and usually requires `sudo`.

Get your hook key from the TokenLeague admin panel.

### Start Using

Claude Code:

```bash
claude
```

Codex CLI:

```bash
codex
```

Workbuddy / CodeBuddy CLI:

- installer writes configuration into `.workbuddy/settings.json` or `~/.workbuddy/settings.json`

Gemini CLI:

```bash
gemini
```

OpenClaw:

```bash
sudo systemctl status tokenleague-openclaw-collector.timer
```

Optional manual run:

```bash
python3 ~/.openclaw/tokenleague_collect.py
```

## Historical Backfill

If history already exists locally but was not uploaded when the hook originally ran, replay it manually with the backfill scripts:

```bash
python3 scripts/backfill_codex.py --dry-run
python3 scripts/backfill_claude.py --dry-run
```

Default scan roots:

- Codex: `~/.codex/sessions`
- Claude Code: `~/.claude/projects`

Shared options:

```bash
--dry-run
--days N
--limit N
--verbose
--root PATH
```

`--dry-run` scans and builds payloads without sending HTTP requests. Real uploads still require `TOKENLEAGUE_HOOK_KEY` and may optionally use `TOKENLEAGUE_API_URL`.

## How It Works

### Hook Events

| Event | Trigger | Action |
| --- | --- | --- |
| `SessionStart` | When Claude Code, Workbuddy, or Gemini CLI starts | Initialize session tracking or display startup status |
| `UserPromptSubmit` | When you send a prompt in Codex CLI | Cache Codex session or transcript metadata |
| `BeforeAgent` | When you send a prompt in Gemini CLI | Start tracking the pending Gemini turn |
| `AfterModel` | After a Gemini model response arrives | Cache Gemini usage metadata for the pending turn |
| `AfterAgent` | After Gemini finishes a turn | Upload prompt usage and update task aggregate |
| `Stop` | When Claude Code, Codex CLI, or Workbuddy stops | Parse transcript or finalized turn usage and upload |
| `SessionEnd` | When Claude Code, Workbuddy, or Gemini CLI exits | Cleanup or final fallback handling |
| `Collector Run` | When you execute the OpenClaw collector | Read Gateway session files and upload new prompt and task aggregates |

### Data Flow

```text
┌────────────────────────────┐
│ Claude / Codex / Workbuddy │
│ Gemini / OpenClaw          │
└─────────────┬──────────────┘
              │ Hooks / Collector
              ▼
┌────────────────────────────┐
│ tokenleague.py / collector │
└─────────────┬──────────────┘
              │ HTTP POST
              ▼
┌────────────────────────────┐
│      TokenLeague API       │
└─────────────┬──────────────┘
              │
              ▼
┌────────────────────────────┐
│ Leaderboard And User Views │
└────────────────────────────┘
```

### Data Sent to TokenLeague

Prompt event payloads contain:

- event ID
- session ID
- start and finish timestamps
- input and output token counts
- agent metadata such as type, version, and model

Task run payloads contain:

- session ID
- start and finish timestamps
- prompt count
- total token counts
- agent metadata

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `TOKENLEAGUE_HOOK_KEY` | Yes | none | Authentication key used by a single user |
| `TOKENLEAGUE_API_URL` | No | `http://localhost:5006` | TokenLeague API URL |
| `TOKENLEAGUE_GEMINI_CLI_VERSION` | No | auto-detect | Override Gemini CLI version when automatic detection is unavailable |
| `TOKENLEAGUE_OPENCLAW_VERSION` | No | auto-detect / `unknown` | Override OpenClaw version when automatic detection is unavailable |

### Installed Files

Repository templates live under `hooks/claude`, `hooks/codex`, `hooks/workbuddy`, `hooks/gemini`, and `hooks/openclaw`.

Claude Code installs into `.claude/settings.json` or `~/.claude/settings.json`.

Codex CLI installs into `.codex/hooks.json` or `~/.codex/hooks.json`, and the hook engine must be enabled in `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

Workbuddy installs into `.workbuddy/settings.json` or `~/.workbuddy/settings.json`.

Gemini installs into `.gemini/settings.json` or `~/.gemini/settings.json`.

OpenClaw installs a collector script and env example into `.openclaw/` or `~/.openclaw/`:

```text
.openclaw/
├── tokenleague_collect.py
└── tokenleague.env.example
```

Global OpenClaw installs also create:

```text
/etc/systemd/system/
├── tokenleague-openclaw-collector.service
└── tokenleague-openclaw-collector.timer
```

## Privacy

The hooks collect statistical metadata only:

- token counts
- timestamps
- model and agent information

They do not collect:

- prompt content
- response content
- file contents
- personal information

## Troubleshooting

### Hooks Not Working

1. Check environment variables:

   ```bash
   echo $TOKENLEAGUE_HOOK_KEY
   echo $TOKENLEAGUE_API_URL
   ```

2. Check TokenLeague is running:

   ```bash
   curl http://localhost:5006/health
   ```

3. Verify the hook key is active in the TokenLeague admin panel.

4. Check hook logs. Hooks run asynchronously and should not block your CLI workflow.

### Session Data Not Appearing

1. Wait a few seconds after stopping the agent.
2. Check the leaderboard time window.
3. Verify your user account is active in TokenLeague.

### Codex CLI Hooks Not Working

1. Check Codex CLI version. `0.116.0+` is recommended.
2. Ensure `~/.codex/config.toml` contains:

   ```toml
   [features]
   codex_hooks = true
   ```

3. Ensure hooks are configured in `~/.codex/hooks.json` or the directory created by `install_hooks.sh --local`.

### Gemini CLI Hooks Not Working

1. Ensure hooks are configured in `~/.gemini/settings.json` or the directory created by `install_hooks.sh --local`.
2. Open Gemini CLI and check `/hooks panel` to verify TokenLeague hooks are enabled.
3. Confirm your environment variables are available in the shell that launches `gemini`.
4. If Gemini CLI version still shows as unknown, set:

   ```bash
   export TOKENLEAGUE_GEMINI_CLI_VERSION="0.34.0"
   ```

### OpenClaw Collector Not Working

1. Ensure `~/.openclaw/tokenleague_collect.py` exists or run `./scripts/install_hooks.sh --openclaw --global`.
2. Prefer putting TokenLeague variables in `~/.openclaw/.env`.
3. Restart the OpenClaw service after changing `.env`.
4. Check the system timer:

   ```bash
   sudo systemctl status tokenleague-openclaw-collector.timer
   sudo systemctl list-timers tokenleague-openclaw-collector.timer
   ```

5. Check collector diagnostics:

   - log: `/tmp/.tokenleague_openclaw_hook.log`
   - state file under `/tmp/`

## Manual Installation

### Claude Code

```bash
mkdir -p .claude/hooks
cp /path/to/TokenLeague/hooks/claude/tokenleague.py .claude/hooks/
cp /path/to/TokenLeague/hooks/claude/settings.json .claude/
chmod +x .claude/hooks/tokenleague.py
```

### Codex CLI

```bash
mkdir -p .codex/hooks
cp /path/to/TokenLeague/hooks/codex/tokenleague.py .codex/hooks/
cp /path/to/TokenLeague/hooks/codex/hooks.json .codex/
chmod +x .codex/hooks/tokenleague.py
```

Then add or update `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

### Workbuddy

```bash
mkdir -p .workbuddy/hooks
cp /path/to/TokenLeague/hooks/workbuddy/tokenleague.py .workbuddy/hooks/
cp /path/to/TokenLeague/hooks/workbuddy/settings.json .workbuddy/
chmod +x .workbuddy/hooks/tokenleague.py
```

### Gemini CLI

```bash
mkdir -p .gemini/hooks
cp /path/to/TokenLeague/hooks/gemini/tokenleague.py .gemini/hooks/
cp /path/to/TokenLeague/hooks/gemini/settings.json .gemini/
chmod +x .gemini/hooks/tokenleague.py
```

### OpenClaw

```bash
mkdir -p ~/.openclaw
cp /path/to/TokenLeague/hooks/openclaw/tokenleague_collect.py ~/.openclaw/
cp /path/to/TokenLeague/hooks/openclaw/tokenleague.env.example ~/.openclaw/
chmod +x ~/.openclaw/tokenleague_collect.py
```

OpenClaw uploads are recorded with `project_name=OpenClaw`. The collector treats Gateway sessions as workspace-agnostic and does not derive a repository name from the current `cwd`.

For 1-minute automatic uploads with systemd, use the installer so the templates are rendered with the correct user, home directory, and collector path:

```bash
./scripts/install_hooks.sh --openclaw --global
```

## API Reference

### POST /api/ingest/prompt-event

Headers:

- `X-Hook-Key`: Your authentication key
- `Content-Type`: application/json

Body:

```json
{
  "external_event_id": "uuid",
  "task_id": "session-id",
  "prompt_started_at": "2026-03-23T10:00:00+00:00",
  "prompt_finished_at": "2026-03-23T10:00:05+00:00",
  "input_token_count": 100,
  "output_token_count": 200,
  "agent_type": "codex",
  "agent_version": "2.1.80",
  "model_name": "claude-sonnet-4-6"
}
```

### POST /api/ingest/task-run

Headers:

- `X-Hook-Key`: Your authentication key
- `Content-Type`: application/json

Body:

```json
{
  "external_task_id": "session-id",
  "started_at": "2026-03-23T10:00:00+00:00",
  "finished_at": "2026-03-23T10:05:00+00:00",
  "prompt_count": 5,
  "input_token_count": 500,
  "output_token_count": 1000,
  "agent_type": "codex",
  "agent_version": "2.1.80",
  "model_name": "claude-sonnet-4-6"
}
```
