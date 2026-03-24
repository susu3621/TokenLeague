#!/bin/bash
#
# TokenLeague Hooks Installation Script
#
# This script installs or uninstalls TokenLeague statistics hooks for supported agents.
#
# Usage:
#   ./install_hooks.sh [--claude] [--codex] [--gemini] [--openclaw] [--both] [--global] [--uninstall]
#
# Options:
#   --claude    Install/uninstall hooks for Claude Code only
#   --codex     Install/uninstall hooks for Codex CLI only
#   --gemini    Install/uninstall hooks for Gemini CLI only
#   --openclaw  Install/uninstall collector assets for OpenClaw
#   --both      Install/uninstall hooks for both (default)
#   --global    Install/uninstall to user's global config directory (~/.claude, ~/.codex, ~/.gemini, ~/.openclaw)
#   --local     Install/uninstall to current project directory (default)
#   --uninstall Remove TokenLeague hooks
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
INSTALL_GEMINI=false
INSTALL_OPENCLAW=false
INSTALL_GLOBAL=false
MODE_UNINSTALL=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HOOKS_SOURCE_DIR="$PROJECT_ROOT/hooks"
OPENCLAW_SYSTEMD_SERVICE_NAME="tokenleague-openclaw-collector.service"
OPENCLAW_SYSTEMD_TIMER_NAME="tokenleague-openclaw-collector.timer"
OPENCLAW_SYSTEMD_UNIT_DIR="/etc/systemd/system"

run_privileged_command() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
    else
        sudo "$@"
    fi
}

resolve_openclaw_install_user() {
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
        printf '%s\n' "$SUDO_USER"
        return
    fi
    id -un
}

resolve_openclaw_install_home() {
    local install_user="$1"
    python3 - "$install_user" <<'PY'
import pwd
import sys

print(pwd.getpwnam(sys.argv[1]).pw_dir)
PY
}

render_openclaw_systemd_template() {
    local template_path="$1"
    local output_path="$2"
    local install_user="$3"
    local install_home="$4"
    local collector_path="$5"
    local python_bin="$6"
    local openclaw_bin_path="$7"
    local openclaw_bin_dir="$8"

    python3 - "$template_path" "$output_path" "$install_user" "$install_home" "$collector_path" "$python_bin" "$openclaw_bin_path" "$openclaw_bin_dir" <<'PY'
from pathlib import Path
import sys

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
install_user = sys.argv[3]
install_home = sys.argv[4]
collector_path = sys.argv[5]
python_bin = sys.argv[6]
openclaw_bin_path = sys.argv[7]
openclaw_bin_dir = sys.argv[8]

content = template_path.read_text(encoding="utf-8")
for placeholder, value in {
    "{{OPENCLAW_USER}}": install_user,
    "{{OPENCLAW_HOME}}": install_home,
    "{{COLLECTOR_PATH}}": collector_path,
    "{{PYTHON_BIN}}": python_bin,
    "{{OPENCLAW_BIN_PATH}}": openclaw_bin_path,
    "{{OPENCLAW_BIN_DIR}}": openclaw_bin_dir,
}.items():
    content = content.replace(placeholder, value)

output_path.write_text(content, encoding="utf-8")
PY
}

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
                        "timeoutSec": 30,
                    }
                ]
            }
        ],
    }
}
target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
}

merge_claude_settings() {
    local target_path="$1"
    local command_path="$2"

    python3 - "$target_path" "$command_path" <<'PY'
import json
import sys
from pathlib import Path

target_path = Path(sys.argv[1])
command_path = sys.argv[2]

# Define the hooks configuration
tokenleague_hooks = {
    "SessionStart": [
        {
            "matcher": "startup",
            "hooks": [
                {
                    "type": "command",
                    "command": command_path,
                    "timeout": 5000
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
                    "timeout": 5000
                }
            ]
        }
    ],
    "SessionEnd": [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": command_path,
                    "timeout": 5000
                }
            ]
        }
    ]
}

