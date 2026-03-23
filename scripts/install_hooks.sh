#!/bin/bash
#
# TokenLeague Hooks Installation Script
#
# This script installs TokenLeague statistics hooks for Claude Code and/or Codex CLI.
#
# Usage:
#   ./install_hooks.sh [--claude] [--codex] [--both] [--global]
#
# Options:
#   --claude    Install hooks for Claude Code only
#   --codex     Install hooks for Codex CLI only
#   --both      Install hooks for both (default)
#   --global    Install to user's global config directory (~/.claude, ~/.codex)
#   --local     Install to current project directory (default)
#
# Environment Variables:
#   TOKENLEAGUE_HOOK_KEY    Your TokenLeague hook key (required for testing)
#   TOKENLEAGUE_API_URL     TokenLeague API URL (default: http://localhost:5006)
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default settings
INSTALL_CLAUDE=false
INSTALL_CODEX=false
INSTALL_GLOBAL=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

write_codex_hooks_config() {
    local target_path="$1"
    local command_path="$2"

    python3 - "$target_path" "$command_path" <<'PY'
import json
import sys
from pathlib import Path

target_path = Path(sys.argv[1])
command_path = sys.argv[2]
payload = {
    "hooks": {
        "UserPromptSubmit": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command_path,
                        "timeoutSec": 10,
                        "statusMessage": "tracking TokenLeague usage",
                    }
                ]
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command_path,
                        "timeoutSec": 10,
                    }
                ]
            }
        ],
    }
}
target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

ensure_codex_feature_flag() {
    local config_dir="$HOME/.codex"
    local config_path="$config_dir/config.toml"

    mkdir -p "$config_dir"

    python3 - "$config_path" <<'PY'
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
lines = config_path.read_text(encoding="utf-8").splitlines() if config_path.exists() else []

features_start = None
features_end = len(lines)
for index, line in enumerate(lines):
    if line.strip() == "[features]":
        features_start = index
        features_end = len(lines)
        for scan in range(index + 1, len(lines)):
            stripped = lines[scan].strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                features_end = scan
                break
        break

if features_start is None:
    if lines and lines[-1].strip():
        lines.append("")
    lines.extend(["[features]", "codex_hooks = true"])
else:
    updated = False
    for index in range(features_start + 1, features_end):
        if lines[index].strip().startswith("codex_hooks"):
            lines[index] = "codex_hooks = true"
            updated = True
            break
    if not updated:
        lines.insert(features_end, "codex_hooks = true")

config_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --claude)
            INSTALL_CLAUDE=true
            shift
            ;;
        --codex)
            INSTALL_CODEX=true
            shift
            ;;
        --both)
            INSTALL_CLAUDE=true
            INSTALL_CODEX=true
            shift
            ;;
        --global)
            INSTALL_GLOBAL=true
            shift
            ;;
        --local)
            INSTALL_GLOBAL=false
            shift
            ;;
        --help|-h)
            echo "TokenLeague Hooks Installation Script"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --claude    Install hooks for Claude Code only"
            echo "  --codex     Install hooks for Codex CLI only"
            echo "  --both      Install hooks for both (default)"
            echo "  --global    Install to user's global config (~/.claude, ~/.codex)"
            echo "  --local     Install to current project directory (default)"
            echo "  --help, -h  Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Default to both if nothing specified
if [[ "$INSTALL_CLAUDE" == "false" && "$INSTALL_CODEX" == "false" ]]; then
    INSTALL_CLAUDE=true
    INSTALL_CODEX=true
fi

echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}       TokenLeague Hooks Installer${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""

# Function to install Claude Code hooks
install_claude_hooks() {
    local target_dir
    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        target_dir="$HOME/.claude"
    else
        target_dir="$PROJECT_ROOT/.claude"
    fi

    echo -e "${YELLOW}Installing Claude Code hooks to: $target_dir${NC}"

    # Create directories
    mkdir -p "$target_dir/hooks"

    # Copy hook script
    cp "$PROJECT_ROOT/.claude/hooks/tokenleague.py" "$target_dir/hooks/tokenleague.py"
    chmod +x "$target_dir/hooks/tokenleague.py"

    # Copy env example
    cp "$PROJECT_ROOT/.claude/hooks/tokenleague.env.example" "$target_dir/hooks/tokenleague.env.example"

    # Create or merge settings.json
    if [[ -f "$target_dir/settings.json" ]]; then
        echo -e "${YELLOW}  → Merging with existing settings.json${NC}"
        # Note: Manual merge may be required for complex configurations
        echo -e "${YELLOW}  → Please manually merge hooks configuration if needed${NC}"
    else
        cp "$PROJECT_ROOT/.claude/settings.json" "$target_dir/settings.json"
    fi

    echo -e "${GREEN}✓ Claude Code hooks installed successfully${NC}"
}

# Function to install Codex CLI hooks
install_codex_hooks() {
    local target_dir
    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        target_dir="$HOME/.codex"
    else
        target_dir="$PROJECT_ROOT/.codex"
    fi

    echo -e "${YELLOW}Installing Codex CLI hooks to: $target_dir${NC}"

    # Create directories
    mkdir -p "$target_dir/hooks"

    # Copy hook script
    cp "$PROJECT_ROOT/.codex/hooks/tokenleague.py" "$target_dir/hooks/tokenleague.py"
    chmod +x "$target_dir/hooks/tokenleague.py"

    # Copy env example
    cp "$PROJECT_ROOT/.codex/hooks/tokenleague.env.example" "$target_dir/hooks/tokenleague.env.example"

    local command_path
    local hooks_config_path="$target_dir/hooks.json"
    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        command_path="python3 $target_dir/hooks/tokenleague.py"
    else
        command_path="python3 .codex/hooks/tokenleague.py"
    fi

    write_codex_hooks_config "$hooks_config_path" "$command_path"
    ensure_codex_feature_flag

    echo -e "${GREEN}✓ Codex CLI hooks installed successfully${NC}"
}

# Perform installations
if [[ "$INSTALL_CLAUDE" == "true" ]]; then
    install_claude_hooks
    echo ""
fi

if [[ "$INSTALL_CODEX" == "true" ]]; then
    install_codex_hooks
    echo ""
fi

# Print configuration instructions
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}       Configuration Required${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Before using the hooks, set the following environment variables:${NC}"
echo ""
echo "  # Required: Your TokenLeague hook key"
echo "  export TOKENLEAGUE_HOOK_KEY=\"your-hook-key-here\""
echo ""
echo "  # Optional: TokenLeague API URL (default: http://localhost:5006)"
echo "  export TOKENLEAGUE_API_URL=\"http://localhost:5006\""
echo ""
echo -e "${YELLOW}Add these to your shell profile (~/.bashrc, ~/.zshrc) for persistence.${NC}"
echo ""

# Print verification instructions
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}       Verification${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
if [[ "$INSTALL_CLAUDE" == "true" ]]; then
    echo -e "To test Claude Code hooks:"
    echo "  1. Start TokenLeague: cd $PROJECT_ROOT && python -m service.app"
    echo "  2. Run: claude"
    echo "  3. Send a prompt and check the leaderboard"
    echo ""
fi
if [[ "$INSTALL_CODEX" == "true" ]]; then
    echo -e "To test Codex CLI hooks:"
    echo "  1. Start TokenLeague: cd $PROJECT_ROOT && python -m service.app"
    echo "  2. Run: codex"
    echo "  3. Send a prompt and check the leaderboard"
    echo ""
fi

echo -e "${GREEN}Installation complete!${NC}"
