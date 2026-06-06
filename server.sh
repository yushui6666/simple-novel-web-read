#!/bin/bash
# 小说阅读器 - 一键启停脚本

PORT=6066
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$APP_DIR/.venv/bin/python"
PID_FILE="$APP_DIR/.server.pid"

# 选择 Python 解释器
if [ -f "$VENV_PYTHON" ]; then
    PYTHON="$VENV_PYTHON"
else
    PYTHON="python3"
fi

start() {
    if lsof -ti:$PORT >/dev/null 2>&1; then
        echo "⚠️  端口 $PORT 已被占用，尝试停止已有进程..."
        stop
        sleep 1
    fi

    echo "🚀 启动小说阅读器..."
    cd "$APP_DIR"
    nohup "$PYTHON" app.py > /dev/null 2>&1 &
    echo $! > "$PID_FILE"

    # 等待启动
    for i in $(seq 1 10); do
        sleep 0.3
        if curl -s -o /dev/null "http://127.0.0.1:$PORT" 2>/dev/null; then
            echo "✅ 已启动 → http://127.0.0.1:$PORT"
            return 0
        fi
    done

    echo "❌ 启动超时，请检查 app.log"
    return 1
}

stop() {
    local pid
    pid=$(lsof -ti:$PORT 2>/dev/null)

    if [ -z "$pid" ]; then
        echo "⚠️  没有运行中的进程 (端口 $PORT)"
        rm -f "$PID_FILE"
        return 0
    fi

    echo "🛑 停止服务 (PID: $pid)..."
    kill $pid 2>/dev/null
    sleep 0.5

    # 如果还没停，强制 kill
    if lsof -ti:$PORT >/dev/null 2>&1; then
        kill -9 $pid 2>/dev/null
        sleep 0.3
    fi

    if lsof -ti:$PORT >/dev/null 2>&1; then
        echo "❌ 停止失败"
        return 1
    fi

    rm -f "$PID_FILE"
    echo "✅ 已停止"
}

status() {
    if lsof -ti:$PORT >/dev/null 2>&1; then
        local pid
        pid=$(lsof -ti:$PORT | head -1)
        echo "🟢 运行中  PID: $pid  端口: $PORT"
        echo "   http://127.0.0.1:$PORT"
    else
        echo "🔴 未运行"
    fi
}

case "${1:-start}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    status)  status ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        echo ""
        echo "  start   → 启动服务"
        echo "  stop    → 停止服务"
        echo "  restart → 重启服务"
        echo "  status  → 查看状态"
        exit 1
        ;;
esac
