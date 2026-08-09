# -*- coding: utf-8 -*-
"""清洗 residential 类别 POI (关键词"小区"爬取混入商业/地址命中)

规则: 名称含住宅标识的保留, 否则删除 (关键词"小区"常命中地址含"小区"的商场/写字楼)。
保留标识: 小区 / 家园 / 新村 / 公寓 / 公馆 / 山庄 / 花园 / 苑 / 邸 / 庭 /
          华府 / 名居 / 雅居 / 嘉苑 / 花苑 / 名邸 / 丽景 / 锦绣 / 城市之光

用法:
  python clean_residential_poi.py --dry-run
  python clean_residential_poi.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import psycopg2

MARKERS = (
    '小区', '家园', '新村', '公寓', '公馆', '山庄', '花园', '苑', '邸', '庭',
    '华府', '名居', '雅居', '嘉苑', '花苑', '名邸', '丽景', '锦绣', '城市之光',
    '水岸', '半岛', '名筑', '豪庭',
)


def is_residential_name(name):
    n = name or ''
    return any(m in n for m in MARKERS)


def main():
    dry = '--dry-run' in sys.argv
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()

    cur.execute("SELECT id, name FROM hefei_poi WHERE category='residential'")
    rows = cur.fetchall()

    keep_ids = []
    drop_ids = []
    drop_samples = []
    for pid, name in rows:
        if is_residential_name(name):
            keep_ids.append(pid)
        else:
            drop_ids.append(pid)
            if len(drop_samples) < 10:
                drop_samples.append((name or '')[:24])

    print(f"residential 总 {len(rows)} 条")
    print(f"  保留(名称含住宅标识): {len(keep_ids)}")
    print(f"  删除(商业/地址命中): {len(drop_ids)}")
    if drop_samples:
        print("  删除样例:")
        for s in drop_samples:
            print("    -", s)

    if dry:
        print("\n[dry-run] 未改动")
    else:
        if drop_ids:
            cur.execute("DELETE FROM hefei_poi WHERE id = ANY(%s)", (drop_ids,))
            print(f"  已删除 {cur.rowcount} 条")
        conn.commit()
        print("完成!")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
