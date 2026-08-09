# -*- coding: utf-8 -*-
"""人口栅格 → 路网节点挂接 (hefei_pop_nearest)

背景: 服务覆盖/盲区/供需比分析需要"人口格点 ↔ 可达节点集"的快速关联。
若每次都对 17 万个格点跑 Dijkstra 不现实; 方案是只把每个格点挂到最近
的步行路网节点 (hefei_pop_nearest), 覆盖判定变为:
  设施反向 Dijkstra → 可达节点集 → JOIN hefei_pop_nearest → 覆盖人口。

设计 (紧凑, 控制存储):
  - 每格点只存最近 1 个 walk 顶点 (KNN, LIMIT 1), 约 17 万行;
  - 距离一并记录, 超远格点 (路网边缘外) 也能挂上, 但覆盖分析可
    按距离阈值 (如 1500m) 过滤, 避免边缘误差。

表结构:
  hefei_pop_nearest (id serial, pop_id bigint FK hefei_pop_grid, node_id int FK vertices,
                     distance_m double precision)
  索引: pop_id 唯一, node_id。

用法:
  python snap_pop_grid.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import psycopg2


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()

    print("=" * 60)
    print("Step 1: 建 walk 顶点缓存 (walk_ok 道路端点)")
    print("=" * 60)
    cur.execute("""
        DROP TABLE IF EXISTS tmp_pop_vertices;
        CREATE TEMP TABLE tmp_pop_vertices AS
        SELECT DISTINCT v.id, v.geometry
        FROM hefei_roads_vertices_pgr v
        JOIN hefei_roads r ON r.source = v.id OR r.target = v.id
        WHERE r.walk_ok
    """)
    cur.execute("CREATE INDEX ON tmp_pop_vertices(id)")
    cur.execute("CREATE INDEX ON tmp_pop_vertices USING GIST(geometry)")
    cur.execute("SELECT count(*) FROM tmp_pop_vertices")
    print(f"  walk 顶点: {cur.fetchone()[0]} 个")

    print("=" * 60)
    print("Step 2: 建表 hefei_pop_nearest")
    print("=" * 60)
    cur.execute("DROP TABLE IF EXISTS hefei_pop_nearest")
    cur.execute("""
        CREATE TABLE hefei_pop_nearest (
            id BIGSERIAL PRIMARY KEY,
            pop_id BIGINT REFERENCES hefei_pop_grid(id) ON DELETE CASCADE,
            node_id INTEGER REFERENCES hefei_roads_vertices_pgr(id),
            distance_m DOUBLE PRECISION
        )
    """)
    cur.execute("CREATE INDEX idx_hpn_pop ON hefei_pop_nearest(pop_id)")
    cur.execute("CREATE INDEX idx_hpn_node ON hefei_pop_nearest(node_id)")
    conn.commit()

    print("=" * 60)
    print("Step 3: KNN 挂接 (每格点 → 最近 walk 顶点)")
    print("=" * 60)
    t0 = time.time()
    cur.execute("""
        INSERT INTO hefei_pop_nearest (pop_id, node_id, distance_m)
        SELECT p.id AS pop_id, v.id AS node_id,
               ST_Distance(p.geometry::geography, v.geometry::geography) AS distance_m
        FROM hefei_pop_grid p
        CROSS JOIN LATERAL (
            SELECT id, geometry FROM tmp_pop_vertices
            ORDER BY p.geometry <-> geometry LIMIT 1
        ) v
    """)
    inserted = cur.rowcount
    conn.commit()
    print(f"  挂接 {inserted} 个格点 ({time.time()-t0:.1f}s)")

    print("=" * 60)
    print("Step 4: 验证")
    print("=" * 60)
    cur.execute("SELECT count(*) FROM hefei_pop_grid")
    total = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM hefei_pop_nearest")
    snapped = cur.fetchone()[0]
    print(f"  人口格点: {total} | 已挂接: {snapped} | 覆盖率 {100*snapped//total}%")

    # 挂接距离分布
    cur.execute("""
        SELECT round(min(distance_m)::numeric), 
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY distance_m)::numeric),
               round(percentile_cont(0.9) WITHIN GROUP (ORDER BY distance_m)::numeric),
               round(max(distance_m)::numeric)
        FROM hefei_pop_nearest
    """)
    mn, md, p90, mx = cur.fetchone()
    print(f"  挂接距离: min={mn}m median={md}m p90={p90}m max={mx}m")

    # 各节点覆盖人口 top10 (供抽查)
    cur.execute("""
        SELECT n.node_id, SUM(g.population) AS pop, count(*)
        FROM hefei_pop_nearest n
        JOIN hefei_pop_grid g ON g.id = n.pop_id
        GROUP BY n.node_id ORDER BY pop DESC LIMIT 5
    """)
    print("\n  人口最多的 5 个挂接节点:")
    for r in cur.fetchall():
        print(f"    node={r[0]} 人口={r[1]} 格点数={r[2]}")

    cur.close()
    conn.close()
    print("\n完成!")


if __name__ == "__main__":
    main()
