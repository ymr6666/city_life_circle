import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()
cur.execute("SELECT count(*) FROM hefei_poi WHERE exit_location IS NOT NULL AND exit_location != ''")
print(f'exit_location 有数据: {cur.fetchone()[0]}')
cur.execute("SELECT count(*) FROM hefei_poi WHERE exit_location IS NOT NULL AND exit_location != '' AND exit_location != 'null'")
print(f'  排除 null 字符串后: {cur.fetchone()[0]}')
conn.close()
