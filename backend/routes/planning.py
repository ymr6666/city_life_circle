"""规划分析 API: POST /api/planning/*

选址模拟 / 关闭影响 / 搬迁影响 —— 「规划分析」Tab 后端。

端点:
  POST /api/planning/closure    关闭影响: {poi_ids, mode?, time_budget_min?,
                                fallback_time_min?, other_category?}
  POST /api/planning/relocation 搬迁影响: {old_poi_id, new_lat, new_lng,
                                mode?, time_budget_min?, snap_radius_m?}
  POST /api/planning/site-selection  选址模拟: {category, mode?, time_budget_min?,
                                bbox?, n_candidates?, extra_candidates?,
                                w_fill?, w_new?, w_overlap?}
"""
from flask import Blueprint, request, jsonify

from engine.coverage import (closure_impact, relocation_impact, site_selection)
from engine.factory import parse_mode

planning_bp = Blueprint('planning', __name__)


def _parse_mode(data):
    mode = data.get('mode', 'walk')
    try:
        parse_mode(mode)
    except ValueError as e:
        raise ValueError(str(e))
    return mode


@planning_bp.route('/api/planning/closure', methods=['POST'])
def planning_closure():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400
    poi_ids = data.get('poi_ids')
    facility_ids = data.get('facility_ids')
    if isinstance(poi_ids, (int, str)):
        poi_ids = [int(poi_ids)]
    elif isinstance(poi_ids, list):
        poi_ids = [int(x) for x in poi_ids]
    if isinstance(facility_ids, (int, str)):
        facility_ids = [int(facility_ids)]
    elif isinstance(facility_ids, list):
        facility_ids = [int(x) for x in facility_ids]
    if not poi_ids and not facility_ids:
        return jsonify({"error": "poi_ids 或 facility_ids 必填"}), 400
    try:
        mode = _parse_mode(data)
        result = closure_impact(
            poi_ids=poi_ids, facility_ids=facility_ids, mode=mode,
            time_budget_min=data.get('time_budget_min', 15),
            fallback_time_min=data.get('fallback_time_min', 30),
            other_category=data.get('other_category'),
            tier=data.get('tier'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if result is None:
        return jsonify({"error": "设施无挂接或无效"}), 404
    return jsonify(result)


@planning_bp.route('/api/planning/relocation', methods=['POST'])
def planning_relocation():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400
    old_poi_id = data.get('old_poi_id')
    old_facility_id = data.get('old_facility_id')
    new_lat = data.get('new_lat')
    new_lng = data.get('new_lng')
    if (old_poi_id is None and old_facility_id is None) or new_lat is None or new_lng is None:
        return jsonify({"error": "old_poi_id/old_facility_id 与 new_lat/new_lng 必填"}), 400
    try:
        mode = _parse_mode(data)
        result = relocation_impact(
            old_poi_id=int(old_poi_id) if old_poi_id else None,
            old_facility_id=int(old_facility_id) if old_facility_id else None,
            new_lat=float(new_lat), new_lng=float(new_lng), mode=mode,
            time_budget_min=data.get('time_budget_min', 15),
            snap_radius_m=data.get('snap_radius_m', 150),
            tier=data.get('tier'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if result is None:
        return jsonify({"error": "旧设施无挂接或新址不可吸附"}), 404
    return jsonify(result)


@planning_bp.route('/api/planning/site-selection', methods=['POST'])
def planning_site_selection():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400
    category = data.get('category')
    if not category:
        return jsonify({"error": "category 必填"}), 400
    try:
        mode = _parse_mode(data)
        result = site_selection(
            category, mode=mode,
            time_budget_min=data.get('time_budget_min', 15),
            bbox=data.get('bbox'),
            n_candidates=data.get('n_candidates', 10),
            extra_candidates=data.get('extra_candidates'),
            w_fill=data.get('w_fill', 1.0),
            w_new=data.get('w_new', 0.5),
            w_overlap=data.get('w_overlap', 0.6),
            auto=bool(data.get('auto', True)))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if result is None:
        return jsonify({"error": f"类别 {category} 无数据"}), 404
    return jsonify(result)
