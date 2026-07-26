import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='city_life_circle', user='postgres', password='admin')
conn.set_client_encoding('UTF8')
cur = conn.cursor()

# 找个有长路段的起始节点
cur.execute("""
  SELECT * FROM pgr_drivingDistance(
    'SELECT id, source, target, cost, reverse_cost FROM hefei_roads WHERE cost > 0',
    1000, 500, directed := false
  )
  ORDER BY cost
""")
rows = cur.fetchall()
print(f'从节点1000出发，500米内可到达 {len(rows)} 个节点')
for r in rows[:10]:
    print(f'  node={r[1]}, seq={r[0]}, cost={r[2]:.1f}m')

# 测试等时圈：获取 edge 范围
cur.execute("""
  SELECT * FROM pgr_drivingDistance(
    'SELECT id, source, target, cost, reverse_cost FROM hefei_roads WHERE cost > 0',
    1000, 1000, directed := false
  )
  ORDER BY cost
""")
rows = cur.fetchall()
max_cost = max(r[2] for r in rows) if rows else 0
print(f'\n从节点1000出发，1000米内可到达 {len(rows)} 个节点')
print(f'最远距离: {max_cost:.1f}m')

# 拿 GeoJSON 形式的 edge 范围
cur.execute("""
  SELECT json_build_object(
    'type', 'FeatureCollection',
    'features', json_agg(
      json_build_object(
        'type', 'Feature',
        'geometry', ST_AsGeoJSON(r.geometry)::json,
        'properties', json_build_object('cost', dd.cost)
      )
    )
  )
  FROM pgr_drivingDistance(
    'SELECT id, source, target, cost, reverse_cost FROM hefei_roads WHERE cost > 0',
    1000, 1000, directed := false
  ) dd
  JOIN hefei_roads r ON r.id = dd.edge
""")
geojson = cur.fetchone()[0]
print(f'\nGeoJSON 中的要素数: {len(geojson["features"])}')

cur.close()
conn.close()
