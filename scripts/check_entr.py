import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

cur.execute("SELECT count(*) FROM hefei_poi")
print(f"Total: {cur.fetchone()[0]}")

cur.execute("SELECT count(*) FROM hefei_poi WHERE entr_location IS NOT NULL AND entr_location != ''")
print(f"Have entr_location: {cur.fetchone()[0]}")

cur.execute("""
    SELECT category, count(*) FROM hefei_poi 
    WHERE entr_location IS NULL OR entr_location = ''
    GROUP BY category ORDER BY count(*) DESC
""")
print("\nMissing entr_location:")
for r in cur.fetchall():
    print(f"  {r[0]:25s} {r[1]}")

# 超市没有被去重
cur.execute("SELECT count(*) FROM hefei_poi WHERE category='supermarket'")
print(f"\nSupermarket (not deduped): {cur.fetchone()[0]}")

conn.close()
