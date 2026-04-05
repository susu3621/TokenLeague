# TokenLeague

TokenLeague 是一个基于 Flask 的 AI 编码助手 Token 用量看板。它通过本地 hooks / collector 接收 prompt 与 task 用量数据，写入 MySQL，并提供排行榜、用户详情、账户管理和运维文档页面。

## 功能特性

- 预计算排行榜首页，快速查看全局排名
- 用户详情页支持项目分布、模型分布、最近 Prompt 事件，以及可按项目切换的趋势图
- 账户页面支持轮换 hook key 和修改本地密码
- 管理页面支持用户管理、LDAP 配置，以及已观测到的 Agent 目录
- 内置 Claude Code、Codex CLI、Cursor、Workbuddy、Gemini CLI、Kiro、OpenClaw 的安装脚本
- 支持 Claude Code 与 Codex 的历史补录
- 提供英文与简体中文界面

## 支持的数据采集来源

- Claude Code
- Codex CLI
- Cursor
- Workbuddy / CodeBuddy CLI
- Gemini CLI
- Kiro
- OpenClaw

更细的 hook 行为、文件位置和排障说明请查看 [docs/HOOKS.md](docs/HOOKS.md)。

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

安装全部支持的集成：

```bash
./scripts/install_hooks.sh --all --cursor --workbuddy --gemini --kiro --openclaw --global
```

仅安装部分集成：

```bash
./scripts/install_hooks.sh --claude --global
./scripts/install_hooks.sh --codex --global
./scripts/install_hooks.sh --gemini --global
./scripts/install_hooks.sh --openclaw --global
```

安装到当前项目目录，而不是用户主目录：

```bash
./scripts/install_hooks.sh --all --cursor --workbuddy --gemini --kiro --openclaw --local
```

卸载已安装的 hooks：

```bash
./scripts/install_hooks.sh --all --cursor --workbuddy --gemini --kiro --openclaw --global --uninstall
```

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
├── hooks/               # hook 与 collector 模板
├── scripts/             # 初始化、迁移、worker、补录、安装脚本
├── service/             # Flask 应用、模板、测试
├── Dockerfile
├── docker-compose.yml
└── README.md
```
