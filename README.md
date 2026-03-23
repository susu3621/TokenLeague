# Template Project Foundation

这个目录承载的是从当前项目抽取出来的、可复用于新项目的基础骨架，不包含当前仓库里已经绑定业务语义的模块。

This directory packages a reusable foundation extracted from the current project without carrying over its business-specific modules.

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
