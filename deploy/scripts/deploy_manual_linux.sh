#!/usr/bin/env bash
# =====================================================================
#  城市时域生活圈分析系统 - Linux 手动部署一键脚本 (不依赖 Docker)
#  自动完成: 装依赖(apt) -> 建库恢复 -> 人口瓦片 -> 低配调优 -> 后端 -> systemd 服务
#  适用: Ubuntu 20.04/22.04/24.04 (PostgreSQL 12/14/16)
#  用法: bash deploy/scripts/deploy_manual_linux.sh
#  卸载: sudo systemctl disable --now city-life-circle && rm -rf <项目目录>
# =====================================================================
set -euo pipefail

# 定位项目根目录: 优先环境变量, 否则从脚本所在位置向上找 (含 deploy/data/city_life_circle.dump 的目录)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "${CLC_PROJECT_DIR:-}" ]; then
  PROJECT_DIR="$CLC_PROJECT_DIR"
else
  PROJECT_DIR="$SCRIPT_DIR"
  while [ "$PROJECT_DIR" != "/" ]; do
    if [ -f "$PROJECT_DIR/deploy/data/city_life_circle.dump" ] && [ -d "$PROJECT_DIR/backend" ]; then
      break
    fi
    PROJECT_DIR="$(dirname "$PROJECT_DIR")"
  done
fi
if [ ! -f "$PROJECT_DIR/deploy/data/city_life_circle.dump" ]; then
  echo "[错误] 无法定位项目目录(需包含 deploy/data/city_life_circle.dump)。"
  echo "       请把脚本放到项目内(如 city-life-circle/deploy/scripts/) 再运行,"
  echo "       或用环境变量指定: CLC_PROJECT_DIR=/路径/city-life-circle bash deploy_manual_linux.sh"
  exit 1
fi
echo "项目目录: $PROJECT_DIR"

# ---- 0. 前置检查 ----
[ -f "$PROJECT_DIR/deploy/data/city_life_circle.dump" ] || { echo "[错误] 缺少 deploy/data/city_life_circle.dump"; exit 1; }
[ -d "$PROJECT_DIR/deploy/data/pop_tiles" ] || { echo "[错误] 缺少 deploy/data/pop_tiles"; exit 1; }
command -v sudo >/dev/null || { echo "[错误] 需要 sudo"; exit 1; }

# ---- 1. 安装依赖 ----
echo "[1/7] 安装 PostgreSQL + PostGIS + pgRouting + Python (apt, 国内源较快)..."
sudo apt-get update -qq
sudo apt-get install -y postgresql postgresql-contrib python3-venv python3-pip curl
PG_VER="$(ls /usr/lib/postgresql/ 2>/dev/null | sort -n | head -1)"
[ -n "$PG_VER" ] || { echo "[错误] 未检测到 PostgreSQL 版本"; exit 1; }
echo "      检测到 PostgreSQL 版本: $PG_VER"
sudo apt-get install -y "postgresql-$PG_VER-postgis-3" "postgresql-$PG_VER-pgrouting" \
  || sudo apt-get install -y postgresql-postgis postgresql-pgrouting

# ---- 2. 数据库配置 ----
DB_USER="${CLC_DB_USER:-postgres}"
DB_NAME="${CLC_DB_NAME:-city_life_circle}"
DB_PASS="${CLC_DB_PASSWORD:-}"
if [ -z "$DB_PASS" ]; then
  read -r -s -p "请输入数据库 postgres 用户的密码(部署后系统会用): " DB_PASS; echo ""
  [ -n "$DB_PASS" ] || { echo "[错误] 密码不能为空"; exit 1; }
fi

# ---- 3. 建库 + 恢复 ----
echo "[3/7] 设置数据库密码并恢复备份..."
sudo -u postgres psql -c "ALTER USER postgres PASSWORD '$DB_PASS';"
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
  sudo -u postgres createdb "$DB_NAME"
