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

from services.database import execute_query, execute_one, execute_query_fresh
from .walk_layer import (adaptive_snap, reachable_polygon_from_edges,
                         _edges_within_nodes)
from .population import population_in_geojson

# 道路边 id 上限 (transit 层地铁/公交/换乘边用 300000+ 偏移, 多边形只用道路边)
_ROAD_EDGE_LIMIT = 300000


def _hull_geojson(node_ids):
    """可达节点的凸包 GeoJSON (少于 3 点返回 None) —— 仅兜底"""
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


def _polygon_for_nodes(ok_column, node_ids, seed_lines=None, seed_points=None,
                       edge_ids=None, node_cost=None, budget=None,
                       edge_cost_sql=None):
    """边域多边形: 可达节点集内"预算内可遍历"道路边 buffer, 体现道路/走廊形状。

    反算覆盖区/交集若用凸包会把整片区域填满, 无法体现步行/驾车/地铁等
    不同交通方式造成的形状差异; 用边域重建则严格贴合道路与走廊。

    - 优先用 node_cost+budget 的"预算内可遍历边" (精确填充)
    - edge_ids (transit 树边) 兜底, 保留中心区+走廊/孤岛形状
    - seed_lines/seed_points: 把设施点位也 buffer 进多边形 (防设施圈外)。
    """
    if not node_ids:
        return None
    edges = None
    if node_cost is not None and budget is not None:
        edges = _edges_within_nodes(node_ids, ok_column, node_cost=node_cost,
                                    budget=budget, edge_cost_sql=edge_cost_sql)
    elif edge_ids:
        edges = [int(e) for e in edge_ids if e is not None and e >= 0]
    if not edges:
        edges = _edges_within_nodes(node_ids, ok_column)
    poly = None
    if edges:
        poly = reachable_polygon_from_edges(edges, seed_lines=seed_lines,
                                            seed_points=seed_points)
    if poly:
        return poly
    if seed_lines:
        poly = reachable_polygon_from_edges([], seed_lines=seed_lines,
                                            seed_points=seed_points)
        if poly:
            return poly
    return _hull_geojson(node_ids)


def _reverse_dijkstra(edge_sql, start_ids, budget, directed):
    """多源反向 Dijkstra: 返回 (node_cost, reachable_edges, nodes)
    node_cost: {node: agg_cost}; reachable_edges: 可达道路边 set; nodes: 含坐标列表
    用全新连接规避复用连接退化。"""
    rows = execute_query_fresh("""
        SELECT dd.node, dd.edge, dd.agg_cost
        FROM pgr_drivingDistance(%s, %s, %s, directed := %s) dd
        WHERE dd.agg_cost <= %s
    """, (edge_sql, start_ids, budget, directed, budget))
    node_cost = {}
    edges = set()
    for n, e, c in rows:
        if n not in node_cost or c < node_cost[n]:
            node_cost[n] = float(c)
        if e is not None and e >= 0 and e < _ROAD_EDGE_LIMIT:
            edges.add(e)
    if not node_cost:
        return {}, set(), []
    phs = ','.join(['%s'] * len(node_cost))
    crows = execute_query(
        f"SELECT id, y AS lng, x AS lat FROM hefei_roads_vertices_pgr WHERE id IN ({phs})",
        tuple(node_cost.keys()))
    coord = {r[0]: (float(r[1]), float(r[2])) for r in crows}
    nodes = [{"node": n, "agg_cost": node_cost[n],
              "lng": coord[n][0], "lat": coord[n][1]}
             for n in sorted(node_cost, key=lambda k: node_cost[k]) if n in coord]
    return node_cost, edges, nodes


def reverse_reachability(layer, facilities, time_budget_min, snap_radius_m=150,
                         snap_max_nodes=1):
    """端到端反算。

    layer:     build_layer(mode) 的产物
    facilities: [{"lat":.., "lng":..}, ...]
    返回: {"facilities":[{...}, ...], "intersection":{...}}
    """
    is_transit = hasattr(layer, "_build_combined_edge_sql")
    directed = bool(layer.directed)      # 有无向由层决定
    swap = directed                      # 有向模式需反转边, 无向模式无需
    ok_column = getattr(layer, "ok_column", None) or f"{layer.road_mode}_ok"
    if is_transit:
        speed_mh = layer.road_layer.speed_kmh * 1000.0
        edge_cost_sql = f"r.cost * 60.0 / {speed_mh}"
    else:
        edge_cost_sql = "r.cost"

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
        cands, _ = adaptive_snap(layer, f["lat"], f["lng"], snap_radius_m, snap_max_nodes)
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
        node_cost, edges, nodes = _reverse_dijkstra(edge_sql, fids, budget, directed)
        ids = [n["node"] for n in nodes]
        # 设施→吸附点连线作为多边形种子, 保证覆盖范围包住设施本身
        seed_lines = [(f["lng"], f["lat"], c["lng"], c["lat"]) for c in cands]
        polygon = _polygon_for_nodes(ok_column, ids, seed_lines=seed_lines,
                                     edge_ids=list(edges) if is_transit else None,
                                     node_cost=node_cost, budget=budget,
                                     edge_cost_sql=edge_cost_sql)
        node_sets.append(set(ids))

        per_facility.append({
            "lat": f["lat"], "lng": f["lng"],
            "snap_candidates": cands, "snap_ok": True,
            "reachable_origins_count": len(nodes),
            "reachable_origins": nodes,
            "polygon": polygon,
            "reachable_population": population_in_geojson(json.dumps(polygon)) if polygon else 0,
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
        # 交集用边域多边形: 交集节点集内道路边 buffer (两端点都在交集中),
        # 体现道路/公交走廊真实形状, 而非凸包填满整片区域
        inter_poly = _polygon_for_nodes(ok_column, list(inter))
        result["intersection"] = {
            "facilities_count": len(facilities),
            "reachable_origins_count": len(inter),
            "reachable_origins": inter_nodes,
            "polygon": inter_poly,
            "reachable_population": population_in_geojson(json.dumps(inter_poly)) if inter_poly else 0,
        }
    return result
