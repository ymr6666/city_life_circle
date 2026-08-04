# -*- coding: utf-8 -*-
"""POI 设施分组 (展示去重): 生成 facility_id / facility_name

背景: 高德 POI 爬取会返回同一设施的多个科室/楼宇 POI (如 安徽省立医院 30 条:
门诊部/住院部/急诊/行政楼/各诊疗中心 + 西区/南区/总院)。
  - 引擎按点独立可达, 这个粒度有意义, 保持不变 (不动 poi_road_nodes/canonical_poi_id)
  - 展示时合并为"一个设施"

方法:
  1. base_name = 名称剥离科室/楼宇后缀 + 括号别名/院区修饰 (如 "(安徽省立医院)", 总院)
  2. 按 (category, base_name) 分组
  3. 组内按距离聚类 (eps 米, 默认 1500): 距离近的并为一个设施; 相距远的院区自动拆开
     (同时避免把同名连锁店误并)
  4. 代表 = 组内名称最短者 (医院本体名最短); facility_id=代表id, facility_name=代表名

用法:
  python group_poi_facilities.py          # eps 默认 1500m
  python group_poi_facilities.py --eps 800
"""
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import psycopg2
from psycopg2.extras import execute_values

# ── 科室/楼宇后缀 (从末尾剥离, 长词优先) ─────────────────────
DEPT_SUFFIX_RE = re.compile(
    r'(?:(?:医学保健|医疗保健|健康管理|口腔医学|脑血管病诊疗|脑胶质瘤诊疗|泛血管疾病管理|'
    r'血液净化|眼视光|眼底病|影像|诊疗)中心|'
    r'(?:门诊|住院)[部楼]|急诊科?|'
    r'(?:行政|医技|综合|医疗|住院|门诊)楼|'
    r'\d+号楼|护理部|体检中心?|手术室|放疗科|产科|儿科|口腔科|眼科门诊|'
    r'核医学科|检验科|病理科|影像科|放射科|超声科|检验中心|预防接种门诊)$'
)

# 括号内别名/院区 (剥离 "(安徽省立医院)" "(西区)" 等)
PAREN_ALIAS = (
    '西区', '南区', '东区', '北区', '本部', '总院', '院区', '老院区', '新院区',
    '南院区', '北院区', '分院', '校区', '安徽省立医院', '主院区', '滨湖院区', '政务院区',
)

# 末尾院区限定词 (总院/西区/本部 ...)
CAMPUS_TAIL = (
    '主院区', '老院区', '新院区', '南院区', '北院区', '东院区', '西院区', '滨湖院区',
    '政务院区', '院区', '总院', '本部', '分院', '校区', '西区', '南区', '东区', '北区',
)


def base_name(name):
    """剥离科室/楼宇/院区修饰, 得到设施基础名; 返回 (base, score)

    score = 剥离操作次数, 用于选代表: 剥离越少的越接近设施本体 (如 医院本体 vs 急诊)。
    """
    n = (name or '').strip()
    if not n:
        return n, 0
    score = 0
    while True:
        m = DEPT_SUFFIX_RE.search(n)
        if not m or len(n) <= len(m.group(0)) + 4:
            break
        n = n[:m.start()].rstrip()
        score += 1
    m = re.search(r'\(([^()]*)\)$', n)
    if m and m.group(1) in PAREN_ALIAS:
        n = n[:m.start()].rstrip()
        score += 1
    for c in sorted(CAMPUS_TAIL, key=len, reverse=True):
        if n.endswith(c) and len(n) > len(c) + 3:
            n = n[:-len(c)].rstrip()
            score += 1
            break
    return n.rstrip(' -·—_'), score


def haversine(lng1, lat1, lng2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(a))


def cluster(members, eps):
    """members: list of (id, lng, lat) 按距离并查集聚类, 返回 [cluster_id] 列表"""
    n = len(members)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        _, lng_i, lat_i = members[i]
        for j in range(i + 1, n):
            _, lng_j, lat_j = members[j]
            if haversine(lng_i, lat_i, lng_j, lat_j) < eps:
                union(i, j)
    return [find(i) for i in range(n)]


def main():
    eps = 1500.0
    if '--eps' in sys.argv:
        eps = float(sys.argv[sys.argv.index('--eps') + 1])

    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()

    cur.execute("ALTER TABLE hefei_poi ADD COLUMN IF NOT EXISTS facility_id INTEGER")
    cur.execute("ALTER TABLE hefei_poi ADD COLUMN IF NOT EXISTS facility_name TEXT")
    conn.commit()

    cur.execute("""
        SELECT id, category, name, ST_X(geometry), ST_Y(geometry)
        FROM hefei_poi ORDER BY id
    """)
    rows = cur.fetchall()
    print(f"总 POI: {len(rows)}")

    # 计算 base_name 并分组
    groups = {}
    for pid, cat, name, lng, lat in rows:
        bn, _ = base_name(name)
        g = groups.setdefault((cat, bn), [])
        g.append((pid, name, lng, lat))

    updates = []          # (facility_id, facility_name, poi_id)
    facility_count = 0
    merged_count = 0
    examples = []
    for (cat, bn), members in groups.items():
        if len(members) <= 1:
            pid, name = members[0][0], members[0][1]
            updates.append((pid, name or bn, pid))
            continue
        cids = cluster([(m[0], m[2], m[3]) for m in members], eps)
        clusters = {}
        for (pid, name, _, _), cid in zip(members, cids):
            clusters.setdefault(cid, []).append((pid, name))
        for cid, cluster_members in clusters.items():
            # 代表 = 剥离次数最少 → 名称最短 → id 最小 (医院本体优先于科室)
            rep = min(cluster_members,
                      key=lambda m: (base_name(m[1])[1], len(m[1]), m[0]))
            for pid, name in cluster_members:
                updates.append((rep[0], rep[1], pid))
            facility_count += 1
            if len(cluster_members) > 1:
                merged_count += len(cluster_members)
                if len(examples) < 12:
                    examples.append((cat, rep[1], [m[1] for m in cluster_members[:6]]))

    execute_values(cur, """
        UPDATE hefei_poi SET facility_id = data.fid, facility_name = data.fname
        FROM (VALUES %s) AS data (fid, fname, id)
        WHERE hefei_poi.id = data.id
    """, updates, page_size=2000)
    conn.commit()

    n_fac = len({u[0] for u in updates})
    print(f"设施总数: {n_fac} | 有分组成员(合并)的点: {merged_count} | 更新: {len(updates)}")
    print(f"\n分组示例 (eps={eps}m):")
    for cat, rep, members in examples:
        print(f"  [{cat}] {rep}  ({len(members)}个: {' | '.join(members)})")

    cur.close()
    conn.close()
    print("\n完成!")


if __name__ == "__main__":
    main()
