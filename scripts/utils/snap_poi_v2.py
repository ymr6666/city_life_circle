"""POI-路网节点挂接 v2
改进:
  1. 使用 entr_location 作为挂接起点（entry点优先于POI几何坐标）
  2. 分 walk/drive 模式，按道路类型过滤路网顶点
  3. 多楼栋医院通过 address 字段自动分组，只挂主入口
  4. 非代表多楼栋复制代表的挂接记录

使用: python snap_poi_v2.py
"""
import psycopg2
import re
import time
from collections import defaultdict

conn = psycopg2.connect(host='localhost', port=5432, dbname='city_life_circle',
                        user='postgres', password='admin')
cur = conn.cursor()

# ══════════════════════════════════════════════
# STEP 0: 准备 — 加 canonical_poi_id 字段
# ══════════════════════════════════════════════

print("Step 0: adding canonical_poi_id column...")
cur.execute("""
    ALTER TABLE hefei_poi ADD COLUMN IF NOT EXISTS canonical_poi_id INTEGER
""")
conn.commit()

# 先全部置 NULL
cur.execute("UPDATE hefei_poi SET canonical_poi_id = NULL")
conn.commit()

# ══════════════════════════════════════════════
# STEP 1: 建模式化路网顶点缓存
# ══════════════════════════════════════════════

print("Step 1: building mode-filtered vertex caches...")

# 步行可用道路类型
walk_highways = [
    'footway', 'path', 'steps', 'pedestrian', 'corridor',
    'residential', 'living_street', 'service', 'unclassified',
    'tertiary', 'tertiary_link', 'track', 'cycleway'
]

# 驾车可用道路类型
drive_highways = [
    'motorway', 'motorway_link',
    'trunk', 'trunk_link',
    'primary', 'primary_link',
    'secondary', 'secondary_link',
    'tertiary', 'tertiary_link',
    'residential', 'living_street', 'service', 'unclassified'
]

cur.execute("DROP TABLE IF EXISTS tmp_walk_vertices")
cur.execute("DROP TABLE IF EXISTS tmp_drive_vertices")

# Walk vertices (exclude motorway/trunk + elevated bridge roads)
placeholders = ','.join(['%s'] * len(walk_highways))
cur.execute(f"""
    CREATE TEMP TABLE tmp_walk_vertices AS
    SELECT DISTINCT v.id, v.geometry
    FROM hefei_roads_vertices_pgr v
    JOIN hefei_roads r ON r.source = v.id OR r.target = v.id
    WHERE r.highway IN ({placeholders})
      -- 额外防御：排除 bridge=yes 的高架路（行人不可达）
      AND NOT (
          r.bridge = 'yes'
          AND (
              r.highway IN ('primary', 'primary_link', 'secondary', 'secondary_link')
              OR r.highway LIKE '%primary%'
              OR r.highway LIKE '%secondary%'
          )
      )
""", walk_highways)
cur.execute("CREATE INDEX idx_twv_id ON tmp_walk_vertices(id)")
cur.execute("CREATE INDEX idx_twv_geom ON tmp_walk_vertices USING GIST(geometry)")
cur.execute("SELECT count(*) FROM tmp_walk_vertices")
print(f"  walk_vertices: {cur.fetchone()[0]} nodes")

# Drive vertices
placeholders = ','.join(['%s'] * len(drive_highways))
cur.execute(f"""
    CREATE TEMP TABLE tmp_drive_vertices AS
    SELECT DISTINCT v.id, v.geometry
    FROM hefei_roads_vertices_pgr v
    JOIN hefei_roads r ON r.source = v.id OR r.target = v.id
    WHERE r.highway IN ({placeholders})
""", drive_highways)
cur.execute("CREATE INDEX idx_tdv_id ON tmp_drive_vertices(id)")
cur.execute("CREATE INDEX idx_tdv_geom ON tmp_drive_vertices USING GIST(geometry)")
cur.execute("SELECT count(*) FROM tmp_drive_vertices")
print(f"  drive_vertices: {cur.fetchone()[0]} nodes")
conn.commit()

