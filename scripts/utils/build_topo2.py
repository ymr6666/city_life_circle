import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='city_life_circle', user='postgres', password='admin')
conn.set_client_encoding('UTF8')
cur = conn.cursor()

cur.execute("SELECT count(*) FROM hefei_roads WHERE source IS NULL")
null_count = cur.fetchone()[0]
print(f"待更新 source/target 的行数: {null_count}")

if null_count > 0:
    cur.execute('CREATE INDEX IF NOT EXISTS idx_roads_u ON hefei_roads(u)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_roads_v ON hefei_roads(v)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_vertices_osm ON hefei_roads_vertices_pgr(osm_id)')
    conn.commit()
    print('索引创建完成')

    cur.execute('UPDATE hefei_roads r SET source = v.id FROM hefei_roads_vertices_pgr v WHERE v.osm_id = r.u')
    print(f'source 更新: {cur.rowcount} 行')

    cur.execute('UPDATE hefei_roads r SET target = v.id FROM hefei_roads_vertices_pgr v WHERE v.osm_id = r.v')
    print(f'target 更新: {cur.rowcount} 行')

    conn.commit()
    print('拓扑构建完成')
else:
    print('source/target 已更新')

cur.close()
conn.close()
