import psycopg2
conn = psycopg2.connect(host='localhost', port=5432, dbname='city_life_circle', user='postgres', password='admin')
conn.set_client_encoding('UTF8')
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
tables = [r[0] for r in cur.fetchall()]
for t in tables:
    cur.execute(f"SELECT count(*) FROM {t}")
    c = cur.fetchone()[0]
    print(f'  {t:35s} {c:>8} rows')
cur.close()
conn.close()
