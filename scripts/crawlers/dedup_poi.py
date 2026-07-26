"""合并同一医院/同一学校的重复 POI
用空间聚类 (300m内 + 同类别) 合并，只保留每类第一个 POI"""
import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# 每个类别（尤其是医院、学校）需要合并
cats_to_merge = ['hospital', 'kindergarten', 'school_primary', 'school_junior',
                 'school_senior', 'school_college']

for cat in cats_to_merge:
    # 在 hefei_poi 上做空间聚类，每类用 300m 阈值
    cur.execute("""
        WITH clustered AS (
            SELECT id, category, sub_category, name,
                   ST_ClusterDBSCAN(geometry, 0.003, 1) OVER (PARTITION BY category) AS cid
            FROM hefei_poi
            WHERE category = %s
        ),
        keep_ids AS (
            SELECT MIN(id) AS keep_id
            FROM clustered
            WHERE cid IS NOT NULL
            GROUP BY category, cid
        )
        DELETE FROM hefei_poi
        WHERE category = %s
          AND id NOT IN (SELECT keep_id FROM keep_ids)
          AND id IN (SELECT id FROM clustered WHERE cid IS NOT NULL)
    """, (cat, cat))

    cur.execute("SELECT count(*) FROM hefei_poi WHERE category=%s", (cat,))
    remaining = cur.fetchone()[0]
    print(f"{cat}: {remaining} 行 (去除重复后)")

conn.commit()
cur.close()
conn.close()
print("\n去重完成")
