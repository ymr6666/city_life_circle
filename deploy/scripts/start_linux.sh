#!/usr/bin/env bash
# =====================================================================
#  城市时域生活圈分析系统 - Linux/macOS 启动脚本
#  用法: bash deploy/scripts/start_linux.sh
# =====================================================================
set -e
cd "$(dirname "$0")/../.."

if [ ! -d backend/.venv ]; then
  echo "[错误] 尚未安装后端依赖, 请先运行 bash deploy/scripts/install_linux.sh"
  exit 1
fi

echo "启动后端 (waitress, http://localhost:5000)..."
export PYTHONUNBUFFERED=1
# shellcheck disable=SC1091
source backend/.venv/bin/activate
cd backend
exec python app.py
