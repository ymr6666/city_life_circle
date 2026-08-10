#!/usr/bin/env bash
# =====================================================================
#  城市时域生活圈分析系统 - Linux/macOS 一键安装脚本
#  功能: 创建Python虚拟环境+安装依赖 / 恢复数据库 / 复制人口瓦片 / 构建前端(可选)
#  前提: PostgreSQL 13 + PostGIS + pgRouting 已安装并启动
#  用法: bash deploy/scripts/install_linux.sh
# =====================================================================
set -e
cd "$(dirname "$0")/../.."

echo "[1/5] 检查环境..."
command -v python3 >/dev/null || { echo "[错误] 未找到 python3"; exit 1; }
command -v psql >/dev/null || { echo "[错误] 未找到 psql, 请安装 postgresql-client"; exit 1; }
echo "      环境 OK"

echo "[2/5] 数据库信息..."
read -r -p "数据库主机[localhost]: " DB_HOST
DB_HOST=${DB_HOST:-localhost}
read -r -s -p "postgres 密码: " DB_PASS
echo ""
export PGPASSWORD="$DB_PASS"

echo "[3/5] 恢复数据库 (city_life_circle)..."
if ! psql -U postgres -h "$DB_HOST" -tc "SELECT 1 FROM pg_database WHERE datname='city_life_circle'" | grep -q 1; then
  createdb -U postgres -h "$DB_HOST" city_life_circle
fi
pg_restore -U postgres -h "$DB_HOST" -d city_life_circle --no-owner --no-privileges --clean --if-exists deploy/data/city_life_circle.dump \
  || echo "[警告] 恢复命令报错, 请检查扩展 postgis/pgrouting 是否已安装"
psql -U postgres -h "$DB_HOST" -d city_life_circle -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS pgrouting;" >/dev/null 2>&1
echo "      数据库恢复完成"

echo "[4/5] 复制人口瓦片到 cache/pop_tiles..."
mkdir -p cache
[ -d deploy/data/pop_tiles ] && cp -r deploy/data/pop_tiles cache/pop_tiles || echo "[警告] 未找到 deploy/data/pop_tiles"

echo "[5/5] 后端依赖 (Python 虚拟环境)..."
python3 -m venv backend/.venv || virtualenv backend/.venv
# shellcheck disable=SC1091
source backend/.venv/bin/activate
pip install --upgrade pip >/dev/null 2>&1 || true
pip install -r backend/requirements.txt
echo "      后端依赖安装完成"

echo ""
echo "============================================================"
echo " 安装完成!"
echo " 启动: bash deploy/scripts/start_linux.sh"
echo " 访问: http://localhost:5000"
echo " 详细说明: docs/部署说明.md"
echo "============================================================"