# ══════════════════════════════════════════════
# STEP 2: 医院分组
# ══════════════════════════════════════════════

print("\nStep 2: grouping hospital buildings...")

def extract_parent_hospital(name, address):
    """从 address 字段提取母医院名，返回 None=独立 POI"""
    if not address:
        return None

    building_keywords = ['内', '门诊', '急诊', '住院', '综合楼', '医技楼',
                         '外科楼', '内科楼', '行政楼', '检验楼', '号楼', '号搂']

    # 找到最后一个"医院"的位置
    hospital_idx = address.rfind('医院')
    if hospital_idx < 0:
        # 地址没"医院"，看名称
        if name:
            for suffix in ['门诊', '急诊', '住院']:
                m = re.search(r'(.+医院)' + suffix + r'(楼|部)?', name)
                if m:
                    return m.group(1)
        return None

    # 检查"医院"后面是不是楼栋标记词
    suffix = address[hospital_idx + 2:hospital_idx + 6]
    is_building = any(suffix.startswith(kw) for kw in building_keywords)

    if not is_building:
        # 尝试 "XX院区"
        m = re.search(r'(.{2,30}院区)', address)
        return m.group(1) if m else None

    # 提取母医院名：从最后一个分隔词后到"医院"为止
    start = hospital_idx
    for sep in ['号', '路', '街', '道', '区']:
        pos = address.rfind(sep, 0, hospital_idx)
        if pos > 0:
            start = pos + 1
            break

    hospital_name = address[start:hospital_idx + 2]
    if len(hospital_name) >= 4:
        return hospital_name.strip()

    return None


def select_canonical(group_rows):
    """从一组楼栋中选代表: 门诊 > 急诊 > 有entry的 > 第一个"""
    for keywords in [['门诊'], ['急诊'], ['住院']]:
        for row in group_rows:
            name = row[1] or ''
            if any(kw in name for kw in keywords):
                return row
    # 选有 entry 的
    for row in group_rows:
        if row[5]:  # entr_location
            return row
    # 兜底
    return group_rows[0]


# 读全部医院
cur.execute("""
    SELECT id, name, sub_category, ST_X(geometry) as lng, ST_Y(geometry) as lat,
           entr_location, address
    FROM hefei_poi WHERE category = 'hospital'
""")
hospital_rows = cur.fetchall()

# 分组
parent_map = defaultdict(list)
for row in hospital_rows:
    parent = extract_parent_hospital(row[1], row[6])
    if parent:
        parent_map[parent].append(row)
    else:
        parent_map[row[1]].append(row)

# 挑选代表 + 写入 canonical_poi_id
hospital_groups = 0
multi_building_groups = 0
for parent, group_rows in parent_map.items():
    hospital_groups += 1
    canonical = select_canonical(group_rows)
    if len(group_rows) > 1:
        multi_building_groups += 1

    for row in group_rows:
        cur.execute(
            "UPDATE hefei_poi SET canonical_poi_id = %s WHERE id = %s",
            (canonical[0], row[0])
        )

conn.commit()
print(f"  hospital groups: {hospital_groups}")
print(f"  multi-building groups: {multi_building_groups}")

# 打印多楼栋医院详情
print("\n  Multi-building hospitals:")
for parent, group_rows in sorted(parent_map.items(), key=lambda x: -len(x[1])):
    if len(group_rows) > 1:
        canonical = [r for r in group_rows if r[0] == r[0]][0]
        # find actual canonical
        for r in group_rows:
            cur.execute("SELECT canonical_poi_id FROM hefei_poi WHERE id=%s", (r[0],))
            cid = cur.fetchone()[0]
            if cid == r[0]:
                canonical = r
                break
        print(f"    {parent} ({len(group_rows)} buildings)")
        for r in group_rows:
            marker = " [CANONICAL]" if r[0] == canonical[0] else ""
            print(f"      {r[1][:35]:35s} entry={'Y' if r[5] else 'N'}{marker}")

# ══════════════════════════════════════════════
# STEP 3: 重建 poi_road_nodes
# ══════════════════════════════════════════════

print("\nStep 3: rebuilding poi_road_nodes table...")

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

