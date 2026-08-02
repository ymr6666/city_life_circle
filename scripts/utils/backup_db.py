# -*- coding: utf-8 -*-
"""数据库备份脚本

备份内容:
  1. PostgreSQL 数据库 city_life_circle (pg_dump 自定义格式)
  2. cache/ 原始抓取数据 (zip, roads_tags/bus_*.json 等)

用法:
  python backup_db.py             # 全量备份 (DB + cache)
  python backup_db.py --db-only   # 只备份数据库
  python backup_db.py --keep 5    # 只保留最近 5 份备份 (默认 5)

恢复:
  pg_restore -h localhost -p 5432 -U postgres -d city_life_circle --clean \
      backups/city_life_circle_YYYYMMDD_HHMMSS.dump
"""
import glob
import os
import shutil
import subprocess
import sys
import time
import zipfile

BACKUP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'backups')
CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'cache')

# 常见 pg_dump 安装路径
PG_DUMP_CANDIDATES = [
    r"D:\PostgreSQL\bin\pg_dump.exe",
    r"C:\Program Files\PostgreSQL\*\bin\pg_dump.exe",
    r"C:\PostgreSQL\*\bin\pg_dump.exe",
]

DB = {
    "host": "localhost",
    "port": 5432,
    "dbname": "city_life_circle",
    "user": "postgres",
    "password": "admin",
}


def find_pg_dump():
    p = shutil.which("pg_dump")
    if p:
        return p
    for c in PG_DUMP_CANDIDATES:
        m = glob.glob(c)
        if m:
            return m[0]
    raise FileNotFoundError("找不到 pg_dump, 请设置 PATH 或在 PG_DUMP_CANDIDATES 中配置路径")


def backup_db(pg_dump, stamp):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dump_file = os.path.join(BACKUP_DIR, f"city_life_circle_{stamp}.dump")
    env = dict(os.environ)
    env["PGPASSWORD"] = DB["password"]
    cmd = [pg_dump, "--format=custom",
           "--host", DB["host"], "--port", str(DB["port"]),
           "--username", DB["user"], "--dbname", DB["dbname"],
           "--file", dump_file]
    print("执行:", " ".join(cmd[:6]) + " ...")
    t0 = time.time()
    r = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        print("pg_dump 失败:\n", r.stderr)
        return None
    size = os.path.getsize(dump_file) / 1024 / 1024
    print(f"  DB 备份完成: {dump_file} ({size:.1f} MB, {time.time()-t0:.0f}s)")
    return dump_file


def backup_cache(stamp):
    if not os.path.isdir(CACHE_DIR):
        return None
    zip_file = os.path.join(BACKUP_DIR, f"cache_{stamp}.zip")
    t0 = time.time()
    with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(CACHE_DIR):
            for f in files:
                p = os.path.join(root, f)
                zf.write(p, os.path.relpath(p, CACHE_DIR))
    print(f"  cache 备份完成: {zip_file} ({os.path.getsize(zip_file)/1024/1024:.1f} MB, {time.time()-t0:.0f}s)")
    return zip_file


def prune(keep):
    """保留最近 keep 份 DB 备份 + 对应 cache 备份"""
    dumps = sorted(glob.glob(os.path.join(BACKUP_DIR, "city_life_circle_*.dump")),
                   key=os.path.getmtime, reverse=True)
    for f in dumps[keep:]:
        os.remove(f)
        print(f"  清理旧备份: {os.path.basename(f)}")
        zip_f = f.replace("city_life_circle_", "cache_").replace(".dump", ".zip")
        if os.path.exists(zip_f):
            os.remove(zip_f)
            print(f"  清理旧备份: {os.path.basename(zip_f)}")


def main():
    args = sys.argv[1:]
    keep = 5
    if "--keep" in args:
        keep = int(args[args.index("--keep") + 1])
    db_only = "--db-only" in args

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    print(f"备份目录: {BACKUP_DIR}")
    print(f"时间戳: {stamp}")

    pg_dump = find_pg_dump()
    if not db_only:
        backup_cache(stamp)
    backup_db(pg_dump, stamp)
    prune(keep)

    print("\n恢复命令:")
    print(f'  pg_restore -h localhost -p 5432 -U postgres -d city_life_circle --clean '
          f'"{os.path.join(BACKUP_DIR, f"city_life_circle_{stamp}.dump")}"')
    print("缓存恢复: 解压 cache_*.zip 到项目 cache/ 目录")


if __name__ == "__main__":
    main()
