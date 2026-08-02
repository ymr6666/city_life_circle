# -*- coding: utf-8 -*-
"""8684 合肥公交爬虫 (低频率)

数据来源: https://hefei.8684.com.cn/
  - 枚举: 用官方 898 个线路码驱动搜索 /so?k=pp&q={keyword} → /x_{hash}
  - 详情: 抓 /x_{hash} → 去程/回程 有序站点 + 运行时间/公司/更新日期

约束: 低频率 (0.5s + 0.3s 抖动), 结果增量缓存, 可断点续跑。

缓存:
  cache/bus_8684_enum.json     code -> {"hash","name","found"}
  cache/bus_8684_lines.json    hash -> {name, code, url, up[], down[], meta}

用法:
  python crawl_8684.py            # 枚举 + 详情
  python crawl_8684.py --enum     # 只枚举
  python crawl_8684.py --detail   # 只抓详情 (已枚举的 hash)
  python crawl_8684.py --status   # 查看进度
"""
import json
import os
import random
import re
import sys
import time

import requests

CACHE = os.path.join(os.path.dirname(__file__), '..', '..', 'cache')
ENUM_FILE = os.path.join(CACHE, 'bus_8684_enum.json')
LINES_FILE = os.path.join(CACHE, 'bus_8684_lines.json')
OFFICIAL_LINE_FILE = os.path.join(CACHE, 'bus_lines_official.json')

BASE = "https://hefei.8684.com.cn"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
SLEEP = 0.5
JITTER = 0.3


def get(url, timeout=25):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200 and r.text.strip():
                return r.text
        except Exception as e:
            print(f"  [retry {attempt+1}] {url} {e}")
        time.sleep(2 * (attempt + 1))
    return None


def load_json(path, default):
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def norm_name(name):
    """8684 线路名 → 官方码: '46路'->'46', 'B1线'->'B1', 'T216路'->'T216'"""
    return re.sub(r"(路|线)$", "", (name or "").strip())


def enum_keyword(code):
    """搜索关键字: 纯数字码加'路'后缀, 字母码用原样"""
    if code.isdigit():
        return code + "路"
    return code


# ── 枚举: code → /x_{hash} ──────────────────────────────────
def enum_lines():
    official = load_json(OFFICIAL_LINE_FILE, [])
    codes = []
    seen = set()
    for r in official:
        c = r.get("LINECODE")
        if c and c not in seen:
            seen.add(c)
            codes.append(c)
    print(f"官方线路码: {len(codes)}")

    enum = load_json(ENUM_FILE, {})
    for i, code in enumerate(codes):
        if code in enum:
            continue
        text = get(f"{BASE}/so?k=pp&q={enum_keyword(code)}")
        found = None
        if text:
            for m in re.finditer(r'<a href="(/x_[0-9a-f]{8})">([^<]+)</a>', text):
                name = m.group(2).strip()
                if norm_name(name) == code:
                    found = {"hash": m.group(1), "name": name}
                    break
        enum[code] = found or {"hash": None, "name": None}
        if (i + 1) % 100 == 0:
            print(f"  枚举 {i+1}/{len(codes)}, 命中 {sum(1 for v in enum.values() if v.get('hash'))}")
            save_json(ENUM_FILE, enum)
        time.sleep(SLEEP + random.random() * JITTER)

    save_json(ENUM_FILE, enum)
    hit = sum(1 for v in enum.values() if v.get("hash"))
    print(f"枚举完成: {hit}/{len(codes)} 命中")
    return enum


# ── 详情: hash → 有序站点 ───────────────────────────────────
_STOPLIST_RE = re.compile(
    r'<div class="section-title">\s*<span class="title">([^<]+)</span>\s*'
    r'<span class="stop-count">共(\d+)站</span>\s*</div>\s*'
    r'<ol class="stops">(.*?)</ol>', re.S)
_STOP_RE = re.compile(r'class="stop-name">([^<]+)</a>')


def parse_line_page(hash_url, text):
    """返回 {name, code, up, down, meta}"""
    data = {"hash": hash_url, "name": None, "up": [], "down": [], "meta": {}}
    m = re.search(r"<h1>(合肥[^<]+?)公交车路线</h1>", text)
    if m:
        data["name"] = m.group(1)
    for tm in re.finditer(r"<li><strong>([^<：]+)：</strong>([^<]*)</li>", text):
        data["meta"][tm.group(1)] = tm.group(2).strip()

    for sm in _STOPLIST_RE.finditer(text):
        title = sm.group(1)      # 如 "合肥46路(去程)"
        stops = [s.strip() for s in _STOP_RE.findall(sm.group(3))]
        if "去程" in title:
            data["up"] = stops
        elif "回程" in title:
            data["down"] = stops
    return data


def fetch_details(enum):
    lines = load_json(LINES_FILE, {})
    todo = [v for v in enum.values() if v.get("hash") and v["hash"] not in lines]
    print(f"待抓详情: {len(todo)}")
    for i, info in enumerate(todo):
        url = BASE + info["hash"]
        text = get(url)
        if text:
            d = parse_line_page(info["hash"], text)
            d["code"] = norm_name(info["name"])
            d["url"] = url
            lines[info["hash"]] = d
        if (i + 1) % 50 == 0:
            print(f"  详情 {i+1}/{len(todo)}, 已存 {len(lines)}")
            save_json(LINES_FILE, lines)
        time.sleep(SLEEP + random.random() * JITTER)

    save_json(LINES_FILE, lines)
    with_stops = sum(1 for v in lines.values() if v.get("up") or v.get("down"))
    print(f"详情完成: {len(lines)} 条 (含有序站点 {with_stops})")
    return lines


# ── 状态 ────────────────────────────────────────────────────
def status():
    enum = load_json(ENUM_FILE, {})
    lines = load_json(LINES_FILE, {})
    hit = sum(1 for v in enum.values() if v.get("hash"))
    with_stops = sum(1 for v in lines.values() if v.get("up") or v.get("down"))
    up_n = sum(len(v.get("up", [])) for v in lines.values())
    down_n = sum(len(v.get("down", [])) for v in lines.values())
    print(f"枚举: {hit}/{len(enum)} 命中 | 详情: {len(lines)} 条, 含站序 {with_stops}")
    print(f"站点数: 去程 {up_n}, 回程 {down_n}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--status" in args:
        status()
    elif "--enum" in args:
        enum_lines()
    elif "--detail" in args:
        fetch_details(load_json(ENUM_FILE, {}))
    else:
        enum = enum_lines()
        fetch_details(enum)
