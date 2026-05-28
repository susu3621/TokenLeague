#!/usr/bin/env bash
# =============================================================================
# deploy.sh — 将 TokenLeague 部署到 homegpu1
# =============================================================================
# 用法:
#   ./deploy.sh [OPTIONS]
#
# 选项:
#   -h, --host   SSH host alias（默认: homegpu1）
#   -p, --path   远端目标路径（默认: ~/project/TokenLeague）
#   --port       服务端口（默认: 5006）
#   -n, --lines  日志行数（默认: 100）
#   --dry-run    只显示将执行的操作，不实际执行
# =============================================================================
set -euo pipefail

SSH_HOST="homegpu1"
REMOTE_PATH="~/project/TokenLeague"
HEALTH_PORT=5006
APP_PORT="$HEALTH_PORT"
LOG_LINES=100
DRY_RUN=false

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
step()    { echo -e "\n${BLUE}━━━ Step $1: $2 ━━━${NC}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--host)
      SSH_HOST="$2"
      shift 2
      ;;
    -p|--path)
      REMOTE_PATH="$2"
      shift 2
      ;;
    --port)
      APP_PORT="$2"
      shift 2
      ;;
    -n|--lines)
      LOG_LINES="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      error "未知参数: $1"
      echo "用法: $0 [-h host] [-p path] [--port port] [-n lines] [--dry-run]"
      exit 1
      ;;
  esac
done

LOCAL_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REMOTE_SETUP='export PATH="/usr/local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"'

run_ssh() {
  local remote_cmd="$1"
  if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "  ${YELLOW}[DRY-RUN SSH→${SSH_HOST}]${NC} ${remote_cmd}"
  else
    ssh "$SSH_HOST" "${REMOTE_SETUP} && mkdir -p ${REMOTE_PATH} && cd ${REMOTE_PATH} && ${remote_cmd}"
  fi
}

detect_remote_os() {
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "unknown"
    return
  fi

  ssh "$SSH_HOST" "${REMOTE_SETUP} && uname -s"
}

detect_compose_cmd() {
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "docker compose"
    return
  fi

  local cmd
  cmd=$(ssh "$SSH_HOST" "${REMOTE_SETUP} && if docker compose version >/dev/null 2>&1; then echo 'docker compose'; elif command -v docker-compose >/dev/null 2>&1; then echo 'docker-compose'; fi")
  if [[ -z "$cmd" ]]; then
    error "远端未找到 docker compose 或 docker-compose"
    exit 1
  fi
  echo "$cmd"
}

check_remote_docker_autostart() {
  local remote_os="$1"

  if [[ "$DRY_RUN" == "true" ]]; then
    info "[DRY-RUN] 跳过 Docker 开机自启检查"
    return
  fi

  case "$remote_os" in
    Linux)
      if ssh "$SSH_HOST" "${REMOTE_SETUP} && command -v systemctl >/dev/null 2>&1"; then
        local enabled_state
        local active_state

        enabled_state=$(ssh "$SSH_HOST" "${REMOTE_SETUP} && systemctl is-enabled docker 2>/dev/null || true")
        active_state=$(ssh "$SSH_HOST" "${REMOTE_SETUP} && systemctl is-active docker 2>/dev/null || true")

        if [[ "$enabled_state" == "enabled" ]]; then
          success "docker.service 已启用，宿主机重启后 Docker 会自动启动"
        else
          warn "docker.service 未启用：容器的 restart: unless-stopped 只有在 Docker 启动后才会生效"
          warn "请在远端执行：sudo systemctl enable --now docker"
        fi

        if [[ "$active_state" != "active" ]]; then
          warn "docker.service 当前状态为 ${active_state:-unknown}，如需自动恢复请先启动 Docker"
        fi
      else
        warn "远端 Linux 未检测到 systemctl，请确认 Docker 会在开机后自动启动"
      fi
      ;;
    Darwin)
      warn "远端为 macOS，请确认 Docker Desktop 已设置为登录后自动启动；Compose 服务已使用 restart: unless-stopped"
      ;;
    *)
      warn "远端系统为 ${remote_os:-unknown}，请确认 Docker 会在宿主机启动后自动拉起；Compose 服务已使用 restart: unless-stopped"
      ;;
  esac
}