# Read existing settings or create new
if target_path.exists():
    try:
        settings = json.loads(target_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        settings = {}
else:
    settings = {}

# Merge hooks - preserve existing hooks and add/update tokenleague hooks
existing_hooks = settings.get("hooks", {})
for event_name, event_hooks in tokenleague_hooks.items():
    if event_name not in existing_hooks:
        existing_hooks[event_name] = event_hooks
    else:
        # Check if tokenleague hook already exists in this event
        existing_events = existing_hooks[event_name]
        tokenleague_exists = False
        for event_config in existing_events:
            hooks_list = event_config.get("hooks", [])
            for hook in hooks_list:
                if "tokenleague" in hook.get("command", ""):
                    # Update existing tokenleague hook
                    hook["command"] = command_path
                    hook["timeout"] = 5000
                    tokenleague_exists = True
                    break
            if tokenleague_exists:
                break
        if not tokenleague_exists:
            # Add tokenleague hooks to existing event
            existing_hooks[event_name] = existing_events + tokenleague_hooks[event_name]

settings["hooks"] = existing_hooks

# Write back
target_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"  → Merged hooks configuration into {target_path}")
PY
}

merge_gemini_settings() {
    local target_path="$1"
    local command_path="$2"

    python3 - "$target_path" "$command_path" <<'PY'
import json
import sys
from pathlib import Path

target_path = Path(sys.argv[1])
command_path = sys.argv[2]

tokenleague_hooks = {
    "SessionStart": [
        {
            "matcher": "startup",
            "hooks": [
                {
                    "name": "tokenleague-session-start",
                    "type": "command",
                    "command": command_path,
                    "timeout": 5000,
                }
            ],
        }
    ],
    "BeforeAgent": [
        {
            "matcher": "*",
            "hooks": [
                {
                    "name": "tokenleague-before-agent",
                    "type": "command",
                    "command": command_path,
                    "timeout": 5000,
                }
            ],
        }
    ],
    "AfterModel": [
        {
            "matcher": "*",
            "hooks": [
                {
                    "name": "tokenleague-after-model",
                    "type": "command",
                    "command": command_path,
                    "timeout": 5000,
                }
            ],
        }
    ],
    "AfterAgent": [
        {
            "matcher": "*",
            "hooks": [
                {
                    "name": "tokenleague-after-agent",
                    "type": "command",
                    "command": command_path,
                    "timeout": 5000,
                }
            ],
        }
    ],
    "SessionEnd": [
        {
            "matcher": "exit",
            "hooks": [
                {
                    "name": "tokenleague-session-end",
                    "type": "command",
                    "command": command_path,
                    "timeout": 5000,
                }
            ],
        }
    ],
}

if target_path.exists():
    try:
        settings = json.loads(target_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        settings = {}
else:
    settings = {}

existing_hooks = settings.get("hooks", {})
for event_name, event_hooks in tokenleague_hooks.items():
    if event_name not in existing_hooks:
        existing_hooks[event_name] = event_hooks
        continue

    existing_events = existing_hooks[event_name]
    tokenleague_exists = False
    for event_config in existing_events:
        hooks_list = event_config.get("hooks", [])
        for hook in hooks_list:
            if "tokenleague" in hook.get("command", ""):
                hook["command"] = command_path
                hook["timeout"] = 5000
                tokenleague_exists = True
                break
        if tokenleague_exists:
            break
    if not tokenleague_exists:
        existing_hooks[event_name] = existing_events + tokenleague_hooks[event_name]

settings["hooks"] = existing_hooks
target_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"  → Merged hooks configuration into {target_path}")
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

# Function to remove TokenLeague hooks from Claude settings.json
remove_claude_hooks() {
    local target_path="$1"

    python3 - "$target_path" <<'PY'
import json
import sys
from pathlib import Path

target_path = Path(sys.argv[1])

if not target_path.exists():
    print(f"  → Settings file not found: {target_path}")
    sys.exit(0)

try:
    settings = json.loads(target_path.read_text(encoding="utf-8"))
except (json.JSONDecodeError, IOError) as exc:
    print(f"  → Failed to read settings: {exc}")
    sys.exit(1)

hooks = settings.get("hooks", {})
if not hooks:
    print(f"  → No hooks configured in {target_path}")
    sys.exit(0)

removed_count = 0
for event_name in list(hooks.keys()):
    event_configs = hooks[event_name]
    new_configs = []
    for config in event_configs:
        hooks_list = config.get("hooks", [])
        new_hooks_list = [h for h in hooks_list if "tokenleague" not in h.get("command", "")]
        if new_hooks_list:
            new_config = dict(config)
            new_config["hooks"] = new_hooks_list
            new_configs.append(new_config)
        removed_count += len(hooks_list) - len(new_hooks_list)

    if new_configs:
        hooks[event_name] = new_configs
    else:
        del hooks[event_name]

if not hooks:
    del settings["hooks"]
else:
    settings["hooks"] = hooks

target_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"  → Removed {removed_count} TokenLeague hook(s) from {target_path}")
PY
}

