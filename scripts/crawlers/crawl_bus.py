# -*- coding: utf-8 -*-
"""合肥公交数据爬虫 (高德 Web 服务 API)

枚举与落库流程:
  Phase 1: 网格搜索 POI「公交车站」(types=150500) → 收集站名 (已完成, 1,068 个)
  Phase 2: 逐站名调用 /v3/bus/stopname (offset=100 分页) → 收集公交线路 id
  Phase 3: 逐线路调用 /v3/bus/lineid (extensions=all) → 有序站序列 + 首末班 + 线路几何

配额约束 (个人认证实测):
  - 公交接口日配额: 100 次/天   (DAILY_QUOTA)
  - 限速: 1 次/秒              (SLEEP=1.1)
  - 合肥公交站点 4000+, 线路 300+  → Phase 3 是主要开销 (每线路 1 次)

每日运行策略 (run_daily):
  1. Phase 2 用当日 40% 配额继续发现线路 (线路发现饱和后自动提前结束)
  2. Phase 3 用剩余配额抓线路详情 (每线路 1 次 lineid)
  3. 遇配额耗尽(infocode 10003/10004) 立即停止, 保存 checkpoint, 次日重跑同一命令续抓
  4. 只有成功(status=1)的请求才标记完成, 失败站点/线路次日自动重试

用法:
  python crawl_bus.py                 # 每日运行 (配额内自动分配 Phase2/Phase3)
  python crawl_bus.py --phase 1       # 只跑 Phase 1 (网格搜站名, POI 接口)
  python crawl_bus.py --phase 2       # 只跑 Phase 2 (发现线路)
  python crawl_bus.py --phase 3       # 只跑 Phase 3 (线路详情, 不受配额预算限制, 谨慎)
  python crawl_bus.py --load          # 用缓存落库 PostGIS (GCJ->WGS)
  python crawl_bus.py --reset         # 清空 _done 标记 (让失败站重新查询)
  python crawl_bus.py --estimate      # 估算请求量与天数
"""
import json
import math
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import AMAP_KEY, DB_CONFIG, HEFEI_BOUNDS

import psycopg2

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'cache')
STOP_NAMES_FILE = os.path.join(CACHE_DIR, 'bus_stop_names.json')
LINES_FILE = os.path.join(CACHE_DIR, 'bus_lines.json')
LINE_DETAIL_FILE = os.path.join(CACHE_DIR, 'bus_line_detail.json')

HEADERS = {"User-Agent": "city-life-circle/1.0"}
SLEEP = 1.1                    # 公交接口限速 1 req/s (留 0.1s 余量)
DAILY_QUOTA = 100              # 个人认证公交接口日配额
PHASE2_FRACTION = 0.4          # 每日配额中 Phase 2 (发现线路) 占用的比例
PLATEAU_STATIONS = 30          # 连续 N 站无新线路 → 判定线路发现饱和, 停止 Phase 2
PAGE_SIZE = 100                # stopname offset 最大 100
GRID_STEP = 0.05
CITY = "340100"                # 合肥 adcode
BUS_STOP_TYPE = "150500"       # POI typecode: 公交车站

# ── 坐标转换 (GCJ-02 → WGS84) ──────────────────────────────
PI = math.pi
X_PI = PI * 3000.0 / 180.0
A = 6378245.0
EE = 0.00669342162296594323


def _out_of_china(lng, lat):
    return lng < 72.004 or lng > 137.8347 or lat < 0.8293 or lat > 55.8271


def _transform_lat(lng, lat):
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat \
          + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * PI) + 20.0 * math.sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * PI) + 40.0 * math.sin(lat / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * PI) + 320 * math.sin(lat * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng, lat):
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng \
          + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * PI) + 20.0 * math.sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * PI) + 40.0 * math.sin(lng / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * PI) + 300.0 * math.sin(lng / 30.0 * PI)) * 2.0 / 3.0
    return ret


def _forward(lng, lat):
    """WGS84 -> GCJ02 (供反解)"""
    if _out_of_china(lng, lat):
        return lng, lat
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * PI
    magic = math.sin(rad_lat)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * PI)
    d_lng = (d_lng * 180.0) / (A / sqrt_magic * math.cos(rad_lat) * PI)
    return lng + d_lng, lat + d_lat


