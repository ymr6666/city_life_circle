# -*- coding: utf-8 -*-
"""高德公交数据质量探测 (限 10 次请求, 1 req/s)

目的: 评估高德能否作为"有序站点序列"来源, 决定是否申请更多 key。
  - 5 次 lineid(extensions=all): 对已获取的线路 id 拿完整有序站点
  - 5 次 linename: 用官方线路码测试能否映射到高德线路

已获取过的不重复获取 (1,068 站名 / 57 线路 id 直接复用缓存)。

用法: python probe_amap_bus.py
"""
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import AMAP_KEY

CACHE = os.path.join(os.path.dirname(__file__), '..', '..', 'cache')
HEADERS = {"User-Agent": "city-life-circle/1.0"}
SLEEP = 1.1

# 用到的官方线路码 (存在则测, 优先数字常规线 + 定制线)
OFFICIAL_CODES = ["1", "46", "116", "312", "T216"]


def api_get(url, params):
    for attempt in range(2):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=25)
            d = r.json()
            if d.get("status") == "1":
                return d
            print(f"    [api] status={d.get('status')} info={d.get('info')} infocode={d.get('infocode')}")
            return None
        except Exception as e:
            print(f"    [api] retry: {e}")
            time.sleep(2)
    return None


def main():
    # ── 5 个已获取线路 id → lineid 完整详情 ──
    known = json.load(open(os.path.join(CACHE, 'bus_lines.json'), encoding="utf-8"))
    known_ids = list(known.keys())[:5]
    print("=" * 70)
    print(f"PART 1: lineid(extensions=all) 对 {len(known_ids)} 条已知线路")
    print("=" * 70)

    results = {"lineid": {}, "linename": {}}
    for lid in known_ids:
        d = api_get("https://restapi.amap.com/v3/bus/lineid",
                    {"key": AMAP_KEY, "id": lid, "extensions": "all"})
        time.sleep(SLEEP)
        if not d:
            results["lineid"][lid] = None
            continue
        bl = (d.get("buslines") or [{}])[0]
        stops = bl.get("busstops") or []
        info = {
            "name": bl.get("name"), "type": bl.get("type"),
            "start": bl.get("start_stop"), "end": bl.get("end_stop"),
            "distance_km": bl.get("distance"),
            "start_time": bl.get("start_time"), "end_time": bl.get("end_time"),
            "direc": bl.get("direc"), "loop": bl.get("loop"),
            "n_stops": len(stops),
            "first3": [(s.get("sequence"), s.get("name")) for s in stops[:3]],
            "last3": [(s.get("sequence"), s.get("name")) for s in stops[-3:]],
            "has_polyline": bool(bl.get("polyline")),
        }
        results["lineid"][lid] = info
        print(f"\n  {lid}  {info['name']}")
        print(f"    类型={info['type']} 距离={info['distance_km']}km 站数={info['n_stops']} "
              f"对向={info['direc']} 环线={info['loop']}")
        print(f"    首3站: {info['first3']}")
        print(f"    末3站: {info['last3']}")
        print(f"    有线路几何: {info['has_polyline']} 首末班: {info['start_time']}/{info['end_time']}")

    # ── 5 个官方线路码 → linename 映射测试 ──
    official = json.load(open(os.path.join(CACHE, 'bus_lines_official.json'), encoding="utf-8"))
    off_codes = set(r.get("LINECODE") for r in official)
    codes = [c for c in OFFICIAL_CODES if c in off_codes]
    print("\n" + "=" * 70)
    print(f"PART 2: linename 官方码映射 ({len(codes)} 个)")
    print("=" * 70)
    for code in codes:
        d = api_get("https://restapi.amap.com/v3/bus/linename",
                    {"key": AMAP_KEY, "city": "340100", "keywords": code,
                     "offset": 20, "page": 1, "extensions": "all"})
        time.sleep(SLEEP)
        if not d:
            results["linename"][code] = None
            print(f"\n  {code}: 查询失败")
            continue
        bls = d.get("buslines") or []
        recs = []
        for bl in bls[:5]:
            stops = bl.get("busstops") or []
            recs.append({
                "id": bl.get("id"), "name": bl.get("name"),
                "start": bl.get("start_stop"), "end": bl.get("end_stop"),
                "n_stops": len(stops), "type": bl.get("type"),
                "first": [(s.get("sequence"), s.get("name")) for s in stops[:2]],
            })
        results["linename"][code] = recs
        print(f"\n  官方码 {code}: 高德返回 {len(bls)} 条")
        for r in recs:
            print(f"    {r['id']}  {r['name']}  站数={r['n_stops']}  {r['start']}->{r['end']}  首站={r['first']}")

    # 官方对应线路对照
    print("\n" + "=" * 70)
    print("官方对照 (bus_lines_official.json)")
    print("=" * 70)
    for code in codes:
        recs = [r for r in official if r.get("LINECODE") == code]
        r = recs[0] if recs else None
        if r:
            print(f"  {code}: 官方首末={r['FIRSTSTATION']}->{r['LASTSTATION']} "
                  f"长度={r.get('UPLEN')}km 站数={r['STATIONCOUNT']} 状态={r['LINESTATUS']}")

    json.dump(results, open(os.path.join(CACHE, 'bus_amap_probe.json'), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n结果已保存 cache/bus_amap_probe.json")


if __name__ == "__main__":
    main()
