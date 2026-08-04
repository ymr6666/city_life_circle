"""高德 POI 2.0 v5 爬虫 - Final版
特性:
  - show_fields=business,navi 保存完整的原始数据
  - 同参数翻页最多 200 条 (page_num ≤ 8)
  - 网格搜索 + 城市级搜索 (≤200 条用城市级)
  - 并发 ≤ 3次/秒
  - 扩展 bbox (覆盖全部地铁站)
使用方法:
  python crawl_poi_v5_final.py           # 执行爬取
  python crawl_poi_v5_final.py --estimate # 仅估算
"""
import time, requests, psycopg2, sys
from config import (
    AMAP_KEY, POI_CATEGORIES_GRID, POI_CATEGORIES_CITY,
    HEFEI_BOUNDS, DB_CONFIG, TYPECODE_LABEL,
)

URL_CITY = "https://restapi.amap.com/v5/place/text"
URL_POLY = "https://restapi.amap.com/v5/place/polygon"
MAX_PAGE = 8           # 200条 / 25 = 8页
PAGE_SIZE = 25
SLEEP = 0.35           # 3 req/sec
HEADERS = {"User-Agent": "city-life-circle/1.0"}

SHOW_FIELDS = "business,navi"

request_count = 0
conn = psycopg2.connect(**DB_CONFIG)
conn.set_client_encoding("UTF8")


def api_get(url, params):
    """统一的 API GET，带重试和计数器"""
    global request_count
    for attempt in range(3):
        request_count += 1
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
            data = resp.json()
            if data["status"] == "1":
                return data
            if "LIMIT" in str(data.get("info", "")).upper():
                time.sleep(10 * (attempt + 1))
            else:
                return data
        except Exception:
            time.sleep(3 * (attempt + 1))
    return {"status": "0"}


def parse_poi(p, category):
    """提取一条 POI 的全部字段"""
    loc = p.get("location", "")
    lng = lat = 0.0
    try:
        lng_str, lat_str = loc.split(",")
        lng, lat = float(lng_str), float(lat_str)
    except (ValueError, AttributeError):
        pass

    biz = p.get("business", {}) or {}
    navi = p.get("navi", {}) or {}
    photos_list = p.get("photos", []) or []
    photos_json = str([ph.get("url","") for ph in photos_list]) if photos_list else None

    return (
        p.get("name", ""), category,
        p.get("typecode", ""),     # sub_category
        p.get("address", ""),
        biz.get("tel", p.get("tel", "")),
        biz.get("business_area"),
        biz.get("rating"),
        biz.get("cost"),
        biz.get("parking_type"),
        biz.get("opentime_today"),
        biz.get("opentime_week"),
        biz.get("tag"),
        biz.get("alias"),
        navi.get("entr_location"),
        navi.get("exit_location"),
        navi.get("navi_poiid"),
        photos_json,
        lng, lat,
    )


def save_pois(poi_list, category):
    """批量写入"""
    cur = conn.cursor()
    cnt = 0
    for p in poi_list:
        row = parse_poi(p, category)
        try:
            cur.execute(
                """INSERT INTO hefei_poi
                   (name,category,sub_category,address,tel,
                    business_area,rating,cost,parking_type,
                    opentime_today,opentime_week,tag,alias,
                    entr_location,exit_location,navi_poiid,photos,
                    geometry)
                   VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,
                           ST_SetSRID(ST_MakePoint(%s,%s),4326))""",
                row,
            )
            cnt += 1
        except Exception:
            continue
    conn.commit()
    cur.close()
    return cnt


def crawl_grid(category_key, cats):
    """网格搜索 (数量超 200 的分类)"""
    global request_count

    l, b, r, t = HEFEI_BOUNDS["bbox"]
    step = HEFEI_BOUNDS["grid_step"]
    cells = []
    x = l
    while x < r:
        y = b
        while y < t:
            poly = f"{x},{y}|{x},{y+step}|{x+step},{y+step}|{x+step},{y}"
            cells.append(poly)
            y += step
        x += step

    all_pois = {}
    for idx, poly in enumerate(cells):
        if request_count >= 2500:
            print("  [STOP] near quota")
            break

        for kw, typecode in cats:
            params = {
                "key": AMAP_KEY, "keywords": kw, "types": typecode,
                "polygon": poly, "page_size": PAGE_SIZE, "page_num": 1,
                "show_fields": SHOW_FIELDS,
            }
            data = api_get(URL_POLY, params)
            pois = data.get("pois", [])
            for p in pois:
                key = (p.get("name",""), p.get("location",""))
                if key not in all_pois:
                    all_pois[key] = p

            # 翻页 (最多 8 页)
            for pg in range(2, MAX_PAGE + 1):
                time.sleep(SLEEP)
                params["page_num"] = pg
                more = api_get(URL_POLY, params).get("pois", [])
                if not more or len(more) < PAGE_SIZE:
                    break
                for p in more:
                    key = (p.get("name",""), p.get("location",""))
                    if key not in all_pois:
                        all_pois[key] = p

            time.sleep(SLEEP)

        if (idx + 1) % 15 == 0:
            print(f"  cells {idx+1}/{len(cells)} unique={len(all_pois)} req={request_count}")

    saved = save_pois(list(all_pois.values()), category_key)
    subs = subtypes_count(category_key)
    print(f"  [OK] {saved} rows | {len(subs)} subtypes: " +
          ", ".join([f"{tc}({TYPECODE_LABEL.get(tc,tc)}:{c})" for tc,c in subs[:6]]))
    return saved


