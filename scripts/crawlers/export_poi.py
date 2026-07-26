import psycopg2, json, csv, os

out_dir = "E:/city-life-circle/data/合肥POI"
os.makedirs(out_dir, exist_ok=True)

conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# 导出 GeoJSON
print("Exporting GeoJSON...")
cur.execute("""
    SELECT json_build_object(
        'type', 'FeatureCollection',
        'features', json_agg(
            json_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(geometry)::json,
                'properties', json_build_object(
                    'id', id, 'name', name, 'category', category,
                    'sub_category', sub_category, 'address', address
                )
            )
        )
    ) FROM hefei_poi
""")
geojson = cur.fetchone()[0]
with open(f"{out_dir}/hefei_poi.geojson", "w", encoding="utf-8") as f:
    json.dump(geojson, f, ensure_ascii=False)
print(f"  -> hefei_poi.geojson ({len(geojson['features'])} features)")

# 导出 CSV
print("Exporting CSV...")
cur.execute("SELECT id, name, category, sub_category, address, ST_X(geometry) as lng, ST_Y(geometry) as lat FROM hefei_poi")
rows = cur.fetchall()
with open(f"{out_dir}/hefei_poi.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["id","name","category","sub_category","address","lng","lat"])
    w.writerows(rows)
print(f"  -> hefei_poi.csv ({len(rows)} rows)")

# 按分类统计
cur.execute("SELECT category, count(*) FROM hefei_poi GROUP BY category ORDER BY count(*) DESC")
print("\n分类统计:")
for r in cur.fetchall():
    print(f"  {r[0]:25s} {r[1]}")

cur.close()
conn.close()

# 列文件大小
for f in ["hefei_poi.geojson", "hefei_poi.csv"]:
    size = os.path.getsize(f"{out_dir}/{f}")
    print(f"\n{f}: {size/1024/1024:.1f} MB")
