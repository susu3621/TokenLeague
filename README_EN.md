# TokenLeague
> Team-level AI token analytics and agent ingestion dashboard

<div align="center">
  <h3>Turn AI coding assistant usage into a shared, reviewable engineering signal</h3>
  <p>TokenLeague collects token and prompt activity from multiple agent tools, stores it centrally, and exposes dashboards for per-user, per-project, and per-model analysis.</p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
    <img src="https://img.shields.io/badge/Web-Flask-000000?style=flat-square&logo=flask&logoColor=white" alt="Flask">
    <img src="https://img.shields.io/badge/Database-MySQL%20%2F%20MariaDB-4479A1?style=flat-square&logo=mysql&logoColor=white" alt="MySQL or MariaDB">
    <img src="https://img.shields.io/badge/Ingestion-Hooks%20%26%20Collectors-0A7B83?style=flat-square" alt="Hooks and collectors">
    <img src="https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square" alt="MIT license">
  </p>

  <p>
    <a href="#overview">Overview</a> •
    <a href="#why-tokenleague">Why TokenLeague</a> •
    <a href="#capabilities">Capabilities</a> •
    <a href="#architecture">Architecture</a> •
    <a href="#docker-compose-recommended">Docker Compose</a> •
    <a href="#hook-installation">Hook Installation</a>
  </p>

  <p>
    <strong>English</strong> |
    <a href="./README.md">简体中文</a>
  </p>
</div>

<p align="center">
  <img src="docs/assets/usage-timeline-masked.png" alt="TokenLeague dashboard with usage timeline and average tokens per prompt trend" width="960" />
</p>

<a id="overview"></a>
## Overview

TokenLeague gives engineering teams one place to inspect how AI coding assistants are used across people, projects, and models. Instead of relying on rough impressions or screenshots, teams get a persistent dashboard with leaderboard rankings, usage timelines, prompt counts, and average tokens per prompt.

The system is built around lightweight local hooks and collectors. Supported agent tools upload usage metadata to the Flask service, which stores it in MySQL or MariaDB and serves both the UI and the API.

<a id="why-tokenleague"></a>
## Why TokenLeague

- Track AI usage by user, project, model, and time window in one shared dashboard
- Make prompt efficiency visible through trend charts, averages, and timeline analysis
- Give teams concrete data for retrospectives, workflow tuning, and tool adoption reviews
- Keep ingestion practical with built-in installers, hook-key authentication, and historical backfill scripts

<a id="capabilities"></a>
## Capabilities

- Dashboard views: precomputed leaderboard, user detail analytics, account settings, admin pages, and in-app docs
- Efficiency metrics: token timeline, prompt counts, average tokens per prompt, project distribution, and model distribution
- Team operations: hook-key rotation, local password changes, LDAP configuration, observed agent catalog, and bilingual UI
- Integrations: installers and templates for Claude Code, Codex CLI, Workbuddy / CodeBuddy CLI, Gemini CLI, and OpenClaw
- Recovery paths: historical replay for Claude Code and Codex sessions when uploads were missed

<a id="architecture"></a>
## Architecture

```text
AI coding assistants / collectors
        |
        v
hooks/* or collector scripts
        |
        v
POST /api/ingest/*
        |
        v
Flask app + MySQL/MariaDB
        |
        +--> /leaderboard
        +--> /users/<id>
        +--> /admin/*
        \--> snapshot worker + docs
```

The default operating model is straightforward: install a hook, authenticate uploads with `TOKENLEAGUE_HOOK_KEY`, and let TokenLeague build shared leaderboard and timeline views from prompt-event and task-run data.

## Supported Ingestion Sources

- Claude Code
- Codex CLI
- Workbuddy / CodeBuddy CLI
- Gemini CLI
- OpenClaw

Detailed per-agent commands, installed file locations, privacy notes, and troubleshooting live in [docs/HOOKS.md](docs/HOOKS.md).

## Core Pages

- `/leaderboard`: default precomputed rankings across tracked users
- `/users/<id>`: per-user detail view with project, model, and timeline analysis
- `/account`: self-service hook-key rotation and password management
- `/admin/users`: user creation, status changes, and hook-key rotation
- `/admin/ldap`: LDAP configuration, connection testing, and directory sync
- `/admin/agents`: observed agent, version, and model catalog
- `/docs`: in-app documentation browser
- `/api`: route-derived API list

## Quick Start

1. Prepare a MySQL or MariaDB instance and fill in `.env`.
2. Bootstrap the schema and create the initial admin account.
3. Start the web app and the leaderboard snapshot worker.
4. Sign in, get a hook key, and install hooks on developer machines.

## Requirements

- Python 3.12+
- MySQL or MariaDB reachable from the app environment
- A writable `.env` file based on `.env.example`

`docker-compose.yml` does **not** provision a database container. Set `MY_APP_DB_HOST`, `MY_APP_DB_PORT`, `MY_APP_DB_NAME`, `MY_APP_DB_USER`, and `MY_APP_DB_PWD` to an existing database service before starting the app.

