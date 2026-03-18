#!/usr/bin/env bash
# Agent Hub Cloud — Production Deployment Script
#
# Usage:
#   ./scripts/deploy.sh          # Full deployment
#   ./scripts/deploy.sh restart   # Restart services
#   ./scripts/deploy.sh stop      # Stop all services
#   ./scripts/deploy.sh status    # Show service status
#   ./scripts/deploy.sh logs      # Show logs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.prod.yml"
ENV_FILE="$PROJECT_DIR/.env"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
err()  { echo -e "${RED}[error]${NC} $*" >&2; }

check_deps() {
    log "Checking dependencies..."
    local missing=0

    if ! command -v docker &>/dev/null; then
        err "Docker not found. Install: https://docs.docker.com/engine/install/"
        missing=1
    fi

    if ! docker compose version &>/dev/null; then
        err "Docker Compose plugin not found."
        missing=1
    fi

    if [ ! -f "$ENV_FILE" ]; then
        err ".env file not found. Copy from .env.example and configure:"
        err "  cp $PROJECT_DIR/.env.example $ENV_FILE"
        missing=1
    fi

    if [ $missing -eq 1 ]; then
        exit 1
    fi

    log "All dependencies OK"
}

check_env() {
    log "Validating environment configuration..."
    source "$ENV_FILE"

    local warnings=0

    if [ "${JWT_SECRET:-}" = "CHANGE-ME-to-a-secure-random-string-at-least-32-chars" ] || [ -z "${JWT_SECRET:-}" ]; then
        warn "JWT_SECRET is not set or still default. Generate one:"
        warn "  python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        warnings=1
    fi

    if [ -z "${MGMT_USAGE_SECRET:-}" ] || [ "${MGMT_USAGE_SECRET:-}" = "CHANGE-ME-to-a-secure-random-string" ]; then
        warn "MGMT_USAGE_SECRET is not set or still default."
        warnings=1
    fi

    if [ "${MGMT_MOCK_MODE:-true}" = "true" ]; then
        warn "MGMT_MOCK_MODE is true — instances will be simulated, not real Docker deployments."
    fi

    if [ $warnings -eq 1 ]; then
        warn "Fix warnings above before deploying to production."
        read -p "Continue anyway? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi

    log "Environment OK"
}

build_frontend() {
    log "Building frontend..."
    cd "$PROJECT_DIR/web"
    if [ ! -d "node_modules" ]; then
        npm ci
    fi
    npm run build
    cd "$PROJECT_DIR"
    log "Frontend built successfully"
}

deploy() {
    check_deps
    check_env

    log "Building frontend..."
    build_frontend

    log "Starting services with Docker Compose..."
    docker compose -f "$COMPOSE_FILE" up --build -d

    log "Waiting for health check..."
    local retries=0
    local max_retries=30
    while [ $retries -lt $max_retries ]; do
        if curl -sf http://localhost:3000/api/health > /dev/null 2>&1; then
            log "Management Plane is healthy!"
            break
        fi
        retries=$((retries + 1))
        sleep 2
    done

    if [ $retries -eq $max_retries ]; then
        warn "Health check timed out. Check logs: ./scripts/deploy.sh logs"
    fi

    echo ""
    log "Deployment complete!"
    log "  Management Plane: http://localhost:3000"
    log "  Health check:     http://localhost:3000/api/health"
    echo ""
}

stop() {
    log "Stopping services..."
    docker compose -f "$COMPOSE_FILE" down
    log "Services stopped"
}

restart() {
    log "Restarting services..."
    docker compose -f "$COMPOSE_FILE" restart
    log "Services restarted"
}

status() {
    docker compose -f "$COMPOSE_FILE" ps
}

show_logs() {
    docker compose -f "$COMPOSE_FILE" logs --tail=100 -f
}

case "${1:-deploy}" in
    deploy)  deploy ;;
    stop)    stop ;;
    restart) restart ;;
    status)  status ;;
    logs)    show_logs ;;
    *)
        echo "Usage: $0 {deploy|stop|restart|status|logs}"
        exit 1
        ;;
esac