def gcj02_to_wgs84(lng, lat):
    if _out_of_china(lng, lat):
        return lng, lat
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * PI
    magic = math.sin(rad_lat)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * PI)
    d_lng = (d_lng * 180.0) / (A / sqrt_magic * math.cos(rad_lat) * PI)
    w_lng, w_lat = lng + d_lng, lat + d_lat
    # 迭代反解提高精度
    for _ in range(5):
        g_lng, g_lat = _forward(w_lng, w_lat)
        w_lng -= g_lng - lng
        w_lat -= g_lat - lat
    return w_lng, w_lat


def parse_loc(loc):
    try:
        lng, lat = loc.split(",")
        return float(lng), float(lat)
    except (ValueError, AttributeError):
        return None


# ── API 请求 (统一重试 + 限速 + 配额保护) ────────────────────
class QuotaExhausted(Exception):
    """当日公交接口配额已用尽"""


_request_count = 0


def api_get(url, params):
    """请求高德接口。
    配额耗尽时抛 QuotaExhausted (立即停止, 不烧配额)。
    网络/业务失败重试 3 次后返回 {"status":"0"}。"""
    global _request_count
    for attempt in range(3):
        _request_count += 1
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
            data = resp.json()
            if data.get("status") == "1":
                return data
            info = str(data.get("info", ""))
            code = str(data.get("infocode", ""))
            if code in ("10003", "10004") or "LIMIT" in info.upper() or "配额" in info:
                raise QuotaExhausted(info or code)
            return data  # 业务性失败, 交由调用方判断
        except QuotaExhausted:
            raise
        except Exception:
            time.sleep(3 * (attempt + 1))
    return {"status": "0"}


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# ════════════════════════════════════════════════════════════
# Phase 1: 网格搜公交车站 POI → 站名列表
# ════════════════════════════════════════════════════════════
def phase1_collect_station_names():
    print("=" * 60)
    print("Phase 1: 网格搜索公交车站 POI (types=%s)" % BUS_STOP_TYPE)
    print("=" * 60)

    stations = load_json(STOP_NAMES_FILE, {})
    l, b, r, t = HEFEI_BOUNDS["bbox"]

    x = l
    while x < r:
        y = b
        while y < t:
            poly = f"{x},{y}|{x},{y+GRID_STEP}|{x+GRID_STEP},{y+GRID_STEP}|{x+GRID_STEP},{y}"
            for pg in range(1, 9):
                time.sleep(SLEEP)
                params = {
                    "key": AMAP_KEY, "types": BUS_STOP_TYPE, "polygon": poly,
                    "page_size": 25, "page_num": pg,
                }
                data = api_get("https://restapi.amap.com/v5/place/polygon", params)
                pois = data.get("pois", [])
                if not pois:
                    break
                for p in pois:
                    loc = parse_loc(p.get("location"))
                    if not loc:
                        continue
                    name = p.get("name", "").strip()
                    if not name:
                        continue
                    stations.setdefault(name, {"lng": loc[0], "lat": loc[1],
                                               "adcode": p.get("adcode")})
                if len(pois) < 25:
                    break
            y += GRID_STEP
        x += GRID_STEP
        save_json(STOP_NAMES_FILE, stations)

    print(f"  公交车站 POI: {len(stations)} 个 (含 _done 标记)")
    save_json(STOP_NAMES_FILE, stations)
    return stations


# ════════════════════════════════════════════════════════════
# Phase 2: 逐站名 stopname → 线路 id
# ════════════════════════════════════════════════════════════
def _query_stopname(name, lines):
    """按站名查线路, offset=100 分页。
    返回: 新增线路数(int); 请求失败(status=0)返回 None(不标记完成)。"""
    core = re.sub(r"[（(].*?[)）]", "", name).strip() or name
    params = {"key": AMAP_KEY, "city": CITY, "keywords": core,
              "offset": PAGE_SIZE, "page": 1}
    prev = len(lines)
    for pg in range(1, 101):
        params["page"] = pg
        data = api_get("https://restapi.amap.com/v3/bus/stopname", params)
        if data.get("status") != "1":
            return None
        stops = data.get("busstops") or []
        if not stops:
            break
        for s in stops:
            for bl in (s.get("buslines") or []):
                lid = bl.get("id")
                if lid:
                    lines.setdefault(lid, {
                        "name": bl.get("name"),
                        "start_stop": bl.get("start_stop"),
                        "end_stop": bl.get("end_stop"),
                    })
        if len(stops) < PAGE_SIZE:
            break
    return len(lines) - prev


