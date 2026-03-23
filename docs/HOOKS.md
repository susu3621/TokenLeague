# TokenLeague Hooks

TokenLeague provides statistics hooks for Claude Code and Codex CLI to automatically track token usage and send it to the TokenLeague leaderboard.

## Quick Start

### Install Hooks

Run the installation script:

```bash
cd /path/to/TokenLeague
./scripts/install_hooks.sh --both --global
```

**Options:**
| Option | Description |
|--------|-------------|
| `--claude` | Install only Claude Code hooks |
| `--codex` | Install only Codex CLI hooks |
| `--both` | Install both (default) |
| `--global` | Install to `~/.claude` and `~/.codex` |
| `--local` | Install to project directory (default) |

**Examples:**
```bash
# Install globally for all projects (recommended)
./scripts/install_hooks.sh --both --global

# Install only Claude Code hooks globally
./scripts/install_hooks.sh --claude --global

# Install to current project directory only
./scripts/install_hooks.sh --both --local
```

### Uninstall Hooks

```bash
# Uninstall global hooks
./scripts/install_hooks.sh --both --global --uninstall

# Uninstall only Claude Code hooks
./scripts/install_hooks.sh --claude --global --uninstall

# Uninstall only Codex CLI hooks
./scripts/install_hooks.sh --codex --global --uninstall
```

### Configure Environment Variables

Add to your shell profile (`~/.bashrc` or `~/.zshrc`):

```bash
# Required: Your TokenLeague hook key
export TOKENLEAGUE_HOOK_KEY="your-hook-key-here"

# Optional: TokenLeague API URL (default: http://localhost:5006)
export TOKENLEAGUE_API_URL="http://localhost:5006"
```

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

## How It Works

### Hook Events

| Event | Trigger | Action |
|-------|---------|--------|
| `SessionStart` | When Claude Code/Codex starts | Initialize session tracking |
| `UserPromptSubmit` | When you send a prompt | Cache Codex session/transcript metadata |
| `Stop` | When Claude Code/Codex stops | Parse Codex transcript and upload token usage |

### Data Flow

```
┌─────────────────┐
│  Claude Code /  │
│   Codex CLI     │
└────────┬────────┘
         │ Hook Events
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

### Settings File

Claude hooks are configured in `.claude/settings.json`.

Codex hooks are configured in `.codex/hooks.json`, and the hook engine must be enabled in `~/.codex/config.toml`:

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
   - Errors don't block Claude Code/Codex

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

3. Ensure hooks are configured in `~/.codex/hooks.json` or `<repo>/.codex/hooks.json`

## Manual Installation

### Claude Code

```bash
# Create directories
mkdir -p .claude/hooks

# Copy files
cp /path/to/TokenLeague/.claude/hooks/tokenleague.py .claude/hooks/
cp /path/to/TokenLeague/.claude/settings.json .

# Make executable
chmod +x .claude/hooks/tokenleague.py
```

### Codex CLI

```bash
# Create directories
mkdir -p .codex/hooks

# Copy files
cp /path/to/TokenLeague/.codex/hooks/tokenleague.py .codex/hooks/
cp /path/to/TokenLeague/.codex/hooks.json .

# Make executable
chmod +x .codex/hooks/tokenleague.py
```

Add or update `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

## Uninstalling

Run the uninstall command:

```bash
./scripts/install_hooks.sh --both --global --uninstall
```

The uninstaller will:
- Remove `tokenleague.py` and `tokenleague.env.example` files
- Remove TokenLeague hooks from `settings.json` / `hooks.json`
- Preserve other hooks and configurations

To completely remove TokenLeague, also remove the environment variables from your shell profile (`~/.bashrc` or `~/.zshrc`).

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