# Function to remove TokenLeague hooks from Codex hooks.json
remove_codex_hooks() {
    local target_path="$1"

    if [[ ! -f "$target_path" ]]; then
        echo -e "${YELLOW}  → Hooks file not found: $target_path${NC}"
        return
    fi

    python3 - "$target_path" <<'PY'
import json
import sys
from pathlib import Path

target_path = Path(sys.argv[1])

if not target_path.exists():
    print(f"  → Hooks file not found: {target_path}")
    sys.exit(0)

try:
    config = json.loads(target_path.read_text(encoding="utf-8"))
except (json.JSONDecodeError, IOError) as exc:
    print(f"  → Failed to read hooks config: {exc}")
    sys.exit(1)

hooks = config.get("hooks", {})
if not hooks:
    print(f"  → No hooks configured in {target_path}")
    sys.exit(0)

removed_count = 0
for event_name in list(hooks.keys()):
    event_configs = hooks[event_name]
    new_configs = []
    for config_item in event_configs:
        hooks_list = config_item.get("hooks", [])
        new_hooks_list = [h for h in hooks_list if "tokenleague" not in h.get("command", "")]
        if new_hooks_list:
            new_config = dict(config_item)
            new_config["hooks"] = new_hooks_list
            new_configs.append(new_config)
        removed_count += len(hooks_list) - len(new_hooks_list)

    if new_configs:
        hooks[event_name] = new_configs
    else:
        del hooks[event_name]

if not hooks:
    del config["hooks"]
else:
    config["hooks"] = hooks

target_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"  → Removed {removed_count} TokenLeague hook(s) from {target_path}")
PY
}

