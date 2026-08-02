# -*- coding: utf-8 -*-
"""下载合肥官方公交数据 (61.133.142.137 开放平台)

两个数据资源:
  340F137F551049FB86196A9296D5F498  公交站点 (total ~5530)
  69262CAE812146D3B438DD3ED963F80D  公交线路 (total ~17637)

分页: pageSize 上限 50/页, token 放在路径中:
  GET {base}/query/{rid}/{token}/{pageNo}/{pageSize}

用法:
  python download_hfbus_official.py              # 下载全部
  python download_hfbus_official.py --analyze    # 仅分析已有缓存
"""
import json
import os
import sys
import time

import requests

TOKEN = "9613026a1482002"
BASE = "http://61.133.142.137:8800/open-api-rest/rest/api/query"
H = {"User-Agent": "city-life-circle/1.0"}
PAGE_SIZE = 50
SLEEP = 0.2

RID_STOP = "340F137F551049FB86196A9296D5F498"
RID_LINE = "69262CAE812146D3B438DD3ED963F80D"

CACHE = os.path.join(os.path.dirname(__file__), '..', '..', 'cache')
STOP_FILE = os.path.join(CACHE, 'bus_stops_official.json')
LINE_FILE = os.path.join(CACHE, 'bus_lines_official.json')


def get(rid, page):
    url = f"{BASE}/{rid}/{TOKEN}/{page}/{PAGE_SIZE}"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=H, timeout=60)
            d = r.json()
            if d.get("status"):
                return d["data"]["result"]
            return None
        except Exception:
            time.sleep(1 * (attempt + 1))
    return None


def download(rid, total_est, out_file):
    if os.path.exists(out_file):
        data = json.load(open(out_file, encoding="utf-8"))
        print(f"  {out_file.split(chr(92))[-1]} 已有 {len(data)} 条")
        return data
    data = []
    page = 1
    while True:
        rows = get(rid, page)
        if not rows:
            break
        data.extend(rows)
        if len(rows) < PAGE_SIZE:
            break
        if page % 40 == 0:
            print(f"  page {page} 累计 {len(data)}")
            json.dump(data, open(out_file, "w", encoding="utf-8"), ensure_ascii=False)
        page += 1
        time.sleep(SLEEP)
    json.dump(data, open(out_file, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  完成: {len(data)} 条 -> {out_file.split(chr(92))[-1]}")
    return data


def main():
    if "--analyze" not in sys.argv:
        print("下载公交站点...")
        stops = download(RID_STOP, 5530, STOP_FILE)
        print("下载公交线路...")
        lines = download(RID_LINE, 17637, LINE_FILE)
    else:
        stops = json.load(open(STOP_FILE, encoding="utf-8"))
        lines = json.load(open(LINE_FILE, encoding="utf-8"))

    print("\n=== 分析 ===")
    print(f"站点: {len(stops)} | 线路记录: {len(lines)}")

    codes = {}
    for r in lines:
        codes.setdefault(r.get("LINECODE"), []).append(r)
    print(f"去重 LINECODE: {len(codes)}")
    multi = {c: v for c, v in codes.items() if len(v) > 1}
    print(f"  多记录 LINECODE: {len(multi)}")
    if multi:
        sample = list(multi.items())[:3]
        for c, v in sample:
            print(f"    {c}: {len(v)} 条 -> LINEIDs={[x['LINEID'] for x in v]} "
                  f"DIR={[x['DIRECTIONTYPE'] for x in v]} DATE={[x['STARTRUNDATE'] for x in v]}")
    from collections import Counter
    print("  DIRECTIONTYPE 分布:", Counter(r.get("DIRECTIONTYPE") for r in lines))
    print("  LINESTATUS 分布:", Counter(r.get("LINESTATUS") for r in lines))

    # STOPLINES 字段: 是数量还是列表?
    sl = [s.get("STOPLINES") for s in stops[:20]]
    print("  STOPLINES 样本:", sl[:8])
    comma = sum(1 for s in stops if s.get("STOPLINES") and "," in str(s.get("STOPLINES")))
    print(f"  STOPLINES 含逗号: {comma}/{len(stops)} (逗号=列表, 否则=数量)")

    # 站点是否含线路码可关联
    print("\n  站点字段键:", sorted(stops[0].keys()))


if __name__ == "__main__":
    main()
