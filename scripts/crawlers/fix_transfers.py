"""修复地铁换乘站: 300m内相邻站合并"""
import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()

# 1. 找合并组
cur.execute("""
    WITH clusters AS (
        SELECT id, name, line_name,
               ST_ClusterDBSCAN(geometry, 0.003, 1) OVER () AS cid
        FROM hefei_metro_stations
    )
    SELECT cid, array_agg(id ORDER BY id), array_agg(DISTINCT line_name), count(*)
    FROM clusters WHERE cid IS NOT NULL
    GROUP BY cid HAVING count(*) > 1
    ORDER BY count(*) DESC
""")
clusters = cur.fetchall()
print(f"发现 {len(clusters)} 个合并组（300m 内多站点）")

for cid, ids, lines, cnt in clusters:
    keep_id = ids[0]
    del_ids = ids[1:]
    
    # 获取站点名
    cur.execute("SELECT id,name,line_name FROM hefei_metro_stations WHERE id = ANY(%s)", (ids,))
    stations = cur.fetchall()
    names = " | ".join([f"{n}({l})" for _, n, l in stations])
    
    # 合并 line_name
    all_lines = set()
    for _, n, l in stations:
        all_lines.update(l.split("|"))
    merged_lines = "|".join(sorted(all_lines))
    is_transfer = len(all_lines) > 1
    
    # 更新保留站的 line_name
    cur.execute("UPDATE hefei_metro_stations SET line_name=%s, is_transfer=%s WHERE id=%s",
                (merged_lines, is_transfer, keep_id))
    
    # 更新 edges 引用: 将被删站的引用改到保留站
    cur.execute("UPDATE hefei_metro_edges SET station_from=%s WHERE station_from = ANY(%s)",
                (keep_id, del_ids))
    cur.execute("UPDATE hefei_metro_edges SET station_to=%s WHERE station_to = ANY(%s)",
                (keep_id, del_ids))
    
    # 删除被合并站
    cur.execute("DELETE FROM hefei_metro_stations WHERE id = ANY(%s)", (del_ids,))
    
    if is_transfer:
        print(f"  [换乘] {names[:80]}")
    else:
        print(f"  [同名合并] {names[:80]}")

conn.commit()

# 统计
cur.execute("SELECT count(*) FROM hefei_metro_stations")
total = cur.fetchone()[0]
cur.execute("SELECT count(*) FROM hefei_metro_stations WHERE is_transfer=true")
transfer = cur.fetchone()[0]
print(f"\n合并后站点: {total}, 换乘站: {transfer}")

cur.execute("SELECT name, line_name FROM hefei_metro_stations WHERE is_transfer=true ORDER BY name")
t_stations = cur.fetchall()
if t_stations:
    print("\n换乘站详情:")
    for r in t_stations:
        print(f"  {r[0]:20s} {r[1]}")

cur.execute("SELECT line_name, count(*) FROM hefei_metro_stations GROUP BY line_name ORDER BY line_name")
print("\n按线路统计:")
for r in cur.fetchall():
    print(f"  {r[0]:30s} {r[1]} stations")

cur.close()
conn.close()