def crawl_city(category_key, cats):
    """城市级搜索 (≤200 条)"""
    start_req = request_count
    all_pois = {}

    for kw, typecode in cats:
        for pg in range(1, MAX_PAGE + 1):
            time.sleep(SLEEP)
            if request_count >= 2500:
                break
            params = {
                "key": AMAP_KEY, "keywords": kw, "types": typecode,
                "region": HEFEI_BOUNDS["city"], "city_limit": "true",
                "page_size": PAGE_SIZE, "page_num": pg,
                "show_fields": SHOW_FIELDS,
            }
            data = api_get(URL_CITY, params)
            pois = data.get("pois", [])
            if not pois:
                break
            for p in pois:
                key = (p.get("name",""), p.get("location",""))
                if key not in all_pois:
                    all_pois[key] = p
            if len(pois) < PAGE_SIZE:
                break

    saved = save_pois(list(all_pois.values()), category_key)
    subs = subtypes_count(category_key)
    used = request_count - start_req
    print(f"  [OK] {saved} rows | {len(subs)} subtypes ({used} req)")
    return saved


def subtypes_count(cat):
    cur = conn.cursor()
    cur.execute(
        "SELECT sub_category,count(*) FROM hefei_poi WHERE category=%s "
        "GROUP BY sub_category ORDER BY count(*) DESC", (cat,))
    rows = cur.fetchall()
    cur.close()
    return rows


# ==================== ESTIMATE ====================
def estimate():
    cells = len(build_grid())
    gc = len(POI_CATEGORIES_GRID)
    cc = len(POI_CATEGORIES_CITY)
    grid_req = gc * cells * 1.5    # avg pages per cell
    city_req = sum([10,10,8,6,3])  # kindergarten/college/senior/food/pedestrian
    total = int(grid_req + city_req)
    t = total * SLEEP * 1.8
    print(f"Grid cells: {cells}, categories: {gc} grid + {cc} city")
    print(f"Est. requests: ~{total}")
    print(f"Est. time: {t:.0f}s ({t/60:.1f} min)")
    print(f"Quota: {total}/2500 ({total*100//2500}%)")


def build_grid():
    l, b, r, t = HEFEI_BOUNDS["bbox"]
    step = HEFEI_BOUNDS["grid_step"]
    cells = []
    x = l
    while x < r:
        y = b
        while y < t:
            cells.append(None)
            y += step
        x += step
    return cells


# ==================== MAIN ====================
def run(only=None):
    global request_count
    start = time.time()

    grid_keys = list(POI_CATEGORIES_GRID.keys())
    city_keys = list(POI_CATEGORIES_CITY.keys())
    if only:
        grid_keys = [k for k in grid_keys if k in only]
        city_keys = [k for k in city_keys if k in only]
        if not grid_keys and not city_keys:
            print(f"未知分类 {only}, 可选: {list(POI_CATEGORIES_GRID) + list(POI_CATEGORIES_CITY)}")
            return

    print(f"Bbox: {HEFEI_BOUNDS['bbox']}, grid_step: {HEFEI_BOUNDS['grid_step']}")
    print(f"Grid categories: {len(grid_keys)}, City categories: {len(city_keys)}")
    if only:
        print(f"仅爬取: {only}")
    print(f"Grid cells: {len(build_grid())}")
    print()

    for key in grid_keys:
        print(f"--- {key} (grid) ---")
        crawl_grid(key, POI_CATEGORIES_GRID[key])
        time.sleep(2)

    for key in city_keys:
        print(f"--- {key} (city) ---")
        crawl_city(key, POI_CATEGORIES_CITY[key])
        time.sleep(2)

    # 汇总
    cur = conn.cursor()
    cur.execute("SELECT category,count(*) FROM hefei_poi GROUP BY category ORDER BY count(*) DESC")
    stats = cur.fetchall()
    cur.execute("SELECT count(*) FROM hefei_poi")
    total = cur.fetchone()[0]
    cur.close()

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"DONE! {elapsed:.0f}s | {request_count} requests | {total} POIs")
    for cat, cnt in stats:
        print(f"  {cat:25s} {cnt:>5}")
    conn.close()


if __name__ == "__main__":
    only = None
    if "--estimate" in sys.argv:
        estimate()
    elif "--only" in sys.argv:
        idx = sys.argv.index("--only")
        only = [c.strip() for c in sys.argv[idx + 1].split(",") if c.strip()]
        run(only)
    else:
        run()
