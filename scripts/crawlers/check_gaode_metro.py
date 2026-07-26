"""用高德 API 查询完整地铁线路数据 (比 OSM 新)"""
import requests, time, psycopg2
from config import AMAP_KEY, DB_CONFIG

HEADERS = {"User-Agent": "city-life-circle/1.0"}
SLEEP = 0.4

# 合肥地铁线路关键词列表
LINES = [
    "合肥地铁1号线", "合肥地铁2号线", "合肥地铁3号线",
    "合肥地铁4号线", "合肥地铁5号线", "合肥地铁6号线", "合肥地铁8号线",
]

# 用高德公交线路查询 API
URL = "https://restapi.amap.com/v3/bus/linename"

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

for line_name in LINES:
    params = {
        "key": AMAP_KEY,
        "city": "合肥",
        "s": "rsv3",
        "parameters": line_name,
    }
    time.sleep(SLEEP)
    try:
        r = requests.get(URL, params=params, headers=HEADERS, timeout=15)
        data = r.json()
        print(f"\n=== {line_name} ===")
        print(f"  status: {data.get('status')}")

        if data.get("status") == "1" and "buslines" in data:
            for bl in data["buslines"][:2]:
                name = bl.get("name", "?")
                fr = bl.get("front_name", "?")
                to = bl.get("terminal_name", "?")
                stops = bl.get("busstops", [])
                print(f"  {name}: {fr} → {to}, {len(stops)} 站")
                for s in stops[:5]:
                    print(f"    {s['name']} ({s['location']})")
                if len(stops) > 5:
                    print(f"    ... 共 {len(stops)} 站")
        elif data.get("status") == "0":
            print(f"  error: {data.get('info')}")
    except Exception as e:
        print(f"  request failed: {e}")

conn.close()
