# -*- coding: utf-8 -*-
"""用高德搜索 POI 2.0 抽查公交站坐标, 核对合肥官方平台数据坐标系

背景: hefei_bus_stops 坐标来自合肥官方平台 (cache/bus_stops_official.json) 的
      LONGITUDE/LATITUDE, 落库时未做任何坐标转换 (load_8684_bus.py), 声称 WGS84。
      本项目路网/地铁/公交/POI 统一 WGS84, 若官方坐标实为 GCJ-02 (偏移~570m)
      则整个公交层会系统性偏移, 需重新评估。

方法: 用高德 /v5/place/text (搜索 POI 2.0, 公交站 typecode) 抽查少量站点:
  - 高德返回 GCJ-02, 转 WGS84 后与官方坐标比对
  - dist_wgs 小 (<150m) → 官方确为 WGS84
  - dist_gcj 小 (<150m) → 官方实为 GCJ-02
  - 两者都大      → 站点/名称不匹配 (记录供人工查看)

约束: 请求次数 ≤10 (1 次 typecode 探测 + 9 个抽查站), 频率 ≤1 req/s (SLEEP=1.2)。
用法: python probe_bus_stops_amap.py
"""
import difflib
import json
import os
import random
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import AMAP_KEY

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'backend'))
from engine.coord_utils import gcj02_to_wgs84  # noqa: E402

CACHE = os.path.join(ROOT, 'cache')
URL = "https://restapi.amap.com/v5/place/text"
HEADERS = {"User-Agent": "city-life-circle/1.0"}
SLEEP = 1.2
MAX_REQUESTS = 10
MAX_SAMPLES = 9  # 1 次留给 typecode 探测

request_count = 0


def api_get(params):
    global request_count
    if request_count >= MAX_REQUESTS:
        return None, "quota"
    request_count += 1
    for attempt in range(2):
        try:
            r = requests.get(URL, params=params, headers=HEADERS, timeout=20)
            d = r.json()
            if d.get("status") == "1":
                return d, None
            return None, f"status={d.get('status')} info={d.get('info')}"
        except Exception as e:
            time.sleep(2)
    return None, "network error"


def haversine(lng1, lat1, lng2, lat2):
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(a))


def parse_loc(s):
    try:
        lng, lat = s.split(",")
        return float(lng), float(lat)
    except (ValueError, AttributeError):
        return None


def discover_bus_typecode():
    """探测"公交车站"的 typecode: 搜索公交站关键词, 读第一条返回的 type/typecode"""
    d, err = api_get({
        "key": AMAP_KEY, "keywords": "公交站", "region": "合肥", "city_limit": "true",
        "page_size": 5, "page_num": 1,
    })
    if not d:
        print(f"  [typecode探测] 失败: {err}")
        return None
    for p in d.get("pois") or []:
        print(f"  [typecode探测] {p.get('name','')} type={p.get('type','')} typecode={p.get('typecode','')}")
        if "公交" in str(p.get("type", "")):
            return p.get("typecode", "")
    return None


def probe_stop(stop, typecode):
    name = stop["STATIONNAME"]
    olng, olat = float(stop["LONGITUDE"]), float(stop["LATITUDE"])
    d, err = api_get({
        "key": AMAP_KEY, "keywords": name, "region": "合肥", "city_limit": "true",
        "types": typecode, "page_size": 5, "page_num": 1,
    })
    if not d:
        return {"name": name, "official": (olng, olat), "error": err}

    best = None  # (dist, key, amap_name, gcj_lng, gcj_lat, wgs_lng, wgs_lat, ratio)
    for p in d.get("pois") or []:
        ll = parse_loc(p.get("location", ""))
        if not ll:
            continue
        glng, glat = ll
        wlng, wlat = gcj02_to_wgs84(glng, glat)
        ratio = difflib.SequenceMatcher(None, name, p.get("name", "")).ratio()
        for dist, key in ((haversine(olng, olat, wlng, wlat), "wgs"),
                          (haversine(olng, olat, glng, glat), "gcj")):
            if best is None or dist < best[0]:
                best = (dist, key, p.get("name", ""), glng, glat, wlng, wlat, ratio)
    return {"name": name, "official": (olng, olat), "best": best}


