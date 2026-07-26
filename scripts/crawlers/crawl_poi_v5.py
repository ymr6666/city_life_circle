"""高德 POI 2.0 (v5) 爬取脚本
特性:
  - v5 端点, 城市级搜索 (100 pages × 25 = 2500 条上限)
  - 保存 typecode 到 sub_category 字段
  - 区分: 三甲/卫生院/专科, 幼儿园/小学/初中/高中/大学
  - 超市使用网格搜索兜底 (市一级可能超 2500)
"""
import time
import requests
import psycopg2
from config import AMAP_KEY, POI_CATEGORIES, DB_CONFIG, HEFEI_BOUNDS, TYPECODE_LABEL

URL = "https://restapi.amap.com/v5/place/text"
URL_POLYGON = "https://restapi.amap.com/v5/place/polygon"
PAGE_SIZE = 25
MAX_PAGES = 100
SLEEP = 0.35
BREAK_BETWEEN_CATS = 2.0
HEADERS = {"User-Agent": "city-life-circle/1.0"}

request_count = 0
conn = psycopg2.connect(**DB_CONFIG)
conn.set_client_encoding("UTF8")


def v5_fetch(keywords, types, page_num=1):
    """v5 城市级关键词搜索"""
    global request_count
    params = {
        "key": AMAP_KEY,
        "keywords": keywords,
        "types": types,
        "region": HEFEI_BOUNDS["city"],
        "city_limit": "true",
        "page_size": PAGE_SIZE,
        "page_num": page_num,
    }
    for attempt in range(3):
        request_count += 1
        try:
            resp = requests.get(URL, params=params, headers=HEADERS, timeout=15)
            data = resp.json()
            if data["status"] == "1":
                return data.get("pois", []), int(data.get("count", 0))
            info = data.get("info", "")
            if "LIMIT" in info.upper():
                time.sleep(10 * (attempt + 1))
            else:
                return [], 0
        except Exception:
            time.sleep(3 * (attempt + 1))
    return [], 0


def v5_fetch_grid(keywords, types, polygon_str, page_num=1):
    """v5 多边形网格搜索"""
    global request_count
    params = {
        "key": AMAP_KEY,
        "types": types,
        "polygon": polygon_str,
        "page_size": PAGE_SIZE,
        "page_num": page_num,
    }
    if keywords:
        params["keywords"] = keywords
    for attempt in range(3):
        request_count += 1
        try:
            resp = requests.get(URL_POLYGON, params=params, headers=HEADERS, timeout=15)
            data = resp.json()
            if data["status"] == "1":
                return data.get("pois", []), int(data.get("count", 0))
        except Exception:
            time.sleep(3 * (attempt + 1))
    return [], 0


def save_pois(poi_list, category):
    cur = conn.cursor()
    cnt = 0
    for p in poi_list:
        name = p.get("name", "")
        loc = p.get("location", "")
        tc = p.get("typecode", "")
        try:
            lng_str, lat_str = loc.split(",")
            lng, lat = float(lng_str), float(lat_str)
            cur.execute(
                "INSERT INTO hefei_poi (name,category,sub_category,address,tel,geometry) "
                "VALUES (%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326))",
                (name, category, tc, p.get("address", ""), "", lng, lat),
            )
            cnt += 1
        except (ValueError, AttributeError):
            continue
    conn.commit()
    cur.close()
    return cnt


def crawl_city(category_key):
    """城市级搜索 (单类 ≤2500 条)"""
    global request_count
    keywords, types = POI_CATEGORIES[category_key]
    print(f"\n--- {category_key}: {keywords} ---")

    all_pois = {}
    for page in range(1, MAX_PAGES + 1):
        if request_count >= 1800:
            print("  [STOP] near quota")
            break
        time.sleep(SLEEP)
        pois, total = v5_fetch(keywords, types, page_num=page)
        if not pois:
            break
        new = 0
        for p in pois:
            k = (p.get("name", ""), p.get("location", ""))
            if k not in all_pois:
                all_pois[k] = p
                new += 1
        if page == 1:
            print(f"  total reported: {total}")
        if page % 10 == 0:
            print(f"  page {page}, collected {len(all_pois)} unique")
        if page >= MAX_PAGES or len(pois) < PAGE_SIZE:
            break

    saved = save_pois(list(all_pois.values()), category_key)
    # 子类统计
    cur = conn.cursor()
    cur.execute(
        "SELECT sub_category, count(*) FROM hefei_poi WHERE category=%s GROUP BY sub_category ORDER BY count(*) DESC",
        (category_key,),
    )
    breakdown = cur.fetchall()
    cur.close()
    print(f"  [OK] {saved} rows | {len(breakdown)} subtypes:")
    for tc, cnt in breakdown[:5]:
        label = TYPECODE_LABEL.get(tc, tc)
        print(f"    {tc} ({label}): {cnt}")


