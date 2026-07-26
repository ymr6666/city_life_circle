import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='city_life_circle', user='postgres', password='admin')
conn.set_client_encoding('UTF8')
cur = conn.cursor()

# pgr_drivingDistance returns: (seq, node, edge, cost, agg_cost)
# cost = edge cost, agg_cost = cumulative cost from source
cur.execute("""
  SELECT seq, node, edge, cost, agg_cost
  FROM pgr_drivingDistance(
    'SELECT id, source, target, cost, reverse_cost FROM hefei_roads WHERE cost > 0',
    1000, 500, directed := false
  )
  ORDER BY agg_cost
  LIMIT 20
""")
rows = cur.fetchall()
print('节点1000出发 500米内 (按累计距离排序):')
for r in rows:
    print(f'  node={r[1]}  edge={r[2]}  edge_cost={r[3]:.1f}m  agg_cost={r[4]:.1f}m')

cur.execute("""
  SELECT count(*), max(agg_cost), min(agg_cost), avg(agg_cost)
  FROM pgr_drivingDistance(
    'SELECT id, source, target, cost, reverse_cost FROM hefei_roads WHERE cost > 0',
    1000, 500, directed := false
  )
""")
count, max_c, min_c, avg_c = cur.fetchone()
print(f'\n500m: {count}个节点, agg_cost范围 {min_c:.1f}m ~ {max_c:.1f}m, 平均 {avg_c:.1f}m')

cur.close()
conn.close()
