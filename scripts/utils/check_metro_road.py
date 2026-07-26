import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# 路网覆盖范围
cur.execute("SELECT ST_Extent(geometry) FROM hefei_roads")
extent = cur.fetchone()[0]

# 地铁站是否在路网内(用 bbox)
cur.execute("""
    SELECT count(*) FROM hefei_metro_stations
    WHERE geometry && ST_MakeEnvelope(117.07,31.68,117.50,32.07,4326)
""")
inside = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM hefei_metro_stations")
total = cur.fetchone()[0]
print(f"地铁站在路网 bbox 内: {inside}/{total}")

# 找不在路网内的站
cur.execute("""
    SELECT name, ST_X(geometry), ST_Y(geometry)
    FROM hefei_metro_stations
    WHERE NOT geometry && ST_MakeEnvelope(117.07,31.68,117.50,32.07,4326)
    ORDER BY ST_X(geometry)
""")
outside = cur.fetchall()
for r in outside:
    print(f"  超出: {r[0]:20s} ({r[1]:.4f},{r[2]:.4f})")

# 每个站距离最近路网节点
cur.execute("""
    SELECT s.name, MIN(ST_Distance(s.geometry, v.geometry)) * 111000 AS dist_m
    FROM hefei_metro_stations s, hefei_roads_vertices_pgr v
    WHERE s.geometry && ST_Expand(v.geometry, 0.01)
    GROUP BY s.id, s.name
    ORDER BY dist_m DESC
    LIMIT 10
""")
print("\n距离路网最远的站:")
for r in cur.fetchall():
    print(f"  {r[0]:20s} {r[1]:.0f}m")

conn.close()
