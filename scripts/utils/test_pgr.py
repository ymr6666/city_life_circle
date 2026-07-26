import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='city_life_circle', user='postgres', password='admin')
conn.set_client_encoding('UTF8')
cur = conn.cursor()

cur.execute("SELECT count(*) FROM hefei_roads WHERE source IS NOT NULL AND target IS NOT NULL")
print(f'已连接的路段: {cur.fetchone()[0]} / 57570')

# 测试 pgRouting: 从节点 1 出发，距离 1000 米内的所有路段
cur.execute("""
  SELECT * FROM pgr_drivingDistance(
    'SELECT id, source, target, cost, reverse_cost FROM hefei_roads',
    1, 1000, directed := false
  ) LIMIT 10
""")
rows = cur.fetchall()
print(f'pgRouting 测试: 从节点1出发1000米内可到达 {len(rows)} 条路段（显示前10）')
for r in rows[:5]:
    print(f'  node={r[1]}, cost={r[2]:.1f}m')

cur.close()
conn.close()
