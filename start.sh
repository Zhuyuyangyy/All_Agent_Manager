#!/bin/bash
# start.sh - Start All_Agent_Manager System
# Usage: ./start.sh [backend|mock|real|all]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Load environment variables
if [ -f ".env" ]; then
    log_info "Loading .env file..."
    export $(grep -v '^#' .env | xargs)
fi

# Default port configuration
BACKEND_PORT=${BACKEND_PORT:-8000}
MOCK_AGENTS_PORT=${MOCK_AGENTS_PORT:-5100}
REAL_AGENTS_PORT=${REAL_AGENTS_PORT:-5100}

show_help() {
    echo "All_Agent_Manager Startup Script"
    echo ""
    echo "Usage: ./start.sh [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  backend    - Start the backend API server only"
    echo "  mock       - Start mock agents only"
    echo "  real       - Start real agents (requires DEEPSEEK_API_KEY)"
    echo "  all        - Start everything (default)"
    echo "  status     - Check running services"
    echo "  stop       - Stop all services"
    echo "  restart    - Restart all services"
    echo ""
    echo "Environment Variables:"
    echo "  BACKEND_PORT       - Backend API port (default: 8000)"
    echo "  MOCK_AGENTS_PORT   - Mock agents port (default: 5100)"
    echo "  REAL_AGENTS_PORT   - Real agents port (default: 5100)"
    echo "  DEEPSEEK_API_KEY   - DeepSeek API key for real agents"
    echo ""
}

check_venv() {
    if [ ! -d "venv" ]; then
        log_info "Creating virtual environment..."
        python3 -m venv venv
    fi
    
    if [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    elif [ -f "venv/Scripts/activate" ]; then
        source venv/Scripts/activate
    fi
    
    # Install requirements if needed
    if [ -f "requirements.txt" ]; then
        pip install -q -r requirements.txt 2>/dev/null || true
    fi
}

start_backend() {
    log_info "Starting Backend API on port $BACKEND_PORT..."
    cd "$SCRIPT_DIR"
    check_venv
    
    if command -v nohup > /dev/null; then
        nohup python -m uvicorn backend.app:app --host 0.0.0.0 --port $BACKEND_PORT > backend.log 2>&1 &
        echo $! > backend.pid
        log_info "Backend started with PID $(cat backend.pid)"
    else
        python -m uvicorn backend.app:app --host 0.0.0.0 --port $BACKEND_PORT &
        log_info "Backend started"
    fi
}

start_mock_agents() {
    log_info "Starting Mock Agents on port $MOCK_AGENTS_PORT..."
    cd "$SCRIPT_DIR"
    check_venv
    
    if command -v nohup > /dev/null; then
        nohup python mock_subagents.py > mock_agents.log 2>&1 &
        echo $! > mock_agents.pid
        log_info "Mock agents started with PID $(cat mock_agents.pid)"
    else
        python mock_subagents.py &
        log_info "Mock agents started"
    fi
}

start_real_agents() {
    log_info "Starting Real Agents (DeepSeek) on port $REAL_AGENTS_PORT..."
    
    if [ -z "$DEEPSEEK_API_KEY" ]; then
        log_warn "DEEPSEEK_API_KEY not set. Real agents will run in fallback mode."
    fi
    
    cd "$SCRIPT_DIR"
    check_venv
    
    if command -v nohup > /dev/null; then
        nohup python backend/real_agents.py > real_agents.log 2>&1 &
        echo $! > real_agents.pid
        log_info "Real agents started with PID $(cat real_agents.pid)"
    else
        python backend/real_agents.py &
        log_info "Real agents started"
    fi
}

stop_service() {
    local name=$1
    local pid_file=$2
    
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 $pid 2>/dev/null; then
            log_info "Stopping $name (PID: $pid)..."
            kill $pid 2>/dev/null || true
            rm -f "$pid_file"
        fi
    fi
    
    # Also try to find by name
    pkill -f "$name" 2>/dev/null || true
}

check_status() {
    log_info "Checking services..."
    
    echo ""
    echo "Port Status:"
    for port in $BACKEND_PORT $MOCK_AGENTS_PORT $REAL_AGENTS_PORT; do
        if lsof -i :$port > /dev/null 2>&1 || netstat -tuln 2>/dev/null | grep -q ":$port "; then
            echo "  Port $port: ${GREEN}RUNNING${NC}"
        else
            echo "  Port $port: ${RED}STOPPED${NC}"
        fi
    done
    
    echo ""
    echo "Process Files:"
    for pid_file in backend.pid mock_agents.pid real_agents.pid; do
        if [ -f "$pid_file" ]; then
            local pid=$(cat "$pid_file")
            if kill -0 $pid 2>/dev/null; then
                echo "  $pid_file: ${GREEN}PID $pid running${NC}"
            else
                echo "  $pid_file: ${RED}stale (PID $pid not running)${NC}"
            fi
        else
            echo "  $pid_file: ${YELLOW}not running${NC}"
        fi
    done
}

stop_all() {
    log_info "Stopping all services..."
    
    stop_service "backend" "backend.pid"
    stop_service "mock_subagents" "mock_agents.pid"
    stop_service "real_agents" "real_agents.pid"
    
    log_info "All services stopped."
}

restart_all() {
    stop_all
    sleep 2
    start_all
}

start_all() {
    log_info "Starting All_Agent_Manager System..."
    echo ""
    
    start_backend
    sleep 2
    start_mock_agents
    sleep 1
    start_real_agents
    
    echo ""
    log_info "All services started!"
    echo ""
    echo "Services:"
    echo "  Backend API:     http://localhost:$BACKEND_PORT"
    echo "  Mock Agents:      Port $MOCK_AGENTS_PORT"
    echo "  Real Agents:      Port $REAL_AGENTS_PORT (DeepSeek)"
    echo ""
    echo "Logs:"
    echo "  Backend:    backend.log"
    echo "  Mock:       mock_agents.log"
    echo "  Real:       real_agents.log"
    echo ""
    echo "Use './start.sh status' to check running services"
}

# Main
COMMAND=${1:-all}

case "$COMMAND" in
    backend)
        start_backend
        ;;
    mock)
        start_mock_agents
        ;;
    real)
        start_real_agents
        ;;
    all)
        start_all
        ;;
    status)
        check_status
        ;;
    stop)
        stop_all
        ;;
    restart)
        restart_all
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "Unknown command: $COMMAND"
        echo ""
        show_help
        exit 1
        ;;
esac
