"""全城分析 API: POST /api/citywide/*

盲区聚类 / 错配分析 / 均衡分析 —— 「全城分析」页后端。

端点:
  POST /api/citywide/clusters  盲区聚类: {category, mode?, time_budget_min?,
                                bbox?, tier?, cluster_cell_deg?, min_points?, top_n?}
  POST /api/citywide/mismatch  错配分析: {category, tier?, bbox?, cell_size_deg?,
                                grid_type?}
  POST /api/citywide/balance   均衡指标: {category, tier?, mode?, time_budget_min?,
                                bbox?}
"""
from flask import Blueprint, request, jsonify

from engine.citywide import (blindzone_clusters, mismatch_grid, balance_metrics)
from engine.factory import parse_mode


def _parse_mode(data):
    mode = data.get('mode', 'walk')
    try:
        parse_mode(mode)
    except ValueError as e:
        raise ValueError(str(e))
    return mode


citywide_bp = Blueprint('citywide', __name__)


@citywide_bp.route('/api/citywide/clusters', methods=['POST'])
def clusters():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400
    category = data.get('category')
    if not category:
        return jsonify({"error": "category 必填"}), 400
    try:
        mode = _parse_mode(data)
        result = blindzone_clusters(
            category, mode=mode,
            time_budget_min=data.get('time_budget_min', 15),
            bbox=data.get('bbox'),
            tier=data.get('tier'),
            cluster_cell_deg=data.get('cluster_cell_deg', 0.0025),
            min_points=data.get('min_points', 5),
            top_n=data.get('top_n', 20),
            connectivity=data.get('connectivity', 4))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if result is None:
        return jsonify({"error": f"类别 {category} 无数据"}), 404
    return jsonify(result)


@citywide_bp.route('/api/citywide/mismatch', methods=['POST'])
def mismatch():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400
    category = data.get('category')
    if not category:
        return jsonify({"error": "category 必填"}), 400
    try:
        result = mismatch_grid(
            category, tier=data.get('tier'),
            bbox=data.get('bbox'),
            cell_size_deg=data.get('cell_size_deg', 0.01),
            grid_type=data.get('grid_type', 'hex'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result)


@citywide_bp.route('/api/citywide/balance', methods=['POST'])
def balance():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400
    category = data.get('category')
    if not category:
        return jsonify({"error": "category 必填"}), 400
    try:
        mode = _parse_mode(data)
        result = balance_metrics(
            category, tier=data.get('tier'), mode=mode,
            time_budget_min=data.get('time_budget_min', 15),
            bbox=data.get('bbox'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if result is None:
        return jsonify({"error": f"类别 {category} 无数据"}), 404
    return jsonify(result)
