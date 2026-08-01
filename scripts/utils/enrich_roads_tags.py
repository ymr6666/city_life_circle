# -*- coding: utf-8 -*-
"""增量获取 OSM 路网缺失 tag 并细化桥隧分类

背景:
    hefei_roads 由 osmnx 导入，默认只保留 bridge/tunnel/lanes 等少量 tag。
    本脚本通过 Overpass 按 way id 增量拉取缺失的
    layer / foot / bicycle / motor_vehicle / sidewalk / cycleway / surface / lit 等，
    回填到 hefei_roads，并计算:
      - bridge_class : none / bridge / elevated / tunnel / footbridge   (物理结构档)
      - walk_ok      : 行人可达
      - cycle_ok     : 骑行可达
      - drive_ok     : 机动车可达

注意: 部分 osmid 为 osmnx 合并后的 "[a, b, c]" 格式，本脚本会展开并对
      多个源 way 的 tag 做聚合 (access 类取最严格, layer 取最大, bridge/tunnel 取任一 yes)。

用法:
    python enrich_roads_tags.py                # 抓取 + 回填 + 分类
    python enrich_roads_tags.py --fetch-only   # 只抓取写缓存 (cache/roads_tags.json)
    python enrich_roads_tags.py --classify-only# 只回填 + 分类 (使用已有缓存)
"""
import json
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import psycopg2

CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'cache', 'roads_tags.json')
BBOX = (31.68, 117.07, 32.07, 117.50)  # south, west, north, east

HEADERS = {"User-Agent": "city-life-circle/1.0 (student project)"}
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
CHUNK = 400          # 每请求 way 数
SLEEP = 1.0          # 请求间隔 (sec), 保持 <2 req/s
RETRY = 2

# 需要抓取的 tag
TAG_COLS = [
    "layer", "foot", "bicycle", "motor_vehicle", "vehicle", "access",
    "sidewalk", "cycleway", "surface", "smoothness", "lit",
    "segregated", "oneway:bicycle", "incline",
]


_dead_mirrors = set()


