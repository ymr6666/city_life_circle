# -*- coding: utf-8 -*-
"""官方公交数据落库 + 有序站点序列生成

数据来源:
  cache/bus_stops_official.json   (5,530 站, 官方接口, WGS84)
  cache/bus_lines_official.json   (17,637 线路记录, 去重后 898 条)

有序站点序列算法 (替代高德 lineid):
  1. 取线路首站 f / 末站 l, 吸附到驾车路网节点
  2. pgr_dijkstra 求 f→l 的最短驾车路径 (drive_ok)
  3. 每条途经站投影到该路径上, 按沿路径里程(frac)排序
  4. route_pos_m = frac × 线路官方长度(UPLEN), 供引擎算相邻站乘车时间
  兜底: 首末站不匹配或路径失败时, 用 PCA 主轴投影排序

表结构 (与 crawl_bus.py 一致, 增加 route_pos_m):
  hefei_bus_stops       (id, stop_no, name, lng, lat, geometry)
  hefei_bus_lines       (id=LINECODE, name, start_stop, end_stop, distance_km, ...)
  hefei_bus_line_stops  (line_id, stop_id, sequence, route_pos_m)

用法:
  python load_official_bus.py --dry   # 只分析, 不落库
  python load_official_bus.py         # 落库
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import psycopg2

CACHE = os.path.join(os.path.dirname(__file__), '..', '..', 'cache')
STOP_FILE = os.path.join(CACHE, 'bus_stops_official.json')
LINE_FILE = os.path.join(CACHE, 'bus_lines_official.json')

SPEED_KMH = 20.0          # 与 config.BUS_SPEED_KMH 一致
SNAP_RADIUS_M = 500       # 首末站吸附半径
DRIVE_EDGE_SQL = ("SELECT id, source, target, cost, reverse_cost "
                  "FROM hefei_roads WHERE cost > 0 AND drive_ok")


# ── 数据读取 ────────────────────────────────────────────────
def load_official():
    stops = json.load(open(STOP_FILE, encoding="utf-8"))
    lines = json.load(open(LINE_FILE, encoding="utf-8"))

    # 线路去重: 每 LINECODE 取一条代表记录
    line_map = {}
    for r in lines:
        code = r.get("LINECODE")
        if not code:
            continue
        # 优先保留 状态=1 / 日期最新 的记录
        prev = line_map.get(code)
        if prev is None:
            line_map[code] = r
        else:
            if (r.get("LINESTATUS") == "1" and prev.get("LINESTATUS") != "1"):
                line_map[code] = r
            elif (r.get("STARTRUNDATE") or "").strip() and not (prev.get("STARTRUNDATE") or "").strip():
                line_map[code] = r
    return stops, line_map


def build_stop_index(stops):
    """STATIONNAME(strip) → [stop records]; STATIONID → stop record"""
    by_name = {}
    by_id = {}
    for s in stops:
        name = (s.get("STATIONNAME") or "").strip()
        by_name.setdefault(name, []).append(s)
        by_id[s.get("STATIONID")] = s
    return by_name, by_id


def stops_of_line(line_code, stops):
    """该线路途经站: STOPLINES 字段含 line_code 的站"""
    return [s for s in stops if line_code in ((s.get("STOPLINES") or "").split(","))]


# ── 路网路径投影 ────────────────────────────────────────────
def snap_to_node(cur, lng, lat):
    """吸附到最近 drive_ok 路网节点, 返回 (node_id, dist_m)"""
    cur.execute("""
        SELECT v.id, ST_Distance(ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, v.geometry::geography)::int
        FROM hefei_roads_vertices_pgr v
        WHERE EXISTS (SELECT 1 FROM hefei_roads r
                      WHERE (r.source=v.id OR r.target=v.id) AND r.drive_ok)
        ORDER BY ST_SetSRID(ST_MakePoint(%s,%s),4326) <-> v.geometry
        LIMIT 1
    """, (lng, lat, lng, lat))
    row = cur.fetchone()
    if row and row[1] <= SNAP_RADIUS_M:
        return row[0]
    return None


def road_path_wkt(cur, f_node, l_node):
    """f→l 最短驾车路径的合并 LineString WKT; 失败返回 None"""
    cur.execute("""
        WITH route AS (
            SELECT edge, node FROM pgr_dijkstra(%s, %s, %s, directed := false)
        )
        SELECT ST_AsText(ST_LineMerge(ST_Collect(r.geometry)))
        FROM route JOIN hefei_roads r ON r.id = route.edge
    """, (DRIVE_EDGE_SQL, f_node, l_node))
    row = cur.fetchone()
    if not row or not row[0]:
        return None
    return row[0]


def locate_frac(cur, path_wkt, lng, lat):
    """站点在路径上的投影比例 [0,1]; 失败返回 None"""
    cur.execute("""
        SELECT ST_LineLocatePoint(ST_GeomFromText(%s, 4326),
                                  ST_SetSRID(ST_MakePoint(%s,%s), 4326))
    """, (path_wkt, lng, lat))
    return cur.fetchone()[0]


# ── PCA 兜底排序 ────────────────────────────────────────────
def pca_order(points):
    """points: [(lng,lat),...] -> 沿主轴投影比例列表 [0,1]"""
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    # 协方差 (主轴方向)
    sxx = sum((p[0]-mx)**2 for p in points)
    syy = sum((p[1]-my)**2 for p in points)
    sxy = sum((p[0]-mx)*(p[1]-my) for p in points)
    import math
    theta = 0.5 * math.atan2(2*sxy, sxx - syy)
    # 沿主轴投影
    ex, ey = math.cos(theta), math.sin(theta)
    ts = [(p[0]-mx)*ex + (p[1]-my)*ey for p in points]
    tmin, tmax = min(ts), max(ts)
    span = (tmax - tmin) or 1.0
    return [(t - tmin) / span for t in ts]


# ── 主流程 ──────────────────────────────────────────────────
def main():
    dry = "--dry" in sys.argv
    stops, line_map = load_official()
    by_name, by_id = build_stop_index(stops)
    print(f"站点 {len(stops)} | 线路(去重) {len(line_map)}")

    if dry:
        print("\n[--dry] 只分析...")
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding("UTF8")
    cur = conn.cursor()

    # 建表
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
            sequence INTEGER,
            route_pos_m DOUBLE PRECISION,
            PRIMARY KEY (line_id, stop_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bls_line ON hefei_bus_line_stops(line_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bls_stop ON hefei_bus_line_stops(stop_id)")
    conn.commit()

    if not dry:
        cur.execute("TRUNCATE hefei_bus_stops, hefei_bus_lines, hefei_bus_line_stops RESTART IDENTITY CASCADE")
        # 1. 站点
        for s in sorted(stops, key=lambda x: x.get("STATIONID") or ""):
            lng, lat = float(s["LONGITUDE"]), float(s["LATITUDE"])
            cur.execute("""
                INSERT INTO hefei_bus_stops (id, name, lng, lat, geometry)
                VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s,%s), 4326))
            """, (s["STATIONID"], s["STATIONNAME"], lng, lat, lng, lat))
        conn.commit()
        print(f"  站点入库: {len(stops)}")

        # 2. 线路
        for code, r in line_map.items():
            name = r.get("LINENAME") or code
            cur.execute("""
                INSERT INTO hefei_bus_lines (id, name, type, start_stop, end_stop,
                    distance_km, company)
                VALUES (%s,%s,%s,%s,%s, %s,%s)
            """, (code, name, r.get("LEVELNAME"), r.get("FIRSTSTATION"),
                  r.get("LASTSTATION"), r.get("UPLEN"), r.get("ORGNAME")))
        conn.commit()
        print(f"  线路入库: {len(line_map)}")

    # 3. 有序站点 (dry 模式只统计成功率)
    stats = {"path": 0, "pca": 0, "skip": 0, "empty": 0}
    t0 = time.time()
    codes = sorted(line_map.keys())
    for i, code in enumerate(codes):
        r = line_map[code]
        line_stops = stops_of_line(code, stops)
        if len(line_stops) < 2:
            stats["skip"] += 1
            continue

        # 首末站匹配
        f_name = (r.get("FIRSTSTATION") or "").strip()
        l_name = (r.get("LASTSTATION") or "").strip()
        f_stop = by_name.get(f_name, [None])[0] if f_name else None
        l_stop = by_name.get(l_name, [None])[0] if l_name else None

        ordered = None
        route_pos = None
        if f_stop and l_stop:
            f_node = snap_to_node(cur, float(f_stop["LONGITUDE"]), float(f_stop["LATITUDE"]))
            l_node = snap_to_node(cur, float(l_stop["LONGITUDE"]), float(l_stop["LATITUDE"]))
            if f_node and l_node and f_node != l_node:
                path_wkt = road_path_wkt(cur, f_node, l_node)
                if path_wkt:
                    fr = []
                    for s in line_stops:
                        frac = locate_frac(cur, path_wkt, float(s["LONGITUDE"]), float(s["LATITUDE"]))
                        fr.append((frac, s))
                    ordered = [s for _, s in sorted(fr)]
                    route_pos = [frac for frac, _ in sorted(fr)]
                    stats["path"] += 1
        if ordered is None:
            # PCA 兜底
            pts = [(float(s["LONGITUDE"]), float(s["LATITUDE"])) for s in line_stops]
            fracs = pca_order(pts)
            ordered = [s for _, s in sorted(zip(fracs, line_stops))]
            route_pos = sorted(fracs)
            stats["pca"] += 1

        # 线路长度 (UPLEN km) → route_pos_m
        try:
            line_len_m = float(r.get("UPLEN") or 0) * 1000.0
        except (TypeError, ValueError):
            line_len_m = 0.0

        if not dry:
            seq = 1
            for frac, s in zip(route_pos, ordered):
                pos_m = round(frac * line_len_m, 1) if line_len_m > 0 else None
                cur.execute("""
                    INSERT INTO hefei_bus_line_stops (line_id, stop_id, sequence, route_pos_m)
                    VALUES (%s, %s, %s, %s)
                """, (code, s["STATIONID"], seq, pos_m))
                seq += 1
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(codes)}  ({time.time()-t0:.0f}s)")
            if not dry:
                conn.commit()
    if not dry:
        conn.commit()
        print("  line_stops 入库完成")

    print(f"\n  排序结果: 路网路径 {stats['path']} | PCA 兜底 {stats['pca']} | "
          f"跳过(<2站) {stats['skip']} | 耗时 {time.time()-t0:.0f}s")

    if not dry:
        cur.execute("SELECT count(*) FROM hefei_bus_stops")
        print(f"\n  hefei_bus_stops: {cur.fetchone()[0]}")
        cur.execute("SELECT count(*) FROM hefei_bus_lines")
        print(f"  hefei_bus_lines: {cur.fetchone()[0]}")
        cur.execute("SELECT count(*), count(DISTINCT line_id) FROM hefei_bus_line_stops")
        r = cur.fetchone()
        print(f"  hefei_bus_line_stops: {r[0]} 条, 覆盖 {r[1]} 线路")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
