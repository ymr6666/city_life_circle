# -*- coding: utf-8 -*-
"""公交站吸附到步行可用路网节点 → bus_stop_road_nodes

创建 bus_stop_road_nodes(stop_no, node_id, distance_m), 供 TransitLayer 的
公交换乘边使用 (公交站节点 ↔ 路网节点 0 成本连接)。

数据依赖: hefei_bus_stops 已由 `python crawl_bus.py --load` 落库
          (stop_no 为整数节点编号, 坐标为 WGS84)

用法: python snap_bus_stops.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import psycopg2

RADIUS_M = 300      # 吸附半径 (与地铁站一致)
MAX_NODES = 3       # 每站最多挂接节点数
BBOX = (117.07, 31.68, 117.50, 32.07)


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding("UTF8")
    cur = conn.cursor()

    print("Step 1: 建步行顶点缓存 (walk_ok)")
    cur.execute("""
        DROP TABLE IF EXISTS tmp_walk_vertices_bus;
        CREATE TEMP TABLE tmp_walk_vertices_bus AS
        SELECT DISTINCT v.id, v.geometry
        FROM hefei_roads_vertices_pgr v
        JOIN hefei_roads r ON r.source = v.id OR r.target = v.id
        WHERE r.walk_ok
    """)
    cur.execute("CREATE INDEX ON tmp_walk_vertices_bus(id)")
    cur.execute("CREATE INDEX ON tmp_walk_vertices_bus USING GIST(geometry)")
    cur.execute("SELECT count(*) FROM tmp_walk_vertices_bus")
    print(f"  步行顶点: {cur.fetchone()[0]}")
    conn.commit()

    print("Step 2: 建 bus_stop_road_nodes 表")
    cur.execute("DROP TABLE IF EXISTS bus_stop_road_nodes CASCADE")
    cur.execute("""
        CREATE TABLE bus_stop_road_nodes (
            id SERIAL PRIMARY KEY,
            stop_no BIGINT REFERENCES hefei_bus_stops(stop_no) ON DELETE CASCADE,
            node_id INTEGER REFERENCES hefei_roads_vertices_pgr(id),
            distance_m DOUBLE PRECISION
        );
        CREATE INDEX idx_bsrn_stop ON bus_stop_road_nodes(stop_no);
        CREATE INDEX idx_bsrn_node ON bus_stop_road_nodes(node_id);
    """)
    conn.commit()

    print("Step 3: 吸附 (半径 %dm, 每站 %d 节点)" % (RADIUS_M, MAX_NODES))
    cur.execute(f"""
        INSERT INTO bus_stop_road_nodes (stop_no, node_id, distance_m)
        SELECT s.stop_no, v.id,
               ST_Distance(s.geometry::geography, v.geometry::geography)
        FROM hefei_bus_stops s
        CROSS JOIN LATERAL (
            SELECT id, geometry FROM tmp_walk_vertices_bus
            WHERE ST_DWithin(geometry::geography, s.geometry::geography, {RADIUS_M})
            ORDER BY s.geometry <-> geometry LIMIT {MAX_NODES}
        ) v
        WHERE s.geometry && ST_MakeEnvelope({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}, 4326)
    """)
    n = cur.rowcount
    conn.commit()
    print(f"  挂接: {n} 条")

    print("Step 4: 验证")
    cur.execute("SELECT count(*), count(DISTINCT stop_no) FROM bus_stop_road_nodes")
    r = cur.fetchone()
    print(f"  覆盖: {r[1]}/{r[0]} (记录/站点)")
    cur.execute("""
        SELECT min(distance_m)::int, percentile_cont(0.5) WITHIN GROUP (ORDER BY distance_m)::int,
               max(distance_m)::int
        FROM bus_stop_road_nodes
    """)
    r = cur.fetchone()
    print(f"  距离: min={r[0]}m median={r[1]}m max={r[2]}m")

    cur.execute("SELECT count(*) FROM hefei_bus_stops")
    total = cur.fetchone()[0]
    cur.execute("SELECT count(DISTINCT stop_no) FROM bus_stop_road_nodes")
    covered = cur.fetchone()[0]
    print(f"\n  公交站覆盖: {covered}/{total} ({100*covered//total if total else 0}%)")

    cur.execute("DROP TABLE IF EXISTS tmp_walk_vertices_bus")
    conn.commit()
    cur.close()
    conn.close()
    print("Done!")


if __name__ == "__main__":
    main()