def overpass_query(query, timeout=60):
    """跨镜像重试 (跳过最近失败过的镜像)"""
    last_err = None
    for mirror in MIRRORS:
        if mirror in _dead_mirrors:
            continue
        for attempt in range(RETRY):
            try:
                r = requests.post(mirror, data={"data": query},
                                  headers=HEADERS, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                last_err = f"{mirror} -> {r.status_code}"
            except Exception as e:
                last_err = f"{mirror} -> {e}"
            time.sleep(2 + attempt * 2)
        # 一轮全失败 → 拉黑, 换下一个镜像
        _dead_mirrors.add(mirror)
    print(f"  [WARN] query failed after retries: {last_err}", flush=True)
    return None


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


def fetch_tags(way_ids, cache):
    """按 id 分批抓取，返回缺失部分更新后的 cache"""
    missing = [w for w in way_ids if str(w) not in cache]
    print(f"way ids: {len(way_ids)}, 已缓存: {len(way_ids) - len(missing)}, 待抓: {len(missing)}")
    if not missing:
        return cache

    for i in range(0, len(missing), CHUNK):
        chunk = missing[i:i + CHUNK]
        q = f"[out:json][timeout:90];\nway(id:{','.join(map(str, chunk))});\nout tags;\n"
        data = overpass_query(q)
        if data and data.get("elements"):
            for el in data["elements"]:
                if el.get("tags"):
                    cache[str(el["id"])] = el["tags"]
        save_cache(cache)  # 增量落盘，防中断丢进度
        if (i // CHUNK) % 10 == 0:
            print(f"  fetched {min(i + CHUNK, len(missing))}/{len(missing)}", flush=True)
        time.sleep(SLEEP)
    return cache


# ────────────────────────────────────────────────────────────
# 聚合规则: 一个边(osmid 可能是 [a,b,c]) 的 tag 如何从源 way 合并
# ────────────────────────────────────────────────────────────
ACCESS_RESTRICT = ("no", "private", "destination", "customers")  # 越靠前越严格


def pick_access(values):
    """access 类 tag: 最严格优先, 其次第一个非空"""
    vals = [v for v in values if v]
    if not vals:
        return None
    for r in ACCESS_RESTRICT:
        if r in vals:
            return r
    return vals[0]


def pick_first(values):
    vals = [v for v in values if v]
    return vals[0] if vals else None


def pick_max_layer(values):
    nums = []
    for v in values:
        m = re.match(r"-?\d+", str(v))
        if m:
            nums.append(int(m.group()))
    if nums:
        return str(max(nums))
    return pick_first(values)


def pick_yes(values):
    vals = [v for v in values if v]
    for v in vals:
        if "yes" in v or "viaduct" in v:
            return v
    return pick_first(vals)


def aggregate_tags(way_tags_list):
    """way_tags_list: [ {tag:val}, ... ] -> 聚合后的单个 tag dict"""
    if len(way_tags_list) == 1:
        return way_tags_list[0]
    agg = {}
    for col in TAG_COLS:
        values = [t.get(col) for t in way_tags_list]
        if col == "layer":
            agg[col] = pick_max_layer(values)
        elif col in ("access", "foot", "bicycle", "motor_vehicle", "vehicle"):
            agg[col] = pick_access(values)
        else:
            agg[col] = pick_first(values)
    # bridge/tunnel 独立处理: 任一源 way 为桥/隧道即视为桥/隧道
    agg["bridge"] = pick_yes([t.get("bridge") for t in way_tags_list])
    agg["tunnel"] = pick_yes([t.get("tunnel") for t in way_tags_list])
    return agg


def expand_osmid(osmid_str):
    return [int(x) for x in re.findall(r"\d+", osmid_str or "")]


# ────────────────────────────────────────────────────────────
# DB 回填 + 分类
# ────────────────────────────────────────────────────────────
def enrich_db(cache):
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding("UTF8")
    cur = conn.cursor()

    # 1. 加列
    print("\n[DB] adding columns...")
    for col in TAG_COLS:
        db_col = col.replace(":", "_").replace("-", "_")
        cur.execute(f"ALTER TABLE hefei_roads ADD COLUMN IF NOT EXISTS {db_col} TEXT")
    cur.execute("ALTER TABLE hefei_roads ADD COLUMN IF NOT EXISTS bridge_class TEXT")
    cur.execute("ALTER TABLE hefei_roads ADD COLUMN IF NOT EXISTS walk_ok BOOLEAN")
    cur.execute("ALTER TABLE hefei_roads ADD COLUMN IF NOT EXISTS cycle_ok BOOLEAN")
    cur.execute("ALTER TABLE hefei_roads ADD COLUMN IF NOT EXISTS drive_ok BOOLEAN")
    conn.commit()

    # 2. 聚合每个 distinct osmid 的 tag
    print("[DB] aggregating tags per osmid...")
    cur.execute("SELECT DISTINCT osmid FROM hefei_roads")
    osmids = [r[0] for r in cur.fetchall()]
    rows = []
    for o in osmids:
        ids = expand_osmid(o)
        tags_list = [cache.get(str(w), {}) for w in ids]
        tags_list = [t for t in tags_list if t]
        if not tags_list:
            continue
        agg = aggregate_tags(tags_list)
        rows.append((o, agg))
    print(f"  resolved {len(rows)} / {len(osmids)} osmids")

    # 3. 写入临时表并回填
    from psycopg2.extras import execute_values
    cur.execute("DROP TABLE IF EXISTS tmp_road_tags")
    cols_sql = ", ".join(c.replace(":", "_").replace("-", "_") for c in TAG_COLS)
    cur.execute(f"""
        CREATE TEMP TABLE tmp_road_tags (
            osmid TEXT PRIMARY KEY,
            {', '.join(f'{c.replace(chr(58),chr(95)).replace(chr(45),chr(95))} TEXT' for c in TAG_COLS)}
        )
    """)
    data = [(o, *(agg.get(c) for c in TAG_COLS)) for o, agg in rows]
    execute_values(cur,
                   f"INSERT INTO tmp_road_tags (osmid, {cols_sql}) VALUES %s",
                   data, page_size=2000)
    conn.commit()
    print(f"  inserted {len(rows)} rows into tmp_road_tags")

    print("[DB] updating hefei_roads...")
    set_clause = ", ".join(
        f"{c.replace(':','_').replace('-','_')} = t.{c.replace(':','_').replace('-','_')}"
        for c in TAG_COLS)
    cur.execute(f"""
        UPDATE hefei_roads r SET {set_clause}
        FROM tmp_road_tags t WHERE r.osmid = t.osmid
    """)
    conn.commit()
    print(f"  updated {cur.rowcount} road rows")

    # 4. 分类
    classify(cur, conn)
    cur.close()
    conn.close()


def classify(cur, conn):
    """四档桥隧分类 + walk/cycle/drive 可达列"""
    print("\n[DB] classifying bridge_class...")
    cur.execute("""
        UPDATE hefei_roads SET bridge_class = CASE
            WHEN tunnel IS NOT NULL AND tunnel != ''
                 AND (tunnel LIKE '%yes%' OR tunnel LIKE '%viaduct%')
            THEN 'tunnel'
            WHEN bridge IS NOT NULL AND bridge != ''
                 AND (bridge LIKE '%yes%' OR bridge LIKE '%viaduct%')
            THEN CASE
                WHEN layer IS NOT NULL AND layer != ''
                     AND layer ~ '^-?[0-9]+$' AND layer::int > 0
                THEN 'elevated'
                WHEN highway LIKE '%footway%' OR highway LIKE '%pedestrian%'
                     OR highway LIKE '%path%' OR highway LIKE '%steps%'
                     OR highway LIKE '%cycleway%'
                THEN 'footbridge'
                ELSE 'bridge'
            END
            ELSE NULL
        END
    """)
    conn.commit()

    print("[DB] classifying walk_ok / cycle_ok / drive_ok...")

    # 非机动车禁止的高架/快速路 (motorway/trunk 及 link, 含数组值)
    no_ped = ("COALESCE(highway,'') NOT IN ('motorway','motorway_link','trunk','trunk_link')"
              " AND COALESCE(highway,'') NOT LIKE '%motorway%'"
              " AND COALESCE(highway,'') NOT LIKE '%trunk%'")

    # 立交高架: bridge_class=elevated, 或 无 layer 的 primary/secondary 桥(回退启发式)
    elevated = ("COALESCE(bridge_class,'') = 'elevated'"
                " OR (COALESCE(bridge,'') LIKE '%yes%' AND layer IS NULL"
                "     AND (COALESCE(highway,'') LIKE '%primary%'"
                "          OR COALESCE(highway,'') LIKE '%secondary%'))")

    # 车行隧道(人行/骑行禁入)
    veh_tunnel = ("COALESCE(tunnel,'') LIKE '%yes%' AND COALESCE(highway,'') NOT LIKE '%footway%'"
                  " AND COALESCE(highway,'') NOT LIKE '%pedestrian%'"
                  " AND COALESCE(highway,'') NOT LIKE '%path%'"
                  " AND COALESCE(highway,'') NOT LIKE '%steps%'"
                  " AND COALESCE(highway,'') NOT LIKE '%cycleway%'")

    walk_ok = f"""
        {no_ped}
        AND NOT ({elevated})
        AND NOT ({veh_tunnel})
        AND COALESCE(foot,'') <> 'no'
        AND NOT (COALESCE(access,'') = 'no'
                 AND COALESCE(foot,'') NOT IN ('yes','designated','permissive'))
        AND COALESCE(access,'') <> 'private'
    """
    cycle_ok = f"""
        {no_ped}
        AND NOT ({elevated})
        AND NOT ({veh_tunnel})
        AND COALESCE(bridge_class,'') <> 'footbridge'
        AND COALESCE(highway,'') NOT LIKE '%steps%'
        AND COALESCE(bicycle,'') <> 'no'
        AND NOT (COALESCE(access,'') = 'no'
                 AND COALESCE(bicycle,'') NOT IN ('yes','designated','permissive'))
    """
    drive_ok = f"""
        (COALESCE(highway,'') IN ('motorway','motorway_link','trunk','trunk_link',
                     'primary','primary_link','secondary','secondary_link',
                     'tertiary','tertiary_link','unclassified','residential',
                     'living_street','service','busway','track')
         OR COALESCE(highway,'') LIKE '%motorway%' OR COALESCE(highway,'') LIKE '%trunk%'
         OR COALESCE(highway,'') LIKE '%primary%' OR COALESCE(highway,'') LIKE '%secondary%'
         OR COALESCE(highway,'') LIKE '%tertiary%' OR COALESCE(highway,'') LIKE '%residential%'
         OR COALESCE(highway,'') LIKE '%service%' OR COALESCE(highway,'') LIKE '%unclassified%'
         OR COALESCE(highway,'') LIKE '%busway%' OR COALESCE(highway,'') LIKE '%living_street%')
        AND COALESCE(highway,'') NOT LIKE '%footway%' AND COALESCE(highway,'') NOT LIKE '%pedestrian%'
        AND COALESCE(highway,'') NOT LIKE '%path%' AND COALESCE(highway,'') NOT LIKE '%steps%'
        AND COALESCE(highway,'') NOT LIKE '%cycleway%' AND COALESCE(highway,'') NOT LIKE '%corridor%'
        AND COALESCE(motor_vehicle,'') <> 'no'
        AND NOT (COALESCE(access,'') IN ('no','private')
                 AND COALESCE(motor_vehicle,'') NOT IN ('yes','designated','permissive'))
    """

    cur.execute(f"UPDATE hefei_roads SET walk_ok = ({walk_ok})")
    print(f"  walk_ok  : {cur.rowcount} rows")
    cur.execute(f"UPDATE hefei_roads SET cycle_ok = ({cycle_ok})")
    print(f"  cycle_ok : {cur.rowcount} rows")
    cur.execute(f"UPDATE hefei_roads SET drive_ok = ({drive_ok})")
    print(f"  drive_ok : {cur.rowcount} rows")
    conn.commit()

    # 汇总
    cur.execute("""
        SELECT
          count(*) FILTER (WHERE cost > 0) AS total,
          count(*) FILTER (WHERE cost > 0 AND walk_ok)  AS walk,
          count(*) FILTER (WHERE cost > 0 AND cycle_ok) AS cycle,
          count(*) FILTER (WHERE cost > 0 AND drive_ok) AS drive
        FROM hefei_roads
    """)
    t, w, c, d = cur.fetchone()
    print(f"\n  总边(>0): {t} | walk: {w} | cycle: {c} | drive: {d}")

    cur.execute("""
        SELECT COALESCE(bridge_class,'none'), count(*) FROM hefei_roads
        WHERE cost > 0 GROUP BY bridge_class ORDER BY count(*) DESC
    """)
    print("  bridge_class 分布:")
    for r in cur.fetchall():
        print(f"    {r[0]:12s} {r[1]}")


def main():
    cache = load_cache()
    if "--classify-only" not in sys.argv:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT osmid FROM hefei_roads")
        osmids = [r[0] for r in cur.fetchall()]
        way_ids = []
        for o in osmids:
            way_ids += expand_osmid(o)
        way_ids = sorted(set(way_ids))
        cur.close()
        conn.close()
        print(f"从 DB 展开得到 {len(way_ids)} 个独立 way id")
        cache = fetch_tags(way_ids, cache)
    else:
        print("--classify-only: 使用已有缓存")

    if "--fetch-only" not in sys.argv:
        enrich_db(cache)
    else:
        print("--fetch-only: 缓存已写入", CACHE_FILE)


if __name__ == "__main__":
    main()
