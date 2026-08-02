# -*- coding: utf-8 -*-
"""8684 公交数据落库 (有序站点序列 + 官方 WGS84 坐标合并)

数据来源:
  cache/bus_8684_lines.json    8684 抓取的线路详情 (去程/回程有序站点)
  cache/bus_stops_official.json  官方接口站点 (5,530, WGS84)
  cache/bus_lines_official.json  官方接口线路元数据

方法:
  1. 官方站点 → hefei_bus_stops
  2. 8684 线路(有站序) + 官方元数据 → hefei_bus_lines
  3. 8684 站名 → 官方站 ID (去括号精确 + difflib 模糊兜底)
  4. 按方向写 hefei_bus_line_stops (sequence + route_pos_m 沿程里程)

用法: python load_8684_bus.py
"""
import json
import math
import os
import re
import sys
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import psycopg2

CACHE = os.path.join(os.path.dirname(__file__), '..', '..', 'cache')
LINES_8684 = os.path.join(CACHE, 'bus_8684_lines.json')
STOP_OFFICIAL = os.path.join(CACHE, 'bus_stops_official.json')
LINE_OFFICIAL = os.path.join(CACHE, 'bus_lines_official.json')

FUZZY_THRESHOLD = 0.85


def norm_name(name):
    return re.sub(r"(路|线)$", "", (name or "").strip())


def strip_paren(name):
    return re.sub(r"[（(].*?[)）]", "", name).strip()


def norm_8684(name):
    """8684 站名 → 核心: 去括号, 取'·'前部分"""
    n = strip_paren(name)
    if "·" in n:
        n = n.split("·")[0].strip()
    return n


