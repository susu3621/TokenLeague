# TokenLeague Hooks

TokenLeague provides statistics hooks and collector assets for Claude Code, Codex CLI, Cursor, Workbuddy (CodeBuddy CLI), Gemini CLI, Kiro, and OpenClaw to automatically track token usage and send it to the TokenLeague leaderboard.

## Quick Start

### Install Hooks

Run the installation script:

```bash
cd /path/to/TokenLeague
./scripts/install_hooks.sh --both --cursor --workbuddy --gemini --kiro --openclaw --global
```

Built-in templates live under `hooks/` inside this repository. The repository checkout itself does not auto-enable agent hooks; installation is explicit.

**Options:**
| Option | Description |
|--------|-------------|
| `--claude` | Install only Claude Code hooks |
| `--codex` | Install only Codex CLI hooks |
| `--cursor` | Install only Cursor hooks |
| `--workbuddy` | Install only Workbuddy / CodeBuddy CLI hooks |
| `--gemini` | Install only Gemini CLI hooks |
| `--kiro` | Stage only Kiro hook scripts for manual Agent Hooks setup |
| `--openclaw` | Install only OpenClaw collector assets |
| `--both` | Install Claude Code and Codex CLI hooks |
| `--global` | Install to `~/.claude`, `~/.codex`, `~/.cursor`, `~/.codebuddy`, `~/.gemini`, `~/.kiro`, and/or `~/.openclaw` depending on flags |
| `--local` | Install to project directory (default) |

**Examples:**
```bash
# Install all supported hooks globally
./scripts/install_hooks.sh --both --cursor --workbuddy --gemini --kiro --openclaw --global

# Install only Claude Code hooks globally
./scripts/install_hooks.sh --claude --global

# Install only Cursor hooks globally
./scripts/install_hooks.sh --cursor --global

# Install only Workbuddy hooks globally
./scripts/install_hooks.sh --workbuddy --global

# Install only Gemini CLI hooks globally
./scripts/install_hooks.sh --gemini --global

# Stage Kiro hook scripts globally
./scripts/install_hooks.sh --kiro --global

# Install only OpenClaw collector assets globally
./scripts/install_hooks.sh --openclaw --global

# Install to current project directory only
./scripts/install_hooks.sh --both --cursor --workbuddy --gemini --kiro --openclaw --local
```

### Uninstall Hooks

```bash
# Uninstall all supported hooks globally
./scripts/install_hooks.sh --both --cursor --workbuddy --gemini --kiro --openclaw --global --uninstall

# Uninstall only Claude Code hooks
./scripts/install_hooks.sh --claude --global --uninstall

# Uninstall only Codex CLI hooks
./scripts/install_hooks.sh --codex --global --uninstall

# Uninstall only Cursor hooks
./scripts/install_hooks.sh --cursor --global --uninstall

# Uninstall only Workbuddy hooks
./scripts/install_hooks.sh --workbuddy --global --uninstall

# Uninstall only Gemini CLI hooks
./scripts/install_hooks.sh --gemini --global --uninstall

# Remove staged Kiro hook scripts
./scripts/install_hooks.sh --kiro --global --uninstall

# Uninstall only OpenClaw collector assets
./scripts/install_hooks.sh --openclaw --global --uninstall
```

### Configure Environment Variables

For Claude / Codex / Cursor / Workbuddy / Gemini / Kiro, add these to your shell profile (`~/.bashrc` or `~/.zshrc`):

```bash
# Required: Your TokenLeague hook key
export TOKENLEAGUE_HOOK_KEY="your-hook-key-here"

# Optional: TokenLeague API URL (default: http://localhost:5006)
export TOKENLEAGUE_API_URL="http://localhost:5006"

# Optional: Override Gemini CLI version detection when needed
export TOKENLEAGUE_GEMINI_CLI_VERSION="0.34.0"

# Optional: Override OpenClaw version detection when needed
export TOKENLEAGUE_OPENCLAW_VERSION="0.1.0"
```

For OpenClaw service deployments, prefer putting these variables in `~/.openclaw/.env` and restarting the service. This is more reliable than relying on interactive shell startup files. The collector reads this file directly and accepts both plain `.env` lines and `export KEY=VALUE` lines.

When you run `./scripts/install_hooks.sh --openclaw --global`, the installer also installs and enables a system-level `systemd` timer named `tokenleague-openclaw-collector.timer`. It runs the collector every 1 minute, writes the unit files into `/etc/systemd/system/`, and renders the current `openclaw` binary path into the service environment so version detection still works under systemd. `sudo` privileges are typically required.

Get your hook key from the TokenLeague admin panel.

### 3. Start Using

**Claude Code:**
```bash
claude
```

**Codex CLI:**
```bash
codex
```

**Cursor:**
Cursor installs config into `.cursor/hooks.json` or `~/.cursor/hooks.json`, and the hook command lives at `.cursor/hooks/tokenleague.py` or `~/.cursor/hooks/tokenleague.py`.

**Workbuddy / CodeBuddy CLI:**
Workbuddy installs config into `.codebuddy/settings.json` or `~/.codebuddy/settings.json`.

