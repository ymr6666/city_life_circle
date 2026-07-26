import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='city_life_circle', user='postgres', password='admin')
conn.set_client_encoding('UTF8')
cur = conn.cursor()

cur.execute("SELECT count(*) FROM hefei_roads WHERE cost IS NULL")
null_cost = cur.fetchone()[0]
print(f'cost 为空的行: {null_cost}')

cur.execute("SELECT count(*) FROM hefei_roads WHERE length IS NULL")
null_len = cur.fetchone()[0]
print(f'length 为空的行: {null_len}')

# 用 ST_Length 补全缺失的长度
cur.execute("UPDATE hefei_roads SET length = ST_Length(geometry::geography) WHERE length IS NULL")
print(f'补充长度: {cur.rowcount} 行')

# 重新设置 cost
cur.execute("UPDATE hefei_roads SET cost = COALESCE(length, ST_Length(geometry::geography)), reverse_cost = COALESCE(length, ST_Length(geometry::geography))")
print(f'cost 更新: {cur.rowcount} 行')

conn.commit()
cur.close()
conn.close()
print('完成')