remove_gemini_hooks() {
    local target_path="$1"

    python3 - "$target_path" <<'PY'
import json
import sys
from pathlib import Path

target_path = Path(sys.argv[1])

if not target_path.exists():
    print(f"  → Settings file not found: {target_path}")
    sys.exit(0)

try:
    settings = json.loads(target_path.read_text(encoding="utf-8"))
except (json.JSONDecodeError, IOError) as exc:
    print(f"  → Failed to read settings: {exc}")
    sys.exit(1)

hooks = settings.get("hooks", {})
if not hooks:
    print(f"  → No hooks configured in {target_path}")
    sys.exit(0)

removed_count = 0
for event_name in list(hooks.keys()):
    event_configs = hooks[event_name]
    new_configs = []
    for config in event_configs:
        hooks_list = config.get("hooks", [])
        new_hooks_list = [h for h in hooks_list if "tokenleague" not in h.get("command", "")]
        if new_hooks_list:
            new_config = dict(config)
            new_config["hooks"] = new_hooks_list
            new_configs.append(new_config)
        removed_count += len(hooks_list) - len(new_hooks_list)

    if new_configs:
        hooks[event_name] = new_configs
    else:
        del hooks[event_name]

if not hooks:
    del settings["hooks"]
else:
    settings["hooks"] = hooks

target_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"  → Removed {removed_count} TokenLeague hook(s) from {target_path}")
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
        --gemini)
            INSTALL_GEMINI=true
            shift
            ;;
        --openclaw)
            INSTALL_OPENCLAW=true
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
        --uninstall)
            MODE_UNINSTALL=true
            shift
            ;;
        --help|-h)
            echo "TokenLeague Hooks Installation Script"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --claude    Install/uninstall hooks for Claude Code only"
            echo "  --codex     Install/uninstall hooks for Codex CLI only"
            echo "  --gemini    Install/uninstall hooks for Gemini CLI only"
            echo "  --openclaw  Install/uninstall collector assets for OpenClaw"
            echo "  --both      Install/uninstall hooks for both (default)"
            echo "  --global    Install/uninstall to user's global config (~/.claude, ~/.codex, ~/.gemini, ~/.openclaw)"
            echo "  --local     Install/uninstall to current project directory (default)"
            echo "  --uninstall Remove TokenLeague hooks"
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
if [[ "$INSTALL_CLAUDE" == "false" && "$INSTALL_CODEX" == "false" && "$INSTALL_GEMINI" == "false" && "$INSTALL_OPENCLAW" == "false" ]]; then
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
    local command_path
    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        target_dir="$HOME/.claude"
        command_path="python3 $target_dir/hooks/tokenleague.py"
    else
        target_dir="$PROJECT_ROOT/.claude"
        command_path="python3 $target_dir/hooks/tokenleague.py"
    fi

    echo -e "${YELLOW}Installing Claude Code hooks to: $target_dir${NC}"

    # Create directories
    mkdir -p "$target_dir/hooks"

    # Copy hook script
    cp "$HOOKS_SOURCE_DIR/claude/tokenleague.py" "$target_dir/hooks/tokenleague.py"
    chmod +x "$target_dir/hooks/tokenleague.py"

    # Copy env example
    cp "$HOOKS_SOURCE_DIR/claude/tokenleague.env.example" "$target_dir/hooks/tokenleague.env.example"

    # Create or merge settings.json
    merge_claude_settings "$target_dir/settings.json" "$command_path"

    echo -e "${GREEN}✓ Claude Code hooks installed successfully${NC}"
}

# Function to install Gemini CLI hooks
install_gemini_hooks() {
    local target_dir
    local command_path
    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        target_dir="$HOME/.gemini"
        command_path="python3 $target_dir/hooks/tokenleague.py"
    else
        target_dir="$PROJECT_ROOT/.gemini"
        command_path="python3 .gemini/hooks/tokenleague.py"
    fi

    echo -e "${YELLOW}Installing Gemini CLI hooks to: $target_dir${NC}"

    mkdir -p "$target_dir/hooks"

    cp "$HOOKS_SOURCE_DIR/gemini/tokenleague.py" "$target_dir/hooks/tokenleague.py"
    chmod +x "$target_dir/hooks/tokenleague.py"

    cp "$HOOKS_SOURCE_DIR/gemini/tokenleague.env.example" "$target_dir/hooks/tokenleague.env.example"

    # Create or merge .gemini/settings.json
    local settings_path="$target_dir/settings.json"
    merge_gemini_settings "$settings_path" "$command_path"

    echo -e "${GREEN}✓ Gemini CLI hooks installed successfully${NC}"
}

# Function to install OpenClaw collector assets
install_openclaw_hooks() {
    local target_dir
    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        target_dir="$(resolve_openclaw_install_home "$(resolve_openclaw_install_user)")/.openclaw"
    else
        target_dir="$PROJECT_ROOT/.openclaw"
    fi

    echo -e "${YELLOW}Installing OpenClaw collector assets to: $target_dir${NC}"

    mkdir -p "$target_dir"

    cp "$PROJECT_ROOT/hooks/openclaw/tokenleague_collect.py" "$target_dir/tokenleague_collect.py"
    chmod +x "$target_dir/tokenleague_collect.py"

    cp "$PROJECT_ROOT/hooks/openclaw/tokenleague.env.example" "$target_dir/tokenleague.env.example"

    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        install_openclaw_systemd_timer
    fi

    echo -e "${GREEN}✓ OpenClaw collector assets installed successfully${NC}"
}

