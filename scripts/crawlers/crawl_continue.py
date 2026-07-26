"""Continue crawling remaining categories"""
import time, requests, psycopg2
from config import (
    AMAP_KEY, POI_CATEGORIES_GRID, POI_CATEGORIES_CITY,
    HEFEI_BOUNDS, DB_CONFIG, TYPECODE_LABEL,
)

URL_CITY = "https://restapi.amap.com/v5/place/text"
URL_POLY = "https://restapi.amap.com/v5/place/polygon"
MAX_PAGE = 8
PAGE_SIZE = 25
SLEEP = 0.35
HEADERS = {"User-Agent": "city-life-circle/1.0"}
SHOW_FIELDS = "business,navi"
request_count = 0

conn = psycopg2.connect(**DB_CONFIG)
conn.set_client_encoding("UTF8")

def api_get(url, params):
    global request_count
    for attempt in range(3):
        request_count += 1
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
            data = resp.json()
            if data["status"] == "1": return data
            if "LIMIT" in str(data.get("info","")).upper():
                time.sleep(10*(attempt+1))
            else: return data
        except: time.sleep(3*(attempt+1))
    return {"status":"0"}

def parse_poi(p, category):
    loc = p.get("location","")
    lng=lat=0.0
    try:
        lng_s,lat_s=loc.split(","); lng=float(lng_s); lat=float(lat_s)
    except: pass
    biz = p.get("business",{}) or {}
    navi = p.get("navi",{}) or {}
    photos = p.get("photos",[]) or []
    photos_s = str([ph.get("url","") for ph in photos]) if photos else None
    return (p.get("name",""),category,p.get("typecode",""),
            p.get("address",""),biz.get("tel",p.get("tel","")),
            biz.get("business_area"),biz.get("rating"),biz.get("cost"),
            biz.get("parking_type"),biz.get("opentime_today"),biz.get("opentime_week"),
            biz.get("tag"),biz.get("alias"),navi.get("entr_location"),
            navi.get("exit_location"),navi.get("navi_poiid"),photos_s,lng,lat)

def save(pois, cat):
    cur=conn.cursor(); n=0
    for p in pois:
        try:
            cur.execute("INSERT INTO hefei_poi (name,category,sub_category,address,tel,"
                "business_area,rating,cost,parking_type,opentime_today,opentime_week,tag,alias,"
                "entr_location,exit_location,navi_poiid,photos,geometry) "
                "VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s, "
                "ST_SetSRID(ST_MakePoint(%s,%s),4326))", parse_poi(p,cat)); n+=1
        except: pass
    conn.commit(); cur.close(); return n

def grid_cells():
    l,b,r,t=HEFEI_BOUNDS["bbox"]; step=HEFEI_BOUNDS["grid_step"]
    cells=[]; x=l
    while x<r:
        y=b
        while y<t:
            cells.append(f"{x},{y}|{x},{y+step}|{x+step},{y+step}|{x+step},{y}")
            y+=step
        x+=step
    return cells

def crawl_grid(key, cats):
    global request_count
    cells=grid_cells(); all_pois={}
    for idx,poly in enumerate(cells):
        if request_count>=2500: break
        for kw,ty in cats:
            p={"key":AMAP_KEY,"keywords":kw,"types":ty,"polygon":poly,
               "page_size":PAGE_SIZE,"page_num":1,"show_fields":SHOW_FIELDS}
            data=api_get(URL_POLY,p)
            for x in data.get("pois",[]):
                k=(x.get("name",""),x.get("location",""))
                if k not in all_pois: all_pois[k]=x
            for pg in range(2,MAX_PAGE+1):
                time.sleep(SLEEP); p["page_num"]=pg
                more=api_get(URL_POLY,p).get("pois",[])
                if not more or len(more)<PAGE_SIZE: break
                for x in more:
                    k=(x.get("name",""),x.get("location",""))
                    if k not in all_pois: all_pois[k]=x
            time.sleep(SLEEP)
        if (idx+1)%15==0:
            print(f"  cells {idx+1}/{len(cells)} u={len(all_pois)} r={request_count}")
    n=save(list(all_pois.values()),key)
    print(f"  [OK] {key}: {n} rows")
    return n

def crawl_city(key, cats):
    global request_count; start=request_count; all_pois={}
    for kw,ty in cats:
        for pg in range(1,MAX_PAGE+1):
            time.sleep(SLEEP)
            if request_count>=2500: break
            p={"key":AMAP_KEY,"keywords":kw,"types":ty,"region":"合肥",
               "city_limit":"true","page_size":PAGE_SIZE,"page_num":pg,
               "show_fields":SHOW_FIELDS}
            data=api_get(URL_CITY,p)
            pois=data.get("pois",[])
            if not pois: break
            for x in pois:
                k=(x.get("name",""),x.get("location",""))
                if k not in all_pois: all_pois[k]=x
            if len(pois)<PAGE_SIZE: break
    n=save(list(all_pois.values()),key)
    print(f"  [OK] {key}: {n} rows ({request_count-start} req)")
    return n

# Only run categories with 0 data
cur=conn.cursor()
for key,cats in POI_CATEGORIES_GRID.items():
    cur.execute("SELECT count(*) FROM hefei_poi WHERE category=%s",(key,))
    if cur.fetchone()[0]==0:
        print(f"--- {key} (grid) ---")
        crawl_grid(key,cats)
        time.sleep(2)
    else:
        print(f"--- {key}: SKIP (already in db) ---")

for key,cats in POI_CATEGORIES_CITY.items():
    cur.execute("SELECT count(*) FROM hefei_poi WHERE category=%s",(key,))
    if cur.fetchone()[0]==0:
        print(f"--- {key} (city) ---")
        crawl_city(key,cats)
        time.sleep(2)
    else:
        print(f"--- {key}: SKIP ---")

cur.execute("SELECT category,count(*) FROM hefei_poi GROUP BY category ORDER BY count(*) DESC")
stats=cur.fetchall()
cur.execute("SELECT count(*) FROM hefei_poi")
total=cur.fetchone()[0]
cur.close()
print(f"\nTotal: {total} POIs")
for c,n in stats: print(f"  {c:25s} {n}")
conn.close()
