# TokenLeague
> 团队级 AI Token 观测与 Agent 使用分析平台

<div align="center">
  <h3>把 AI 编码助手的使用轨迹沉淀成可复盘、可比较、可持续优化的数据面板</h3>
  <p>TokenLeague 通过 hooks 和 collectors 持续采集多种 AI Agent 的 Token、Prompt 与任务统计，帮助团队看清谁在用、用在哪里、趋势如何变化，以及效率是否在改善。</p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
    <img src="https://img.shields.io/badge/Web-Flask-000000?style=flat-square&logo=flask&logoColor=white" alt="Flask">
    <img src="https://img.shields.io/badge/Database-MySQL%20%2F%20MariaDB-4479A1?style=flat-square&logo=mysql&logoColor=white" alt="MySQL or MariaDB">
    <img src="https://img.shields.io/badge/Ingestion-Hooks%20%26%20Collectors-0A7B83?style=flat-square" alt="Hooks and collectors">
    <img src="https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square" alt="MIT license">
  </p>

  <p>
    <a href="#overview">项目概览</a> •
    <a href="#why-tokenleague">项目价值</a> •
    <a href="#capabilities">能力概览</a> •
    <a href="#architecture">架构说明</a> •
    <a href="#docker-compose-recommended">Docker Compose</a> •
    <a href="#hook-installation">Hook 安装</a>
  </p>

  <p>
    <a href="./README_EN.md">English</a> |
    <strong>简体中文</strong>
  </p>
</div>

<p align="center">
  <img src="docs/assets/usage-timeline-masked.png" alt="TokenLeague 仪表盘截图，展示使用时间线与平均每次 Prompt Token 趋势" width="960" />
</p>

<a id="overview"></a>
## 项目概览

TokenLeague 为工程团队提供一个统一的 AI 编码助手使用观测面板。它不再依赖零散截图或主观印象，而是把成员、项目、模型维度的 Token 使用情况、Prompt 次数、平均每次 Prompt Token 和时间线趋势沉淀为可持续查看的数据视图。

整个系统围绕轻量级本地 hooks 和 collectors 设计。各类 Agent 在本地采集用量元数据并上传到 Flask 服务端，再由 MySQL 或 MariaDB 持久化，最终统一呈现在 Web UI 和 API 中。

<a id="why-tokenleague"></a>
## 项目价值

- 让团队按成员、项目、模型和时间窗口统一查看 AI 使用情况
- 用趋势图、平均值和时间线把 Prompt 效率问题可视化
- 为复盘、流程优化和工具采纳评估提供可追溯的数据依据
- 通过安装脚本、hook key 鉴权和历史补录，把接入成本控制在可操作范围内

<a id="capabilities"></a>
## 能力概览

- 仪表盘视图：预计算排行榜、用户详情页、账户设置、管理后台、站内文档
- 效率指标：Token 时间线、Prompt 次数、平均每次 Prompt Token、项目分布、模型分布
- 团队运维：hook key 轮换、本地密码修改、LDAP 配置、已观测 Agent 目录、双语界面
- 集成能力：内置 Claude Code、Codex CLI、Workbuddy / CodeBuddy CLI、Gemini CLI、OpenClaw 的模板与安装流程
- 恢复能力：支持对 Claude Code 和 Codex 的历史记录进行补录

<a id="architecture"></a>
## 架构说明

```text
AI 编码助手 / Collector
        |
        v
hooks/* 或采集脚本
        |
        v
POST /api/ingest/*
        |
        v
Flask 应用 + MySQL/MariaDB
        |
        +--> /leaderboard
        +--> /users/<id>
        +--> /admin/*
        \--> 快照 worker + 文档页
```

默认工作流很直接：安装 hook，使用 `TOKENLEAGUE_HOOK_KEY` 鉴权上传，再由 TokenLeague 基于 prompt-event 和 task-run 数据生成共享排行榜和时间线分析视图。

## 支持的数据采集来源

- Claude Code
- Codex CLI
- Workbuddy / CodeBuddy CLI
- Gemini CLI
- OpenClaw

更完整的各 Agent 安装命令、文件位置、隐私边界和排障说明，请查看 [docs/HOOKS.md](docs/HOOKS.md)。

## 主要页面

- `/leaderboard`：默认预计算排行榜，查看整体排名
- `/users/<id>`：单个用户的项目、模型和时间线分析页
- `/account`：个人 hook key 轮换与密码管理
- `/admin/users`：用户创建、禁用/启用和 hook key 轮换
- `/admin/ldap`：LDAP 配置、连通性测试和目录同步
- `/admin/agents`：已观测到的 Agent / 版本 / 模型目录
- `/docs`：站内文档浏览页
- `/api`：根据 Flask 路由生成的 API 列表

## 快速开始

1. 准备一个 MySQL 或 MariaDB 实例，并填写 `.env`。
2. 初始化数据库结构并创建管理员账号。
3. 启动 Web 服务和排行榜快照 worker。
4. 登录后台，获取 hook key，然后在开发者机器上安装 hooks。

## 运行要求

- Python 3.12+
- 可访问的 MySQL 或 MariaDB
- 基于 `.env.example` 生成并填写好的 `.env`

`docker-compose.yml` **不会** 自动启动数据库容器。启动 TokenLeague 前，请先把 `MY_APP_DB_HOST`、`MY_APP_DB_PORT`、`MY_APP_DB_NAME`、`MY_APP_DB_USER`、`MY_APP_DB_PWD` 指向现成的数据库实例。

<a id="docker-compose-recommended"></a>
## Docker Compose 部署（推荐）

如果你要在单机上快速得到一套稳定、可重复的部署，优先走这条路径。

