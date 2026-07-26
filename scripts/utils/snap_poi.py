"""POI-路网节点挂接 - 优化版 (KNN 查询)"""
import psycopg2, time
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# Step 1: 建表 (跳过 road_node_modes，直接用边的 highway 过滤)
print("Step 1: creating poi_road_nodes...")
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
conn.commit()

# Step 2: 每种类型逐个处理
radius_map = {
    'hospital': (150, 5),
    'school_college': (150, 5),
    'park': (150, 5),
    'mall': (100, 3),
    'school_primary': (80, 3),
    'school_junior': (80, 3),
    'school_senior': (80, 3),
    'supermarket': (50, 2),
    'market_food': (50, 2),
    'kindergarten': (50, 2),
    'street_commercial': (30, 1),
    'street_pedestrian': (30, 1),
}

print("Step 2: snapping POIs...")
total = 0
for cat, (radius_m, max_n) in radius_map.items():
    radius_deg = radius_m / 111000.0
    t0 = time.time()

    cur.execute("""
        INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
        SELECT p.id, v.id, 'walk',
               ST_Distance(p.geometry::geography, v.geometry::geography)
        FROM hefei_poi p
        CROSS JOIN LATERAL (
            SELECT id FROM hefei_roads_vertices_pgr
            WHERE ST_DWithin(geometry, p.geometry, %s)
            ORDER BY geometry <-> p.geometry
            LIMIT %s
        ) v
        WHERE p.category = %s
    """, (radius_deg, max_n, cat))

    cur.execute("SELECT count(*) FROM poi_road_nodes WHERE mode='walk'")
    cnt = cur.fetchone()[0]
    elapsed = time.time() - t0
    print(f"  {cat:20s} radius={radius_m}m max={max_n} → {cnt} links ({elapsed:.1f}s)")
    total += cur.rowcount  # already counted by SELECT above
    conn.commit()

# 补未挂接的 POI (强制挂最近1个节点)
cur.execute("""
    INSERT INTO poi_road_nodes (poi_id, node_id, mode, distance_m)
    SELECT p.id, v.id, 'walk',
           ST_Distance(p.geometry::geography, v.geometry::geography)
    FROM hefei_poi p
    WHERE p.id NOT IN (SELECT DISTINCT poi_id FROM poi_road_nodes WHERE mode='walk')
    CROSS JOIN LATERAL (
        SELECT id FROM hefei_roads_vertices_pgr
        ORDER BY geometry <-> p.geometry LIMIT 1
    ) v
""")
print(f"  补挂未覆盖POI: {cur.rowcount} 个")
conn.commit()

# 验证
print("\nStep 3: verify...")
cur.execute("SELECT count(DISTINCT poi_id) FROM poi_road_nodes WHERE mode='walk'")
print(f"  POIs linked: {cur.fetchone()[0]}")
cur.execute("SELECT count(*) FROM poi_road_nodes WHERE mode='walk'")
print(f"  Total links: {cur.fetchone()[0]}")
cur.execute("SELECT count(*) FROM poi_road_nodes WHERE mode='cycle'")
print(f"  Cycle mode links: {cur.fetchone()[0]}")
cur.execute("SELECT count(*) FROM poi_road_nodes WHERE mode='drive'")
print(f"  Drive mode links: {cur.fetchone()[0]}")

cur.execute("""
    SELECT p.name, p.category, MAX(pn.distance_m)::INT
    FROM poi_road_nodes pn JOIN hefei_poi p ON p.id=pn.poi_id
    WHERE pn.mode='walk' GROUP BY p.id,p.name,p.category
    ORDER BY max DESC LIMIT 10
""")
print("\n  Farthest links:")
for r in cur.fetchall():
    print(f"    {r[0]:30s} {r[1]:15s} {r[2]}m")

cur.close()
conn.close()
print("\nDone!")
