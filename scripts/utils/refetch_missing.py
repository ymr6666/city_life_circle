# -*- coding: utf-8 -*-
"""补抓 unresolved osmids 对应的 way tags"""
import json, os, re, sys, time
import requests
import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'cache', 'roads_tags.json')
HEADERS = {"User-Agent": "city-life-circle/1.0 (student project)"}
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
CHUNK = 300
SLEEP = 1.0


def expand(o):
    return [int(x) for x in re.findall(r'\d+', o or '')]


def query(q):
    for mirror in MIRRORS:
        try:
            r = requests.post(mirror, data={"data": q}, headers=HEADERS, timeout=60)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
    return None


cache = json.load(open(CACHE_FILE, encoding='utf-8'))
conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()
cur.execute("SELECT DISTINCT osmid FROM hefei_roads")
osmids = [r[0] for r in cur.fetchall()]
conn.close()

unresolved_ids = set()
for o in osmids:
    ids = expand(o)
    if not all(str(w) in cache for w in ids):
        unresolved_ids.update(ids)
# 去掉已在 cache 的
unresolved_ids = [w for w in unresolved_ids if str(w) not in cache]
print("to refetch ways:", len(unresolved_ids))

for i in range(0, len(unresolved_ids), CHUNK):
    chunk = unresolved_ids[i:i + CHUNK]
    q = f"[out:json][timeout:60];\nway(id:{','.join(map(str, chunk))});\nout tags;\n"
    data = query(q)
    if data:
        for el in data.get("elements", []):
            if el.get("tags"):
                cache[str(el["id"])] = el["tags"]
    json.dump(cache, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False)
    if (i // CHUNK) % 10 == 0:
        print(f"  {min(i + CHUNK, len(unresolved_ids))}/{len(unresolved_ids)}", flush=True)
    time.sleep(SLEEP)

print("cache ways now:", len(cache))
