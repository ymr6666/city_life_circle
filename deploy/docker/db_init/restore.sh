# 数据库首次初始化脚本: 启用扩展 + 恢复全量备份
# 仅当数据卷为空时由 postgres 官方 entrypoint 自动执行 (幂等, 重启不影响)
#!/bin/bash
set -e

echo "[db_init] 启用扩展 postgis / pgrouting ..."
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;
SQL

echo "[db_init] 恢复 city_life_circle.dump ..."
pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --no-owner --no-privileges /docker-entrypoint-initdb.d/city_life_circle.dump

echo "[db_init] 完成"
