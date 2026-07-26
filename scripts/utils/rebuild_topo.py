import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='city_life_circle', user='postgres', password='admin')
conn.set_client_encoding('UTF8')
cur = conn.cursor()

print('创建顶点表...')
cur.execute("""
  CREATE TABLE hefei_roads_vertices_pgr AS
  SELECT ROW_NUMBER() OVER (ORDER BY osmid) AS id, osmid AS osm_id, y AS x, x AS y, geometry
  FROM hefei_nodes
""")
cur.execute("ALTER TABLE hefei_roads_vertices_pgr ADD PRIMARY KEY (id)")
conn.commit()

print('添加拓扑列...')
cur.execute("ALTER TABLE hefei_roads ADD COLUMN id SERIAL PRIMARY KEY")
cur.execute("ALTER TABLE hefei_roads ADD COLUMN source INTEGER")
cur.execute("ALTER TABLE hefei_roads ADD COLUMN target INTEGER")
cur.execute("ALTER TABLE hefei_roads ADD COLUMN cost DOUBLE PRECISION")
cur.execute("ALTER TABLE hefei_roads ADD COLUMN reverse_cost DOUBLE PRECISION")
conn.commit()

print('创建索引...')
cur.execute("CREATE INDEX idx_roads_u ON hefei_roads(u)")
cur.execute("CREATE INDEX idx_roads_v ON hefei_roads(v)")
cur.execute("CREATE INDEX idx_vertices_osm ON hefei_roads_vertices_pgr(osm_id)")
conn.commit()

print('关联 source/target...')
cur.execute("UPDATE hefei_roads r SET source = v.id FROM hefei_roads_vertices_pgr v WHERE v.osm_id = r.u")
print(f'  source: {cur.rowcount} 行')
cur.execute("UPDATE hefei_roads r SET target = v.id FROM hefei_roads_vertices_pgr v WHERE v.osm_id = r.v")
print(f'  target: {cur.rowcount} 行')

print('设置 cost...')
cur.execute("SELECT count(*) FROM hefei_roads WHERE length IS NULL")
null_len = cur.fetchone()[0]
if null_len > 0:
    cur.execute("UPDATE hefei_roads SET length = ST_Length(geometry::geography) WHERE length IS NULL")
cur.execute("UPDATE hefei_roads SET cost = length, reverse_cost = length")
print(f'  cost: {cur.rowcount} 行')

conn.commit()

# 验证
cur.execute("SELECT count(*) FROM hefei_roads WHERE source IS NOT NULL AND target IS NOT NULL")
print(f'\n验证: {cur.fetchone()[0]}/95924 条路段已连接')

cur.execute("""
  SELECT count(*), max(agg_cost)
  FROM pgr_drivingDistance(
    'SELECT id, source, target, cost, reverse_cost FROM hefei_roads WHERE cost > 0',
    1, 1000, directed := false
  )
""")
cnt, maxc = cur.fetchone()
print(f'pgRouting 测试: 从节点1出发1000m内可到达 {cnt} 个节点，最远 {maxc:.1f}m')

cur.close()
conn.close()