def haversine(lng1, lat1, lng2, lat2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def main():
    lines_8684 = json.load(open(LINES_8684, encoding="utf-8"))
    stops_off = json.load(open(STOP_OFFICIAL, encoding="utf-8"))
    lines_off = json.load(open(LINE_OFFICIAL, encoding="utf-8"))

    # 官方站点索引
    off_full = {}    # 全名 -> stop
    off_core = {}    # 去括号核心 -> stop
    for s in stops_off:
        name = (s.get("STATIONNAME") or "").strip()
        off_full.setdefault(name, s)
        core = strip_paren(name)
        off_core.setdefault(core, s)
    off_cores = list(off_core.keys())

    # 官方线路元数据
    off_line_meta = {}
    for r in lines_off:
        off_line_meta.setdefault(r["LINECODE"], r)

    # 有效线路: 有去/回程站序
    valid = {h: d for h, d in lines_8684.items() if d.get("up") or d.get("down")}
    print(f"8684 有站序线路: {len(valid)}")

    def match(stop_name):
        """8684 站名 → 官方 stop (dict), 无则 None"""
        if stop_name in off_full:
            return off_full[stop_name]
        core = norm_8684(stop_name)
        if core in off_core:
            return off_core[core]
        best, best_r = None, 0.0
        for c in off_cores:
            r = SequenceMatcher(None, core, c).ratio()
            if r > best_r:
                best_r, best = r, c
        if best and best_r >= FUZZY_THRESHOLD:
            return off_core[best]
        return None

    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding("UTF8")
    cur = conn.cursor()

    # ── 建表 ──
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hefei_bus_stops (
            id TEXT PRIMARY KEY,
            stop_no BIGSERIAL UNIQUE,
            name TEXT, adcode TEXT,
            lng DOUBLE PRECISION, lat DOUBLE PRECISION,
            geometry GEOMETRY(Point, 4326)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hefei_bus_lines (
            id TEXT PRIMARY KEY,
            name TEXT, type TEXT,
            start_stop TEXT, end_stop TEXT,
            distance_km DOUBLE PRECISION,
            start_time TEXT, end_time TEXT,
            direc_id TEXT, loop_flag BOOLEAN, company TEXT,
            geometry GEOMETRY(LineString, 4326)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hefei_bus_line_stops (
            line_id TEXT REFERENCES hefei_bus_lines(id) ON DELETE CASCADE,
            stop_id TEXT REFERENCES hefei_bus_stops(id) ON DELETE CASCADE,
            direction TEXT,
            sequence INTEGER,
            route_pos_m DOUBLE PRECISION,
            PRIMARY KEY (line_id, stop_id, direction)
        )
    """)
    cur.execute("ALTER TABLE hefei_bus_line_stops ADD COLUMN IF NOT EXISTS direction TEXT")
    # 旧表 PK 是 (line_id, stop_id), 同一站上下行都会出现 → 换成含 direction 的复合 PK
    cur.execute("ALTER TABLE hefei_bus_line_stops DROP CONSTRAINT IF EXISTS hefei_bus_line_stops_pkey")
    cur.execute("""
        SELECT 1 FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = 'hefei_bus_line_stops' AND c.conname = 'hefei_bus_line_stops_pkey2'
    """)
    if not cur.fetchone():
        cur.execute("ALTER TABLE hefei_bus_line_stops ADD CONSTRAINT hefei_bus_line_stops_pkey2 "
                    "PRIMARY KEY (line_id, stop_id, direction)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bls_line ON hefei_bus_line_stops(line_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bls_stop ON hefei_bus_line_stops(stop_id)")
    conn.commit()

    cur.execute("TRUNCATE hefei_bus_stops, hefei_bus_lines, hefei_bus_line_stops RESTART IDENTITY CASCADE")

    # ── 1. 站点 ──
    for s in sorted(stops_off, key=lambda x: x.get("STATIONID") or ""):
        lng, lat = float(s["LONGITUDE"]), float(s["LATITUDE"])
        cur.execute("""
            INSERT INTO hefei_bus_stops (id, name, lng, lat, geometry)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s,%s), 4326))
        """, (s["STATIONID"], s["STATIONNAME"], lng, lat, lng, lat))
    conn.commit()
    print(f"  hefei_bus_stops: {len(stops_off)}")

    # ── 2. 线路 + 3. 站序 ──
    stats = {"exact": 0, "core": 0, "fuzzy": 0, "miss": 0}
    n_lines = n_pairs = 0
    for h, d in sorted(valid.items()):
        code = d.get("code") or norm_name(d.get("name")) or h
        meta = off_line_meta.get(code, {})
        cur.execute("""
            INSERT INTO hefei_bus_lines (id, name, type, start_stop, end_stop,
                distance_km, company)
            VALUES (%s,%s,%s,%s,%s, %s,%s)
        """, (code, d.get("name"), meta.get("LEVELNAME"),
              meta.get("FIRSTSTATION"), meta.get("LASTSTATION"),
              meta.get("UPLEN"), meta.get("ORGNAME")))
        n_lines += 1

        for direction, stops in (("up", d.get("up", [])), ("down", d.get("down", []))):
            # 匹配站序
            matched = []   # (stop_id, lng, lat)
            for name in stops:
                s = match(name)
                if s:
                    matched.append((s["STATIONID"], float(s["LONGITUDE"]), float(s["LATITUDE"])))
                    how = "exact" if name in off_full else "core" if norm_8684(name) in off_core else "fuzzy"
                    stats[how] += 1
                else:
                    stats["miss"] += 1
            if len(matched) < 2:
                continue
            # 沿程里程 (同一方向内重复站只保留首次, 避免环线/折返重复)
            pos = 0.0
            seq = 0
            prev = matched[0]
            seen = {prev[0]}
            for stop_id, lng, lat in matched:
                if stop_id in seen:
                    continue
                seen.add(stop_id)
                if seq > 0:
                    pos += haversine(prev[1], prev[2], lng, lat)
                cur.execute("""
                    INSERT INTO hefei_bus_line_stops (line_id, stop_id, direction, sequence, route_pos_m)
                    VALUES (%s, %s, %s, %s, %s)
                """, (code, stop_id, direction, seq, round(pos, 1)))
                n_pairs += 1
                seq += 1
                prev = (stop_id, lng, lat)

    conn.commit()
    print(f"  hefei_bus_lines: {n_lines}")
    print(f"  hefei_bus_line_stops: {n_pairs}")
    print(f"  站名匹配: 精确 {stats['exact']} | 去括号 {stats['core']} | 模糊 {stats['fuzzy']} | 未匹配 {stats['miss']}")
    total = sum(stats.values())
    print(f"  匹配率: {(stats['exact']+stats['core']+stats['fuzzy'])/total*100:.1f}%" if total else "n/a")

    # ── 验证 ──
    cur.execute("SELECT count(*) FROM hefei_bus_stops")
    print(f"\n  hefei_bus_stops: {cur.fetchone()[0]}")
    cur.execute("SELECT count(*) FROM hefei_bus_lines")
    print(f"  hefei_bus_lines: {cur.fetchone()[0]}")
    cur.execute("SELECT count(*), count(DISTINCT line_id) FROM hefei_bus_line_stops")
    r = cur.fetchone()
    print(f"  hefei_bus_line_stops: {r[0]} 条, 覆盖 {r[1]} 线路")
    cur.execute("SELECT count(DISTINCT stop_id) FROM hefei_bus_line_stops")
    print(f"  有站序的站点数: {cur.fetchone()[0]}")

    cur.close()
    conn.close()
    print("Done!")


if __name__ == "__main__":
    main()
