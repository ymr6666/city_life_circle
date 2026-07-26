import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# kindergarten 表的样本
cur.execute("SELECT name, sub_category FROM hefei_poi WHERE category='kindergarten' LIMIT 15")
print("=== kindergarten (本应是幼儿园) ===")
for r in cur.fetchall():
    print(f"  {r[0]:40s} {r[1]}")

print()
cur.execute("SELECT name, sub_category FROM hefei_poi WHERE category='school_college' LIMIT 15")
print("=== school_college (本应是大学) ===")
for r in cur.fetchall():
    print(f"  {r[0]:40s} {r[1]}")

conn.close()