1. 复制环境变量模板，并填写数据库连接信息：

```bash
cp .env.example .env
```

2. 使用应用镜像初始化数据库结构并创建管理员：

```bash
docker compose run --rm web python3 /app/scripts/init_db.py --admin-password '<强密码>'
```

3. 启动 Web 服务和排行榜快照 worker：

```bash
docker compose up --build -d
```

`docker-compose.yml` 已为 `web` 和 `worker` 配置 `restart: unless-stopped`，所以只要 Docker daemon 重新启动，容器就会自动恢复。若宿主机是 Linux，还需要把 Docker 设为开机自启，这样整机重启后整套服务也能自动恢复：

```bash
sudo systemctl enable --now docker
```

4. 打开 `http://localhost:5006/login`，使用以下账号登录：

- 用户名：`admin`
- 密码：初始化时传给 `--admin-password` 的值

5. 需要排查问题时查看日志：

```bash
docker compose logs -f web worker
```

`worker` 会在启动后立即刷新一次默认排行榜快照，之后每小时刷新一次。`/leaderboard` 页面读取的就是这份快照，而不是每次请求都扫描全量历史数据。

## 本地 Python 运行

如果你在做本地开发，或者希望不经 Docker 直接运行 Flask 服务，可以走这条路径。

1. 创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r service/requirements.txt
```

2. 复制环境变量文件，并导入当前 shell：

```bash
cp .env.example .env
set -a
source .env
set +a
```

3. 初始化数据库并创建管理员：

```bash
python3 scripts/init_db.py --admin-password '<强密码>'
```

4. 启动 Web 服务：

```bash
cd service
./run.sh
```

5. 如需让 `/leaderboard` 持续刷新，在另一个终端启动快照 worker：

```bash
python3 scripts/run_leaderboard_snapshot_worker.py
```

## 环境变量

### 应用与数据库

| 变量 | 是否必需 | 作用 |
| --- | --- | --- |
| `MY_FLASK_SECRET_KEY` | 是 | Flask Session 签名密钥 |
| `MY_APP_DB_HOST` | 是 | 数据库地址 |
| `MY_APP_DB_PORT` | 否 | 数据库端口，默认 `3306` |
| `MY_APP_DB_NAME` | 是 | 数据库名 |
| `MY_APP_DB_USER` | 是 | 数据库用户名 |
| `MY_APP_DB_PWD` | 是 | 数据库密码 |
| `PORT` | 否 | HTTP 端口，默认 `5006` |

仓库中的初始化脚本和迁移脚本也兼容历史的 `MY_KMM_DB_*` 环境变量别名。

### Hook 运行时

| 变量 | 是否必需 | 作用 |
| --- | --- | --- |
| `TOKENLEAGUE_HOOK_KEY` | 是 | 单个用户上报数据时使用的认证 key |
| `TOKENLEAGUE_API_URL` | 否 | 默认为 `http://localhost:5006` |
| `TOKENLEAGUE_GEMINI_CLI_VERSION` | 否 | 手动覆盖 Gemini 版本探测 |
| `TOKENLEAGUE_OPENCLAW_VERSION` | 否 | 手动覆盖 OpenClaw 版本探测 |

<a id="hook-installation"></a>
## Hook 安装

仓库中的 hook 模板位于 `hooks/` 目录。只有在显式执行安装脚本后，它们才会被写入用户目录或项目目录。

安装当前对外文档覆盖的全部集成：

```bash
./scripts/install_hooks.sh --claude --codex --workbuddy --gemini --openclaw --global
```

仅安装部分集成：

```bash
./scripts/install_hooks.sh --claude --global
./scripts/install_hooks.sh --codex --global
./scripts/install_hooks.sh --workbuddy --global
./scripts/install_hooks.sh --gemini --global
./scripts/install_hooks.sh --openclaw --global
```

安装到当前项目目录，而不是用户主目录：

```bash
./scripts/install_hooks.sh --claude --codex --workbuddy --gemini --openclaw --local
```

卸载已安装的 hooks：

```bash
./scripts/install_hooks.sh --claude --codex --workbuddy --gemini --openclaw --global --uninstall
```

安装脚本说明：

- `--all` 当前只会启用 Claude Code 和 Codex CLI
- 如果还需要 Workbuddy、Gemini CLI 或 OpenClaw，请显式加上对应参数

OpenClaw 额外说明：

- 全局安装 OpenClaw 时，还会安装一个 `systemd` timer
- OpenClaw service 场景建议优先使用 `~/.openclaw/.env`

更完整的各 Agent 安装命令、文件路径和排障说明请查看 [docs/HOOKS.md](docs/HOOKS.md)。

## 历史补录

对 hooks 未及时上传的历史记录进行补录：

```bash
python3 scripts/backfill_codex.py --dry-run
python3 scripts/backfill_claude.py --dry-run
```

常用参数：

```bash
--dry-run
--days N
--limit N
--verbose
--root PATH
```

默认扫描目录：

- Codex：`~/.codex/sessions`
- Claude Code：`~/.claude/projects`

真正上传时仍然需要 `TOKENLEAGUE_HOOK_KEY`。

## 开发与测试

运行完整服务测试：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests
```

常用定向测试命令：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_deploy_assets.py
```

## 仓库结构

```text
.
├── docs/                # 站内文档与运维说明
│   └── assets/          # README 中使用的文档图片
├── hooks/               # hook 与 collector 模板
├── scripts/             # 初始化、迁移、worker、补录、安装脚本
├── service/             # Flask 应用、模板、测试
├── Dockerfile
├── docker-compose.yml
└── README_EN.md
```
