"""六维生活圈评分 API: POST /api/score

输入坐标 + 出行方式 + 时间, 返回综合宜居分 + 六维子分 + 依据明细。

请求 (JSON):
  {lat, lng, mode?, time_budget_min?, snap_radius_m?,
   weights?: {"medical":1.4, ...}   # 可选, 用户维度权重 (默认全 1)
   family?: "none"|"elderly"|"child"|"elderly+child"}  # 可选, 家庭结构预设
"""
from flask import Blueprint, request, jsonify

from engine.scoring import compute_score, DIMENSION_LABEL

score_bp = Blueprint('score', __name__)

VALID_FAMILY = ("none", "elderly", "child", "elderly+child")


@score_bp.route('/api/score', methods=['POST'])
def score():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400

    lat = data.get('lat')
    lng = data.get('lng')
    if lat is None or lng is None:
        return jsonify({"error": "lat and lng are required"}), 400

    mode = data.get('mode', 'walk')
    time_budget_min = data.get('time_budget_min', 15)
    snap_radius_m = data.get('snap_radius_m', 150)
    snap_max_nodes = data.get('snap_max_nodes', 1)

    family = data.get('family', 'none')
    if family not in VALID_FAMILY:
        return jsonify({"error": f"family must be one of {VALID_FAMILY}"}), 400

    weights = data.get('weights')
    if weights is not None:
        if not isinstance(weights, dict):
            return jsonify({"error": "weights must be an object"}), 400
        weights = {k: float(v) for k, v in weights.items() if k in DIMENSION_LABEL}
        if not weights:
            weights = None

    try:
        result = compute_score(lat, lng, mode, time_budget_min,
                               weights=weights, family=family,
                               snap_radius_m=snap_radius_m,
                               snap_max_nodes=snap_max_nodes)
    except ValueError as e:
        return jsonify({"error": str(e)}), 503

    if not result:
        return jsonify({"error": "no accessible road node near origin"}), 404

    return jsonify(result)
