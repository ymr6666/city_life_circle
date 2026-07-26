import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

cur.execute("UPDATE hefei_poi SET category='_tmp' WHERE category='kindergarten'")
cur.execute("UPDATE hefei_poi SET category='kindergarten' WHERE category='school_college'")
cur.execute("UPDATE hefei_poi SET category='school_college' WHERE category='_tmp'")
conn.commit()

cur.execute("SELECT category, count(*) FROM hefei_poi WHERE category IN ('kindergarten','school_college') GROUP BY category")
for r in cur.fetchall():
    # verify some names
    cur.execute("SELECT name FROM hefei_poi WHERE category=%s LIMIT 5", (r[0],))
    names = [row[0] for row in cur.fetchall()]
    print(f"{r[0]}: {r[1]} rows, samples: {names}")

# re-export
import json, csv, os
out_dir = "E:/city-life-circle/data/合肥POI"

cur.execute("SELECT json_build_object('type','FeatureCollection','features',json_agg(json_build_object('type','Feature','geometry',ST_AsGeoJSON(geometry)::json,'properties',json_build_object('name',name,'category',category,'sub_category',sub_category)))) FROM hefei_poi")
with open(f"{out_dir}/hefei_poi.geojson","w",encoding="utf-8") as f:
    json.dump(cur.fetchone()[0], f, ensure_ascii=False)
print(f"GeoJSON re-exported")

cur.execute("SELECT id,name,category,sub_category,address,ST_X(geometry),ST_Y(geometry) FROM hefei_poi")
rows = cur.fetchall()
with open(f"{out_dir}/hefei_poi.csv","w",encoding="utf-8-sig",newline="") as f:
    w = csv.writer(f)
    w.writerow(["id","name","category","sub_category","address","lng","lat"])
    w.writerows(rows)
print(f"CSV re-exported")

cur.execute("SELECT category,count(*) FROM hefei_poi GROUP BY category ORDER BY count(*) DESC")
print("\nFinal stats:")
for r in cur.fetchall():
    print(f"  {r[0]:25s} {r[1]}")

conn.close()
