#!/bin/bash

# FastAPI Application Startup Script
# Usage: ./scripts/start.sh [api|worker|beat|all]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default values
MODE=${1:-all}
LOG_LEVEL=${LOG_LEVEL:-info}
WORKERS=${WORKERS:-4}
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8000}

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if uv is installed
check_uv() {
    if ! command -v uv &> /dev/null; then
        log_error "uv is not installed. Please install it first."
        exit 1
    fi
}

# Start FastAPI application
start_api() {
    log_info "Starting FastAPI application on ${HOST}:${PORT}..."
    uv run uvicorn app.main:app --host ${HOST} --port ${PORT} --reload
}

# Start Celery worker
start_worker() {
    log_info "Starting Celery worker with ${WORKERS} workers..."
    uv run celery -A app.celery_app worker \
        --loglevel=${LOG_LEVEL} \
        --concurrency=${WORKERS}
}

# Start Celery beat scheduler
start_beat() {
    log_info "Starting Celery beat scheduler with RedBeat..."
    uv run celery -A app.celery_app beat \
        --loglevel=${LOG_LEVEL} \
        -S redbeat.RedBeatScheduler
}

# Start all services in background
start_all() {
    log_info "Starting all services..."
    
    # Create logs directory
    mkdir -p logs
    
    # Start Celery worker in background
    log_info "Starting Celery worker..."
    uv run celery -A app.celery_app worker \
        --loglevel=${LOG_LEVEL} \
        --concurrency=${WORKERS} \
        > logs/worker.log 2>&1 &
    WORKER_PID=$!
    echo $WORKER_PID > logs/worker.pid
    log_info "Celery worker started (PID: $WORKER_PID)"
    
    # Start Celery beat in background
    log_info "Starting Celery beat..."
    uv run celery -A app.celery_app beat \
        --loglevel=${LOG_LEVEL} \
        -S redbeat.RedBeatScheduler \
        > logs/beat.log 2>&1 &
    BEAT_PID=$!
    echo $BEAT_PID > logs/beat.pid
    log_info "Celery beat started (PID: $BEAT_PID)"
    
    # Start FastAPI (foreground)
    log_info "Starting FastAPI application..."
    uv run uvicorn app.main:app --host ${HOST} --port ${PORT}
}

# Stop all services
stop_all() {
    log_info "Stopping all services..."
    
    if [ -f logs/worker.pid ]; then
        kill $(cat logs/worker.pid) 2>/dev/null || true
        rm logs/worker.pid
        log_info "Celery worker stopped"
    fi
    
    if [ -f logs/beat.pid ]; then
        kill $(cat logs/beat.pid) 2>/dev/null || true
        rm logs/beat.pid
        log_info "Celery beat stopped"
    fi
    
    log_info "All services stopped"
}

# Show usage
show_usage() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  api      Start FastAPI application only"
    echo "  worker   Start Celery worker only"
    echo "  beat     Start Celery beat scheduler only"
    echo "  all      Start all services (default)"
    echo "  stop     Stop all background services"
    echo ""
    echo "Environment variables:"
    echo "  LOG_LEVEL  Log level (default: info)"
    echo "  WORKERS    Number of Celery workers (default: 4)"
    echo "  HOST       API host (default: 0.0.0.0)"
    echo "  PORT       API port (default: 8000)"
}

# Main
check_uv

case $MODE in
    api)
        start_api
        ;;
    worker)
        start_worker
        ;;
    beat)
        start_beat
        ;;
    all)
        start_all
        ;;
    stop)
        stop_all
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        log_error "Unknown command: $MODE"
        show_usage
        exit 1
        ;;
esac

