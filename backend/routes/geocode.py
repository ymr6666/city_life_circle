"""地理编码 API: 地名(关键词) → 经纬度 (WGS84)

调用高德搜索 POI 2.0 (/v5/place/text)。高德返回 GCJ-02,
在 services/amap.py 边界处一次性转换为 WGS84, 与全库坐标系统一。
"""
from flask import Blueprint, request, jsonify

from services.amap import geocode_keywords

geocode_bp = Blueprint('geocode', __name__)


@geocode_bp.route('/api/geocode', methods=['GET', 'POST'])
def geocode():
    """地名/地址 → 经纬度

    GET  /api/geocode?keywords=政务区万象城&region=合肥&limit=5[&types=060100]
    POST /api/geocode  {keywords, region?, limit?, types?}

    返回坐标均为 WGS84 (lng/lat 顺序), 可直接用于 /api/isochrone。
    """
    if request.method == 'GET':
        keywords = (request.args.get('keywords')
                    or request.args.get('q')
                    or request.args.get('address'))
        region = request.args.get('region', '合肥')
        limit = request.args.get('limit', 5)
        types = request.args.get('types')
    else:
        data = request.get_json() or {}
        keywords = data.get('keywords') or data.get('q') or data.get('address')
        region = data.get('region', '合肥')
        limit = data.get('limit', 5)
        types = data.get('types')

    if not keywords or not str(keywords).strip():
        return jsonify({"error": "keywords (地名/地址) required"}), 400

    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 5

    try:
        results = geocode_keywords(str(keywords).strip(), region=region,
                                   limit=limit, types=types)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502

    if not results:
        return jsonify({
            "query": str(keywords).strip(),
            "region": region,
            "coord_sys": "WGS84",
            "count": 0,
            "results": [],
        }), 404

    return jsonify({
        "query": str(keywords).strip(),
        "region": region,
        "coord_sys": "WGS84",
        "count": len(results),
        "results": results,
    })
