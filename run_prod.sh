#!/bin/bash
# 消字号合规预审引擎 — 生产环境启动脚本
#
# 环境变量（在 .env 中设置）:
#   PORT       — 监听端口，默认 8000
#   WORKERS    — worker 进程数，默认 1（建议 = CPU 核数）
#
# 用法:
#   ./run_prod.sh           # 默认 8000 端口
#   PORT=8080 ./run_prod.sh # 指定端口

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 检查 Python 环境
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "错误: 未安装 FastAPI，请先运行 pip install -r requirements.txt"
    exit 1
fi

PORT="${PORT:-8000}"
WORKERS="${WORKERS:-1}"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  消字号合规预审引擎"
echo "  端口: $PORT  |  Workers: $WORKERS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exec python3 -m uvicorn server.main:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers "$WORKERS" \
    --no-access-log
