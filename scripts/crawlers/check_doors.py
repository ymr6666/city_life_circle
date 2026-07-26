import psycopg2
c = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin').cursor()

# 搜含 '门' 的 POI
cats = ['mall','supermarket','hospital','park','school_primary','school_junior',
        'school_senior','school_college','market_food','kindergarten','street_commercial']

for cat in cats:
    c.execute("SELECT name,sub_category FROM hefei_poi WHERE category=%s AND (name LIKE %s OR name LIKE %s) LIMIT 5", (cat, '%门%', '%入口%'))
    rows = c.fetchall()
    if rows:
        print(f'\n=== {cat} ===')
        for r in rows:
            print(f'  {r[0]:40s} {r[1]}')

# 各类别含入口标记的统计
print('\n=== 含 "门"/"入口" 的POI 按类别统计 ===')
c.execute("SELECT category, count(*) FROM hefei_poi WHERE name LIKE '%门%' OR name LIKE '%入口%' GROUP BY category ORDER BY count(*) DESC")
for r in c.fetchall():
    print(f'  {r[0]:25s} {r[1]}')

# 全部POI含入口的比例
c.execute("SELECT count(*) FROM hefei_poi WHERE name LIKE '%门%' OR name LIKE '%入口%'")
door_pois = c.fetchone()[0]
c.execute("SELECT count(*) FROM hefei_poi")
total = c.fetchone()[0]
print(f'\n含门/入口的POI: {door_pois} / {total} ({100*door_pois//total}%)')

c.close()