def phase2_budget(max_req):
    """在配额预算内查询未完成的站名; 线路发现饱和时提前结束。返回已用请求数。"""
    global _request_count
    stop_names = load_json(STOP_NAMES_FILE, {})
    lines = load_json(LINES_FILE, {})
    done = set(stop_names.get("_done", []))
    names = [n for n in stop_names if n != "_done" and n not in done]

    start_req = _request_count
    empty_streak = 0
    processed = 0
    try:
        for name in names:
            if _request_count - start_req >= max_req:
                break
            new_n = _query_stopname(name, lines)
            if new_n is None:
                continue                      # 失败, 不标记, 次日重试
            done.add(name)
            processed += 1
            if new_n == 0:
                empty_streak += 1
                if empty_streak >= PLATEAU_STATIONS:
                    print(f"  [plateau] 连续 {PLATEAU_STATIONS} 站无新线路, 判定覆盖饱和")
                    break
            else:
                empty_streak = 0
            if processed % 10 == 0:
                save_json(STOP_NAMES_FILE, stop_names)
                save_json(LINES_FILE, lines)
    except QuotaExhausted:
        # 配额中止: 先保存 checkpoint 再向上抛
        stop_names["_done"] = sorted(done)
        save_json(STOP_NAMES_FILE, stop_names)
        save_json(LINES_FILE, lines)
        raise

    stop_names["_done"] = sorted(done)
    save_json(STOP_NAMES_FILE, stop_names)
    save_json(LINES_FILE, lines)
    used = _request_count - start_req
    print(f"  [Phase2] 用 {used} 请求 | 已完成站 {len(done)}/{len(stop_names)-1} | 已知线路 {len(lines)}")
    return used


# ════════════════════════════════════════════════════════════
# Phase 3: 逐线路 lineid (extensions=all) → 有序站序列
# ════════════════════════════════════════════════════════════
def _fetch_line_detail(lid, details):
    data = api_get("https://restapi.amap.com/v3/bus/lineid",
                   {"key": AMAP_KEY, "id": lid, "extensions": "all"})
    if data.get("status") != "1":
        return  # 失败, 不记录, 次日重试
    bl = (data.get("buslines") or [{}])[0]
    if not bl.get("id"):
        details[lid] = None
        return
    stops = []
    for s in bl.get("busstops") or []:
        loc = parse_loc(s.get("location"))
        if loc:
            stops.append({
                "seq": s.get("sequence"), "id": s.get("id"),
                "name": s.get("name"), "lng": loc[0], "lat": loc[1],
            })
    details[lid] = {
        "id": lid, "name": bl.get("name"), "type": bl.get("type"),
        "start_stop": bl.get("start_stop"), "end_stop": bl.get("end_stop"),
        "distance_km": bl.get("distance"), "start_time": bl.get("start_time"),
        "end_time": bl.get("end_time"), "direc": bl.get("direc"),
        "loop": bl.get("loop"), "company": bl.get("company"),
        "polyline": bl.get("polyline"), "stops": stops,
    }


def phase3_budget(max_req):
    """在配额预算内抓取已知线路的详情。返回已用请求数。"""
    global _request_count
    lines = load_json(LINES_FILE, {})
    details = load_json(LINE_DETAIL_FILE, {})
    ids = [l for l in lines if l not in details]

    start_req = _request_count
    done_cnt = 0
    try:
        for lid in ids:
            if _request_count - start_req >= max_req:
                break
            _fetch_line_detail(lid, details)
            done_cnt += 1
            if done_cnt % 25 == 0:
                save_json(LINE_DETAIL_FILE, details)
    except QuotaExhausted:
        save_json(LINE_DETAIL_FILE, details)
        raise
    save_json(LINE_DETAIL_FILE, details)

    used = _request_count - start_req
    ok = sum(1 for v in details.values() if v)
    print(f"  [Phase3] 用 {used} 请求 | 线路详情 {ok}/{len(lines)}")
    return used


