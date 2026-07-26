"""验证地铁数据 + 导出文件"""
import psycopg2, json, csv, os

conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# 验证
cur.execute("SELECT count(*) FROM hefei_metro_stations")
print(f"站点: {cur.fetchone()[0]}")
cur.execute("SELECT count(*) FROM hefei_metro_edges")
print(f"边: {cur.fetchone()[0]}")
cur.execute("SELECT count(*) FROM hefei_metro_stations WHERE is_transfer=true")
print(f"换乘站: {cur.fetchone()[0]}")

# 检查孤立边（引用了已删除站的边）
cur.execute("""
    SELECT count(*) FROM hefei_metro_edges e
    LEFT JOIN hefei_metro_stations s1 ON e.station_from=s1.id
    LEFT JOIN hefei_metro_stations s2 ON e.station_to=s2.id
    WHERE s1.id IS NULL OR s2.id IS NULL
""")
print(f"孤立边: {cur.fetchone()[0]}")

# 导出 GeoJSON
out_dir = "E:/city-life-circle/data/合肥地铁"
os.makedirs(out_dir, exist_ok=True)

# 站点
cur.execute("""
    SELECT json_build_object('type','FeatureCollection','features',
        json_agg(json_build_object('type','Feature',
            'geometry', ST_AsGeoJSON(geometry)::json,
            'properties', json_build_object('name',name,'line_name',line_name,'is_transfer',is_transfer)
        ))
    ) FROM hefei_metro_stations
""")
with open(f"{out_dir}/hefei_metro_stations.geojson","w",encoding="utf-8") as f:
    json.dump(cur.fetchone()[0], f, ensure_ascii=False)

# 边
cur.execute("""
    SELECT json_build_object('type','FeatureCollection','features',
        json_agg(json_build_object('type','Feature',
            'geometry', ST_AsGeoJSON(geometry)::json,
            'properties', json_build_object('line_name',line_name,'distance_km',distance_km,'time_min',time_min)
        ))
    ) FROM hefei_metro_edges
""")
with open(f"{out_dir}/hefei_metro_edges.geojson","w",encoding="utf-8") as f:
    json.dump(cur.fetchone()[0], f, ensure_ascii=False)

print(f"\nExported: {out_dir}/")
for f in ["hefei_metro_stations.geojson","hefei_metro_edges.geojson"]:
    size = os.path.getsize(f"{out_dir}/{f}")
    print(f"  {f}: {size/1024:.1f} KB")

cur.close()
conn.close()
