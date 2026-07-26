import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# 检查 navi 引导点字段
cur.execute("""
    SELECT name, category, ST_AsText(geometry), entr_location
    FROM hefei_poi
    WHERE entr_location IS NOT NULL AND entr_location != ''
    LIMIT 15
""")
print("=== entr_location 样本 (导航入口坐标) ===")
for r in cur.fetchall():
    geom = r[2].replace("POINT(","").replace(")","")[:15]
    print(f"  {r[0]:25s} {r[1]:12s} POI=({geom})  entry=({r[3][:20]})")

cur.execute("""
    SELECT count(*) as total,
           count(entr_location) as has_navi,
           count(exit_location) as has_exit
    FROM hefei_poi
""")
total, navi, exit_ = cur.fetchone()
print(f"\n总计 {total}")
print(f"  有 navi 入口坐标: {navi} ({100*navi//total}%)")
print(f"  有 navi 出口坐标: {exit_} ({100*exit_//total}%)")

cur.close()
conn.close()
