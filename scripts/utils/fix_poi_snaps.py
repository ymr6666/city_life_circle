"""
修复 POI walk 挂接：排除高架桥和高速/快速路节点上的挂接，重挂孤 POI

用法: python fix_poi_snaps.py
"""
import psycopg2
import time
from collections import defaultdict

conn = psycopg2.connect(host='localhost', port=5432, dbname='city_life_circle',
                        user='postgres', password='admin')
cur = conn.cursor()

# ============================================================
# STEP 1: 统计修复前状态
# ============================================================
print("=" * 60)
print("Step 1: 修复前状态")
print("=" * 60)

cur.execute("SELECT count(*) FROM poi_road_nodes WHERE mode='walk'")
before_total = cur.fetchone()[0]
cur.execute("SELECT count(DISTINCT poi_id) FROM poi_road_nodes WHERE mode='walk'")
before_pois = cur.fetchone()[0]
print(f"  walk 挂接: {before_total} 条, 覆盖 {before_pois} 个 POI")

cur.execute("""
    SELECT MIN(distance_m)::int, AVG(distance_m)::int,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY distance_m)::int as median,
           MAX(distance_m)::int
    FROM poi_road_nodes WHERE mode='walk'
""")
r = cur.fetchone()
print(f"  距离 (min/avg/median/max): {r[0]}m / {r[1]}m / {r[2]}m / {r[3]}m")

# ============================================================
# STEP 2: 构建干净的步行顶点表
# ============================================================
print("\n" + "=" * 60)
print("Step 2: 构建干净的 walk 顶点过滤")
print("=" * 60)

# 排除规则:
# 1. 高速/快速路: motorway, trunk 及其 _link 变体
# 2. 高架桥: primary/secondary + bridge=yes (行人无法上桥)

cur.execute("DROP TABLE IF EXISTS tmp_walk_vertices_clean")
cur.execute("""
    CREATE TEMP TABLE tmp_walk_vertices_clean AS
    SELECT DISTINCT v.id, v.geometry
    FROM hefei_roads_vertices_pgr v
    JOIN hefei_roads r ON r.source = v.id OR r.target = v.id
    WHERE
        -- 排除高速/快速路
        r.highway NOT IN ('motorway', 'motorway_link', 'trunk', 'trunk_link')
        AND r.highway NOT LIKE '%motorway%'
        AND r.highway NOT LIKE '%trunk%'
        -- 排除高架桥(primary/secondary + bridge=yes)
        AND NOT (
            r.bridge = 'yes'
            AND (
                r.highway IN ('primary', 'primary_link', 'secondary', 'secondary_link')
                OR r.highway LIKE '%primary%'
                OR r.highway LIKE '%secondary%'
            )
        )
""")
cur.execute("CREATE INDEX idx_twvc_id ON tmp_walk_vertices_clean(id)")
cur.execute("CREATE INDEX idx_twvc_geom ON tmp_walk_vertices_clean USING GIST(geometry)")
cur.execute("SELECT count(*) FROM tmp_walk_vertices_clean")
clean_count = cur.fetchone()[0]
conn.commit()
print(f"  干净步行顶点: {clean_count}")

# ============================================================
# STEP 3: 识别并删除问题挂接
# ============================================================
print("\n" + "=" * 60)
print("Step 3: 识别并删除问题 walk 挂接")
print("=" * 60)

# 找出挂到了非干净节点的 walk 记录
cur.execute("""
    CREATE TEMP TABLE tmp_bad_snaps AS
    SELECT pn.id
    FROM poi_road_nodes pn
    WHERE pn.mode = 'walk'
      AND pn.node_id NOT IN (SELECT id FROM tmp_walk_vertices_clean)
""")
cur.execute("SELECT count(*) FROM tmp_bad_snaps")
bad_count = cur.fetchone()[0]
print(f"  问题挂接: {bad_count} 条")

# 查看问题节点上挂了什么 POI
cur.execute("""
    SELECT p.category, count(DISTINCT p.id) as poi_cnt, count(*) as snap_cnt
    FROM tmp_bad_snaps bs
    JOIN poi_road_nodes pn ON pn.id = bs.id
    JOIN hefei_poi p ON p.id = pn.poi_id
    GROUP BY p.category ORDER BY snap_cnt DESC
""")
print(f"  {'category':25s} {'POIs':>6s} {'snaps':>6s}")
for r in cur.fetchall():
    print(f"  {r[0]:25s} {r[1]:>6d} {r[2]:>6d}")

# 删除问题挂接
cur.execute("""
    DELETE FROM poi_road_nodes
    WHERE id IN (SELECT id FROM tmp_bad_snaps)
""")
conn.commit()
print(f"\n  已删除 {cur.rowcount} 条问题 walk 挂接")

# ============================================================
# STEP 4: 找出孤 POI (无任何 walk 挂接) 并重挂
# ============================================================
print("\n" + "=" * 60)
print("Step 4: 找出孤 POI 并重挂")
print("=" * 60)

