"""服务覆盖分析 API: POST /api/coverage + POST /api/blindzone

「全城视角」设施覆盖分析: 单/多设施、整类设施的多时间阈值覆盖人口。
复用引擎 coverage.py (一次反向 Dijkstra → 成本剖面 → 多阈值切片 → 人口聚合)。

请求 (JSON, 二选一):
  A. 类别覆盖: {category: "hospital", mode?, time_budgets?: [5,10,15],
                include_polygon?}
     → 可达"任意一个"该类设施的人口 + 覆盖率 + 盲区人口
  B. 指定设施: {poi_ids: [6622, 6623], mode?, time_budgets?, include_polygon?}
     → 各设施逐设施覆盖人口 + 合计(并集)覆盖
  C. 独占覆盖(关闭/搬迁影响): {exclusive: [poi_ids], time_budget_min?,
                                mode?, other_category?}
     → 仅这些设施能到达、其他同类到不了的人口 (受影响人口)

mode: walk/cycle/drive/metro/bus/walk+metro/bus (默认 walk)
time_budgets: 分钟列表 (默认 [5,10,15]); time_budget_min: 单个阈值 (C)
"""
from flask import Blueprint, request, jsonify

from engine.coverage import (category_coverage, facility_coverage,
                             exclusive_catchment, blindzone_grid, point_curve)
from engine.factory import parse_mode

coverage_bp = Blueprint('coverage', __name__)

DEFAULT_BUDGETS = [5, 10, 15]


def _parse_budgets(data):
    tb = data.get('time_budgets', DEFAULT_BUDGETS)
    if isinstance(tb, (int, float)):
        tb = [float(tb)]
    elif isinstance(tb, list):
        tb = [float(t) for t in tb]
    else:
        raise ValueError("time_budgets 必须是数字或数字列表")
    return sorted(t for t in tb if t > 0)


def _parse_mode(data):
    mode = data.get('mode', 'walk')
    try:
        parse_mode(mode)
    except ValueError as e:
        raise ValueError(str(e))
    return mode


@coverage_bp.route('/api/coverage', methods=['POST'])
def coverage():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400

    try:
        mode = _parse_mode(data)
        include_polygon = bool(data.get('include_polygon', False))

        # C. 独占覆盖 (关闭/搬迁影响)
        if data.get('exclusive'):
            excl = data.get('exclusive')
            if isinstance(excl, (int, str)):
                excl = [int(excl)]
            else:
                excl = [int(x) for x in excl]
            t = float(data.get('time_budget_min', 10))
            result = exclusive_catchment(excl, mode=mode, time_budget_min=t,
                                         other_category=data.get('other_category'))
            if result is None:
                return jsonify({"error": "设施无挂接或类别无效"}), 404
            return jsonify(result)

        # A. 类别覆盖
        if data.get('category'):
            tb = _parse_budgets(data)
            result = category_coverage(data['category'], mode=mode,
                                       time_budgets=tb,
                                       include_polygon=include_polygon)
            if result is None:
                return jsonify({"error": f"类别 {data['category']} 无挂接数据"}), 404
            return jsonify(result)

        # B. 指定设施覆盖
        if data.get('poi_ids'):
            pois = data['poi_ids']
            if isinstance(pois, (int, str)):
                pois = [int(pois)]
            else:
                pois = [int(x) for x in pois]
            if not pois:
                return jsonify({"error": "poi_ids 不能为空"}), 400
            tb = _parse_budgets(data)
            result = facility_coverage(pois, mode=mode, time_budgets=tb,
                                       include_polygon=include_polygon)
            return jsonify(result)

        return jsonify({"error": "需要 category / poi_ids / exclusive 之一"}), 400

    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@coverage_bp.route('/api/blindzone', methods=['POST'])
def blindzone():
    """服务盲区网格识别: POST /api/blindzone

    请求: {category, mode?, time_budget_min?, bbox?, cell_size_deg?,
           grid_type?}
      category: 设施类别 (如 hospital/supermarket/school_primary)
      mode: walk/cycle/drive 等 (默认 walk)
      time_budget_min: 阈值分钟 (默认 15)
      bbox: [minlng, minlat, maxlng, maxlat] (默认合肥全城)
      cell_size_deg: 网格尺寸 (0.005≈500m, 0.01≈1km, 默认 0.01)
      grid_type: square / hex (默认 square)
    响应: GeoJSON FeatureCollection, meta 含全城覆盖/盲区人口统计。
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400

    category = data.get('category')
    if not category:
        return jsonify({"error": "category 必填"}), 400
    try:
        mode = _parse_mode(data)
        result = blindzone_grid(
            category, mode=mode,
            time_budget_min=data.get('time_budget_min', 15),
            bbox=data.get('bbox'),
            cell_size_deg=data.get('cell_size_deg', 0.01),
            grid_type=data.get('grid_type', 'square'),
            point_mode=bool(data.get('point_mode', False)),
            max_points=int(data.get('max_points', 15000)),
            tier=data.get('tier'))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if result is None:
        return jsonify({"error": f"类别 {category} 无挂接数据"}), 404
    return jsonify(result)


@coverage_bp.route('/api/coverage-curve', methods=['POST'])
def coverage_curve():
    """起点多阈值覆盖曲线: POST /api/coverage-curve

    请求: {lat, lng, mode?, time_budgets?: [5,10,15,20,30], snap_radius_m?}
    响应: {mode, origin, time_budgets,
           points:[{time_budget_min, covered_population,
                    reachable_facilities_count}]}
    一次 Dijkstra 多阈值切片, 用于等时圈"覆盖率-时间衰减"图。
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400
    lat = data.get('lat')
    lng = data.get('lng')
    if lat is None or lng is None:
        return jsonify({"error": "lat/lng 必填"}), 400
    tb = data.get('time_budgets', [5, 10, 15, 20, 30])
    if isinstance(tb, (int, float)):
        tb = [float(tb)]
    elif isinstance(tb, list):
        tb = [float(t) for t in tb]
    else:
        return jsonify({"error": "time_budgets 非法"}), 400
    try:
        mode = _parse_mode(data)
        result = point_curve(float(lat), float(lng), mode=mode,
                             time_budgets=tb,
                             snap_radius_m=data.get('snap_radius_m', 150))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if result is None:
        return jsonify({"error": "起点不可吸附"}), 404
    return jsonify(result)
