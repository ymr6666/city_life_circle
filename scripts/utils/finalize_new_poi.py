# -*- coding: utf-8 -*-
"""新增 POI 类别的增量后处理: GCJ-02 → WGS84 + 挂接路网

用途: 增量补充新爬取的类别 (如 bank/elderly_care/library/culture/post/government),
不触碰已有 POI (避免二次转换), 只处理指定类别。

步骤:
  1. 把指定类别的新行 GCJ 值备份到 hefei_poi_gcj_backup (只补缺失, 不覆盖旧备份)
  2. geometry / entr_location / exit_location GCJ → WGS84
  3. 增量挂接 poi_road_nodes (walk/drive, 仅插入缺失的 poi_id)

用法:
  python finalize_new_poi.py                     # 处理全部新类别
  python finalize_new_poi.py --only bank,library
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

# 新增类别挂接参数 (radius_m, max_nodes)
NEW_RADIUS_MAP = {
    'bank': (50, 2),
    'elderly_care': (50, 2),
    'library': (100, 3),
    'culture': (100, 3),
    'post': (50, 2),
    'government': (100, 3),
    'residential': (0, 1),   # 需求点: 仅转坐标, 配合 --no-snap 不挂接
}
BBOX = (117.07, 31.68, 117.50, 32.07)
DEFAULT_CATS = tuple(NEW_RADIUS_MAP.keys())


def parse_ll(s):
    try:
        lng, lat = s.split(',')
        return float(lng), float(lat)
    except (ValueError, AttributeError):
        return None


def convert_text_coord(s):
    ll = parse_ll(s)
    if not ll:
        return s
    wlng, wlat = gcj02_to_wgs84(ll[0], ll[1])
    return f"{wlng:.6f},{wlat:.6f}"


def main():
    args = sys.argv[1:]
    cats = DEFAULT_CATS
    if '--only' in args:
        cats = tuple(c.strip() for c in args[args.index('--only') + 1].split(',') if c.strip())
        unknown = [c for c in cats if c not in NEW_RADIUS_MAP]
        if unknown:
            print(f"未知类别: {unknown}, 可选: {list(NEW_RADIUS_MAP)}")
            return

    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()
    phs = ','.join(['%s'] * len(cats))

    print("=" * 60)
    print("Step 1: 备份新行 GCJ 值 -> hefei_poi_gcj_backup (仅补缺失)")
    print("=" * 60)
    cur.execute(f"""
        INSERT INTO hefei_poi_gcj_backup (id, geometry, entr_location, exit_location)
        SELECT p.id, p.geometry, p.entr_location, p.exit_location
        FROM hefei_poi p
        WHERE p.category IN ({phs})
          AND NOT EXISTS (SELECT 1 FROM hefei_poi_gcj_backup b WHERE b.id = p.id)
    """, cats)
    print(f"  备份新增 {cur.rowcount} 条")
    conn.commit()

    print("=" * 60)
    print("Step 2: 转换 geometry GCJ -> WGS84")
    print("=" * 60)
    cur.execute(f"SELECT id, ST_X(geometry), ST_Y(geometry) FROM hefei_poi WHERE category IN ({phs})", cats)
    rows = cur.fetchall()
    t0 = time.time()
    updates = [(gcj02_to_wgs84(lng, lat)[0], gcj02_to_wgs84(lng, lat)[1], pid) for pid, lng, lat in rows]
    execute_values(cur, """
        UPDATE hefei_poi SET geometry = ST_SetSRID(ST_MakePoint(data.lng, data.lat), 4326)
        FROM (VALUES %s) AS data (lng, lat, id)
        WHERE hefei_poi.id = data.id
    """, updates, page_size=2000)
    conn.commit()
    print(f"  转换 {len(updates)} 条几何 ({time.time()-t0:.1f}s)")

    print("=" * 60)
    print("Step 3: 转换 entr_location / exit_location")
    print("=" * 60)
    cur.execute(f"SELECT id, entr_location, exit_location FROM hefei_poi WHERE category IN ({phs})", cats)
    entr_u, exit_u = [], []
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
    print(f"  entr {len(entr_u)} 条, exit {len(exit_u)} 条")

    print("=" * 60)
    print("Step 4: 增量挂接 poi_road_nodes (walk/drive)")
    print("=" * 60)
    if '--no-snap' in args:
        print("  --no-snap 跳过挂接 (用于需求点类, 如 residential)")
    else:
        _snap(cur, conn, cats, phs)
    print("=" * 60)
    print("完成!")
    cur.close()
    conn.close()


def _snap(cur, conn, cats, phs):
    """walk/drive 增量挂接 (仅缺失的 poi_id)"""
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
        for cat, (radius, max_n) in NEW_RADIUS_MAP.items():
            if cat not in cats:
                continue
            bbox = f"p.geometry && ST_MakeEnvelope({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}, 4326)"
            cur.execute(f"""
                INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
                SELECT t.poi_id, t.node_id, '{mode}', t.distance_m
                FROM (
                    SELECT p.id AS poi_id, v.id AS node_id,
                           ST_Distance(({snap_sql})::geography, v.geometry::geography) AS distance_m,
                           ROW_NUMBER() OVER (PARTITION BY p.id ORDER BY ({snap_sql}) <-> v.geometry) AS rn
                    FROM hefei_poi p
                    CROSS JOIN LATERAL (
                        SELECT id, geometry FROM tmp_poi_vertices
                        ORDER BY ({snap_sql}) <-> geometry LIMIT {max_n * 3}
                    ) v
                    WHERE p.category = %s AND {bbox}
                      AND NOT EXISTS (SELECT 1 FROM poi_road_nodes prn
                                      WHERE prn.poi_id = p.id AND prn.mode = %s)
                ) t
                WHERE t.rn <= {max_n} AND t.distance_m <= {radius}
            """, (cat, mode))
            total += cur.rowcount
        # 兜底: 类别内仍未挂接 → 最近 1 节点
        cur.execute(f"""
            INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
            SELECT p.id, v.id, '{mode}',
                   ST_Distance(({snap_sql})::geography, v.geometry::geography)
            FROM hefei_poi p
            CROSS JOIN LATERAL (
                SELECT id, geometry FROM tmp_poi_vertices
                ORDER BY ({snap_sql}) <-> geometry LIMIT 1
            ) v
            WHERE p.category IN ({phs})
              AND p.geometry && ST_MakeEnvelope({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}, 4326)
              AND NOT EXISTS (SELECT 1 FROM poi_road_nodes prn
                              WHERE prn.poi_id = p.id AND prn.mode = %s)
        """, (*cats, mode))
        total += cur.rowcount
        conn.commit()
        cur.execute("SELECT count(DISTINCT poi_id) FROM poi_road_nodes WHERE mode=%s", (mode,))
        print(f"  [{mode}] 新增 {total} 条 | 全表去重 {cur.fetchone()[0]} POI")


if __name__ == "__main__":
    main()
