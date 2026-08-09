# -*- coding: utf-8 -*-
"""清洗 culture 类别 POI (关键词爬取混入噪声)

依据 typecode 白名单:
  - 140xxx 科教文化 = 真正的文化场馆 → 保留在 culture
  - 140500 = 图书馆 → 归入 library 类别
  - 其余 (110xxx 购物 / 080xxx 体育娱乐 / 130xxx 银行 / 060xxx 市场 /
          050xxx 餐饮 / 070xxx 生活 / 100xxx 住宿 / 150xxx 交通 / 170xxx 商务 / 090xxx 医疗)
    = 关键词搜索噪声 → 删除

用法:
  python clean_culture_poi.py --dry-run   # 只统计不动数据
  python clean_culture_poi.py             # 执行
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import psycopg2

# 文化场馆白名单 (任一 typecode 命中即保留)
CULTURE_KEEP = {
    '140000', '140100', '140200', '140300', '140400',
    '140600', '140700', '140800', '140900', '141000', '141100',
    '120300',   # 文化馆/文化传媒 (v5 部分文化馆带 12 系类型)
}
LIBRARY_CODE = '140500'


def main():
    dry = '--dry-run' in sys.argv
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()

    cur.execute("SELECT id, sub_category FROM hefei_poi WHERE category='culture'")
    rows = cur.fetchall()

    to_library = []
    to_keep = 0
    to_delete = []
    for pid, sub in rows:
        codes = {c for c in (sub or '').split('|') if c}
        if LIBRARY_CODE in codes:
            to_library.append(pid)
        elif codes & CULTURE_KEEP:
            to_keep += 1
        else:
            to_delete.append(pid)

    print(f"culture 总 {len(rows)} 条")
    print(f"  保留(文化场馆): {to_keep}")
    print(f"  归入 library: {len(to_library)}")
    print(f"  删除(噪声): {len(to_delete)}")

    if dry:
        print("\n[dry-run] 未改动数据")
    else:
        if to_library:
            cur.execute(
                "UPDATE hefei_poi SET category='library' WHERE id = ANY(%s)",
                (to_library,))
            print(f"  已迁移 {cur.rowcount} 条 → library")
        if to_delete:
            cur.execute("DELETE FROM hefei_poi WHERE id = ANY(%s)", (to_delete,))
            print(f"  已删除 {cur.rowcount} 条噪声")
        conn.commit()
        print("完成!")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
