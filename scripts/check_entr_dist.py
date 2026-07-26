"""检查引导点和POI主坐标之间的距离"""
import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# 解析 entr_location 并和 geometry 比距离
cur.execute("""
    SELECT name, category,
           split_part(entr_location,',',1)::float as e_lng,
           split_part(entr_location,',',2)::float as e_lat,
           ST_X(geometry) as poi_lng, ST_Y(geometry) as poi_lat,
           ST_Distance(
               geometry::geography,
               ST_SetSRID(ST_MakePoint(
                   split_part(entr_location,',',1)::float,
                   split_part(entr_location,',',2)::float
               ), 4326)::geography
           ) as dist_m
    FROM hefei_poi
    WHERE entr_location IS NOT NULL AND entr_location != ''
      AND entr_location LIKE '%,%'
    ORDER BY dist_m DESC
    LIMIT 15
""")
print("=== 引导点偏离最远的 15 个 ===")
for r in cur.fetchall():
    name, cat, elng, elat, plng, plat, dist = r
    print(f"  {name:25s} {cat:12s} POI=({plng:.4f},{plat:.4f}) Entry=({elng:.4f},{elat:.4f}) {dist:.0f}m")

# 平均距离 - 简化
cur.execute("""
    SELECT AVG(dist_m)::INT, MIN(dist_m)::INT, MAX(dist_m)::INT FROM (
        SELECT ST_Distance(
               geometry::geography,
               ST_SetSRID(ST_MakePoint(
                   split_part(entr_location,',',1)::float,
                   split_part(entr_location,',',2)::float
               ), 4326)::geography
           ) as dist_m
        FROM hefei_poi
        WHERE entr_location IS NOT NULL AND entr_location != ''
          AND entr_location LIKE '%,%'
    ) t
""")
avg, min_d, max_d = cur.fetchone()
print(f"\n  distance: avg={avg}m  min={min_d}m  max={max_d}m")

# 看看距离<1m的
cur.execute(f"SELECT count(*) FROM hefei_poi "
    "WHERE entr_location IS NOT NULL AND entr_location != '' AND entr_location LIKE '%,%' "
    "AND ST_Distance(geometry::geography, ST_SetSRID(ST_MakePoint("
    "split_part(entr_location,',',1)::float, split_part(entr_location,',',2)::float"
    "), 4326)::geography) < 1")
near_zero = cur.fetchone()[0]
print(f"  entr ~= poi (<1m): {near_zero} / 3721 ({100*near_zero//3721}%)")

# 检查 entr_location 格式
cur.execute("SELECT entr_location FROM hefei_poi WHERE entr_location IS NOT NULL AND entr_location != '' LIMIT 5")
print("\n=== entr_location 原始格式 ===")
for r in cur.fetchall():
    print(f"  {r[0][:60]}")

cur.close()
conn.close()