def crawl_grid(category_key):
    """网格搜索 (用于数据量大的分类: hospital, supermarket)"""
    global request_count
    keywords, types = POI_CATEGORIES[category_key]
    print(f"\n--- {category_key}: {keywords} (grid) ---")

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
        if request_count >= 1800:
            print("  [STOP] near quota")
            break
        time.sleep(SLEEP)
        pois, cnt = v5_fetch_grid(keywords, types, poly, page_num=1)
        for p in pois:
            k = (p.get("name", ""), p.get("location", ""))
            if k not in all_pois:
                all_pois[k] = p
        for pg2 in range(2, 6):
            time.sleep(SLEEP)
            more, _ = v5_fetch_grid(keywords, types, poly, page_num=pg2)
            if not more:
                break
            for p in more:
                k = (p.get("name", ""), p.get("location", ""))
                if k not in all_pois:
                    all_pois[k] = p
        if (idx + 1) % 10 == 0:
            print(f"  cells {idx+1}/{len(cells)}, collected {len(all_pois)} unique")

    saved = save_pois(list(all_pois.values()), category_key)
    cur = conn.cursor()
    cur.execute(
        "SELECT sub_category, count(*) FROM hefei_poi WHERE category=%s GROUP BY sub_category ORDER BY count(*) DESC",
        (category_key,),
    )
    breakdown = cur.fetchall()
    cur.close()
    print(f"  [OK] {saved} rows | {len(breakdown)} subtypes:")
    for tc, cnt in breakdown[:8]:
        label = TYPECODE_LABEL.get(tc, tc)
        print(f"    {tc} ({label}): {cnt}")


# ============ 估算模式 ============
def estimate():
    """不执行爬取，只估算用时会话"""
    cats = list(POI_CATEGORIES.keys())
    estimates = {
        "hospital": 70, "supermarket": 54,
        "school_primary": 60, "school_junior": 60,
        "park": 60, "mall": 60, "street_commercial": 60,
        # city-level (<=200)
        "kindergarten": 20, "school_college": 20,
        "school_senior": 8,
        "market_food": 10, "street_pedestrian": 5,
    }
    total_pages = 0
    print("=== ESTIMATE ===")
    for k in cats:
        ep = estimates.get(k, 15)
        total_pages += ep
        print(f"  {k:20s} ~{ep:>3} requests")
    t_net = total_pages * SLEEP * 2       # 含翻页和网络
    t_breaks = len(cats) * BREAK_BETWEEN_CATS
    t_total = t_net + t_breaks + 30       # +30s 入库缓冲
    print(f"\n  total requests: ~{total_pages}")
    print(f"  estimated time:   ~{t_total:.0f}s (~{t_total/60:.1f} min)")
    print(f"  daily quota used: {total_pages}/2000 ({total_pages*100//2000}%)")


def run():
    """主入口"""
    global request_count
    start = time.time()

    # 清空旧 POI
    cur = conn.cursor()
    cur.execute("DELETE FROM hefei_poi")
    conn.commit()
    cur.close()
    print("Old POI data cleared.")

    GRID_CATS = {"hospital", "supermarket", "school_primary", "school_junior", "park", "mall", "street_commercial"}

    for key in POI_CATEGORIES:
        if key in GRID_CATS:
            crawl_grid(key)
        else:
            crawl_city(key)
        time.sleep(BREAK_BETWEEN_CATS)

    # 汇总
    cur = conn.cursor()
    cur.execute("SELECT category, count(*) FROM hefei_poi GROUP BY category ORDER BY count(*) DESC")
    stats = cur.fetchall()
    cur.execute("SELECT count(*) FROM hefei_poi")
    total = cur.fetchone()[0]
    cur.close()

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"DONE! {elapsed:.0f}s | {request_count} requests | {total} POIs")
    for cat, cnt in stats:
        # 子类
        cur = conn.cursor()
        cur.execute(
            "SELECT sub_category,count(*) FROM hefei_poi WHERE category=%s GROUP BY sub_category ORDER BY count(*) DESC LIMIT 5",
            (cat,),
        )
        subs = cur.fetchall()
        cur.close()
        labels = [f"{tc}({TYPECODE_LABEL.get(tc,'?')}:{c})" for tc, c in subs]
        print(f"  {cat:25s} {cnt:>5}  [{', '.join(labels)}]")
    conn.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--estimate":
        estimate()
    else:
        run()
