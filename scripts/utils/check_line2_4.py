import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# Line 2 站点
cur.execute("SELECT name, ST_X(geometry), ST_Y(geometry) FROM hefei_metro_stations WHERE line_name LIKE '%2%' ORDER BY ST_X(geometry)")
print(f"=== Line 2: {cur.rowcount} 站 ===")
for r in cur.fetchall():
    print(f"  {r[0]:20s} ({r[1]:.4f}, {r[2]:.4f})")

# Line 4 站点
cur.execute("SELECT name, ST_X(geometry), ST_Y(geometry) FROM hefei_metro_stations WHERE line_name LIKE '%4%' ORDER BY ST_X(geometry)")
print(f"\n=== Line 4: {cur.rowcount} 站 ===")
for r in cur.fetchall():
    print(f"  {r[0]:20s} ({r[1]:.4f}, {r[2]:.4f})")

# 检查是否有站名含 南岗 的
cur.execute("SELECT name FROM hefei_metro_stations WHERE name LIKE '%南岗%'")
print(f"\n含 南岗 的站: {[r[0] for r in cur.fetchall()]}")

# 所有线路统计
cur.execute("SELECT line_name, count(*) FROM hefei_metro_stations GROUP BY line_name ORDER BY line_name")
print("\n按线路统计:")
for r in cur.fetchall():
    print(f"  {r[0]:15s} {r[1]} stations")

conn.close()
