# -*- coding: utf-8 -*-
"""高德 POI 坐标 GCJ-02 → WGS84 转换工具

背景: hefei_poi 由高德 POI 爬虫导入, geometry / entr_location / exit_location
      均为 GCJ-02 (火星坐标), 而路网/地铁/公交为 WGS84 (偏移 ~570m),
      导致 POI 挂接路网误差大 (挂接中位数 ~100m, 最远数公里)。

本工具:
  1. 备份原始 GCJ 值到 hefei_poi_gcj_backup (可回滚)
  2. 将 geometry / entr_location / exit_location 转换为 WGS84
  3. 用 walk_ok/drive_ok 重建 poi_road_nodes (替换旧的 highway 白名单方式)

用法:
  python convert_poi_coords.py           # 转换 + 重建挂接
  python convert_poi_coords.py --no-resnap

回滚 (如转错):
  UPDATE hefei_poi p SET geometry = b.geometry,
      entr_location = b.entr_location, exit_location = b.exit_location
  FROM hefei_poi_gcj_backup b WHERE p.id = b.id;
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
from config import DB_CONFIG
from engine.coord_utils import gcj02_to_wgs84

import psycopg2
from psycopg2.extras import execute_values

# 与 snap_poi_v2 一致的挂接参数 (radius_m, max_nodes)
RADIUS_MAP = {
    'hospital': (150, 5), 'school_college': (150, 5), 'park': (150, 5),
    'mall': (100, 3), 'school_primary': (80, 3), 'school_junior': (80, 3),
    'school_senior': (80, 3), 'supermarket': (50, 2), 'market_food': (50, 2),
    'kindergarten': (50, 2), 'street_commercial': (30, 1),
    'street_pedestrian': (30, 1),
    'pharmacy': (50, 2),   # 药店: 临街店面
    'sports': (150, 5),    # 运动场馆: 多入口
}
BBOX = (117.07, 31.68, 117.50, 32.07)


def parse_ll(s):
    try:
        lng, lat = s.split(',')
        return float(lng), float(lat)
    except (ValueError, AttributeError):
        return None


def convert_text_coord(s):
    """entr_location/exit_location: "lng,lat" GCJ → "lng,lat" WGS"""
    ll = parse_ll(s)
    if not ll:
        return s
    wlng, wlat = gcj02_to_wgs84(ll[0], ll[1])
    return f"{wlng:.6f},{wlat:.6f}"


def main():
    resnap = '--no-resnap' not in sys.argv
    resnap_only = '--resnap-only' in sys.argv
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()

    if not resnap_only:
        print("=" * 60)
        print("Step 1: 备份原始 GCJ 值 -> hefei_poi_gcj_backup")
        print("=" * 60)
        cur.execute("DROP TABLE IF EXISTS hefei_poi_gcj_backup")
        cur.execute("""
            CREATE TABLE hefei_poi_gcj_backup AS
            SELECT id, geometry, entr_location, exit_location FROM hefei_poi
        """)
        cur.execute("SELECT count(*) FROM hefei_poi_gcj_backup")
        print(f"  已备份 {cur.fetchone()[0]} 条")
        conn.commit()

        print("=" * 60)
        print("Step 2: 转换 geometry GCJ -> WGS84")
        print("=" * 60)
        cur.execute("SELECT id, ST_X(geometry), ST_Y(geometry) FROM hefei_poi")
        rows = cur.fetchall()
        t0 = time.time()
        geoupdates = []
        for pid, lng, lat in rows:
            wlng, wlat = gcj02_to_wgs84(lng, lat)
            geoupdates.append((wlng, wlat, pid))
        execute_values(cur, """
            UPDATE hefei_poi SET geometry = ST_SetSRID(ST_MakePoint(data.lng, data.lat), 4326)
            FROM (VALUES %s) AS data (lng, lat, id)
            WHERE hefei_poi.id = data.id
        """, geoupdates, page_size=2000)
        conn.commit()
        print(f"  转换 {len(geoupdates)} 条几何 ({time.time()-t0:.1f}s)")

        print("=" * 60)
        print("Step 3: 转换 entr_location / exit_location")
        print("=" * 60)
        cur.execute("SELECT id, entr_location, exit_location FROM hefei_poi")
        entr_u = []
        exit_u = []
        for pid, entr, exit_ in cur.fetchall():
            if entr:
                entr_u.append((convert_text_coord(entr), pid))
            if exit_:
                exit_u.append((convert_text_coord(exit_), pid))
        if entr_u:
            execute_values(cur, """
                UPDATE hefei_poi SET entr_location = data.v
                FROM (VALUES %s) AS data (v, id) WHERE hefei_poi.id = data.id
            """, entr_u, page_size=2000)
        if exit_u:
            execute_values(cur, """
                UPDATE hefei_poi SET exit_location = data.v
                FROM (VALUES %s) AS data (v, id) WHERE hefei_poi.id = data.id
            """, exit_u, page_size=2000)
        conn.commit()
        print(f"  entr_location {len(entr_u)} 条, exit_location {len(exit_u)} 条")

    if resnap:
        print("=" * 60)
        print("Step 4: 重建 poi_road_nodes (walk_ok / drive_ok)")
        print("=" * 60)
        rebuild_snap(cur, conn)

    print("=" * 60)
    print("Step 5: 验证 (转换后 POI 到最近可走路网的距离)")
    print("=" * 60)
    cur.execute("""
        SELECT min(d)::int, percentile_cont(0.5) WITHIN GROUP (ORDER BY d)::int,
               max(d)::int
        FROM (
            SELECT p.id, ST_Distance(p.geometry::geography, r.geometry::geography) AS d
            FROM hefei_poi p
            CROSS JOIN LATERAL (
                SELECT geometry FROM hefei_roads
                WHERE walk_ok AND geometry && p.geometry
                ORDER BY p.geometry <-> geometry LIMIT 1
            ) r
        ) t
    """)
    r = cur.fetchone()
    print(f"  POI→最近可走路: min={r[0]}m median={r[1]}m max={r[2]}m")
    print("\n  回滚命令: 见脚本 docstring")

    cur.close()
    conn.close()
    print("Done!")


def rebuild_snap(cur, conn):
    """重建 poi_road_nodes: walk/drive 两种模式, entry 优先, 医院 canonical"""
    cur.execute("DROP TABLE IF EXISTS poi_road_nodes")
    cur.execute("""
        CREATE TABLE poi_road_nodes (
            id SERIAL PRIMARY KEY,
            poi_id INTEGER REFERENCES hefei_poi(id) ON DELETE CASCADE,
            node_id INTEGER REFERENCES hefei_roads_vertices_pgr(id),
            mode TEXT,
            distance_m DOUBLE PRECISION
        )
    """)
    cur.execute("CREATE INDEX idx_prn_poi ON poi_road_nodes(poi_id)")
    cur.execute("CREATE INDEX idx_prn_node ON poi_road_nodes(node_id)")
    cur.execute("CREATE INDEX idx_prn_mode ON poi_road_nodes(mode)")
    conn.commit()

    # 顶点缓存 (walk_ok / drive_ok)
    for mode, okcol in (('walk', 'walk_ok'), ('drive', 'drive_ok')):
        cur.execute(f"""
            DROP TABLE IF EXISTS tmp_poi_vertices;
            CREATE TEMP TABLE tmp_poi_vertices AS
            SELECT DISTINCT v.id, v.geometry
            FROM hefei_roads_vertices_pgr v
            JOIN hefei_roads r ON r.source = v.id OR r.target = v.id
            WHERE r.{okcol}
        """)
        cur.execute("CREATE INDEX ON tmp_poi_vertices(id)")
        cur.execute("CREATE INDEX ON tmp_poi_vertices USING GIST(geometry)")
        cur.execute("SELECT count(*) FROM tmp_poi_vertices")
        n = cur.fetchone()[0]

        snap_sql = """
            CASE WHEN p.entr_location IS NOT NULL AND p.entr_location != ''
                      AND position(',' in p.entr_location) > 0
                 THEN ST_SetSRID(ST_MakePoint(
                      split_part(p.entr_location, ',', 1)::float,
                      split_part(p.entr_location, ',', 2)::float), 4326)
                 ELSE p.geometry
            END
        """
        total = 0
        for cat, (radius, max_n) in RADIUS_MAP.items():
            bbox = f"p.geometry && ST_MakeEnvelope({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}, 4326)"
            # 所有 POI (含医院科室/楼宇) 独立挂接, 不做 canonical 复制:
            # 引擎粒度按"可达哪个楼宇/入口"保留, 展示去重由 facility_id 负责
            catf = f"p.category='{cat}' AND {bbox}"
            cur.execute(f"""
                INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
                SELECT t.poi_id, t.node_id, '{mode}', t.distance_m
                FROM (
                    SELECT p.id AS poi_id, v.id AS node_id,
                           ST_Distance(({snap_sql})::geography, v.geometry::geography) AS distance_m,
                           ROW_NUMBER() OVER (
                               PARTITION BY p.id ORDER BY ({snap_sql}) <-> v.geometry
                           ) AS rn
                    FROM hefei_poi p
                    CROSS JOIN LATERAL (
                        SELECT id, geometry FROM tmp_poi_vertices
                        ORDER BY ({snap_sql}) <-> geometry LIMIT {max_n * 3}
                    ) v
                    WHERE {catf}
                ) t
                WHERE t.rn <= {max_n} AND t.distance_m <= {radius}
            """)
            total += cur.rowcount
        # 兜底: 未挂接 POI → 最近 1 节点
        cur.execute(f"""
            INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
            SELECT p.id, v.id, '{mode}',
                   ST_Distance(({snap_sql})::geography, v.geometry::geography)
            FROM hefei_poi p
            CROSS JOIN LATERAL (
                SELECT id, geometry FROM tmp_poi_vertices
                ORDER BY ({snap_sql}) <-> geometry LIMIT 1
            ) v
            WHERE p.id NOT IN (SELECT DISTINCT poi_id FROM poi_road_nodes WHERE mode = %s)
              AND p.geometry && ST_MakeEnvelope({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}, 4326)
        """, (mode,))
        conn.commit()
        cur.execute("SELECT count(*), count(DISTINCT poi_id) FROM poi_road_nodes WHERE mode=%s", (mode,))
        r = cur.fetchone()
        print(f"  [{mode}] 顶点 {n} 个 | 挂接 {r[0]} 条 / {r[1]} POI")


if __name__ == "__main__":
    main()
