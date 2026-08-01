from flask import Blueprint, request, jsonify
from engine.factory import build_layer
from collections import defaultdict

isochrone_bp = Blueprint('isochrone', __name__)


@isochrone_bp.route('/api/isochrone', methods=['POST'])
def isochrone():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400

    lat = data.get('lat')
    lng = data.get('lng')
    mode = data.get('mode', 'walk')
    time_budget_min = data.get('time_budget_min', 15)
    snap_radius_m = data.get('snap_radius_m', 150)

    if lat is None or lng is None:
        return jsonify({"error": "lat and lng are required"}), 400

    try:
        layer = build_layer(mode)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        result = layer.compute_reachability(lat, lng, time_budget_min, snap_radius_m)
    except ValueError as e:
        # 公交/地铁数据未就绪
        return jsonify({"error": str(e)}), 503

    if not result:
        return jsonify({"error": "no accessible road node near origin"}), 404

    pois_by_category = defaultdict(list)
    for poi in result['pois']:
        pois_by_category[poi['category']].append({
            "id": poi['id'],
            "name": poi['name'],
            "sub_category": poi['sub_category'],
            "lng": poi['lng'],
            "lat": poi['lat'],
            "distance_m": poi['distance_m'],
        })

    category_stats = {}
    for cat, items in pois_by_category.items():
        category_stats[cat] = {"count": len(items), "items": items}

    response = {
        "mode": mode,
        "time_budget_min": time_budget_min,
        "origin": {"lat": lat, "lng": lng},
        "start_node": result['snap_candidates'][0],
        "reachable_pois_count": len(result['pois']),
        "pois_by_category": category_stats,
    }

    # 单道路模式 (walk/cycle/drive)
    if result.get('distance_budget_m') is not None:
        response['distance_budget_m'] = result['distance_budget_m']
        response['reachable_nodes_count'] = result['reachable_nodes_count']
        response['reachable_nodes'] = result['reachable_nodes']
    else:
        # 耦合模式: 道路节点 + 各公交模式
        transit_modes = getattr(layer, 'transit_modes', ())
        response['reachable_road_nodes_count'] = result['reachable_road_nodes_count']
        response['reachable_road_nodes'] = result['reachable_road_nodes']
        if 'metro' in transit_modes:
            response['reachable_metro_stations_count'] = result['reachable_metro_stations_count']
            response['reachable_metro_stations'] = result['reachable_metro_stations']
        if 'bus' in transit_modes:
            response['reachable_bus_stops_count'] = result['reachable_bus_stops_count']
            response['reachable_bus_stops'] = result['reachable_bus_stops']

    return jsonify(response)