<a id="docker-compose-recommended"></a>
## Docker Compose (Recommended)

Use this path when you want the simplest repeatable deployment on one host.

1. Copy the environment template and edit the database connection values:

```bash
cp .env.example .env
```

2. Initialize the database schema and bootstrap the admin account through the app image:

```bash
docker compose run --rm web python3 /app/scripts/init_db.py --admin-password '<strong-password>'
```

3. Start the web app and the leaderboard snapshot worker:

```bash
docker compose up --build -d
```

`docker-compose.yml` sets both services to `restart: unless-stopped`, so they come back automatically after the Docker daemon starts again. On Linux hosts, also enable Docker at boot so a full machine reboot restores the stack without manual intervention:

```bash
sudo systemctl enable --now docker
```

4. Open `http://localhost:5006/login` and sign in with:

- username: `admin`
- password: the password passed to `--admin-password`

5. Follow logs when needed:

```bash
docker compose logs -f web worker
```

The `worker` service refreshes the default leaderboard snapshot once on startup and then every hour. `/leaderboard` reads that snapshot instead of scanning all historical prompt events on every request.

## Local Python Setup

Use this path when you are developing locally or want to run the Flask app outside Docker.

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r service/requirements.txt
```

2. Copy the environment file and export it into your shell:

```bash
cp .env.example .env
set -a
source .env
set +a
```

3. Initialize the database and create the admin account:

```bash
python3 scripts/init_db.py --admin-password '<strong-password>'
```

4. Start the web app:

```bash
cd service
./run.sh
```

5. In another terminal, optionally start the snapshot worker so `/leaderboard` stays fresh:

```bash
python3 scripts/run_leaderboard_snapshot_worker.py
```

## Environment Variables

### Application and Database

| Variable | Required | Purpose |
| --- | --- | --- |
| `MY_FLASK_SECRET_KEY` | Yes | Flask session signing key |
| `MY_APP_DB_HOST` | Yes | Database host |
| `MY_APP_DB_PORT` | No | Database port, defaults to `3306` |
| `MY_APP_DB_NAME` | Yes | Database name |
| `MY_APP_DB_USER` | Yes | Database user |
| `MY_APP_DB_PWD` | Yes | Database password |
| `PORT` | No | HTTP port, defaults to `5006` |

The repository also accepts the legacy `MY_KMM_DB_*` aliases used by the migration and init scripts.

### Hook Runtime

| Variable | Required | Purpose |
| --- | --- | --- |
| `TOKENLEAGUE_HOOK_KEY` | Yes | Authenticates usage uploads for one user |
| `TOKENLEAGUE_API_URL` | No | Defaults to `http://localhost:5006` |
| `TOKENLEAGUE_GEMINI_CLI_VERSION` | No | Overrides Gemini version detection |
| `TOKENLEAGUE_OPENCLAW_VERSION` | No | Overrides OpenClaw version detection |

<a id="hook-installation"></a>
## Hook Installation

Repository hook templates live under `hooks/`. They are only activated when you run the installer.

Install every documented integration:

```bash
./scripts/install_hooks.sh --claude --codex --workbuddy --gemini --openclaw --global
```

Install only selected integrations:

```bash
./scripts/install_hooks.sh --claude --global
./scripts/install_hooks.sh --codex --global
./scripts/install_hooks.sh --workbuddy --global
./scripts/install_hooks.sh --gemini --global
./scripts/install_hooks.sh --openclaw --global
```

Install hooks into the current project instead of the user profile:

```bash
./scripts/install_hooks.sh --claude --codex --workbuddy --gemini --openclaw --local
```

Remove installed hooks:

```bash
./scripts/install_hooks.sh --claude --codex --workbuddy --gemini --openclaw --global --uninstall
```

Installer note:

- `--all` currently enables Claude Code and Codex CLI only
- use explicit flags when you also want Workbuddy, Gemini CLI, or OpenClaw

OpenClaw note:

- global OpenClaw installation also installs a `systemd` timer
- prefer `~/.openclaw/.env` for OpenClaw service environments

See [docs/HOOKS.md](docs/HOOKS.md) for detailed per-agent commands, file locations, and troubleshooting.

## Historical Backfill

Replay usage that was not uploaded when hooks originally ran:

```bash
python3 scripts/backfill_codex.py --dry-run
python3 scripts/backfill_claude.py --dry-run
```

Common options:

```bash
--dry-run
--days N
--limit N
--verbose
--root PATH
```

Default scan roots:

- Codex: `~/.codex/sessions`
- Claude Code: `~/.claude/projects`

Real uploads still require `TOKENLEAGUE_HOOK_KEY`.

## Development And Tests

Run the service test suite:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests
```

Useful targeted commands:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_deploy_assets.py
```

## Repository Layout

```text
.
├── docs/                # in-app docs and operational guides
│   └── assets/          # README documentation images
├── hooks/               # hook and collector templates
├── scripts/             # init, migrations, workers, backfill, installers
├── service/             # Flask app, templates, tests
├── Dockerfile
├── docker-compose.yml
└── README.md
```