# ══════════════════════════════════════════════
# STEP 4: POI 挂接
# ══════════════════════════════════════════════

print("\nStep 4: snapping POIs to road nodes...")

# 类别参数 (radius_m, max_nodes)
radius_map = {
    'hospital':         (150, 5),
    'school_college':   (150, 5),
    'park':             (150, 5),
    'mall':             (100, 3),
    'school_primary':   (80, 3),
    'school_junior':    (80, 3),
    'school_senior':    (80, 3),
    'supermarket':      (50, 2),
    'market_food':      (50, 2),
    'kindergarten':     (50, 2),
    'street_commercial': (30, 1),
    'street_pedestrian': (30, 1),
}

# snap_point SQL: entry 优先, geometry 兜底
# 注意：用 position 代替 LIKE 避免 % 和 psycopg2 占位符冲突
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

def snap_pois(category, mode, vertex_table, radius_m, max_nodes):
    """挂接一个类别到一个模式的顶点表"""
    radius_deg = radius_m / 111000.0
    t0 = time.time()

    # 医院只挂接 canonical (canonical_poi_id = id 或 canonical_poi_id IS NULL)
    # 只挂接合肥 bbox 内的 POI
    bbox_filter = "p.geometry && ST_MakeEnvelope(117.07, 31.68, 117.50, 32.07, 4326)"
    if category == 'hospital':
        cat_filter = f"p.category = 'hospital' AND (p.canonical_poi_id = p.id OR p.canonical_poi_id IS NULL) AND {bbox_filter}"
    else:
        cat_filter = f"p.category = '{category}' AND {bbox_filter}"

    cur.execute(f"""
        INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
        SELECT p.id, v.id, %s,
               ST_Distance(
                   ({snap_sql})::geography,
                   v.geometry::geography
               )
        FROM hefei_poi p
        CROSS JOIN LATERAL (
            SELECT id, geometry FROM {vertex_table}
            WHERE ST_DWithin(geometry, ({snap_sql}), %s)
            ORDER BY ({snap_sql}) <-> geometry
            LIMIT %s
        ) v
        WHERE {cat_filter}
    """, (mode, radius_deg, max_nodes))

    cur.execute("""
        SELECT count(*) FROM poi_road_nodes pn
        JOIN hefei_poi p ON p.id = pn.poi_id
        WHERE pn.mode = %s
          AND p.category = %s
    """, (mode, category))
    cnt = cur.fetchone()[0]
    elapsed = time.time() - t0
    print(f"  [{mode:5s}] {category:20s} r={radius_m}m n={max_nodes} -> {cnt:>6} links ({elapsed:.1f}s)")
    conn.commit()
    return cnt


total_walk = 0
total_drive = 0

for cat, (radius, max_n) in radius_map.items():
    w = snap_pois(cat, 'walk', 'tmp_walk_vertices', radius, max_n)
    total_walk += w
    d = snap_pois(cat, 'drive', 'tmp_drive_vertices', radius, max_n)
    total_drive += d

print(f"\n  total walk links: {total_walk}")
print(f"  total drive links: {total_drive}")

# 兜底：未挂接的 POI 强制挂最近 1 个节点
print("\n  Fallback: snapping unlinked POIs...")

for mode, vertex_table in [('walk', 'tmp_walk_vertices'), ('drive', 'tmp_drive_vertices')]:
    cur.execute(f"""
        INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
        SELECT p.id, v.id, %s,
               ST_Distance(
                   ({snap_sql})::geography,
                   v.geometry::geography
               )
        FROM hefei_poi p
        CROSS JOIN LATERAL (
            SELECT id, geometry FROM {vertex_table}
            ORDER BY ({snap_sql}) <-> geometry
            LIMIT 1
        ) v
        WHERE p.id NOT IN (
            SELECT DISTINCT poi_id FROM poi_road_nodes WHERE mode = %s
        )
        -- 非代表医院先不挂，等 copy 阶段
        AND NOT (p.category = 'hospital'
                 AND p.canonical_poi_id IS NOT NULL
                 AND p.canonical_poi_id != p.id)
        -- 只挂接合肥 bbox 内的 POI
        AND p.geometry && ST_MakeEnvelope(117.07, 31.68, 117.50, 32.07, 4326)
    """, (mode, mode))
    print(f"  [{mode:5s}] fallback: {cur.rowcount} POIs linked")
    conn.commit()

