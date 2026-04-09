# TokenLeague

[English](README.md) | [简体中文](README_CN.md)

TokenLeague 用来帮助团队持续记录 AI 编码助手的 Token 用量与使用效率。它把每天的使用数据沉淀成共享看板，让团队能回看 Token 花在什么地方、不同项目和模型的使用模式如何变化，并据此做复盘和自我提升。

<p align="center">
  <img src="docs/assets/usage-timeline-masked.png" alt="TokenLeague 仪表盘截图，展示使用时间线与平均每次 Prompt Token 趋势" width="960" />
</p>

## 项目目的

- 让团队按成员、项目、模型统一记录 Token 用量
- 通过时间线和平均每次 Prompt Token 等指标把效率问题可视化
- 为复盘、提示词优化和工作习惯改进提供客观数据依据

## 功能特性

- 预计算排行榜首页，快速查看全局排名
- 用户详情页支持项目分布、模型分布、最近 Prompt 事件，以及可按项目切换的趋势图
- 重点展示 Token 时间线、平均每次 Prompt Token 等效率相关视图
- 账户页面支持轮换 hook key 和修改本地密码
- 管理页面支持用户管理、LDAP 配置，以及已观测到的 Agent 目录
- 内置 Claude Code、Codex CLI、Workbuddy、Gemini CLI、OpenClaw 的安装脚本与采集能力
- 支持 Claude Code 与 Codex 的历史补录
- 提供英文与简体中文界面

## 支持的数据采集来源

- Claude Code
- Codex CLI
- Workbuddy / CodeBuddy CLI
- Gemini CLI
- OpenClaw

更细的 hook 行为、文件位置和排障说明请查看 [docs/HOOKS.md](docs/HOOKS.md)。英文说明请查看 [README.md](README.md)。

## 主要页面

- `/leaderboard`：默认预计算排行榜
- `/users/<id>`：单个用户的项目、模型和时间线分析页
- `/account`：个人 hook key 与密码管理
- `/admin/users`：用户创建、禁用/启用、hook key 轮换
- `/admin/ldap`：LDAP 配置、连通性测试、目录同步
- `/admin/agents`：已观测到的 Agent / 版本 / 模型目录
- `/docs`：站内文档浏览页
- `/api`：根据 Flask 路由生成的 API 列表

## 运行要求

- Python 3.12+
- 可访问的 MySQL 或 MariaDB
- 基于 `.env.example` 生成并填写好的 `.env`

`docker-compose.yml` **不会** 自动启动数据库容器。启动 TokenLeague 前，请先把 `MY_APP_DB_HOST`、`MY_APP_DB_PORT`、`MY_APP_DB_NAME`、`MY_APP_DB_USER`、`MY_APP_DB_PWD` 指向现成的数据库实例。

## Docker Compose 部署（推荐）

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
└── README.md
```
