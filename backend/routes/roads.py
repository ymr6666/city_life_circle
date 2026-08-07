"""路网 GeoJSON API: 按视口(bbox)返回道路, 供前端叠加显示

用途: 前端在地图上叠加路网 (验证可达性/道路分类)。
设计: 全量 10 万+ 边太重, 前端随地图平移按当前视野范围请求,
      并用 ST_Simplify 降点, 限制单次返回数量。

GET /api/roads?minlng=..&minlat=..&maxlng=..&maxlat=..[&mode=all|walk|cycle|drive][&tolerance=0.00002]
"""
from flask import Blueprint, request, jsonify

from services.database import execute_one

roads_bp = Blueprint('roads', __name__)

MAX_BBOX_DEG = 1.0     # 防止一次拉取过大
MAX_FEATURES = 30000   # 单次返回边数上限


@roads_bp.route('/api/roads', methods=['GET'])
def roads():
    args = request.args
    try:
        minlng = float(args['minlng'])
        minlat = float(args['minlat'])
        maxlng = float(args['maxlng'])
        maxlat = float(args['maxlat'])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "minlng,minlat,maxlng,maxlat required"}), 400
    if not (minlng < maxlng and minlat < maxlat):
        return jsonify({"error": "invalid bbox"}), 400
    if maxlng - minlng > MAX_BBOX_DEG or maxlat - minlat > MAX_BBOX_DEG:
        return jsonify({"error": f"bbox too large (max {MAX_BBOX_DEG} deg)"}), 400

    mode = args.get('mode', 'all')
    try:
        tol = float(args.get('tolerance', 0.00002))
    except (TypeError, ValueError):
        tol = 0.00002

    ok_filter = ""
    if mode in ('walk', 'cycle', 'drive'):
        ok_filter = f" AND {mode}_ok"

    row = execute_one(f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(
                json_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(ST_Simplify(r.geometry, %s))::json,
                    'properties', json_build_object(
                        'id', r.id, 'highway', r.highway, 'name', r.name,
                        'bridge_class', r.bridge_class
                    )
                )
            ), '[]'::json)
        )
        FROM (
            SELECT id, highway, name, bridge_class, geometry
            FROM hefei_roads
            WHERE geometry && ST_MakeEnvelope(%s, %s, %s, %s, 4326){ok_filter}
            LIMIT {MAX_FEATURES}
        ) r
    """, (tol, minlng, minlat, maxlng, maxlat))

    if row and row[0]:
        return jsonify(row[0])
    return jsonify({"type": "FeatureCollection", "features": []})
