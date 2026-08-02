"""
反算 (Reverse Isochrone) 引擎

语义: 给定设施坐标, 求"哪些起点能在时间预算内到达该设施"。
  单设施: 能到达该设施的所有路网起点 (覆盖范围)。
  多设施: 各设施覆盖范围的交集 = 同时能到达全部设施的区域 (最优选址)。

单向道路处理:
  数据含 29,099 条 oneway 边, 对步行类模式(无向图)正反一致, 无影响;
  对驾车/骑行(有向图), "能到达 F 的起点" ≠ "从 F 能到达的地方",
  必须**反转边方向** (交换 source/target) 再跑 Dijkstra, 否则覆盖范围错。
  实现: 对 directed 模式用 swap 边集, 对无向模式直接复用。

算法: 多源 pgr_drivingDistance (设施吸附节点为 ARRAY 起点), 逐设施一次。
"""
import json

from services.database import execute_query, execute_one
from .walk_layer import adaptive_snap


def _hull_geojson(node_ids):
    """可达节点的凸包 GeoJSON (少于 3 点返回 None)"""
    if not node_ids or len(node_ids) < 3:
        return None
    phs = ','.join(['%s'] * len(node_ids))
    row = execute_one(f"""
        SELECT ST_AsGeoJSON(ST_ConvexHull(ST_Collect(v.geometry)))
        FROM hefei_roads_vertices_pgr v WHERE v.id IN ({phs})
    """, tuple(node_ids))
    if row and row[0]:
        try:
            return json.loads(row[0])
        except ValueError:
            return None
    return None


def reverse_reachability(layer, facilities, time_budget_min, snap_radius_m=150):
    """端到端反算。

    layer:     build_layer(mode) 的产物
    facilities: [{"lat":.., "lng":..}, ...]
    返回: {"facilities":[{...}, ...], "intersection":{...}}
    """
    is_transit = hasattr(layer, "_build_combined_edge_sql")
    directed = bool(layer.directed)      # 有无向由层决定
    swap = directed                      # 有向模式需反转边, 无向模式无需

    if is_transit:
        edge_sql = layer._build_combined_edge_sql(swap=swap)
        budget = time_budget_min          # 耦合图成本为分钟
    else:
        edge_sql = layer._edge_sql(swap=swap)
        budget = layer.get_distance_budget(time_budget_min)   # 单模式成本为米

    # 1. 各设施吸附到路网节点 (自适应半径容错)
    snaps = []
    start_ids = set()
    for f in facilities:
        cands, _ = adaptive_snap(layer, f["lat"], f["lng"], snap_radius_m, 3)
        snaps.append(cands)
        for c in cands:
            start_ids.add(c["id"])
    if not start_ids:
        return None

    # 2. 逐设施多源反向 Dijkstra → "能到达它的起点" 集合
    per_facility = []
    node_sets = []
    for f, cands in zip(facilities, snaps):
        if not cands:
            per_facility.append({
                "lat": f["lat"], "lng": f["lng"],
                "snap_candidates": [], "snap_ok": False,
                "reachable_origins_count": 0, "reachable_origins": [],
                "polygon": None,
            })
            node_sets.append(set())
            continue
        fids = [c["id"] for c in cands]
        rows = execute_query("""
            SELECT dd.node, MIN(dd.agg_cost) AS agg_cost, v.y AS lng, v.x AS lat
            FROM pgr_drivingDistance(%s, %s, %s, directed := %s) dd
            JOIN hefei_roads_vertices_pgr v ON v.id = dd.node
            WHERE dd.agg_cost <= %s
            GROUP BY dd.node, v.x, v.y
            ORDER BY agg_cost
        """, (edge_sql, fids, budget, directed, budget))
        ids = [r[0] for r in rows]
        nodes = [{"node": r[0], "agg_cost": float(r[1]),
                  "lng": float(r[2]), "lat": float(r[3])} for r in rows]
        node_sets.append(set(ids))
        per_facility.append({
            "lat": f["lat"], "lng": f["lng"],
            "snap_candidates": cands, "snap_ok": True,
            "reachable_origins_count": len(nodes),
            "reachable_origins": nodes,
            "polygon": _hull_geojson(ids),
        })

    result = {
        "facilities": per_facility,
    }

    # 3. 多设施交集 = 同时能到达全部设施的起点 (最优选址)
    if len(node_sets) >= 2:
        inter = set.intersection(*node_sets)
        inter_nodes = sorted(
            (n for n in per_facility[0]["reachable_origins"] if n["node"] in inter),
            key=lambda n: n["agg_cost"])
        result["intersection"] = {
            "facilities_count": len(facilities),
            "reachable_origins_count": len(inter),
            "reachable_origins": inter_nodes,
            "polygon": _hull_geojson(list(inter)),
        }
    return result
