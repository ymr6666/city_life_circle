import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# 三甲 + 主要医院
cur.execute("SELECT name FROM hefei_poi WHERE category='hospital' AND sub_category LIKE '%090101%' ORDER BY name")
print("=== 现有三甲 ===")
for r in cur.fetchall():
    print(f"  {r[0]}")
print(f"  共 {cur.rowcount} 个")

# 大医院
cur.execute("SELECT name FROM hefei_poi WHERE category='school_college' ORDER BY name LIMIT 10")
print("\n=== 大学样本 ===")
for r in cur.fetchall():
    print(f"  {r[0]}")

# 看看有没有重复名字的医院 (same name, diff id)
cur.execute("""
    SELECT name, count(*) FROM hefei_poi WHERE category='hospital'
    GROUP BY name HAVING count(*) > 1 ORDER BY count(*) DESC LIMIT 10
""")
print("\n=== 仍有重名的医院 ===")
for r in cur.fetchall():
    print(f"  {r[0]:40s} x{r[1]}")

conn.close()