# ════════════════════════════════════════════════════════════
# 每日运行 (配额预算内自动分配 Phase2 + Phase3)
# ════════════════════════════════════════════════════════════
def run_daily():
    print("=" * 60)
    print("公交爬虫 每日运行  (日配额 %d, 限速 %d req/s)" % (DAILY_QUOTA, int(round(1 / SLEEP))))
    print("=" * 60)
    stop_names = load_json(STOP_NAMES_FILE, {})
    lines = load_json(LINES_FILE, {})
    details = load_json(LINE_DETAIL_FILE, {})
    done_stations = len(stop_names.get("_done", []))
    ok = sum(1 for v in details.values() if v)
    print(f"  当前缓存: 站名 {len(stop_names)-1} 个(完成 {done_stations}) | "
          f"线路 {len(lines)} 条 | 线路详情 {ok} 条")
    print()

    try:
        budget = DAILY_QUOTA
        # Phase 2: 发现线路 (占 40% 配额, 饱和自动提前结束)
        p2 = int(budget * PHASE2_FRACTION)
        used = phase2_budget(p2)
        # Phase 3: 抓线路详情 (用剩余配额)
        if used < budget:
            used += phase3_budget(budget - used)
        print(f"\n  本次共使用 {used} 请求")
        if used >= budget:
            print("  [quota] 已用满今日配额, 明天再运行: python crawl_bus.py")
    except QuotaExhausted as e:
        print(f"\n  [quota] 今日配额用尽: {e}")
        print("  checkpoint 已保存, 明天再运行: python crawl_bus.py")