run_rsync() {
  local rsync_cmd=(
    rsync -rltvz --delete
    --no-group --no-owner
    --exclude='__pycache__/'
    --exclude='*.pyc'
    --exclude='.git/'
    --exclude='.env'
    --exclude='.env.*'
    --exclude='data/'
    --exclude='.pytest_cache/'
    --exclude='.worktrees/'
    "${LOCAL_PATH}/"
    "${SSH_HOST}:${REMOTE_PATH}/"
  )

  if [[ "$DRY_RUN" == "true" ]]; then
    echo -e "  ${YELLOW}[DRY-RUN]${NC} ${rsync_cmd[*]}"
  else
    "${rsync_cmd[@]}"
  fi
}

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║             TokenLeague 部署脚本                ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
info "本地路径 : $LOCAL_PATH"
info "远端主机 : $SSH_HOST"
info "远端路径 : $REMOTE_PATH"
info "服务端口 : $APP_PORT"
info "日志行数 : $LOG_LINES"
[[ "$DRY_RUN" == "true" ]] && warn "模式: DRY-RUN（不会实际执行任何操作）"

step 1 "检查 SSH 连接性"
if [[ "$DRY_RUN" == "true" ]]; then
  info "[DRY-RUN] 跳过 SSH 连通性检查"
else
  if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$SSH_HOST" 'echo OK' >/dev/null 2>&1; then
    error "无法连接到 ${SSH_HOST}，请检查 SSH 配置和网络连接"
    exit 1
  fi
  success "SSH 连接正常: $SSH_HOST"
fi

step 2 "检测远端 Docker Compose"
COMPOSE_CMD="$(detect_compose_cmd)"
success "Docker Compose 命令: $COMPOSE_CMD"

step 3 "检查宿主机 Docker 开机自启"
REMOTE_OS="$(detect_remote_os)"
check_remote_docker_autostart "$REMOTE_OS"

step 4 "创建远端目录"
run_ssh "mkdir -p data/postgres"
success "远端目录已就绪"

step 5 "rsync 同步代码"
run_rsync
success "代码同步完成"

step 6 "校验 Compose 配置"
run_ssh "test -f .env && PORT=${APP_PORT} ${COMPOSE_CMD} config >/dev/null"
success "Compose 配置有效"

step 7 "构建并启动容器"
run_ssh "PORT=${APP_PORT} ${COMPOSE_CMD} up -d --build --remove-orphans"
success "新容器已启动"

step 8 "等待服务健康检查通过（超时 60s）"
if [[ "$DRY_RUN" == "true" ]]; then
  info "[DRY-RUN] 跳过健康检查"
else
  MAX_WAIT=60
  INTERVAL=5
  elapsed=0

  while [[ $elapsed -lt $MAX_WAIT ]]; do
    if ssh "$SSH_HOST" "${REMOTE_SETUP} && curl -sf http://localhost:${HEALTH_PORT}/health >/dev/null 2>&1"; then
      success "健康检查通过，耗时 ${elapsed}s"
      break
    fi

    info "等待中... 已等待 ${elapsed}s / ${MAX_WAIT}s"
    sleep "$INTERVAL"
    elapsed=$((elapsed + INTERVAL))
  done

  if [[ $elapsed -ge $MAX_WAIT ]]; then
    error "健康检查超时，最近日志如下："
    ssh "$SSH_HOST" "${REMOTE_SETUP} && cd ${REMOTE_PATH} && PORT=${APP_PORT} ${COMPOSE_CMD} logs --tail=${LOG_LINES} web" || true
    exit 1
  fi
fi

step 9 "打印最近 ${LOG_LINES} 行容器日志"
echo ""
echo -e "${BLUE}────── web 容器日志（最近 ${LOG_LINES} 行）──────${NC}"
run_ssh "PORT=${APP_PORT} ${COMPOSE_CMD} logs --tail=${LOG_LINES} web"

echo ""
info "Compose 服务使用 restart: unless-stopped；只要 Docker 启动，web 和 worker 会自动恢复"
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        TokenLeague 部署完成，端口 ${APP_PORT}        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
