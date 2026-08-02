"""地铁站吸附到步行可用路网节点 (简化版)"""
import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='city_life_circle',
                        user='postgres', password='admin')
cur = conn.cursor()

# 直接使用 snap_poi_v2 已验证可用的步行道路白名单
walk_highways = [
    'footway', 'path', 'steps', 'pedestrian', 'corridor',
    'residential', 'living_street', 'service', 'unclassified',
    'tertiary', 'tertiary_link', 'track', 'cycleway'
]

print("Step 1: 建步行顶点缓存")
placeholders = ','.join(['%s'] * len(walk_highways))
cur.execute(f"""
    DROP TABLE IF EXISTS tmp_walk_vertices_metro;
    CREATE TEMP TABLE tmp_walk_vertices_metro AS
    SELECT DISTINCT v.id, v.geometry
    FROM hefei_roads_vertices_pgr v
    JOIN hefei_roads r ON r.source = v.id OR r.target = v.id
    WHERE r.highway IN ({placeholders})
""", walk_highways)
cur.execute("CREATE INDEX ON tmp_walk_vertices_metro(id)")
cur.execute("CREATE INDEX ON tmp_walk_vertices_metro USING GIST(geometry)")
cur.execute("SELECT count(*) FROM tmp_walk_vertices_metro")
print(f"  节点: {cur.fetchone()[0]}")
conn.commit()

print("Step 2: 建 metro_station_road_nodes 表")
cur.execute("DROP TABLE IF EXISTS metro_station_road_nodes CASCADE")
cur.execute("""
    CREATE TABLE metro_station_road_nodes (
        id SERIAL PRIMARY KEY,
        station_id INTEGER REFERENCES hefei_metro_stations(id) ON DELETE CASCADE,
        node_id INTEGER REFERENCES hefei_roads_vertices_pgr(id),
        distance_m DOUBLE PRECISION
    );
    CREATE INDEX idx_msrn_station ON metro_station_road_nodes(station_id);
    CREATE INDEX idx_msrn_node ON metro_station_road_nodes(node_id);
""")
conn.commit()

print("Step 3: 每个地铁站吸附最近 3 个步行节点 (300m)")
cur.execute(f"""
    INSERT INTO metro_station_road_nodes (station_id, node_id, distance_m)
    SELECT ms.id, v.id,
           ST_Distance(ms.geometry::geography, v.geometry::geography)
    FROM hefei_metro_stations ms
    CROSS JOIN LATERAL (
        SELECT id, geometry FROM tmp_walk_vertices_metro
        WHERE ST_DWithin(geometry::geography, ms.geometry::geography, 300)
        ORDER BY ms.geometry <-> geometry LIMIT 3
    ) v
""")
print(f"  插入 {cur.rowcount} 条")
conn.commit()

print("Step 4: 验证")
cur.execute("SELECT count(*), count(DISTINCT station_id) FROM metro_station_road_nodes")
total_s, total_st = cur.fetchone()
print(f"  挂接: {total_s} 条 | 覆盖 {total_st}/{169} 站")

cur.execute("""
    SELECT MIN(distance_m)::int, AVG(distance_m)::int,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY distance_m)::int as p50,
           MAX(distance_m)::int
    FROM metro_station_road_nodes
""")
r = cur.fetchone()
print(f"  距离: min={r[0]}m  avg={r[1]}m  median={r[2]}m  max={r[3]}m")

cur.execute("DROP TABLE IF EXISTS tmp_walk_vertices_metro")
conn.commit()
cur.close()
conn.close()
print("Done!")