# ════════════════════════════════════════════════════════════
# 落库
# ════════════════════════════════════════════════════════════
def load_to_db(stop_names, line_details):
    print("=" * 60)
    print("Load: 写入 PostGIS (坐标 GCJ->WGS)")
    print("=" * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding("UTF8")
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS hefei_bus_stops (
            id TEXT PRIMARY KEY,
            stop_no BIGSERIAL UNIQUE,     -- 图节点整数编号 (供 pgRouting)
            name TEXT,
            adcode TEXT,
            lng DOUBLE PRECISION,
            lat DOUBLE PRECISION,
            geometry GEOMETRY(Point, 4326)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hefei_bus_lines (
            id TEXT PRIMARY KEY,
            name TEXT,
            type TEXT,
            start_stop TEXT,
            end_stop TEXT,
            distance_km DOUBLE PRECISION,
            start_time TEXT,
            end_time TEXT,
            direc_id TEXT,
            loop_flag BOOLEAN,
            company TEXT,
            geometry GEOMETRY(LineString, 4326)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hefei_bus_line_stops (
            line_id TEXT REFERENCES hefei_bus_lines(id) ON DELETE CASCADE,
            stop_id TEXT REFERENCES hefei_bus_stops(id) ON DELETE CASCADE,
            sequence INTEGER,
            PRIMARY KEY (line_id, stop_id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bls_line ON hefei_bus_line_stops(line_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bls_stop ON hefei_bus_line_stops(stop_id)")
    conn.commit()

    # 1. stops: 线路站优先, POI 站名兜底
    stops = {}
    for lid, d in line_details.items():
        if not d:
            continue
        for s in d["stops"]:
            if s["id"] not in stops:
                stops[s["id"]] = {"name": s["name"], "lng": s["lng"], "lat": s["lat"]}
    known_names = {s["name"] for s in stops.values()}
    for nm, info in stop_names.items():
        if nm == "_done" or nm in known_names:
            continue
        stops.setdefault(f"POI-{nm}", {"name": nm, "lng": info["lng"], "lat": info["lat"]})

    cur.execute("TRUNCATE hefei_bus_stops, hefei_bus_lines, hefei_bus_line_stops RESTART IDENTITY CASCADE")
    n = 0
    for sid, info in stops.items():
        wlng, wlat = gcj02_to_wgs84(info["lng"], info["lat"])
        cur.execute("""
            INSERT INTO hefei_bus_stops (id, name, lng, lat, geometry)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
        """, (sid, info["name"], wlng, wlat, wlng, wlat))
        n += 1
    conn.commit()
    print(f"  stops: {n}")

    # 2. lines
    n = 0
    for lid, d in line_details.items():
        if not d:
            continue
        geom = None
        if d.get("polyline"):
            pts = d["polyline"].split(";")
            wpts = [gcj02_to_wgs84(*parse_loc(p)) for p in pts if parse_loc(p)]
            if len(wpts) >= 2:
                geom = wpts
        if geom:
            wkt = "LINESTRING(" + ",".join(f"{p[0]} {p[1]}" for p in geom) + ")"
            cur.execute("""
                INSERT INTO hefei_bus_lines (id, name, type, start_stop, end_stop,
                    distance_km, start_time, end_time, direc_id, loop_flag, company, geometry)
                VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s, ST_GeomFromText(%s, 4326))
            """, (lid, d["name"], d["type"], d["start_stop"], d["end_stop"],
                  d["distance_km"], d["start_time"], d["end_time"], d["direc"],
                  str(d.get("loop")) == "1", d.get("company"), wkt))
        else:
            cur.execute("""
                INSERT INTO hefei_bus_lines (id, name, type, start_stop, end_stop,
                    distance_km, start_time, end_time, direc_id, loop_flag, company)
                VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,%s)
            """, (lid, d["name"], d["type"], d["start_stop"], d["end_stop"],
                  d["distance_km"], d["start_time"], d["end_time"], d["direc"],
                  str(d.get("loop")) == "1", d.get("company")))
        n += 1
    conn.commit()
    print(f"  lines: {n}")

    # 3. line_stops
    n = 0
    for lid, d in line_details.items():
        if not d:
            continue
        for s in d["stops"]:
            cur.execute("""
                INSERT INTO hefei_bus_line_stops (line_id, stop_id, sequence)
                VALUES (%s, %s, %s)
            """, (lid, s["id"], int(s.get("seq") or 0)))
            n += 1
    conn.commit()
    print(f"  line_stops: {n}")

    # 验证
    cur.execute("SELECT count(*) FROM hefei_bus_stops")
    print(f"\n  hefei_bus_stops: {cur.fetchone()[0]}")
    cur.execute("SELECT count(*) FROM hefei_bus_lines")
    print(f"  hefei_bus_lines: {cur.fetchone()[0]}")
    cur.execute("SELECT count(*) FROM hefei_bus_line_stops")
    print(f"  hefei_bus_line_stops: {cur.fetchone()[0]}")
    cur.execute("SELECT count(DISTINCT line_id) FROM hefei_bus_line_stops")
    print(f"  有完整站序的线路: {cur.fetchone()[0]}")

    cur.close()
    conn.close()


# ════════════════════════════════════════════════════════════
def estimate():
    # 线路发现饱和约 200 站, 线路约 400 条 (上下行)
    p2 = 200
    p3 = 400
    total = p2 + p3
    days = math.ceil(total / DAILY_QUOTA)
    print(f"Phase2 ~{p2}  Phase3 ~{p3}  Total ~{total} 请求")
    print(f"日配额 {DAILY_QUOTA} → 预计 {days} 天完成")


def reset_done():
    stop_names = load_json(STOP_NAMES_FILE, {})
    if "_done" in stop_names:
        del stop_names["_done"]
        save_json(STOP_NAMES_FILE, stop_names)
        print("已清空 _done 标记, 全部站名将重新查询")


# ════════════════════════════════════════════════════════════
def main():
    args = sys.argv[1:]

    if "--estimate" in args:
        estimate()
        return
    if "--reset" in args:
        reset_done()
        return

    stop_names = load_json(STOP_NAMES_FILE, {})
    line_details = load_json(LINE_DETAIL_FILE, {})

    if "--load" in args:
        load_to_db(stop_names, line_details)
        return

    if "--phase" in args:
        idx = args.index("--phase")
        phase = int(args[idx + 1])
        if phase == 1:
            phase1_collect_station_names()
        elif phase == 2:
            stop_names = load_json(STOP_NAMES_FILE, {})
            phase2_budget(DAILY_QUOTA)          # 手动跑用满当日配额
        elif phase == 3:
            lines = load_json(LINES_FILE, {})
            print(f"[manual] Phase3 用满当日配额 {DAILY_QUOTA} 次")
            phase3_budget(DAILY_QUOTA)
        else:
            print("phase 只支持 1/2/3")
        return

    # 默认: 每日运行
    run_daily()


if __name__ == "__main__":
    main()
