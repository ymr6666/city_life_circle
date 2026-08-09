# -*- coding: utf-8 -*-
"""大面积设施多点挂接 (公园/大学/商场等)

背景: 公园/大学/大型商场 POI 是几何中心, 周围是绿地/校园内部无路。
snap_poi_v2 只在 POI 点周围 150m 找节点, 大设施只挂到 1 个方向的门,
另一侧人口即使紧邻设施也因路网不连通而"不可达" (覆盖分析误判盲区)。

方案: 以 POI 为中心, 在 8 个方向 (N/NE/E/.../NW) × 递增半径 (150/300/500m)
采样虚拟点, 每个方向取最近的可走路网节点 → 覆盖设施四周多个门。

仅增量处理指定类别, 不触碰已有挂接 (同一 poi_id 已有 walk 挂接则跳过)。
重建请先删对应 poi_id 的 walk 记录。

用法:
  python snap_large_facilities.py            # park/school_college/mall
  python snap_large_facilities.py --only park
"""
import os
import sys
import time
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import psycopg2

# 需要多点挂接的大面积设施: (radius 阶梯, 方向数, 每方向最多节点)
LARGE_CATEGORIES = {
    'park':            ((150, 300, 500, 800), 8, 2),
    'school_college':  ((150, 300, 500), 8, 2),
    'mall':            ((150, 300, 500), 8, 2),
    'sports':          ((150, 300, 500), 8, 2),
}
BBOX = (117.07, 31.68, 117.50, 32.07)


def _directions(n):
    """n 个均匀方向单位向量"""
    return [(math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n))
            for i in range(n)]


def main():
    args = sys.argv[1:]
    cats = list(LARGE_CATEGORIES)
    if '--only' in args:
        cats = [c.strip() for c in args[args.index('--only') + 1].split(',') if c.strip()]
        unknown = [c for c in cats if c not in LARGE_CATEGORIES]
        if unknown:
            print(f"未知类别: {unknown}, 可选: {list(LARGE_CATEGORIES)}")
            return

    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()

    # walk 顶点缓存
    cur.execute("""
        DROP TABLE IF EXISTS tmp_lf_vertices;
        CREATE TEMP TABLE tmp_lf_vertices AS
        SELECT DISTINCT v.id, v.geometry
        FROM hefei_roads_vertices_pgr v
        JOIN hefei_roads r ON r.source = v.id OR r.target = v.id
        WHERE r.walk_ok
    """)
    cur.execute("CREATE INDEX ON tmp_lf_vertices(id)")
    cur.execute("CREATE INDEX ON tmp_lf_vertices USING GIST(geometry)")
    cur.execute("SELECT count(*) FROM tmp_lf_vertices")
    print(f"walk 顶点: {cur.fetchone()[0]} 个")

    for cat in cats:
        radii, ndir, max_per_dir = LARGE_CATEGORIES[cat]
        t0 = time.time()
        # 删除该类别已有 walk 挂接 (重建)
        cur.execute("""
            DELETE FROM poi_road_nodes prn
            USING hefei_poi p
            WHERE prn.poi_id = p.id AND p.category = %s AND prn.mode = 'walk'
        """, (cat,))
        conn.commit()
        # 取该类 POI
        cur.execute("""
            SELECT p.id, ST_X(p.geometry), ST_Y(p.geometry)
            FROM hefei_poi p
            WHERE p.category = %s
              AND p.geometry && ST_MakeEnvelope(%s,%s,%s,%s,4326)
        """, (cat, *BBOX))
        pois = cur.fetchall()
        if not pois:
            print(f"[{cat:16s}] 无 POI ({time.time()-t0:.1f}s)")
            continue

        dirs = _directions(ndir)
        inserted = 0
        skipped_no_road = 0
        for pid, plng, plat in pois:
            got = 0
            for r in radii:
                for dx, dy in dirs:
                    if got >= ndir * max_per_dir:
                        break
                    slat = plat + dy * r / 111000.0
                    slng = plng + dx * r / (111000.0 * math.cos(math.radians(plat)))
                    cur.execute("""
                        SELECT id, ST_Distance(
                                   ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,
                                   v.geometry::geography) AS d
                        FROM tmp_lf_vertices v
                        ORDER BY ST_SetSRID(ST_MakePoint(%s,%s),4326) <-> v.geometry
                        LIMIT 1
                    """, (slng, slat, slng, slat))
                    row = cur.fetchone()
                    if not row:
                        continue
                    nid, d = row
                    if d > 800:
                        continue
                    cur.execute("""
                        SELECT 1 FROM poi_road_nodes WHERE poi_id=%s AND node_id=%s AND mode='walk'
                    """, (pid, nid))
                    if cur.fetchone():
                        continue
                    cur.execute("""
                        INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
                        VALUES (%s, %s, 'walk', %s)
                    """, (pid, nid, float(d)))
                    got += 1
                    inserted += 1
                if got >= ndir * max_per_dir:
                    break
            if got == 0:
                skipped_no_road += 1
        conn.commit()
        cur.execute("""
            SELECT count(DISTINCT pn.poi_id) FROM poi_road_nodes pn
            JOIN hefei_poi p ON p.id=pn.poi_id WHERE p.category=%s AND pn.mode='walk'
        """, (cat,))
        covered = cur.fetchone()[0]
        print(f"[{cat:16s}] 新增 {inserted} 条 / {len(pois)} POI (无路可挂 {skipped_no_road}) | "
              f"该类已挂 {covered} POI ({time.time()-t0:.1f}s)")

    cur.close()
    conn.close()
    print("\n完成!")


if __name__ == "__main__":
    main()