**Gemini CLI:**
```bash
gemini
```

**Kiro:**
Kiro does not publish a stable on-disk hook config path in its docs. `./scripts/install_hooks.sh --kiro` only stages scripts under `.kiro/hooks/` or `~/.kiro/hooks/`.

Open the `Agent Hooks` UI in Kiro and register two `Shell Command` hooks:

```text
Prompt Submit -> python3 .kiro/hooks/tokenleague.py prompt-submit
Agent Stop    -> python3 .kiro/hooks/tokenleague.py agent-stop
```

If you staged globally, use `python3 ~/.kiro/hooks/tokenleague.py prompt-submit` and `python3 ~/.kiro/hooks/tokenleague.py agent-stop`.

**OpenClaw:**
```bash
sudo systemctl status tokenleague-openclaw-collector.timer
```

Optional manual run:
```bash
python3 ~/.openclaw/tokenleague_collect.py
```

## Historical Backfill

If a user's local history already exists but was not uploaded when the hook originally ran, replay it manually with the backfill scripts:

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

`--dry-run` scans and builds payloads without sending any HTTP requests. Real uploads still require `TOKENLEAGUE_HOOK_KEY`, and may optionally use `TOKENLEAGUE_API_URL`.
`--days N` filters transcript files by filesystem modification time so you can replay only the last few days of history instead of the full archive.

## How It Works

### Hook Events

| Event | Trigger | Action |
|-------|---------|--------|
| `SessionStart` | When Claude Code, Workbuddy, or Gemini CLI starts | Initialize session tracking or display startup status |
| `UserPromptSubmit` | When you send a prompt in Codex CLI | Cache Codex session/transcript metadata |
| `sessionStart` | When Cursor starts a session | Initialize Cursor hook state |
| `BeforeAgent` | When you send a prompt in Gemini CLI | Start tracking the pending Gemini turn |
| `AfterModel` | After a Gemini model response arrives | Cache Gemini usage metadata for the pending turn |
| `AfterAgent` | After Gemini finishes a turn | Upload prompt usage and update task aggregate |
| `Stop` | When Claude Code, Codex CLI, or Workbuddy stops | Parse transcript or finalized turn usage and upload |
| `stop` | When Cursor stops | Parse Cursor transcript usage and upload |
| `SessionEnd` | When Claude Code, Workbuddy, or Gemini CLI exits | Cleanup or final fallback handling |
| `sessionEnd` | When Cursor exits | Re-run transcript parsing as an exit fallback |
| `Prompt Submit` | When a configured Kiro shell command runs on prompt submit | Print TokenLeague configuration status into Kiro context |
| `Agent Stop` | When a configured Kiro shell command runs after agent completion | Upload transcript usage when a transcript path is available |
| `Collector Run` | When you execute the OpenClaw collector | Read Gateway session files and upload new prompt/session aggregates |

### Data Flow

```
┌─────────────────┐
│ Claude / Codex /│
│ Cursor / Work-  │
│ buddy / Gemini /│
│ Kiro / OpenClaw │
└────────┬────────┘
         │ Hook Events / Collector
         ▼
┌─────────────────┐
│ tokenleague.py  │
│   Hook Script   │
└────────┬────────┘
         │ HTTP POST
         ▼
┌─────────────────┐
│  TokenLeague    │
│      API        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Leaderboard   │
│    Display      │
└─────────────────┘
```

### Data Sent to TokenLeague

**Prompt Event** (`/api/ingest/prompt-event`):
- Event ID (unique identifier)
- Session ID (task identifier)
- Timestamps (started, finished)
- Token counts (input, output)
- Agent metadata (type, version, model)

**Task Run** (`/api/ingest/task-run`):
- Session ID
- Timestamps (started, finished)
- Prompt count
- Total token counts
- Agent metadata

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TOKENLEAGUE_HOOK_KEY` | Yes | - | Your authentication key |
| `TOKENLEAGUE_API_URL` | No | `http://localhost:5006` | TokenLeague API URL |
| `TOKENLEAGUE_GEMINI_CLI_VERSION` | No | auto-detect | Override Gemini CLI version if automatic detection is unavailable |
| `TOKENLEAGUE_OPENCLAW_VERSION` | No | auto-detect / `unknown` | Override OpenClaw version when automatic detection from `openclaw --version` or installed CLI metadata is unavailable |

### Settings File

Repository templates live under `hooks/claude`, `hooks/codex`, `hooks/cursor`, `hooks/workbuddy`, `hooks/gemini`, `hooks/kiro`, and `hooks/openclaw`.

Claude hooks are installed into `.claude/settings.json` or `~/.claude/settings.json`.

Codex hooks are installed into `.codex/hooks.json` or `~/.codex/hooks.json`, and the hook engine must be enabled in `~/.codex/config.toml`:

```json
{
  "hooks": {
    "UserPromptSubmit": [...],
    "Stop": [...]
  }
}
```

```toml
[features]
codex_hooks = true
```

Cursor hooks are installed into `.cursor/hooks.json` or `~/.cursor/hooks.json`:

```json
{
  "version": 1,
  "hooks": {
    "sessionStart": [...],
    "stop": [...],
    "sessionEnd": [...]
  }
}
```

