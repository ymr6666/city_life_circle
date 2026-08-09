# -*- coding: utf-8 -*-
"""邮政类别迁移: 邮政储蓄银行→bank, 纯邮政删除

背景: 邮政设施多为邮政储蓄银行(160139), 寄件多走快递, 纯邮政网点意义不大。
方案:
  1. post 类中"储蓄/邮储"相关 POI → category='bank' (200 个)
  2. 其余纯邮政 POI → 删除 (199 个)
  3. 连带处理 poi_road_nodes / facility 分组引用 (ON DELETE CASCADE 自动清挂接)

用法:
  python migrate_post_to_bank.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import psycopg2


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()

    print("=" * 60)
    print("Step 1: 邮政储蓄银行 → bank")
    print("=" * 60)
    cur.execute("""
        UPDATE hefei_poi SET category = 'bank'
        WHERE category = 'post'
          AND (name LIKE '%储蓄%' OR name LIKE '%邮储%')
    """)
    moved = cur.rowcount
    print(f"  迁移 {moved} 条 → bank")
    conn.commit()

    # 迁移后的 sub_category 归并到银行口径 (160139 为主)
    cur.execute("""
        UPDATE hefei_poi SET sub_category = '160139'
        WHERE category = 'bank' AND sub_category LIKE '%160139%'
    """)
    conn.commit()

    print("=" * 60)
    print("Step 2: 删除纯邮政 POI")
    print("=" * 60)
    cur.execute("SELECT count(*) FROM hefei_poi WHERE category = 'post'")
    left = cur.fetchone()[0]
    cur.execute("DELETE FROM hefei_poi WHERE category = 'post'")
    deleted = cur.rowcount
    conn.commit()
    print(f"  删除 {deleted} 条纯邮政 POI")

    print("=" * 60)
    print("Step 3: 验证")
    print("=" * 60)
    cur.execute("SELECT category, count(*) FROM hefei_poi GROUP BY category ORDER BY count(*) DESC")
    for r in cur.fetchall():
        print(f"  {r[0]:20s} {r[1]}")
    cur.execute("SELECT count(*) FROM hefei_poi WHERE category='post'")
    print(f"\n  post 剩余: {cur.fetchone()[0]}")
    cur.execute("SELECT count(*) FROM poi_road_nodes pn JOIN hefei_poi p ON p.id=pn.poi_id WHERE p.category='bank'")
    print(f"  bank walk 挂接: {cur.fetchone()[0]} 条")

    cur.close()
    conn.close()
    print("\n完成!")


if __name__ == "__main__":
    main()