cur.execute("""
    SELECT count(DISTINCT p.id)
    FROM hefei_poi p
    WHERE p.id NOT IN (
        SELECT DISTINCT poi_id FROM poi_road_nodes WHERE mode='walk'
    )
      AND p.geometry && ST_MakeEnvelope(117.07, 31.68, 117.50, 32.07, 4326)
""")
orphan_count = cur.fetchone()[0]
print(f"  孤 POI (无 walk 挂接): {orphan_count}")

cur.execute("""
    SELECT p.category, count(*) as cnt
    FROM hefei_poi p
    WHERE p.id NOT IN (
        SELECT DISTINCT poi_id FROM poi_road_nodes WHERE mode='walk'
    )
      AND p.geometry && ST_MakeEnvelope(117.07, 31.68, 117.50, 32.07, 4326)
    GROUP BY p.category ORDER BY cnt DESC
""")
print(f"  {'category':25s} {'count':>6s}")
for r in cur.fetchall():
    print(f"  {r[0]:25s} {r[1]:>6d}")

# 重挂：对孤 POI 找最近 3 个干净步行节点（100m 内）
# snap_point 优先用 entry，无 entry 用 geometry
snap_sql = """
    CASE WHEN p.entr_location IS NOT NULL
              AND p.entr_location != ''
              AND position(',' in p.entr_location) > 0
         THEN ST_SetSRID(ST_MakePoint(
             split_part(p.entr_location, ',', 1)::float,
             split_part(p.entr_location, ',', 2)::float
         ), 4326)
         ELSE p.geometry
    END
"""

print("\n  重挂中...")
t0 = time.time()

# 用更大的半径 (200m) 重挂，确保能找到可用的地面节点
cur.execute(f"""
    INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
    SELECT p.id, v.id, 'walk',
           ST_Distance(
               ({snap_sql})::geography,
               v.geometry::geography
           )
    FROM hefei_poi p
    CROSS JOIN LATERAL (
        SELECT id, geometry FROM tmp_walk_vertices_clean
        WHERE ST_DWithin(geometry, ({snap_sql}), 0.0018)
        ORDER BY ({snap_sql}) <-> geometry
        LIMIT 3
    ) v
    WHERE p.id NOT IN (
        SELECT DISTINCT poi_id FROM poi_road_nodes WHERE mode='walk'
    )
      AND p.geometry && ST_MakeEnvelope(117.07, 31.68, 117.50, 32.07, 4326)
      -- 医院非代表不单独挂，后续 copy
      AND NOT (p.category = 'hospital'
               AND p.canonical_poi_id IS NOT NULL
               AND p.canonical_poi_id != p.id)
""")
re_snapped = cur.rowcount
conn.commit()

# 兜底：200m 内无干净节点的孤 POI，强制挂最近 1 个
cur.execute(f"""
    INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
    SELECT p.id, v.id, 'walk',
           ST_Distance(
               ({snap_sql})::geography,
               v.geometry::geography
           )
    FROM hefei_poi p
    CROSS JOIN LATERAL (
        SELECT id, geometry FROM tmp_walk_vertices_clean
        ORDER BY ({snap_sql}) <-> geometry
        LIMIT 1
    ) v
    WHERE p.id NOT IN (
        SELECT DISTINCT poi_id FROM poi_road_nodes WHERE mode='walk'
    )
      AND p.geometry && ST_MakeEnvelope(117.07, 31.68, 117.50, 32.07, 4326)
      AND NOT (p.category = 'hospital'
               AND p.canonical_poi_id IS NOT NULL
               AND p.canonical_poi_id != p.id)
""")
fallback = cur.rowcount
conn.commit()

print(f"  200m 内重挂: {re_snapped} 条")
print(f"  强制兜底: {fallback} 条")
print(f"  耗时: {time.time()-t0:.1f}s")

# ============================================================
# STEP 5: 处理非代表医院的 walk 挂接
# ============================================================
print("\n" + "=" * 60)
print("Step 5: 非代表医院同步 walk 挂接")
print("=" * 60)

# 先清除非代表医院的旧 walk 挂接
cur.execute("""
    DELETE FROM poi_road_nodes
    WHERE mode = 'walk'
      AND poi_id IN (
        SELECT h.id FROM hefei_poi h
        WHERE h.category = 'hospital'
          AND h.canonical_poi_id IS NOT NULL
          AND h.canonical_poi_id != h.id
      )
""")
print(f"  清除非代表旧 walk 挂接: {cur.rowcount} 条")
conn.commit()

# 从代表复制
cur.execute("""
    INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
    SELECT h.id, pn.node_id, 'walk', pn.distance_m
    FROM hefei_poi h
    JOIN poi_road_nodes pn ON pn.poi_id = h.canonical_poi_id AND pn.mode = 'walk'
    WHERE h.category = 'hospital'
      AND h.canonical_poi_id IS NOT NULL
      AND h.canonical_poi_id != h.id
""")
print(f"  从代表复制: {cur.rowcount} 条")
conn.commit()

