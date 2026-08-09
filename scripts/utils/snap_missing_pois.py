# -*- coding: utf-8 -*-
"""补挂未挂接 POI + 住宅小区需求点挂接

背景:
  - poi_road_nodes 已覆盖路网 bbox (117.07-117.50, 31.68-32.07) 内全部设施 POI;
    未挂接的非住宅 POI 全部位于路网范围外 (肥东/肥西/长丰县域), 无路网可挂,
    本脚本仅对"落出路网扩展范围"做兜底最近节点挂接 (距离一般很大, 标记 skip)。
  - 住宅小区 (residential) 是**需求点**, 按项目约定**不进入 poi_road_nodes**
    (避免出现在设施统计/等时圈设施列表), 单独挂到 hefei_residential_nearest:
      每小区 → 最近 walk 顶点, 供供需比/选址/生活圈达标分析用。

表结构:
  hefei_residential_nearest (id serial, poi_id int FK hefei_poi, node_id int FK vertices,
                             distance_m double precision)
  索引: poi_id 唯一, node_id。

用法:
  python snap_missing_pois.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import psycopg2

# 路网实际覆盖范围 (hefei_roads ST_Extent, 比分析 bbox 略大)
ROAD_BBOX = (117.068, 31.679, 117.504, 32.074)


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()

    print("=" * 60)
    print("Step 1: 建 walk 顶点缓存 (walk_ok 道路端点)")
    print("=" * 60)
    cur.execute("""
        DROP TABLE IF EXISTS tmp_miss_vertices;
        CREATE TEMP TABLE tmp_miss_vertices AS
        SELECT DISTINCT v.id, v.geometry
        FROM hefei_roads_vertices_pgr v
        JOIN hefei_roads r ON r.source = v.id OR r.target = v.id
        WHERE r.walk_ok
    """)
    cur.execute("CREATE INDEX ON tmp_miss_vertices(id)")
    cur.execute("CREATE INDEX ON tmp_miss_vertices USING GIST(geometry)")
    cur.execute("SELECT count(*) FROM tmp_miss_vertices")
    print(f"  walk 顶点: {cur.fetchone()[0]} 个")

    print("=" * 60)
    print("Step 2: 建表 hefei_residential_nearest (住宅需求点)")
    print("=" * 60)
    cur.execute("DROP TABLE IF EXISTS hefei_residential_nearest")
    cur.execute("""
        CREATE TABLE hefei_residential_nearest (
            id BIGSERIAL PRIMARY KEY,
            poi_id INTEGER REFERENCES hefei_poi(id) ON DELETE CASCADE,
            node_id INTEGER REFERENCES hefei_roads_vertices_pgr(id),
            distance_m DOUBLE PRECISION
        )
    """)
    cur.execute("CREATE INDEX idx_hrn_poi ON hefei_residential_nearest(poi_id)")
    cur.execute("CREATE INDEX idx_hrn_node ON hefei_residential_nearest(node_id)")
    conn.commit()

    print("=" * 60)
    print("Step 3: 住宅小区 → 最近 walk 顶点 (需求点)")
    print("=" * 60)
    t0 = time.time()
    cur.execute("""
        INSERT INTO hefei_residential_nearest (poi_id, node_id, distance_m)
        SELECT p.id AS poi_id, v.id AS node_id,
               ST_Distance(p.geometry::geography, v.geometry::geography) AS distance_m
        FROM hefei_poi p
        CROSS JOIN LATERAL (
            SELECT id, geometry FROM tmp_miss_vertices
            ORDER BY p.geometry <-> geometry LIMIT 1
        ) v
        WHERE p.category = 'residential'
    """)
    residential_snapped = cur.rowcount
    conn.commit()
    print(f"  住宅小区挂接 {residential_snapped} 个 ({time.time()-t0:.1f}s)")

    print("=" * 60)
    print("Step 4: 未挂接设施 POI 兜底 (仅路网范围内可挂, 界外 skip)")
    print("=" * 60)
    # 先统计: 未挂接的非住宅 POI 中, 有多少落在路网范围内
    cur.execute("""
        SELECT count(*) FROM hefei_poi p
        LEFT JOIN poi_road_nodes w ON w.poi_id = p.id AND w.mode = 'walk'
        WHERE w.poi_id IS NULL AND p.category != 'residential'
          AND p.geometry && ST_MakeEnvelope(%s,%s,%s,%s,4326)
    """, ROAD_BBOX)
    in_road = cur.fetchone()[0]
    cur.execute("""
        SELECT count(*) FROM hefei_poi p
        LEFT JOIN poi_road_nodes w ON w.poi_id = p.id AND w.mode = 'walk'
        WHERE w.poi_id IS NULL AND p.category != 'residential'
    """)
    total_missing = cur.fetchone()[0]
    print(f"  未挂接非住宅 POI: {total_missing} (路网范围内 {in_road}, 界外 {total_missing - in_road})")

    if in_road:
        t0 = time.time()
        for mode, okcol in (('walk', 'walk_ok'), ('drive', 'drive_ok')):
            cur.execute(f"""
                DROP TABLE IF EXISTS tmp_miss_vertices;
                CREATE TEMP TABLE tmp_miss_vertices AS
                SELECT DISTINCT v.id, v.geometry
                FROM hefei_roads_vertices_pgr v
                JOIN hefei_roads r ON r.source = v.id OR r.target = v.id
                WHERE r.{okcol}
            """)
            cur.execute("CREATE INDEX ON tmp_miss_vertices(id)")
            cur.execute("CREATE INDEX ON tmp_miss_vertices USING GIST(geometry)")
            cur.execute(f"""
                INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
                SELECT p.id AS poi_id, v.id AS node_id, '{mode}',
                       ST_Distance(p.geometry::geography, v.geometry::geography) AS distance_m
                FROM hefei_poi p
                CROSS JOIN LATERAL (
                    SELECT id, geometry FROM tmp_miss_vertices
                    ORDER BY p.geometry <-> geometry LIMIT 1
                ) v
                WHERE p.category != 'residential'
                  AND p.geometry && ST_MakeEnvelope(%s,%s,%s,%s,4326)
                  AND NOT EXISTS (SELECT 1 FROM poi_road_nodes prn
                                  WHERE prn.poi_id = p.id AND prn.mode = %s)
            """, (*ROAD_BBOX, mode))
            conn.commit()
            print(f"  [{mode}] 补挂 {cur.rowcount} 条 ({time.time()-t0:.1f}s)")
    else:
        print("  路网范围内无未挂接设施 POI, 跳过")

    print("=" * 60)
    print("Step 5: 验证")
    print("=" * 60)
    cur.execute("SELECT count(*), count(DISTINCT poi_id) FROM hefei_residential_nearest")
    r = cur.fetchone()
    print(f"  hefei_residential_nearest: {r[0]} 条 / {r[1]} 小区")
    cur.execute("""
        SELECT round(min(distance_m)::numeric),
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY distance_m)::numeric),
               round(max(distance_m)::numeric)
        FROM hefei_residential_nearest
    """)
    mn, md, mx = cur.fetchone()
    print(f"  小区挂接距离: min={mn}m median={md}m max={mx}m")

    cur.execute("""
        SELECT mode, count(*), count(DISTINCT poi_id) FROM poi_road_nodes
        GROUP BY mode ORDER BY mode
    """)
    for r in cur.fetchall():
        print(f"  poi_road_nodes [{r[0]:5s}] {r[1]} 条 / {r[2]} POI")

    cur.close()
    conn.close()
    print("\n完成!")


if __name__ == "__main__":
    main()