# ══════════════════════════════════════════════
# STEP 5: 非代表医院复制代表的挂接记录
# ══════════════════════════════════════════════

print("\nStep 5: copying snap points for non-canonical hospitals...")

cur.execute("""
    INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
    SELECT h.id, pn.node_id, pn.mode, pn.distance_m
    FROM hefei_poi h
    JOIN poi_road_nodes pn ON pn.poi_id = h.canonical_poi_id
    WHERE h.category = 'hospital'
      AND h.canonical_poi_id IS NOT NULL
      AND h.canonical_poi_id != h.id
      AND NOT EXISTS (
          SELECT 1 FROM poi_road_nodes pn2
          WHERE pn2.poi_id = h.id
      )
""")
print(f"  copied to {cur.rowcount} non-canonical hospital POIs")
conn.commit()

# ══════════════════════════════════════════════
# STEP 6: 验证
# ══════════════════════════════════════════════

print("\n" + "=" * 60)
print("Step 6: verification")
print("=" * 60)

cur.execute("""
    SELECT mode, count(*) as total_links, count(DISTINCT poi_id) as pois
    FROM poi_road_nodes GROUP BY mode
""")
for r in cur.fetchall():
    print(f"  [{r[0]:5s}] {r[1]:>6} links  covering {r[2]} POIs")

cur.execute("SELECT count(*) FROM hefei_poi")
total_pois = cur.fetchone()[0]
cur.execute("SELECT count(DISTINCT poi_id) FROM poi_road_nodes WHERE mode='walk'")
walk_pois = cur.fetchone()[0]
cur.execute("SELECT count(DISTINCT poi_id) FROM poi_road_nodes WHERE mode='drive'")
drive_pois = cur.fetchone()[0]
print(f"\n  POI total: {total_pois}")
print(f"  walk coverage: {walk_pois}/{total_pois} ({100*walk_pois//total_pois}%)")
print(f"  drive coverage: {drive_pois}/{total_pois} ({100*drive_pois//total_pois}%)")

# 按类别统计
print(f"\n  {'category':25s} {'total':>5} {'walk':>5} {'drive':>5}")
print("  " + "-" * 43)
cur.execute("""
    SELECT p.category,
           count(DISTINCT p.id),
           count(DISTINCT w.poi_id),
           count(DISTINCT d.poi_id)
    FROM hefei_poi p
    LEFT JOIN poi_road_nodes w ON w.poi_id = p.id AND w.mode = 'walk'
    LEFT JOIN poi_road_nodes d ON d.poi_id = p.id AND d.mode = 'drive'
    GROUP BY p.category ORDER BY p.category
""")
for r in cur.fetchall():
    wpct = 100 * r[2] // r[1] if r[1] else 0
    dpct = 100 * r[3] // r[1] if r[1] else 0
    print(f"  {r[0]:25s} {r[1]:>5} {r[2]:>5} {r[3]:>5}")

# 平均每POI挂接节点数
cur.execute("""
    SELECT mode, AVG(cnt)::numeric(4,1) FROM (
        SELECT mode, poi_id, count(*) as cnt
        FROM poi_road_nodes GROUP BY mode, poi_id
    ) t GROUP BY mode
""")
for r in cur.fetchall():
    print(f"\n  avg nodes per POI ({r[0]}): {r[1]}")

# 最远挂接距离
cur.execute("""
    SELECT p.name, p.category, pn.mode, pn.distance_m::INT
    FROM poi_road_nodes pn JOIN hefei_poi p ON p.id = pn.poi_id
    ORDER BY pn.distance_m DESC LIMIT 10
""")
print("\n  Farthest snap distances:")
for r in cur.fetchall():
    print(f"    [{r[2]:5s}] {r[0]:30s} {r[1]:15s} {r[3]}m")

cur.close()
conn.close()
print("\nDone!")