install_openclaw_systemd_timer() {
    local install_user
    install_user="$(resolve_openclaw_install_user)"
    local install_home
    install_home="$(resolve_openclaw_install_home "$install_user")"
    local collector_path="$install_home/.openclaw/tokenleague_collect.py"
    local python_bin
    python_bin="$(command -v python3 || true)"
    if [[ -z "$python_bin" ]]; then
        python_bin="/usr/bin/python3"
    fi
    local openclaw_bin_path
    openclaw_bin_path="$(command -v openclaw || true)"
    if [[ -z "$openclaw_bin_path" ]]; then
        openclaw_bin_path="$install_home/.npm-global/bin/openclaw"
    fi
    local openclaw_bin_dir
    openclaw_bin_dir="$(dirname "$openclaw_bin_path")"

    local service_template="$PROJECT_ROOT/hooks/openclaw/$OPENCLAW_SYSTEMD_SERVICE_NAME"
    local timer_template="$PROJECT_ROOT/hooks/openclaw/$OPENCLAW_SYSTEMD_TIMER_NAME"
    local rendered_service
    rendered_service="$(mktemp)"
    local rendered_timer
    rendered_timer="$(mktemp)"

    render_openclaw_systemd_template "$service_template" "$rendered_service" "$install_user" "$install_home" "$collector_path" "$python_bin" "$openclaw_bin_path" "$openclaw_bin_dir"
    render_openclaw_systemd_template "$timer_template" "$rendered_timer" "$install_user" "$install_home" "$collector_path" "$python_bin" "$openclaw_bin_path" "$openclaw_bin_dir"

    run_privileged_command install -m 0644 "$rendered_service" "$OPENCLAW_SYSTEMD_UNIT_DIR/$OPENCLAW_SYSTEMD_SERVICE_NAME"
    run_privileged_command install -m 0644 "$rendered_timer" "$OPENCLAW_SYSTEMD_UNIT_DIR/$OPENCLAW_SYSTEMD_TIMER_NAME"
    rm -f "$rendered_service" "$rendered_timer"

    run_privileged_command systemctl daemon-reload
    run_privileged_command systemctl enable --now tokenleague-openclaw-collector.timer
    run_privileged_command systemctl restart tokenleague-openclaw-collector.timer

    echo -e "${GREEN}  ✓ Installed systemd timer: $OPENCLAW_SYSTEMD_TIMER_NAME${NC}"
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
    cp "$HOOKS_SOURCE_DIR/codex/tokenleague.py" "$target_dir/hooks/tokenleague.py"
    chmod +x "$target_dir/hooks/tokenleague.py"

    # Copy env example
    cp "$HOOKS_SOURCE_DIR/codex/tokenleague.env.example" "$target_dir/hooks/tokenleague.env.example"

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

# Function to uninstall OpenClaw collector assets
uninstall_openclaw_hooks() {
    local target_dir
    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        target_dir="$(resolve_openclaw_install_home "$(resolve_openclaw_install_user)")/.openclaw"
    else
        target_dir="$PROJECT_ROOT/.openclaw"
    fi

    echo -e "${YELLOW}Uninstalling OpenClaw collector assets from: $target_dir${NC}"

    if [[ -f "$target_dir/tokenleague_collect.py" ]]; then
        rm -f "$target_dir/tokenleague_collect.py"
        echo -e "${GREEN}  ✓ Removed tokenleague_collect.py${NC}"
    else
        echo -e "${YELLOW}  → tokenleague_collect.py not found${NC}"
    fi

    if [[ -f "$target_dir/tokenleague.env.example" ]]; then
        rm -f "$target_dir/tokenleague.env.example"
        echo -e "${GREEN}  ✓ Removed tokenleague.env.example${NC}"
    fi

    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        uninstall_openclaw_systemd_timer
    fi

    echo -e "${GREEN}✓ OpenClaw collector assets uninstalled${NC}"
}

uninstall_openclaw_systemd_timer() {
    if run_privileged_command test -f "$OPENCLAW_SYSTEMD_UNIT_DIR/$OPENCLAW_SYSTEMD_TIMER_NAME"; then
        run_privileged_command systemctl disable --now tokenleague-openclaw-collector.timer || true
        run_privileged_command rm -f "$OPENCLAW_SYSTEMD_UNIT_DIR/$OPENCLAW_SYSTEMD_SERVICE_NAME"
        run_privileged_command rm -f "$OPENCLAW_SYSTEMD_UNIT_DIR/$OPENCLAW_SYSTEMD_TIMER_NAME"
        run_privileged_command systemctl daemon-reload
        echo -e "${GREEN}  ✓ Removed systemd timer: $OPENCLAW_SYSTEMD_TIMER_NAME${NC}"
    else
        echo -e "${YELLOW}  → systemd timer not found${NC}"
    fi
}

# Function to uninstall Gemini CLI hooks
uninstall_gemini_hooks() {
    local target_dir
    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        target_dir="$HOME/.gemini"
    else
        target_dir="$PROJECT_ROOT/.gemini"
    fi

    echo -e "${YELLOW}Uninstalling Gemini CLI hooks from: $target_dir${NC}"

    if [[ -f "$target_dir/hooks/tokenleague.py" ]]; then
        rm -f "$target_dir/hooks/tokenleague.py"
        echo -e "${GREEN}  ✓ Removed tokenleague.py${NC}"
    else
        echo -e "${YELLOW}  → tokenleague.py not found${NC}"
    fi

    if [[ -f "$target_dir/hooks/tokenleague.env.example" ]]; then
        rm -f "$target_dir/hooks/tokenleague.env.example"
        echo -e "${GREEN}  ✓ Removed tokenleague.env.example${NC}"
    fi

    remove_gemini_hooks "$target_dir/settings.json"

    echo -e "${GREEN}✓ Gemini CLI hooks uninstalled${NC}"
}

# Function to uninstall Claude Code hooks
uninstall_claude_hooks() {
    local target_dir
    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        target_dir="$HOME/.claude"
    else
        target_dir="$PROJECT_ROOT/.claude"
    fi

    echo -e "${YELLOW}Uninstalling Claude Code hooks from: $target_dir${NC}"

    # Remove hook script
    if [[ -f "$target_dir/hooks/tokenleague.py" ]]; then
        rm -f "$target_dir/hooks/tokenleague.py"
        echo -e "${GREEN}  ✓ Removed tokenleague.py${NC}"
    else
        echo -e "${YELLOW}  → tokenleague.py not found${NC}"
    fi

    # Remove env example
    if [[ -f "$target_dir/hooks/tokenleague.env.example" ]]; then
        rm -f "$target_dir/hooks/tokenleague.env.example"
        echo -e "${GREEN}  ✓ Removed tokenleague.env.example${NC}"
    fi

    # Remove hooks from settings.json
    remove_claude_hooks "$target_dir/settings.json"

    echo -e "${GREEN}✓ Claude Code hooks uninstalled${NC}"
}

# Function to uninstall Codex CLI hooks
uninstall_codex_hooks() {
    local target_dir
    if [[ "$INSTALL_GLOBAL" == "true" ]]; then
        target_dir="$HOME/.codex"
    else
        target_dir="$PROJECT_ROOT/.codex"
    fi

    echo -e "${YELLOW}Uninstalling Codex CLI hooks from: $target_dir${NC}"

    # Remove hook script
    if [[ -f "$target_dir/hooks/tokenleague.py" ]]; then
        rm -f "$target_dir/hooks/tokenleague.py"
        echo -e "${GREEN}  ✓ Removed tokenleague.py${NC}"
    else
        echo -e "${YELLOW}  → tokenleague.py not found${NC}"
    fi

    # Remove env example
    if [[ -f "$target_dir/hooks/tokenleague.env.example" ]]; then
        rm -f "$target_dir/hooks/tokenleague.env.example"
        echo -e "${GREEN}  ✓ Removed tokenleague.env.example${NC}"
    fi

    # Remove hooks from hooks.json
    remove_codex_hooks "$target_dir/hooks.json"

    echo -e "${GREEN}✓ Codex CLI hooks uninstalled${NC}"
}

# Main execution
if [[ "$MODE_UNINSTALL" == "true" ]]; then
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}       TokenLeague Hooks Uninstaller${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo ""

    if [[ "$INSTALL_CLAUDE" == "true" ]]; then
        uninstall_claude_hooks
        echo ""
    fi

    if [[ "$INSTALL_CODEX" == "true" ]]; then
        uninstall_codex_hooks
        echo ""
    fi

    if [[ "$INSTALL_GEMINI" == "true" ]]; then
        uninstall_gemini_hooks
        echo ""
    fi

    if [[ "$INSTALL_OPENCLAW" == "true" ]]; then
        uninstall_openclaw_hooks
        echo ""
    fi

    echo -e "${GREEN}Uninstallation complete!${NC}"
else
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}       TokenLeague Hooks Installer${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo ""

    # Perform installations
    if [[ "$INSTALL_CLAUDE" == "true" ]]; then
        install_claude_hooks
        echo ""
    fi

    if [[ "$INSTALL_CODEX" == "true" ]]; then
        install_codex_hooks
        echo ""
    fi

    if [[ "$INSTALL_GEMINI" == "true" ]]; then
        install_gemini_hooks
        echo ""
    fi

    if [[ "$INSTALL_OPENCLAW" == "true" ]]; then
        install_openclaw_hooks
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
    if [[ "$INSTALL_OPENCLAW" == "true" ]]; then
        if [[ "$INSTALL_GLOBAL" == "true" ]]; then
            echo -e "${YELLOW}For OpenClaw service installs, put these variables in ~/.openclaw/.env and restart the service.${NC}"
            echo -e "${YELLOW}The installer also enables a systemd timer that runs the collector every minute.${NC}"
            echo -e "${YELLOW}Use shell profile exports only as a fallback for terminal-started agents.${NC}"
        else
            echo -e "${YELLOW}For local OpenClaw installs, copy these variables into .openclaw/.env or export them before running the collector.${NC}"
        fi
    else
        echo -e "${YELLOW}Add these to your shell profile (~/.bashrc, ~/.zshrc) for persistence.${NC}"
    fi
    echo ""

    # Print verification instructions
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}       Verification${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    local_openclaw_collector_path="$PROJECT_ROOT/.openclaw/tokenleague_collect.py"
    global_openclaw_collector_path="$HOME/.openclaw/tokenleague_collect.py"
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
    if [[ "$INSTALL_GEMINI" == "true" ]]; then
        echo -e "To test Gemini CLI hooks:"
        echo "  1. Start TokenLeague: cd $PROJECT_ROOT && python -m service.app"
        echo "  2. Run: gemini"
        echo "  3. Send a prompt and check the leaderboard"
        echo ""
    fi
    if [[ "$INSTALL_OPENCLAW" == "true" ]]; then
        echo -e "To test OpenClaw collector support:"
        echo "  1. Start TokenLeague: cd $PROJECT_ROOT && python -m service.app"
        echo "  2. Add TokenLeague variables to ~/.openclaw/.env"
        echo "  3. Restart the OpenClaw service"
        if [[ "$INSTALL_GLOBAL" == "true" ]]; then
            echo "  4. Check timer status: sudo systemctl status $OPENCLAW_SYSTEMD_TIMER_NAME"
            echo "  5. Optional manual run: python3 $global_openclaw_collector_path"
        else
            echo "  4. Run: python3 $local_openclaw_collector_path"
        fi
        echo ""
    fi

    echo -e "${GREEN}Installation complete!${NC}"
fi
