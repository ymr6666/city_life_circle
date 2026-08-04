"""多边形内分类设施统计 API: POST /api/poi-stat

输入等时圈/自画多边形 (GeoJSON), 返回:
  - 圈内 POI 总数 + 按 category 统计 (含 sub_category typecode 拆分)
  - 圈内地铁站 / 公交站数量 (评分"交通"维度用)
约定:
  - 多边形坐标与全库一致为 WGS84
  - pois_by_category = 原始 POI 粒度 (科室/楼宇各自计数, 引擎视角)
  - facilities_by_category = 设施粒度 (facility_id 去重, 展示/评分用)
  - sub_category 为组合 typecode 时 (如 "090601|090300") 逐项计入各子类
"""
from collections import defaultdict
import json

from flask import Blueprint, request, jsonify

from services.database import execute_query

poi_stat_bp = Blueprint('poi_stat', __name__)


def _extract_geometry(obj):
    """从请求体提取 GeoJSON 几何 (支持 Polygon/MultiPolygon/Feature)"""
    if not isinstance(obj, dict):
        return None
    if obj.get('type') in ('Polygon', 'MultiPolygon'):
        return obj
    if obj.get('type') == 'Feature':
        g = obj.get('geometry')
        if isinstance(g, dict) and g.get('type') in ('Polygon', 'MultiPolygon'):
            return g
    return None


def _count_stations(table, geom_json):
    return execute_query(
        f"SELECT count(*) FROM {table} WHERE ST_Covers(ST_GeomFromGeoJSON(%s), geometry)",
        (geom_json,),
    )[0][0]


@poi_stat_bp.route('/api/poi-stat', methods=['POST'])
def poi_stat():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400

    polygon = data.get('polygon', data)
    geom = _extract_geometry(polygon)
    if not geom:
        return jsonify({"error": "polygon (GeoJSON Polygon/MultiPolygon/Feature) required"}), 400
    include_items = bool(data.get('include_items', False))

    try:
        geom_json = json.dumps(geom, ensure_ascii=False)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid polygon geometry"}), 400

    try:
        rows = execute_query(
            "SELECT p.category, COALESCE(p.sub_category, ''),"
            "       ST_X(p.geometry), ST_Y(p.geometry), p.id, p.name,"
            "       COALESCE(p.facility_id, p.id),"
            "       COALESCE(p.facility_name, p.name),"
            "       ST_X(COALESCE(f.geometry, p.geometry)),"
            "       ST_Y(COALESCE(f.geometry, p.geometry)),"
            "       COALESCE(f.sub_category, p.sub_category)"
            " FROM hefei_poi p"
            " LEFT JOIN hefei_poi f ON f.id = p.facility_id"
            " WHERE ST_Covers(ST_GeomFromGeoJSON(%s), p.geometry)",
            (geom_json,),
        )
    except Exception:
        return jsonify({"error": "invalid or unsupported polygon"}), 400

    cat_count = defaultdict(int)
    cat_subs = defaultdict(lambda: defaultdict(int))
    cat_items = defaultdict(list)
    facilities = defaultdict(dict)   # category -> {facility_id: {...}}
    for cat, sub, lng, lat, pid, name, fid, fname, flng, flat, fsub in rows:
        cat_count[cat] += 1
        for code in (sub or '').split('|'):
            if code:
                cat_subs[cat][code] += 1
        if include_items and len(cat_items[cat]) < 200:
            cat_items[cat].append({"id": pid, "name": name, "sub_category": sub,
                                   "lng": lng, "lat": lat})
        fac = facilities[cat].setdefault(fid, {
            "name": fname, "sub_category": fsub,
            "lng": flng, "lat": flat, "count": 0,
        })
        fac["count"] += 1

    pois_by_category = {}
    for cat in sorted(cat_count, key=lambda c: -cat_count[c]):
        entry = {
            "count": cat_count[cat],
            "sub_categories": dict(sorted(cat_subs[cat].items(), key=lambda kv: -kv[1])),
        }
        if include_items:
            entry["items"] = cat_items[cat]
        pois_by_category[cat] = entry

    facilities_by_category = {}
    for cat, fac_map in facilities.items():
        facilities_by_category[cat] = {
            "count": len(fac_map),
            "items": sorted(fac_map.values(), key=lambda f: -f['count']),
        }

    try:
        metro = _count_stations('hefei_metro_stations', geom_json)
        bus = _count_stations('hefei_bus_stops', geom_json)
    except Exception:
        return jsonify({"error": "invalid or unsupported polygon"}), 400

    return jsonify({
        "total_pois": len(rows),
        "total_facilities": sum(v['count'] for v in facilities_by_category.values()),
        "pois_by_category": pois_by_category,
        "facilities_by_category": facilities_by_category,
        "metro_stations": metro,
        "bus_stops": bus,
    })
