"""验证新字段、去重、导出"""
import psycopg2, json, csv, os
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# 检查新字段填充率
fields = ['entr_location','business_area','rating','cost','opentime_today','alias','navi_poiid']
print("=== 新字段填充率 ===")
cur.execute("SELECT count(*) FROM hefei_poi")
total = cur.fetchone()[0]
print(f"Total POIs: {total}")
for fld in fields:
    cur.execute(f"SELECT count(*) FROM hefei_poi WHERE {fld} IS NOT NULL AND {fld} != ''")
    cnt = cur.fetchone()[0]
    print(f"  {fld:20s}: {cnt:>5} ({100*cnt//total}%)")

# 去重 (300m聚类)
print("\n=== 去重 (300m 聚类) ===")
cats_merge = ['hospital','kindergarten','school_primary','school_junior','school_senior','school_college']
for cat in cats_merge:
    cur.execute("""
        WITH c AS (
            SELECT id, category,
                   ST_ClusterDBSCAN(geometry,0.003,1) OVER(PARTITION BY category) AS cid
            FROM hefei_poi WHERE category=%s
        ), keep AS (
            SELECT MIN(id) AS kid FROM c WHERE cid IS NOT NULL GROUP BY category, cid
        )
        DELETE FROM hefei_poi
        WHERE category=%s AND id NOT IN (SELECT kid FROM keep)
          AND id IN (SELECT id FROM c WHERE cid IS NOT NULL)
    """, (cat,cat))
    cur.execute("SELECT count(*) FROM hefei_poi WHERE category=%s", (cat,))
    print(f"  {cat:20s}: {cur.fetchone()[0]:>5} rows")

cur.execute("SELECT count(*) FROM hefei_poi")
total = cur.fetchone()[0]
conn.commit()
print(f"\nAfter dedup: {total}")

# 统计
cur.execute("SELECT category,count(*) FROM hefei_poi GROUP BY category ORDER BY count(*) DESC")
print("\n=== Final stats ===")
for r in cur.fetchall():
    print(f"  {r[0]:25s} {r[1]}")

cur.close(); conn.close()