def main():
    global request_count
    random.seed(20260804)
    stops = json.load(open(os.path.join(CACHE, 'bus_stops_official.json'), encoding="utf-8"))
    print(f"官方站点总数: {len(stops)}\n")

    print("=" * 70)
    print("Step 1: typecode 探测 (公交站)")
    print("=" * 70)
    typecode = discover_bus_typecode()
    time.sleep(SLEEP)
    if not typecode:
        print("无法确定公交站 typecode, 中止")
        return
    print(f"  → 使用 typecode={typecode}\n")

    # 抽样: 固定 3 个已知枢纽 + 6 个随机, 保证城区分布
    hub_names = ["市府广场", "合肥南站", "明珠广场"]
    hubs = [s for s in stops if s["STATIONNAME"] in hub_names]
    rest = [s for s in stops if s["STATIONNAME"] not in hub_names]
    samples = hubs[:3] + random.sample(rest, max(0, MAX_SAMPLES - len(hubs)))

    print("=" * 70)
    print(f"Step 2: 抽查 {len(samples)} 站 (请求次数上限 {MAX_REQUESTS})")
    print("=" * 70)
    rows = []
    for i, s in enumerate(samples):
        r = probe_stop(s, typecode)
        rows.append(r)
        ok = "OK" if not r.get("error") else "FAIL"
        print(f"  [{i+1}/{len(samples)}] {s['STATIONNAME']} ({ok}) 累计请求 {request_count}")
        json.dump(rows, open(os.path.join(CACHE, 'bus_stops_amap_probe.json'), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        if request_count >= MAX_REQUESTS:
            print(f"  [警告] 已达 {MAX_REQUESTS} 次请求上限, 停止后续抽样")
            break
        time.sleep(SLEEP)

    print("\n" + "=" * 70)
    print("Step 3: 汇总")
    print("=" * 70)
    hdr = f"{'官方站名':<14}{'官方(lng,lat)':<24}{'匹配':<12}{'名称相似度':<10}{'距高德转WGS':<12}{'距高德原GCJ':<12}判定"
    print(hdr)
    print("-" * len(hdr))
    n_wgs = n_gcj = n_bad = 0
    for r in rows:
        name = r["name"]
        olng, olat = r["official"]
        if r.get("error"):
            print(f"{name:<14}{f'{olng:.6f},{olat:.6f}':<23}{'查询失败':<12}{r['error']}")
            n_bad += 1
            continue
        _, key, aname, glng, glat, wlng, wlat, ratio = r["best"]
        dwgs = haversine(olng, olat, wlng, wlat)
        dgcj = haversine(olng, olat, glng, glat)
        if dwgs <= 150:
            verdict, n_wgs = "WGS84", n_wgs + 1
        elif dgcj <= 150:
            verdict, n_gcj = "GCJ-02", n_gcj + 1
        else:
            verdict, n_bad = "不匹配", n_bad + 1
        print(f"{name:<14}{f'{olng:.6f},{olat:.6f}':<23}{aname:<12}{ratio:<10.2f}"
              f"{dwgs:<12.1f}{dgcj:<12.1f}{verdict}")

    print("-" * len(hdr))
    print(f"判定: WGS84={n_wgs}  GCJ-02={n_gcj}  不匹配/失败={n_bad}  (请求数 {request_count}/{MAX_REQUESTS})")
    json.dump(rows, open(os.path.join(CACHE, 'bus_stops_amap_probe.json'), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n结果已保存 cache/bus_stops_amap_probe.json")


if __name__ == "__main__":
    main()
