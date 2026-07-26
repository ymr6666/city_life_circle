"""只重爬 hospital + school_college，不做任何去重"""
import time, requests, psycopg2
from config import AMAP_KEY, HEFEI_BOUNDS, DB_CONFIG, TYPECODE_LABEL

URL_POLY = "https://restapi.amap.com/v5/place/polygon"
URL_CITY = "https://restapi.amap.com/v5/place/text"
SLEEP = 0.35
HEADERS = {"User-Agent": "city-life-circle/1.0"}
SHOW = "business,navi"

request_count = 0
conn = psycopg2.connect(**DB_CONFIG)
conn.set_client_encoding("UTF8")
cur = conn.cursor()

def api_get(url, params):
    global request_count
    for attempt in range(3):
        request_count += 1
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=20)
            d = r.json()
            if d["status"] == "1": return d
            if "LIMIT" in str(d.get("info","")).upper(): time.sleep(10*(attempt+1))
            else: return d
        except: time.sleep(3*(attempt+1))
    return {"status":"0"}

def save(pois, cat):
    cur2 = conn.cursor(); n = 0
    for p in pois:
        loc = p.get("location","")
        try:
            lng, lat = [float(x) for x in loc.split(",")]
            biz = p.get("business",{}) or {}
            navi = p.get("navi",{}) or {}
            photos = p.get("photos",[]) or []
            photos_s = str([ph.get("url","") for ph in photos]) if photos else None
            cur2.execute(
                '''INSERT INTO hefei_poi (name,category,sub_category,address,tel,
                   business_area,rating,cost,parking_type,opentime_today,opentime_week,tag,alias,
                   entr_location,exit_location,navi_poiid,photos,geometry)
                   VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,
                   ST_SetSRID(ST_MakePoint(%s,%s),4326))''',
                (p.get("name",""), cat, p.get("typecode",""),
                 p.get("address",""), biz.get("tel",p.get("tel","")),
                 biz.get("business_area"), biz.get("rating"), biz.get("cost"),
                 biz.get("parking_type"), biz.get("opentime_today"), biz.get("opentime_week"),
                 biz.get("tag"), biz.get("alias"),
                 navi.get("entr_location"), navi.get("exit_location"), navi.get("navi_poiid"),
                 photos_s, lng, lat))
            n += 1
        except: pass
    conn.commit(); cur2.close(); return n

def grid_cells():
    l,b,r,t = HEFEI_BOUNDS["bbox"]; step = HEFEI_BOUNDS["grid_step"]
    cells = []; x=l
    while x<r:
        y=b
        while y<t:
            cells.append(f"{x},{y}|{x},{y+step}|{x+step},{y+step}|{x+step},{y}"); y+=step
        x+=step
    return cells

def crawl_hospital_grid():
    print("=== Hospital (grid, no dedup) ===")
    cells = grid_cells()
    all_pois = {}
    for idx, poly in enumerate(cells):
        if request_count >= 2000: break
        params = {"key":AMAP_KEY,"keywords":"医疗","types":"090100|090200|090300|090400|090500",
                  "polygon":poly,"page_size":25,"page_num":1,"show_fields":SHOW}
        data = api_get(URL_POLY, params)
        for p in data.get("pois",[]):
            k = (p.get("name",""), p.get("location",""))
            if k not in all_pois: all_pois[k] = p
        for pg in range(2, 9):
            time.sleep(SLEEP); params["page_num"] = pg
            more = api_get(URL_POLY, params).get("pois",[])
            if not more or len(more)<25: break
            for p in more:
                k = (p.get("name",""),p.get("location",""))
                if k not in all_pois: all_pois[k] = p
        time.sleep(SLEEP)
        if (idx+1)%15==0: print(f"  cells {idx+1}/{len(cells)} u={len(all_pois)} r={request_count}")
    n = save(list(all_pois.values()), "hospital")
    print(f"  Saved: {n}")
    return n

def crawl_college_city():
    print("=== School College (city, no dedup) ===")
    all_pois = {}
    for pg in range(1, 9):
        time.sleep(SLEEP)
        if request_count >= 2000: break
        params = {"key":AMAP_KEY,"keywords":"","types":"141201",
                  "region":"合肥","city_limit":"true","page_size":25,"page_num":pg,"show_fields":SHOW}
        data = api_get(URL_CITY, params)
        pois = data.get("pois",[])
        if not pois: break
        for p in pois:
            k = (p.get("name",""),p.get("location",""))
            if k not in all_pois: all_pois[k] = p
        if len(pois)<25: break
    n = save(list(all_pois.values()), "school_college")
    print(f"  Saved: {n}")
    return n

# ====== MAIN ======
# 清空这两类的旧去重数据
cur.execute("DELETE FROM hefei_poi WHERE category = 'hospital'")
cur.execute("DELETE FROM hefei_poi WHERE category = 'school_college'")
conn.commit()
print("Old hospital + school_college data deleted.\n")

start = time.time()
h = crawl_hospital_grid()
time.sleep(2)
c = crawl_college_city()

# 统计
cur.execute("SELECT category, count(*) FROM hefei_poi GROUP BY category ORDER BY count(*) DESC")
stats = cur.fetchall()
cur.execute("SELECT count(*) FROM hefei_poi")
total = cur.fetchone()[0]
cur.close()

elapsed = time.time() - start
print(f"\nDone! {elapsed:.0f}s | {request_count} requests | total {total} POIs")
for cat, cnt in stats:
    print(f"  {cat:25s} {cnt}")

conn.close()
