import psycopg2

conn = psycopg2.connect(host='localhost', port=5432, dbname='city_life_circle', user='postgres', password='admin')
conn.set_client_encoding('UTF8')
cur = conn.cursor()

cur.execute('SELECT id, length, cost, ST_Length(geometry::geography) AS len_m FROM hefei_roads LIMIT 10')
rows = cur.fetchall()
for r in rows:
    print(f'id={r[0]} length={r[1]} cost={r[2]} len_m={r[3]:.1f}')

cur.close()
conn.close()