fi
# 先建扩展(服务器可用版本), 再恢复 —— 否则 dump 里的 CREATE EXTENSION 在缺扩展时恢复会失败
sudo -u postgres psql -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS pgrouting;" >/dev/null
# 恢复失败立即退出(不再静默吞掉, 避免"空库假成功")
sudo -u postgres pg_restore -d "$DB_NAME" --no-owner --no-privileges --clean --if-exists \
  "$PROJECT_DIR/deploy/data/city_life_circle.dump"
echo "      数据库恢复完成"

# ---- 4. 人口瓦片 ----
echo "[4/7] 复制人口瓦片到 cache/pop_tiles ..."
mkdir -p "$PROJECT_DIR/cache"
rm -rf "$PROJECT_DIR/cache/pop_tiles"
cp -r "$PROJECT_DIR/deploy/data/pop_tiles" "$PROJECT_DIR/cache/pop_tiles"

# ---- 5. PostgreSQL 低配调优 (2核4G游戏服共存) ----
echo "[5/7] PostgreSQL 低配调优..."
PG_CONF="/etc/postgresql/$PG_VER/main/postgresql.conf"
if [ -f "$PG_CONF" ]; then
  sudo sed -i -E \
    -e "s/^#?shared_buffers\s*=.*/shared_buffers = 256MB/" \
    -e "s/^#?effective_cache_size\s*=.*/effective_cache_size = 1GB/" \
    -e "s/^#?work_mem\s*=.*/work_mem = 32MB/" \
    -e "s/^#?maintenance_work_mem\s*=.*/maintenance_work_mem = 128MB/" \
    -e "s/^#?max_connections\s*=.*/max_connections = 50/" \
    "$PG_CONF" 2>/dev/null || true
  echo "      已写入低配参数到 $PG_CONF"
else
  echo "      [警告] 未找到 $PG_CONF, 跳过调优"
fi
sudo systemctl restart postgresql

# ---- 6. Python 后端 ----
echo "[6/7] 安装后端依赖 (清华 PyPI 源)..."
cd "$PROJECT_DIR/backend"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple -q
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo "      后端依赖安装完成"

# ---- 7. systemd 服务 ----
AMAP_KEY="${AMAP_KEY:-}"
if [ -z "$AMAP_KEY" ]; then
  read -r -p "请输入高德 Web 服务 key(可选, 回车跳过): " AMAP_KEY
fi
echo "[7/7] 注册并启动 systemd 服务..."
ENV_FILE="/etc/city-life-circle.env"
sudo tee "$ENV_FILE" >/dev/null <<EOF
CLC_DB_HOST=localhost
CLC_DB_PORT=5432
CLC_DB_NAME=$DB_NAME
CLC_DB_USER=$DB_USER
CLC_DB_PASSWORD=$DB_PASS
AMAP_KEY=$AMAP_KEY
EOF
sudo chmod 600 "$ENV_FILE"

sudo tee /etc/systemd/system/city-life-circle.service >/dev/null <<EOF
[Unit]
Description=City Life Circle Backend
After=network.target postgresql.service

[Service]
User=$(whoami)
WorkingDirectory=$PROJECT_DIR/backend
EnvironmentFile=$ENV_FILE
ExecStart=$PROJECT_DIR/backend/.venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now city-life-circle
sleep 4
sudo systemctl --no-pager --lines=12 status city-life-circle || true

echo ""
echo "=============================================================="
echo " 部署完成!"
echo " 访问地址: http://<服务器IP>:5000"
echo " 服务管理: sudo systemctl restart|stop|status city-life-circle"
echo " 查看日志: sudo journalctl -u city-life-circle -f"
echo " 一键卸载: sudo systemctl disable --now city-life-circle"
echo "          sudo -u postgres dropdb --if-exists $DB_NAME"
echo "          rm -rf $PROJECT_DIR"
echo "=============================================================="
