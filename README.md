# TokenLeague

Token League 是一个 AI 助手 Token 使用量排行榜应用，用于追踪 Claude Code、Codex CLI、Gemini CLI 和 OpenClaw 的使用统计。

TokenLeague is a token usage leaderboard application for tracking AI assistant usage.

## 功能特性

- Token 使用量排行榜
- 多用户支持
- 支持 Claude Code、Codex CLI、Gemini CLI 和 OpenClaw 统计
- Web 管理界面

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 到 `.env` 并配置：

```bash
cp .env.example .env
```

### 3. 初始化数据库

```bash
python3 scripts/init_db.py --admin-password <your-password>
```

### 4. 启动服务

```bash
python -m service.app
```

访问 `http://localhost:5006/login`

默认测试账号：
- username: `admin`
- password: `admin123`

## Hooks 安装

TokenLeague 提供统计 hooks / collector，自动追踪 Claude Code、Codex CLI、Gemini CLI 和 OpenClaw 的 token 使用量。

仓库内置模板现在统一放在 `hooks/` 目录下，checkout 本仓库本身不会默认启用任何 agent hook。只有在你显式执行安装脚本时，才会把模板复制到 `~/.claude`、`~/.codex`、`~/.gemini`、`~/.openclaw` 或项目级本地目录。

### 安装 Hooks

```bash
# 全局安装全部已支持 hooks
./scripts/install_hooks.sh --both --gemini --global

# 仅安装 Claude Code hooks
./scripts/install_hooks.sh --claude --global

# 仅安装 Codex CLI hooks
./scripts/install_hooks.sh --codex --global

# 仅安装 Gemini CLI hooks
./scripts/install_hooks.sh --gemini --global

# 仅安装 OpenClaw collector
./scripts/install_hooks.sh --openclaw --global

# 项目级安装（仅当前项目）
./scripts/install_hooks.sh --both --gemini --openclaw --local
```

### 配置环境变量

安装后，Claude / Codex / Gemini 推荐在 `~/.bashrc` 或 `~/.zshrc` 中添加：

```bash
# 必需：你的 TokenLeague hook key（从管理面板获取）
export TOKENLEAGUE_HOOK_KEY="your-hook-key-here"

# 可选：API URL（默认 http://localhost:5006）
export TOKENLEAGUE_API_URL="http://localhost:5006"

# 可选：手动指定 Gemini CLI 版本
export TOKENLEAGUE_GEMINI_CLI_VERSION="0.34.0"

# 可选：手动指定 OpenClaw 版本
export TOKENLEAGUE_OPENCLAW_VERSION="0.1.0"
```

如果你使用 OpenClaw service 启动，优先把这些变量写入 `~/.openclaw/.env`，不要只放在 shell profile 里。service 进程通常不会继承交互式 shell 环境。OpenClaw collector 会直接读取这个文件，兼容 `.env` 和 `export KEY=VALUE` 两种写法。未显式设置 `TOKENLEAGUE_OPENCLAW_VERSION` 时，collector 会优先执行 `openclaw --version` 读取版本，取不到时再回退到已安装 CLI 的元数据探测；OpenClaw 上报的 `project_name` 固定为 `OpenClaw`，不再从当前 workspace 推导仓库名。

### 卸载 Hooks

```bash
# 卸载全部已支持 hooks
./scripts/install_hooks.sh --both --gemini --global --uninstall

# 仅卸载 Claude Code hooks
./scripts/install_hooks.sh --claude --global --uninstall

# 仅卸载 Codex CLI hooks
./scripts/install_hooks.sh --codex --global --uninstall

# 仅卸载 Gemini CLI hooks
./scripts/install_hooks.sh --gemini --global --uninstall

# 仅卸载 OpenClaw collector
./scripts/install_hooks.sh --openclaw --global --uninstall
```

更多详情请参考 [docs/HOOKS.md](docs/HOOKS.md)。

---

## 模板说明 (Template Foundation)

## What this template keeps

- Flask + Jinja application wiring
- Session authentication and role checks
- Basic settings storage
- Docs page and API list page
- Numbered migration workflow
- Docker and local startup assets
- Minimal pytest baseline

对应中文理解：

- Web 服务基础骨架
- 登录鉴权与管理员权限
- 系统设置键值存储
- 文档页与 API 清单页
- 迁移脚本执行机制
- 最小可运行与最小可测试能力

## What is intentionally excluded

- Knowledge graph, news, travel, books, contacts, infra, and other domain modules
- Private deployment hosts and local filesystem paths
- Project-specific third-party integrations
- Current-project database schemas outside the generic base tables

也就是下面这些内容不会直接进入模板：

- 当前个人信息流系统的业务页面和业务表
- 私有网络环境、私有服务地址、私有目录路径
- 与具体项目强绑定的 AI / 邮件 / 推送 / CI 集成

## Directory overview

```text
template/
├── README.md
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── docs/
├── service/
└── scripts/
```

## How to start

1. Copy `template/` into a new repository or duplicate it as the starting directory of a new project.
2. Copy `.env.example` to `.env` or export the same variables in your shell.
3. Run `python3 scripts/init_db.py --admin-password <your-password>`.
4. Start the service with `cd service && ./run.sh`.
5. Visit `http://localhost:5006/login`.

Default in-memory test credentials:

- username: `admin`
- password: `admin123`

中文使用流程：

1. 复制 `template/` 到新仓库，或直接作为新项目初始目录。
2. 按 `.env.example` 配置数据库和 Flask 密钥。
3. 先初始化数据库，再启动服务。
4. 确认 `/login`、`/docs`、`/api`、`/settings` 正常后，再开始加业务模块。

## Extension rules

- Add new business tables through `scripts/migrations/`.
- Keep base auth and settings helpers in `service/auth.py` and `service/db.py`.
- Split new domain modules into separate files or packages instead of growing `service/app.py` into a monolith.
- Add at least one focused pytest file for every new capability.

## Suggested next steps for a new project

- Rename page titles and copy in `service/templates/`.
- Replace the placeholder docs in `docs/README.md`.
- Add your first domain migration and route module.
- Extend `docker-compose.yml` with project-specific dependencies only when needed.
