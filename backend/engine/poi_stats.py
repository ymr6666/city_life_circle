"""设施统计共享逻辑: 按 category 聚合 POI 为设施, 含同名近距去重

供 /api/isochrone 与 /api/poi-stat 复用, 统一设施粒度统计口径。

同名去重:
  group_poi_facilities.py 已按 (category, 基础名, 1500m) 生成 facility_id。
  但命名剥离规则不全时 (如 "X医院门诊部" 与 "X医院住院部" 各自成组),
  同一物理设施会有多个 facility_id。这里在查询时再补一刀:
  同 category 同 facility_name、代表点相距 <= merge_dist_m 的设施合并,
  连锁分店 (距离远) 保持独立。
"""
import math

DEFAULT_MERGE_DIST_M = 300


def _haversine_m(lng1, lat1, lng2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(a))


def build_facilities_by_category(pois, merge_dist_m=DEFAULT_MERGE_DIST_M, include_items=True):
    """从可达/圈内 POI 列表构建设施粒度统计 (含同名近距去重)

    pois: [{category, id, name, sub_category, facility_id, facility_name,
            fac_lng, fac_lat, fac_sub_category, ...}]  (fac_* 可缺省, 回退到自身)
    include_items=False 时不返回每个设施的成员 POI 列表 (缩小响应体积)。
    返回: {category: {count, items: [{name, sub_category, lng, lat, count, items?, merged?}]}}
    """
    fac = {}
    for p in pois:
        cat = p.get('category')
        fid = p.get('facility_id') or p.get('id')
        if cat is None or fid is None:
            continue
        d = fac.setdefault(cat, {}).setdefault(fid, {
            "name": p.get('facility_name') or p.get('name') or '',
            "address": p.get('address') or '',
            "category": cat,
            "sub_category": p.get('fac_sub_category') or p.get('sub_category') or '',
            "rating": p.get('rating') or '',
            "cost": p.get('cost') or '',
            "opentime_today": p.get('opentime_today') or '',
            "lng": p.get('fac_lng') if p.get('fac_lng') is not None else p.get('lng'),
            "lat": p.get('fac_lat') if p.get('fac_lat') is not None else p.get('lat'),
            "count": 0,
            "items": [],
        })
        d["count"] += 1
        d["items"].append(p)

    result = {}
    for cat, m in fac.items():
        by_name = {}
        for d in m.values():
            by_name.setdefault(d["name"], []).append(d)

        merged_list = []
        for name, ds in by_name.items():
            # 确定性排序 (lng, lat, name)
            ds.sort(key=lambda d: (d["lng"] or 0, d["lat"] or 0))
            groups = []
            for d in ds:
                placed = False
                for g in groups:
                    rep = g[0]
                    if (_haversine_m(rep["lng"], rep["lat"], d["lng"], d["lat"])
                            < merge_dist_m):
                        g.append(d)
                        placed = True
                        break
                if not placed:
                    groups.append([d])
            for g in groups:
                if len(g) == 1:
                    merged_list.append(g[0])
                else:
                    rep = dict(g[0])
                    rep["count"] = sum(x["count"] for x in g)
                    if include_items:
                        rep["items"] = [it for x in g for it in x["items"]]
                    rep["merged"] = len(g)
                    merged_list.append(rep)

        if not include_items:
            for d in merged_list:
                d.pop("items", None)
        merged_list.sort(key=lambda d: -d["count"])
        result[cat] = {"count": len(merged_list), "items": merged_list}
    return result
