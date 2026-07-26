import time
import requests
import psycopg2
from config import AMAP_KEY, POI_CATEGORIES, HEFEI_BOUNDS, DB_CONFIG

URL = "https://restapi.amap.com/v3/place/polygon"
SLEEP = 0.3
MAX_RETRIES = 3

HEADERS = {"User-Agent": "city-life-circle/1.0 (student project)"}
request_count = 0
conn = psycopg2.connect(**DB_CONFIG)
conn.set_client_encoding("UTF8")


def build_grid():
    """把合肥切成网格，每个格子 ~3km × 3km"""
    l, b, r, t = HEFEI_BOUNDS["bbox"]
    step = HEFEI_BOUNDS["grid_step"]  # 0.05° ≈ 5.5km
    cells = []
    x = l
    while x < r:
        y = b
        while y < t:
            # polygon 格式: 左下|左上|右上|右下
            poly = f"{x},{y}|{x},{y+step}|{x+step},{y+step}|{x+step},{y}"
            cells.append((poly, x, y))
            y += step
        x += step
    return cells


def fetch_grid_cell(keywords, polygon_str, page=1):
    """在一个网格格子里搜 POI"""
    global request_count
    params = {
        "key": AMAP_KEY,
        "keywords": keywords,
        "polygon": polygon_str,
        "offset": 25,
        "page": page,
        "extensions": "all",
    }
    for attempt in range(MAX_RETRIES):
        request_count += 1
        try:
            resp = requests.get(URL, params=params, headers=HEADERS, timeout=15)
            data = resp.json()
            if data["status"] == "1":
                return data.get("pois", []), int(data.get("count", 0))
            info = data.get("info", "?")
            if "LIMIT" in info.upper() or "OVER_QUOTA" in info.upper():
                wait = 10 * (attempt + 1)
                print(f"  [WARN] Rate limit, waiting {wait}s...")
                time.sleep(wait)
            else:
                return [], 0
        except Exception as e:
            wait = 3 * (attempt + 1)
            time.sleep(wait)
    return [], 0


def save_pois(poi_list, category):
    cur = conn.cursor()
    for p in poi_list:
        name = p.get("name", "")
        loc = p.get("location", "0,0")
        try:
            lng_str, lat_str = loc.split(",")
            lng, lat = float(lng_str), float(lat_str)
            cur.execute(
                "INSERT INTO hefei_poi (name,category,sub_category,address,tel,geometry) "
                "VALUES (%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326))",
                (name, category, category, p.get("address",""), p.get("tel",""), lng, lat),
            )
        except (ValueError, AttributeError):
            continue
        except Exception:
            continue
    conn.commit()
    cur.close()


def crawl_category(category_key):
    global request_count
    cat_names = POI_CATEGORIES[category_key]["keywords"].split("|")
    main_name = cat_names[0]
    print(f"\n{'='*50}")
    print(f"Crawling: {' + '.join(cat_names)}")
    start_count = request_count

    cells = build_grid()
    all_pois = {}

    for sub_kw in cat_names:
        for idx, (poly, cx, cy) in enumerate(cells):
            if request_count >= 1800:
                print("  🛑 接近配额，停止")
                break

            pois, cnt = fetch_grid_cell(sub_kw, poly, page=1)
            if not pois:
                time.sleep(SLEEP)
                continue

            for p in pois:
                key = (p.get("name",""), p.get("location",""))
                if key not in all_pois:
                    all_pois[key] = p

            if cnt > 25:
                max_page = min((cnt - 1) // 25 + 1, 4)
                for pg in range(2, max_page + 1):
                    time.sleep(SLEEP)
                    more_pois, _ = fetch_grid_cell(sub_kw, poly, page=pg)
                    for p in more_pois:
                        key = (p.get("name",""), p.get("location",""))
                        if key not in all_pois:
                            all_pois[key] = p

            time.sleep(SLEEP)

            if (idx + 1) % 10 == 0:
                print(f"  [{sub_kw}] Cells: {idx+1}/{len(cells)} (requests: {request_count}, collected: {len(all_pois)})")

    # 写入去重后的数据
    save_pois(list(all_pois.values()), category_key)

    # 统计
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM hefei_poi WHERE category=%s", (category_key,))
    final = cur.fetchone()[0]
    cur.close()
    conn.commit()
    pages_used = request_count - start_count
    print(f"  [OK] {main_name} save: {final} rows ({pages_used} requests)")


if __name__ == "__main__":
    start = time.time()

    cur = conn.cursor()
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name='hefei_poi'")
    if cur.fetchone() is None:
        print("Run setup_tables.py first")
        exit(1)
    cur.close()

    cells = build_grid()
    print(f"Hefei grid: {len(cells)} cells (step {HEFEI_BOUNDS['grid_step']} deg)")

    for key in POI_CATEGORIES:
        crawl_category(key)
        time.sleep(2.0)

    cur = conn.cursor()
    cur.execute("SELECT category, count(*) FROM hefei_poi GROUP BY category ORDER BY category")
    stats = cur.fetchall()
    cur.execute("SELECT count(*) FROM hefei_poi")
    total = cur.fetchone()[0]
    cur.close()

    elapsed = time.time() - start
    print(f"\n{'='*50}")
    print(f"Done! {elapsed:.0f}s, {request_count} requests, {total} POIs")
    for cat, cnt in stats:
        print(f"  {cat}: {cnt}")

    conn.close()
