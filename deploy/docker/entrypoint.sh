#!/bin/sh
# 后端容器入口: 等待数据库恢复完成(hefei_roads 有数据)后再启动服务
# 解决 db 容器 initdb 恢复 dump 期间 app 提前启动导致连接失败的问题
set -e

echo "[entrypoint] waiting for database restore ..."
python - <<'PY'
import time, os, psycopg2

cfg = dict(
    host=os.environ['CLC_DB_HOST'],
    port=int(os.environ.get('CLC_DB_PORT', '5432')),
    dbname=os.environ['CLC_DB_NAME'],
    user=os.environ['CLC_DB_USER'],
    password=os.environ.get('CLC_DB_PASSWORD', ''),
)

for i in range(120):
    try:
        conn = psycopg2.connect(**cfg)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM hefei_roads")
        n = int(cur.fetchone()[0])
        conn.close()
        if n and n > 1000:
            print(f"[entrypoint] database ready ({n} road segments)")
            break
    except Exception:
        pass
    time.sleep(2)
else:
    print("[entrypoint] WARNING: database not ready after 240s, starting anyway")
PY

echo "[entrypoint] starting app ..."
exec python app.py