The command script lives at `.cursor/hooks/tokenleague.py` or `~/.cursor/hooks/tokenleague.py`.

Workbuddy hooks are installed into `.codebuddy/settings.json` or `~/.codebuddy/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [...],
    "Stop": [...],
    "SessionEnd": [...]
  }
}
```

Gemini hooks are installed into `.gemini/settings.json` or `~/.gemini/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [...],
    "BeforeAgent": [...],
    "AfterModel": [...],
    "AfterAgent": [...],
    "SessionEnd": [...]
  }
}
```

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

Kiro stages scripts into `.kiro/hooks/` or `~/.kiro/hooks/`:

```text
.kiro/
└── hooks/
    ├── tokenleague.py
    ├── tokenleague.env.example
    └── tokenleague_transcript_hook.py
```

Kiro setup remains manual in the `Agent Hooks` UI. Recommended bindings:

```text
Prompt Submit -> python3 .kiro/hooks/tokenleague.py prompt-submit
Agent Stop    -> python3 .kiro/hooks/tokenleague.py agent-stop
```

## Privacy

The hooks only collect **statistical data**:
- Token counts (input/output)
- Timestamps
- Model and agent information

The hooks **do NOT collect**:
- Prompt content
- Response content
- File contents
- Personal information

## Troubleshooting

### Hooks Not Working

1. **Check environment variables:**
   ```bash
   echo $TOKENLEAGUE_HOOK_KEY
   echo $TOKENLEAGUE_API_URL
   ```

2. **Check TokenLeague is running:**
   ```bash
   curl http://localhost:5006/health
   ```

3. **Check hook key is valid:**
   - Go to TokenLeague admin panel
   - Verify your hook key is active

4. **Check hook logs:**
   - Hooks run asynchronously and silently
   - Errors don't block Claude Code/Codex/Gemini CLI/OpenClaw

### Session Data Not Appearing

1. Wait a few seconds after stopping
2. Check the leaderboard time window (day/week/all)
3. Verify your user account is active in TokenLeague

### Codex CLI Hooks Not Working

1. Check Codex CLI version (`0.116.0+` recommended)

2. Ensure `~/.codex/config.toml` contains:
   ```toml
   [features]
   codex_hooks = true
   ```

3. Ensure hooks are configured in `~/.codex/hooks.json` or the directory created by `install_hooks.sh --local`

### Gemini CLI Hooks Not Working

1. Ensure hooks are configured in `~/.gemini/settings.json` or the directory created by `install_hooks.sh --local`

2. Open Gemini CLI and check `/hooks panel` to verify TokenLeague hooks are enabled

3. Confirm your environment variables are available in the shell that launches `gemini`

4. If Gemini CLI version still shows as unknown, set:
   ```bash
   export TOKENLEAGUE_GEMINI_CLI_VERSION="0.34.0"
   ```

### OpenClaw Collector Not Working

1. Ensure `~/.openclaw/tokenleague_collect.py` exists or run `./scripts/install_hooks.sh --openclaw --global`

2. Prefer putting TokenLeague variables in `~/.openclaw/.env`

3. Restart the OpenClaw service after changing `.env`

4. Check the system timer:
   ```bash
   sudo systemctl status tokenleague-openclaw-collector.timer
   sudo systemctl list-timers tokenleague-openclaw-collector.timer
   ```

5. If OpenClaw still cannot see shell-provided variables, use `env.shellEnv.enabled` only as a fallback

6. Check collector diagnostics:
   - log: `/tmp/.tokenleague_openclaw_hook.log`
   - cursor: `/tmp/.tokenleague_openclaw_cursor.json`

## Manual Installation

### Claude Code

```bash
# Create directories
mkdir -p .claude/hooks

# Copy files
cp /path/to/TokenLeague/hooks/claude/tokenleague.py .claude/hooks/
cp /path/to/TokenLeague/hooks/claude/settings.json .claude/

# Make executable
chmod +x .claude/hooks/tokenleague.py
```

### Codex CLI

```bash
# Create directories
mkdir -p .codex/hooks

# Copy files
cp /path/to/TokenLeague/hooks/codex/tokenleague.py .codex/hooks/
cp /path/to/TokenLeague/hooks/codex/hooks.json .codex/

# Make executable
chmod +x .codex/hooks/tokenleague.py
```

Add or update `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

### Gemini CLI

```bash
# Create directories
mkdir -p .gemini/hooks

# Copy files
cp /path/to/TokenLeague/hooks/gemini/tokenleague.py .gemini/hooks/
cp /path/to/TokenLeague/hooks/gemini/settings.json .gemini/

# Make executable
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

## Uninstalling

Run the uninstall command:

```bash
./scripts/install_hooks.sh --both --gemini --openclaw --global --uninstall
```

The uninstaller will:
- Remove `tokenleague.py` and `tokenleague.env.example` files
- Remove TokenLeague hooks from `settings.json` / `hooks.json`
- Preserve other hooks and configurations

To completely remove TokenLeague, also remove the environment variables from your shell profile or `~/.openclaw/.env`.

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