# ============================================================
# STEP 6: 最终验证与统计
# ============================================================
print("\n" + "=" * 60)
print("Step 6: 修复后验证")
print("=" * 60)

cur.execute("SELECT count(*) FROM poi_road_nodes WHERE mode='walk'")
after_total = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM poi_road_nodes WHERE mode='drive'")
drive_total = cur.fetchone()[0]
cur.execute("SELECT count(DISTINCT poi_id) FROM poi_road_nodes WHERE mode='walk'")
after_pois = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM hefei_poi")
total_pois = cur.fetchone()[0]

print(f"  walk 挂接: {after_total} 条 (修复前 {before_total}, 增量 {after_total-before_total:+d})")
print(f"  drive 挂接: {drive_total} 条 (未修改)")
print(f"  walk 覆盖: {after_pois}/{total_pois} ({100*after_pois//total_pois}%)")

# 距离分布统计
print(f"\n{'='*60}")
print("距离分布 (walk)")
print(f"{'='*60}")

cur.execute("""
    SELECT MIN(distance_m)::int,
           AVG(distance_m)::int,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY distance_m)::int as p50,
           percentile_cont(0.75) WITHIN GROUP (ORDER BY distance_m)::int as p75,
           percentile_cont(0.85) WITHIN GROUP (ORDER BY distance_m)::int as p85,
           percentile_cont(0.95) WITHIN GROUP (ORDER BY distance_m)::int as p95,
           MAX(distance_m)::int
    FROM poi_road_nodes WHERE mode='walk'
""")
r = cur.fetchone()
print(f"  min:    {r[0]:>8d} m")
print(f"  avg:    {r[1]:>8d} m")
print(f"  p50:    {r[2]:>8d} m")
print(f"  p75:    {r[3]:>8d} m")
print(f"  p85:    {r[4]:>8d} m")
print(f"  p95:    {r[5]:>8d} m")
print(f"  max:    {r[6]:>8d} m")

# 分段统计
cur.execute("""
    SELECT
        CASE
            WHEN distance_m <= 50 THEN '0-50m'
            WHEN distance_m <= 100 THEN '50-100m'
            WHEN distance_m <= 200 THEN '100-200m'
            WHEN distance_m <= 500 THEN '200-500m'
            WHEN distance_m <= 1000 THEN '500m-1km'
            ELSE '>1km'
        END as range_bucket,
        count(*) as cnt,
        round(100.0 * count(*) / sum(count(*)) OVER (), 1) as pct
    FROM poi_road_nodes WHERE mode='walk'
    GROUP BY range_bucket
    ORDER BY MIN(distance_m)
""")
print(f"\n  {'range':12s} {'count':>7s} {'pct':>7s}")
for r in cur.fetchall():
    print(f"  {r[0]:12s} {r[1]:>7d} {r[2]:>6.1f}%")

# 按类别统计每 POI 平均挂接节点数
print(f"\n{'='*60}")
print("每 POI 平均 walk 节点数")
print(f"{'='*60}")

cur.execute("""
    SELECT p.category,
           count(DISTINCT p.id) as poi_cnt,
           count(*) as snap_cnt,
           round(count(*)::numeric / count(DISTINCT p.id), 1) as avg_nodes,
           round(avg(pn.distance_m)::numeric, 0)::int as avg_dist_m
    FROM hefei_poi p
    JOIN poi_road_nodes pn ON pn.poi_id = p.id AND pn.mode = 'walk'
    GROUP BY p.category ORDER BY poi_cnt DESC
""")
print(f"  {'category':25s} {'POIs':>6s} {'snaps':>7s} {'avg_nodes':>10s} {'avg_dist':>8s}")
print(f"  {'-'*60}")
for r in cur.fetchall():
    print(f"  {r[0]:25s} {r[1]:>6d} {r[2]:>7d} {float(r[3]):>10.1f} {r[4]:>7d}m")

# 检查还有没有挂到问题节点的漏网之鱼
cur.execute("""
    SELECT count(*)
    FROM poi_road_nodes pn
    WHERE pn.mode = 'walk'
      AND pn.node_id NOT IN (SELECT id FROM tmp_walk_vertices_clean)
""")
remaining_bad = cur.fetchone()[0]
print(f"\n  挂到非干净节点的残余: {remaining_bad} 条")

# 最远挂接
cur.execute("""
    SELECT p.name, p.category, pn.distance_m::INT
    FROM poi_road_nodes pn
    JOIN hefei_poi p ON p.id = pn.poi_id
    WHERE pn.mode = 'walk'
    ORDER BY pn.distance_m DESC LIMIT 5
""")
print(f"\n  最远挂接:")
for r in cur.fetchall():
    print(f"    {str(r[0] or 'NULL')[:35]:35s} {r[1]:15s} {r[2]}m")

cur.execute("DROP TABLE IF EXISTS tmp_walk_vertices_clean")
cur.execute("DROP TABLE IF EXISTS tmp_bad_snaps")
conn.commit()

cur.close()
conn.close()
print("\nDone!")
