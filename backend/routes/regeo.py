"""逆地理编码 API: WGS84 坐标 → 地址 + 最近 POI

用途: 地图选点 / 反算设施列表显示地址, 而不是裸的经纬度。

GET  /api/regeo?lat=31.861&lng=117.285[&poinums=3]
POST /api/regeo  {"lat":31.861,"lng":117.285}
"""
from flask import Blueprint, request, jsonify

from services.amap import regeo

regeo_bp = Blueprint('regeo', __name__)


@regeo_bp.route('/api/regeo', methods=['GET', 'POST'])
def regeo_route():
    if request.method == 'GET':
        lat = request.args.get('lat')
        lng = request.args.get('lng')
        poinums = request.args.get('poinums', 3)
    else:
        data = request.get_json() or {}
        lat = data.get('lat')
        lng = data.get('lng')
        poinums = data.get('poinums', 3)

    try:
        lat = float(lat)
        lng = float(lng)
        poinums = max(1, min(int(poinums), 10))
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lng (float) required"}), 400

    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return jsonify({"error": "invalid coordinates"}), 400

    try:
        result = regeo(lng, lat, poinums)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 502

    result["coord_sys"] = "WGS84"
    result["lng"] = lng
    result["lat"] = lat
    return jsonify(result)
