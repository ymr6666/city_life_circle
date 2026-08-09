"""服务覆盖分析引擎 (coverage) —— 「全城视角」分析核心

语义: "T 分钟内能到达该设施/该类设施的人口"。
原理:
  1. 设施(或整类)的挂接路网节点为多源起点, 跑**一次**反向 Dijkstra
     (从设施出发, 求"哪些起点能在预算内到达它"), 得到全成本剖面 {node: cost}
  2. 多时间阈值只是对成本剖面**切片**: 5/10/15min 不再重跑 Dijkstra
  3. JOIN hefei_pop_nearest (人口格点→最近 walk 顶点) 逐阈值聚合覆盖人口

三类查询:
  - category_coverage: 整类设施多源反向 (可达任意一个该类设施的人口)
       → 覆盖人口 / 覆盖率 / 盲区人口 (= 总人口 - 覆盖人口)
  - facility_coverage: 指定若干设施各自的覆盖人口 (供需/搬迁影响逐设施评估)
  - exclusive_catchment: 某设施**独占**覆盖区 (仅它能到达、其他同类到不了的
      人口) → 关闭/搬迁影响的受影响人口

人口挂接距离上限: 超过该距离的格点视为"路网外"(填充带/县域), 不计入覆盖。
"""
import json

from services.database import execute_query, execute_one, execute_query_fresh
from .walk_layer import _polygon_area_m2, adaptive_snap
from .reverse import _ROAD_EDGE_LIMIT, _polygon_for_nodes
from .factory import build_layer

# 人口格点→路网节点挂接距离上限 (米): 超过视为路网外 (1.5km≈96% 人口)
POP_SNAP_MAX_M = 1500.0

# 多源起点数量阈值: 超过用"虚拟超级节点"合并为单源 Dijkstra
# (pgr_drivingDistance 多源是逐源跑再 UNION, 源多时 O(N×可达集) 爆炸;
#  加一个 0 成本虚拟节点连到所有源, 单源 Dijkstra 一次算到最近设施成本)
MULTI_SOURCE_LIMIT = 200
# 虚拟节点 id (远离路网 1~42785 / 地铁 100000+ / 公交 200000+)
_VIRTUAL_NODE = 900000000


def total_population():
    """分析范围内总人口 (挂接距离 <= POP_SNAP_MAX_M 的格点人口)"""
    row = execute_one("""
        SELECT COALESCE(SUM(g.population), 0)
        FROM hefei_pop_nearest n
        JOIN hefei_pop_grid g ON g.id = n.pop_id
        WHERE n.distance_m <= %s
    """, (POP_SNAP_MAX_M,))
    return int(row[0]) if row else 0


def _supernode_edge_sql(edge_sql, start_ids):
    """给边集加"虚拟超级节点"边: 虚拟节点 0 成本连到所有起点。

    pgr_drivingDistance 多源内部逐源跑再 UNION (源多时 O(N×可达集) 爆炸),
    加一个虚拟节点连到所有源, 单源 Dijkstra 一次即可得到"到最近源"的成本,
    复杂度与源数无关。虚拟节点 id 远离路网/地铁/公交节点偏移。
    """
    vals = ','.join(f'({_VIRTUAL_NODE + i}, {nid})' for i, nid in enumerate(start_ids))
    return f"""
        SELECT id, source, target, cost, reverse_cost FROM (
            {edge_sql}
        ) e
        UNION ALL
        SELECT {_VIRTUAL_NODE} + s, {_VIRTUAL_NODE}, node, 0, 0
        FROM (VALUES {vals}) AS t(s, node)
    """


def _reverse_profile(edge_sql, start_ids, budget, directed):
    """多源反向 Dijkstra 全成本剖面: {node: agg_cost} (到最近源的 cost)

    budget 传最大阈值; 返回所有 agg_cost <= budget 的节点 (供多阈值切片)。
    源数 > MULTI_SOURCE_LIMIT 时自动用虚拟超级节点 (单源, 不爆炸)。
    """
    if len(start_ids) > MULTI_SOURCE_LIMIT:
        edge_sql = _supernode_edge_sql(edge_sql, start_ids)
        start_ids = [_VIRTUAL_NODE]
    rows = execute_query_fresh("""
        SELECT dd.node, dd.agg_cost
        FROM pgr_drivingDistance(%s, %s, %s, directed := %s) dd
        WHERE dd.agg_cost <= %s
    """, (edge_sql, start_ids, budget, directed, budget))
    node_cost = {}
    for n, c in rows:
        if n == _VIRTUAL_NODE:
            continue
        if n not in node_cost or c < node_cost[n]:
            node_cost[n] = float(c)
    return node_cost


def _population_by_node(node_ids):
    """人口格点按挂接节点聚合人口: {node: population} (仅距离<=上限的格点)"""
    if not node_ids:
        return {}
    phs = ','.join(['%s'] * len(node_ids))
    rows = execute_query(f"""
        SELECT n.node_id, COALESCE(SUM(g.population), 0)
        FROM hefei_pop_nearest n
        JOIN hefei_pop_grid g ON g.id = n.pop_id
        WHERE n.node_id IN ({phs}) AND n.distance_m <= %s
        GROUP BY n.node_id
    """, (*node_ids, POP_SNAP_MAX_M))
    return {r[0]: int(r[1]) for r in rows}


def _slice_thresholds(node_cost, thresholds, pop_by_node, cost_per_min=None):
    """成本剖面按多阈值切片 → [{threshold, covered_population, node_count}]

    cost_per_min: 每分钟对应的成本 (单模式=米/分钟, 耦合模式=1.0 即成本即分钟)。
    切片时把"分钟"阈值换算到成本单位再过滤, 否则步行(米)与分钟混比会漏判。
    """
    cpm = cost_per_min or 1.0
    out = []
    for t in sorted(set(thresholds)):
        cost = t * cpm
        nodes = [n for n, c in node_cost.items() if c <= cost]
        pop = sum(pop_by_node.get(n, 0) for n in nodes)
        out.append({
            "time_budget_min": t,
            "covered_population": pop,
            "reachable_origins_count": len(nodes),
        })
    return out


def _edge_setup(layer, max_time_min):
    """复用 reverse.py 的边集/预算换算: 单模式成本=米, 耦合模式成本=分钟

    返回 (edge_sql, directed, ok_column, edge_cost_sql, budget, cost_per_min)
    cost_per_min: 每分钟的成本 (单模式=米/分钟, 耦合模式=1.0 成本即分钟)。
    """
    is_transit = hasattr(layer, "_build_combined_edge_sql")
    directed = bool(layer.directed)
    swap = directed                      # 有向模式需反转边 (能到达 F 的起点)
    ok_column = getattr(layer, "ok_column", None) or f"{layer.road_mode}_ok"
    if is_transit:
        speed_mh = layer.road_layer.speed_kmh * 1000.0
        edge_cost_sql = f"r.cost * 60.0 / {speed_mh}"
        edge_sql = layer._build_combined_edge_sql(swap=swap)
        budget = max_time_min
        cost_per_min = 1.0
    else:
        speed_mh = layer.speed_kmh * 1000.0
        edge_cost_sql = "r.cost"
        edge_sql = layer._edge_sql(swap=swap)
        budget = layer.get_distance_budget(max_time_min)
        cost_per_min = speed_mh / 60.0
    return edge_sql, directed, ok_column, edge_cost_sql, budget, cost_per_min


def _start_ids_from_nodes(node_ids):
    """挂接表 node 集合 → 去重起始节点列表 (含路网范围内校验)"""
    ids = [int(n) for n in node_ids if n is not None and n >= 0]
    return sorted(set(ids))


def _category_facility_filter(category, tier):
    """按等级生成类别设施过滤 SQL 片段 + 参数。

    返回 (where_sql, params): 限定 category 且等级>=tier (若该类别有等级映射)。
    等级依据 hefei_poi.sub_category (typecode) 判定; 无映射类别不过滤。
    """
    from .standards import CATEGORY_TIERS, typecode_tier, category_default_tier
    tier_map, _ = CATEGORY_TIERS.get(category, ({}, 1))
    if not tier_map:
        return "p.category = %s", [category]
    t = int(tier) if tier is not None else category_default_tier(category)
    # 收集等级>=t 的 typecode (精确 + 组合含该 code 的)
    codes = [c for c, lv in tier_map.items() if lv >= t]
    if not codes:
        return "p.category = %s", [category]
    # 用 EXISTS 匹配组合 typecode (sub_category 可能含 '|')
    ph = ','.join(['%s'] * len(codes))
    return (f"p.category = %s AND ("
            f"p.sub_category IS NULL OR p.sub_category = '' "
            f"OR EXISTS (SELECT 1 FROM unnest(string_to_array(p.sub_category,'|')) AS tc(code) "
            f"WHERE tc.code IN ({ph})))",
            [category, *codes])


def _category_start_ids(category, tier=None, mode='walk'):
    """按等级过滤的类别挂接节点集 (等级>=tier 的设施)。"""
    where, params = _category_facility_filter(category, tier)
    rows = execute_query(f"""
        SELECT DISTINCT pn.node_id
        FROM poi_road_nodes pn
        JOIN hefei_poi p ON p.id = pn.poi_id
        WHERE {where} AND pn.mode = %s
    """, (*params, mode))
    return _start_ids_from_nodes([r[0] for r in rows])


def _facility_list(category, bbox, tier=None):
    """bbox 内类别设施列表, 支持等级过滤 + facility 分组。

    facility 分组: 同一 facility_id 的多部门 POI 合并为一条 (取组内最高等级),
    解决"三甲医院各部门独立 POI"导致列表冗余/点选繁琐的问题。
    """
    bounds = (bbox[0], bbox[1], bbox[2], bbox[3])
    where, params = _category_facility_filter(category, tier)
    rows = execute_query(f"""
        SELECT COALESCE(p.facility_id, p.id) AS fid,
               COALESCE(p.facility_name, p.name) AS fname,
               max(p.sub_category) AS sub,
               ST_X(ST_Centroid(ST_Collect(p.geometry))) AS lng,
               ST_Y(ST_Centroid(ST_Collect(p.geometry))) AS lat,
               count(*) AS n_poi,
               string_agg(DISTINCT p.address, ' / ') AS address
        FROM hefei_poi p
        WHERE {where}
          AND p.geometry && ST_MakeEnvelope(%s,%s,%s,%s,4326)
        GROUP BY COALESCE(p.facility_id, p.id), COALESCE(p.facility_name, p.name)
    """, (*params, *bounds))
    out = []
    for fid, fname, sub, lng, lat, n_poi, address in rows:
        out.append({
            "id": int(fid), "name": fname, "sub_category": sub,
            "lng": float(lng or 0), "lat": float(lat or 0),
            "n_poi": int(n_poi or 1), "address": address or '',
        })
    return out


def category_coverage(category, mode="walk", time_budgets=(5, 10, 15),
                      include_polygon=False):
    """整类设施覆盖: 可达"任意一个"该类设施的人口 (盲区分析基础)

    多源 = 该类全部设施挂接节点; 反向 Dijkstra 一次得到每节点到最近设施的
    最短成本, 阈值切片得覆盖人口。
    """
    time_budgets = sorted(float(t) for t in time_budgets if t > 0)
    if not time_budgets:
        raise ValueError("time_budgets 必须为正数")
    max_t = max(time_budgets)

    rows = execute_query("""
        SELECT DISTINCT pn.node_id
        FROM poi_road_nodes pn
        JOIN hefei_poi p ON p.id = pn.poi_id
        WHERE p.category = %s AND pn.mode = 'walk'
    """, (category,))
    start_ids = _start_ids_from_nodes([r[0] for r in rows])
    if not start_ids:
        return None

    layer = build_layer(mode)
    edge_sql, directed, ok_column, edge_cost_sql, budget, cpm = _edge_setup(layer, max_t)
    node_cost = _reverse_profile(edge_sql, start_ids, budget, directed)
    if not node_cost:
        return None

    pop_by_node = _population_by_node(list(node_cost))
    thresholds = _slice_thresholds(node_cost, time_budgets, pop_by_node, cpm)

    total = total_population()
    for t in thresholds:
        t["coverage_rate"] = round(t["covered_population"] / total, 4) if total else 0.0
        t["blind_population"] = total - t["covered_population"]

    result = {
        "category": category,
        "mode": mode,
        "time_budgets": time_budgets,
        "facility_count": len(set(r[0] for r in execute_query(
            "SELECT pn.poi_id FROM poi_road_nodes pn "
            "JOIN hefei_poi p ON p.id = pn.poi_id WHERE p.category = %s AND pn.mode='walk'",
            (category,)))),
        "total_population": total,
        "thresholds": thresholds,
    }

    if include_polygon:
        max_threshold = thresholds[-1]
        max_cost = max_threshold["time_budget_min"] * cpm
        nodes = [n for n, c in node_cost.items() if c <= max_cost]
        polygon = _polygon_for_nodes(
            ok_column, nodes, node_cost=node_cost,
            budget=max_cost, edge_cost_sql=edge_cost_sql)
        result["polygon"] = polygon
    return result


def facility_coverage(poi_ids, mode="walk", time_budgets=(5, 10, 15),
                      include_polygon=False):
    """指定设施逐设施覆盖人口 (多阈值) + 合计覆盖

    poi_ids: hefei_poi.id 列表 (各设施独立反向, 输出各自覆盖人口,
    用于关闭/搬迁影响、供需比、选址的设施级评估)。
    """
    poi_ids = [int(p) for p in poi_ids if p]
    if not poi_ids:
        raise ValueError("poi_ids 不能为空")
    time_budgets = sorted(float(t) for t in time_budgets if t > 0)
    if not time_budgets:
        raise ValueError("time_budgets 必须为正数")
    max_t = max(time_budgets)

    layer = build_layer(mode)
    edge_sql, directed, ok_column, edge_cost_sql, budget, cpm = _edge_setup(layer, max_t)

    # 设施基本信息 + 挂接节点
    phs = ','.join(['%s'] * len(poi_ids))
    fac_rows = execute_query(f"""
        SELECT p.id, p.name, p.category, ST_X(p.geometry), ST_Y(p.geometry),
               COALESCE(p.facility_name, p.name)
        FROM hefei_poi p WHERE p.id IN ({phs})
    """, tuple(poi_ids))
    fac_info = {r[0]: {"id": r[0], "name": r[1], "category": r[2],
                       "lng": float(r[3]), "lat": float(r[4]),
                       "facility_name": r[5]} for r in fac_rows}

    snap_rows = execute_query(f"""
        SELECT pn.poi_id, pn.node_id FROM poi_road_nodes pn
        WHERE pn.mode = 'walk' AND pn.poi_id IN ({phs})
    """, tuple(poi_ids))
    nodes_by_poi = {}
    for pid, nid in snap_rows:
        nodes_by_poi.setdefault(pid, []).append(nid)

    total = total_population()
    facilities = []
    union_nodes = set()
    for pid in poi_ids:
        info = fac_info.get(pid)
        if info is None:
            continue
        start_ids = _start_ids_from_nodes(nodes_by_poi.get(pid, []))
        if not start_ids:
            facilities.append({**info, "snap_ok": False, "thresholds": []})
            continue
        node_cost = _reverse_profile(edge_sql, start_ids, budget, directed)
        if not node_cost:
            facilities.append({**info, "snap_ok": False, "thresholds": []})
            continue
        union_nodes |= set(node_cost)
        pop_by_node = _population_by_node(list(node_cost))
        thresholds = _slice_thresholds(node_cost, time_budgets, pop_by_node, cpm)
        for t in thresholds:
            t["coverage_rate"] = round(t["covered_population"] / total, 4) if total else 0.0
        fac = {**info, "snap_ok": True, "thresholds": thresholds}
        if include_polygon:
            max_t_used = thresholds[-1]["time_budget_min"]
            max_cost = max_t_used * cpm
            nodes = [n for n, c in node_cost.items() if c <= max_cost]
            fac["polygon"] = _polygon_for_nodes(
                ok_column, nodes, node_cost=node_cost,
                budget=max_cost, edge_cost_sql=edge_cost_sql)
        facilities.append(fac)

    # 合计: 所有指定设施并集覆盖 (多源一次)
    combined = None
    if union_nodes:
        cnode_cost = {n: c for n, c in node_cost.items()}  # 兜底
        # 重新多源 (精确): 全部设施节点合并一次反向
        all_start = _start_ids_from_nodes([n for ns in nodes_by_poi.values() for n in ns])
        cnode_cost = _reverse_profile(edge_sql, all_start, budget, directed)
        cpop = _population_by_node(list(cnode_cost))
        combined = {
            "covered": _slice_thresholds(cnode_cost, time_budgets, cpop, cpm),
            "polygon": None,
        }
        for t in combined["covered"]:
            t["coverage_rate"] = round(t["covered_population"] / total, 4) if total else 0.0
        if include_polygon:
            max_t_used = combined["covered"][-1]["time_budget_min"]
            max_cost = max_t_used * cpm
            nodes = [n for n, c in cnode_cost.items() if c <= max_cost]
            combined["polygon"] = _polygon_for_nodes(
                ok_column, nodes, node_cost=cnode_cost,
                budget=max_cost, edge_cost_sql=edge_cost_sql)

    return {
        "mode": mode,
        "time_budgets": time_budgets,
        "total_population": total,
        "facilities": facilities,
        "combined": combined,
    }


def blindzone_grid(category, mode="walk", time_budget_min=15,
                   bbox=None, cell_size_deg=0.005, grid_type="square",
                   max_snap_m=POP_SNAP_MAX_M, pop_snap_m=POP_SNAP_MAX_M,
                   point_mode=False, max_points=15000, tier=None):
    """服务盲区网格识别: 每个网格的覆盖/盲区人口与覆盖率。

    语义: 网格内"阈值时间内到不了任何该类设施"的人口 = 盲区人口。
    一次多源反向 Dijkstra 得每节点到最近设施成本 → 网格内人口按挂接节点
    是否可达聚合: 盲区率 = 1 - 覆盖人口/总人口。

    关键: 人口按**人口点自身位置**聚合到网格 (ST_SquareGrid 原点在 0,0,
    用解析法 floor(lng/cell), floor(lat/cell)), 而非按挂接顶点——
    顶点可能落在相邻格导致"有人口的格显示 0 人口"的白区 bug。

    point_mode=True 时返回原始 100m 人口格点 (带 covered/tier),
    前端直接渲染为 100m 分辨率点 (max_points 抽样防卡顿)。
    tier: '充裕' 成本≤70%阈值 / '紧张' 70%~100% / '盲区' 超阈值。

    响应附带 facilities (该类别 bbox 内 POI 点, 供前端展示/点击) 与
    origin (中心点回显)。

    参数:
      bbox: [minlng, minlat, maxlng, maxlat] (默认合肥全城)
      cell_size_deg: 网格尺寸 (度; 0.005≈500m, 0.01≈1km)
      grid_type: 仅支持 'square' (六边形已废弃)
      point_mode: True=返回 100m 原始人口点, False=网格聚合
      max_snap_m: 人口格点挂接距离上限 (超过视为路网外, 不计覆盖)
    返回 GeoJSON FeatureCollection, 每 feature properties:
      {population, covered_population, blind_population, coverage_rate,
       blind_rate, time_budget_min}
    """
    bbox = bbox or [117.07, 31.68, 117.50, 32.07]
    if (len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
        raise ValueError("bbox 必须为 [minlng, minlat, maxlng, maxlat]")
    t = float(time_budget_min)
    if t <= 0:
        raise ValueError("time_budget_min 必须为正数")
    if grid_type != 'square':
        raise ValueError("grid_type 仅支持 square (六边形已废弃)")
    cell = float(cell_size_deg)
    if cell <= 0:
        raise ValueError("cell_size_deg 必须为正数")
    bounds = (bbox[0], bbox[1], bbox[2], bbox[3])

    # 1. 整类设施多源反向 (按等级过滤: 只算 tier>=tier 的设施)
    start_ids = _category_start_ids(category, tier, mode='walk')
    if not start_ids:
        return None

    layer = build_layer(mode)
    edge_sql, directed, ok_column, edge_cost_sql, budget, cpm = _edge_setup(layer, t)
    node_cost = _reverse_profile(edge_sql, start_ids, budget, directed)
    if not node_cost:
        return None
    # 覆盖: 成本 <= 阈值 (单模式换算: 阈值分钟 × 每分钟米数; 耦合模式成本即分钟)
    threshold_cost = t * cpm
    covered = {n for n, c in node_cost.items() if c <= threshold_cost}
    # 紧张带: 成本在 70%~100% 阈值之间 (可达但时间紧张)
    tight_cost = 0.7 * threshold_cost

    # 2. bbox 内该类别设施 (按等级过滤 + facility 分组)
    facilities = _facility_list(category, bbox, tier)
    facility_pts = facilities

    # 3. 拉取 bbox 内人口点 (带挂接节点), 单次查询
    import json as _json
    pop_rows = execute_query("""
        SELECT ST_X(g.geometry) AS lng, ST_Y(g.geometry) AS lat,
               g.population AS population, n.node_id AS node_id
        FROM hefei_pop_grid g
        JOIN hefei_pop_nearest n ON n.pop_id = g.id
        WHERE g.geometry && ST_MakeEnvelope(%s,%s,%s,%s,4326)
          AND n.distance_m <= %s
    """, (*bounds, pop_snap_m))

    def tier_of(node_id):
        """人口点服务等级: 盲区 / 紧张 / 充裕"""
        c = node_cost.get(node_id)
        if c is None or c > threshold_cost:
            return "盲区"
        if c > tight_cost:
            return "紧张"
        return "充裕"

    # point_mode: 返回 100m 原始人口点 (抽样)
    if point_mode:
        pts = []
        total_all = 0
        covered_all = 0
        n_pts = len(pop_rows)
        step = max(1, n_pts // max_points) if n_pts > max_points else 1
        for k, (lng, lat, population, node_id) in enumerate(pop_rows):
            if k % step != 0:
                continue
            population = int(population)
            tier = tier_of(node_id)
            is_covered = tier != "盲区"
            total_all += population
            if is_covered:
                covered_all += population
            pts.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(lng), float(lat)]},
                "properties": {
                    "population": population,
                    "covered": is_covered,
                    "blind": not is_covered,
                    "tier": tier,
                    "time_budget_min": t,
                },
            })
        return {
            "type": "FeatureCollection",
            "features": pts,
            "facilities": facility_pts,
            "meta": {
                "category": category,
                "mode": mode,
                "time_budget_min": t,
                "point_mode": True,
                "bbox": bbox,
                "n_cells": len(pts),
                "sampled": n_pts,
                "tier": tier,
                "cells_population": total_all,
                "covered_population": covered_all,
                "blind_population": total_all - covered_all,
                "coverage_rate": round(covered_all / total_all, 4) if total_all else 0.0,
            },
        }

    # 网格聚合 (仅 square): 解析法 i = floor(lng/cell), j = floor(lat/cell)
    cells_map = {}
    for lng, lat, population, node_id in pop_rows:
        i = int(lng / cell)
        j = int(lat / cell)
        key = (i, j)
        d = cells_map.setdefault(key, [0, 0, 0])   # [总人口, 覆盖人口, 紧张人口]
        d[0] += int(population)
        tier = tier_of(node_id)
        if tier != "盲区":
            d[1] += int(population)
            if tier == "紧张":
                d[2] += int(population)
    total_all = 0
    covered_all = 0
    features = []
    for (i, j), (total, covered_pop, tight_pop) in cells_map.items():
        blind = total - covered_pop
        total_all += total
        covered_all += covered_pop
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [i * cell, j * cell],
                    [(i + 1) * cell, j * cell],
                    [(i + 1) * cell, (j + 1) * cell],
                    [i * cell, (j + 1) * cell],
                    [i * cell, j * cell],
                ]],
            },
            "properties": {
                "population": total,
                "covered_population": covered_pop,
                "blind_population": blind,
                "tight_population": tight_pop,
                "coverage_rate": round(covered_pop / total, 4) if total else 0.0,
                "blind_rate": round(blind / total, 4) if total else 0.0,
                "time_budget_min": t,
            },
        })

    # 4. meta: 基于当前 bbox 范围统计 (而非全城)
    return {
        "type": "FeatureCollection",
        "features": features,
        "facilities": facility_pts,
        "meta": {
            "category": category,
            "mode": mode,
            "time_budget_min": t,
            "grid_type": grid_type,
            "cell_size_deg": cell,
            "bbox": bbox,
            "n_cells": len(features),
            "tier": tier,
            "cells_population": total_all,
            "covered_population": covered_all,
            "blind_population": total_all - covered_all,
            "coverage_rate": round(covered_all / total_all, 4) if total_all else 0.0,
        },
    }


def exclusive_catchment(poi_ids, mode="walk", time_budget_min=10,
                        other_category=None):
    """独占覆盖: 指定设施(们)能到达、但同类别其他设施到不了的人口。

    poi_ids: 要评估的设施 (关闭/搬迁的目标); other_category: 其余设施类别
    (默认取与目标相同的 category)。受影响人口 = 独占区人口。
    实现: 目标设施多源反向 ∪ 与"其余同类"多源反向做节点差集。
    """
    poi_ids = [int(p) for p in poi_ids if p]
    if not poi_ids:
        raise ValueError("poi_ids 不能为空")
    time_budget_min = float(time_budget_min)

    layer = build_layer(mode)
    edge_sql, directed, ok_column, edge_cost_sql, budget, cpm = _edge_setup(layer, time_budget_min)

    phs = ','.join(['%s'] * len(poi_ids))
    if other_category is None:
        row = execute_one(f"SELECT category FROM hefei_poi WHERE id IN ({phs}) LIMIT 1",
                          tuple(poi_ids))
        other_category = row[0] if row else None

    target_rows = execute_query(f"""
        SELECT pn.node_id FROM poi_road_nodes pn
        WHERE pn.mode='walk' AND pn.poi_id IN ({phs})
    """, tuple(poi_ids))
    target_ids = _start_ids_from_nodes([r[0] for r in target_rows])

    # 其余同类设施节点 (排除目标)
    other_rows = execute_query("""
        SELECT DISTINCT pn.node_id
        FROM poi_road_nodes pn JOIN hefei_poi p ON p.id = pn.poi_id
        WHERE p.category = %s AND pn.mode='walk'
          AND pn.poi_id != ALL(%s::int[])
    """, (other_category, poi_ids))
    other_ids = _start_ids_from_nodes([r[0] for r in other_rows])

    if not target_ids:
        return None

    t_cost = _reverse_profile(edge_sql, target_ids, budget, directed)
    t_nodes = set(t_cost)
    exclusive_nodes = set(t_nodes)
    if other_ids:
        o_cost = _reverse_profile(edge_sql, other_ids, budget, directed)
        exclusive_nodes -= set(o_cost)

    pop_by_node = _population_by_node(list(exclusive_nodes))
    exclusive_pop = sum(pop_by_node.values())
    total = total_population()

    result = {
        "poi_ids": poi_ids,
        "other_category": other_category,
        "mode": mode,
        "time_budget_min": time_budget_min,
        "exclusive_node_count": len(exclusive_nodes),
        "affected_population": exclusive_pop,
        "total_population": total,
        "polygon": None,
    }
    if exclusive_nodes:
        result["polygon"] = _polygon_for_nodes(
            ok_column, list(exclusive_nodes), node_cost=t_cost,
            budget=budget, edge_cost_sql=edge_cost_sql)
    return result


def _exclusive_nodes(layer, target_ids, other_ids, edge_sql, budget, directed):
    """独占节点集: 目标设施能到达、但其他同类在预算内到不了的节点。"""
    t_cost = _reverse_profile(edge_sql, target_ids, budget, directed)
    exclusive = set(t_cost)
    if other_ids:
        o_cost = _reverse_profile(edge_sql, other_ids, budget, directed)
        exclusive -= set(o_cost)
    return exclusive, t_cost


def closure_impact(poi_ids=None, facility_ids=None, mode="walk", time_budget_min=15,
                   fallback_time_min=30, other_category=None, tier=None):
    """关闭影响评估: 设施关闭后受影响的区域/人口 + 可替代设施明细。

    受影响人口 = 独占覆盖人口 (目标设施能到达、但其他同类在 time_budget_min
    内到不了的人口 —— 这些人口关闭后立即失去该服务)。

    目标设施: poi_ids (部门 POI) 或 facility_ids (facility 分组, 展开为组内
    全部部门 POI, 解决三甲医院多部门需逐一点选的问题)。

    可替代设施 (受 tier 过滤): 受影响区域内"更长时间阈值(fallback_time_min)内
    能到达的同类设施"列表 (退级方案); 区域内每节点取最近其他同类设施距离分级:
      lost   = 完全失去 (目标被关后无任何同类可达)
      downgraded = 退级 (fallback 内可到其他同类, 但比原目标远/慢)

    tier: 评估等级 (仅该等级>=tier 的"其他同类"算替代/退级, 防止诊所抵消三甲)。
    例如关闭三甲医院 tier=3 → 只有其他三甲/综合算替代, 诊所不抵消。

    返回:
      affected_population  受影响人口 (独占区)
      downgraded_population 退级人口 (受影响区中 fallback 内可达其他同类)
      lost_population      完全失去人口
      replacement_facilities 受影响区最近的替代设施列表 [{id,name,distance_m}]
      polygon              受影响区域
      time_budget_min / fallback_time_min
    """
    poi_ids = [int(p) for p in (poi_ids or []) if p]
    facility_ids = [int(f) for f in (facility_ids or []) if f]
    if not poi_ids and not facility_ids:
        raise ValueError("poi_ids 或 facility_ids 至少一项")
    time_budget_min = float(time_budget_min)
    fallback_time_min = float(fallback_time_min)
    if fallback_time_min < time_budget_min:
        raise ValueError("fallback_time_min 应 >= time_budget_min")

    # facility_ids → 展开为该 facility 分组内的全部部门 POI
    if facility_ids:
        rows_f = execute_query("""
            SELECT id FROM hefei_poi
            WHERE facility_id = ANY(%s::int[])
               OR facility_name IN (
                   SELECT facility_name FROM hefei_poi WHERE id = ANY(%s::int[]))
        """, (facility_ids, facility_ids))
        poi_ids = sorted(set(poi_ids) | {r[0] for r in rows_f})
    if not poi_ids:
        return None

    layer = build_layer(mode)
    edge_sql, directed, ok_column, edge_cost_sql, budget, cpm = _edge_setup(layer, time_budget_min)
    # 退级阈值成本 (单模式=米, 耦合=分钟)
    fallback_budget = layer.get_distance_budget(fallback_time_min) \
        if not hasattr(layer, "_build_combined_edge_sql") else fallback_time_min

    phs = ','.join(['%s'] * len(poi_ids))
    if other_category is None:
        row = execute_one(f"SELECT category FROM hefei_poi WHERE id IN ({phs}) LIMIT 1",
                          tuple(poi_ids))
        other_category = row[0] if row else None

    target_rows = execute_query(f"""
        SELECT pn.node_id FROM poi_road_nodes pn
        WHERE pn.mode='walk' AND pn.poi_id IN ({phs})
    """, tuple(poi_ids))
    target_ids = _start_ids_from_nodes([r[0] for r in target_rows])
    if not target_ids:
        return None

    # 其余同类设施节点 (排除目标; 按 tier 过滤, 仅同档及以上算替代)
    where_other, other_params = _category_facility_filter(other_category, tier)
    other_rows = execute_query(f"""
        SELECT DISTINCT pn.node_id
        FROM poi_road_nodes pn JOIN hefei_poi p ON p.id = pn.poi_id
        WHERE {where_other} AND pn.mode='walk'
          AND pn.poi_id != ALL(%s::int[])
    """, (*other_params, poi_ids))
    other_ids = _start_ids_from_nodes([r[0] for r in other_rows])

    exclusive_nodes, t_cost = _exclusive_nodes(layer, target_ids, other_ids,
                                               edge_sql, budget, directed)

    pop_by_node = _population_by_node(list(exclusive_nodes))
    affected_pop = sum(pop_by_node.values())

    # 受影响节点上, 每节点的"最近其他同类"成本 (退级判定)
    downgraded_nodes = set()
    lost_nodes = set(exclusive_nodes)
    if other_ids:
        o_cost_long = _reverse_profile(edge_sql, other_ids, fallback_budget, directed)
        for n in exclusive_nodes:
            if n in o_cost_long:
                downgraded_nodes.add(n)
                lost_nodes.discard(n)

    downgraded_pop = sum(pop_by_node.get(n, 0) for n in downgraded_nodes)
    lost_pop = sum(pop_by_node.get(n, 0) for n in lost_nodes)

    # 受影响区最近替代设施 (取若干) — 以受影响区质心为锚, 查最近的同类设施
    replacement = []
    if other_ids and exclusive_nodes:
        # 受影响节点质心 (代表区)
        rows_c = execute_query("""
            SELECT ST_X(ST_Centroid(ST_Collect(v.geometry))), ST_Y(ST_Centroid(ST_Collect(v.geometry)))
            FROM hefei_roads_vertices_pgr v WHERE v.id = ANY(%s::int[])
        """, (list(exclusive_nodes),))
        if rows_c and rows_c[0][0] is not None:
            cx, cy = float(rows_c[0][0]), float(rows_c[0][1])
            where_rep, rep_params = _category_facility_filter(other_category, tier)
            rep_rows = execute_query(f"""
                SELECT COALESCE(p.facility_id, p.id),
                       COALESCE(p.facility_name, p.name),
                       min(ST_Distance(ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,
                                       p.geometry::geography)) AS d,
                       ST_X(ST_Centroid(ST_Collect(p.geometry))),
                       ST_Y(ST_Centroid(ST_Collect(p.geometry))),
                       count(*)
                FROM hefei_poi p
                WHERE {where_rep} AND p.id != ALL(%s::int[])
                  AND p.geometry && ST_MakeEnvelope(%s,%s,%s,%s,4326)
                GROUP BY COALESCE(p.facility_id, p.id), COALESCE(p.facility_name, p.name)
                ORDER BY min(ST_Distance(ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,
                                         p.geometry::geography))
                LIMIT 10
            """, (cx, cy, *rep_params, poi_ids, cx - 0.05, cy - 0.05, cx + 0.05, cy + 0.05, cx, cy))
            replacement = [{
                "id": r[0], "name": r[1], "distance_m": round(float(r[2])),
                "lng": float(r[3]), "lat": float(r[4]), "n_poi": int(r[5]),
            } for r in rep_rows]

    result = {
        "poi_ids": poi_ids,
        "facility_ids": facility_ids,
        "other_category": other_category,
        "mode": mode,
        "time_budget_min": time_budget_min,
        "fallback_time_min": fallback_time_min,
        "tier": tier,
        "affected_population": affected_pop,
        "downgraded_population": downgraded_pop,
        "lost_population": lost_pop,
        "total_population": total_population(),
        "replacement_facilities": replacement,
        "exclusive_node_count": len(exclusive_nodes),
        "polygon": None,
    }
    if exclusive_nodes:
        result["polygon"] = _polygon_for_nodes(
            ok_column, list(exclusive_nodes), node_cost=t_cost,
            budget=budget, edge_cost_sql=edge_cost_sql)
    return result


def relocation_impact(old_poi_id=None, old_facility_id=None, new_lat=None,
                      new_lng=None, mode="walk", time_budget_min=15,
                      snap_radius_m=150, tier=None):
    """搬迁影响: 关闭旧设施 + 在新址新建同类设施 的净影响。

    受影响人口 = 旧设施独占区 (关闭后立即失去服务)
    恢复人口   = 旧设施独占区 ∩ 新址覆盖 (搬到新址后能重新覆盖到的人口)
    未恢复人口 = 受影响人口 − 恢复人口 (净损失)
    新增覆盖人口 = 新址覆盖 − 旧设施覆盖 (搬到更优位置带来的额外覆盖)

    旧设施: old_poi_id (部门 POI) 或 old_facility_id (facility 分组,
    展开为组内全部部门 POI)。tier 过滤"其他同类"替代判定。

    返回: 净影响摘要 + 受影响/恢复/新增区域 polygon。
    """
    if new_lat is None or new_lng is None:
        raise ValueError("new_lat / new_lng 必填")
    new_lat, new_lng = float(new_lat), float(new_lng)
    old_poi_id = int(old_poi_id) if old_poi_id else None
    old_facility_id = int(old_facility_id) if old_facility_id else None
    if not old_poi_id and not old_facility_id:
        raise ValueError("old_poi_id 或 old_facility_id 必填")
    time_budget_min = float(time_budget_min)

    layer = build_layer(mode)
    edge_sql, directed, ok_column, edge_cost_sql, budget, cpm = _edge_setup(layer, time_budget_min)

    # 旧设施信息 + 展开 facility 分组
    if old_facility_id:
        rows_f = execute_query("""
            SELECT id FROM hefei_poi
            WHERE facility_id = %s OR facility_name = (
                SELECT facility_name FROM hefei_poi WHERE id = %s)
        """, (old_facility_id, old_facility_id))
        old_pois = [r[0] for r in rows_f]
        row = execute_one("SELECT category FROM hefei_poi WHERE id = %s",
                          (old_facility_id,))
    else:
        old_pois = [old_poi_id]
        row = execute_one("SELECT category FROM hefei_poi WHERE id = %s", (old_poi_id,))
    if not row:
        raise ValueError("旧设施不存在")
    category = row[0]
    if not old_pois:
        return None
    old_poi_id = old_pois[0]

    phs_o = ','.join(['%s'] * len(old_pois))
    old_target = execute_query(f"""
        SELECT pn.node_id FROM poi_road_nodes pn
        WHERE pn.mode='walk' AND pn.poi_id IN ({phs_o})
    """, tuple(old_pois))
    old_ids = _start_ids_from_nodes([r[0] for r in old_target])
    if not old_ids:
        return None

    # 其他同类节点 (排除旧设施组; 按 tier 过滤)
    where_other, other_params = _category_facility_filter(category, tier)
    other_rows = execute_query(f"""
        SELECT DISTINCT pn.node_id
        FROM poi_road_nodes pn JOIN hefei_poi p ON p.id = pn.poi_id
        WHERE {where_other} AND pn.mode='walk' AND pn.poi_id != ALL(%s::int[])
    """, (*other_params, old_pois))
    other_ids = _start_ids_from_nodes([r[0] for r in other_rows])

    exclusive_nodes, old_cost = _exclusive_nodes(layer, old_ids, other_ids,
                                                 edge_sql, budget, directed)
    old_nodes = set(old_cost)

    # 新址作为"虚拟设施"挂接, 评估覆盖
    cands, _ = adaptive_snap(layer, new_lat, new_lng, snap_radius_m, 1)
    if not cands:
        return None
    new_ids = [c["id"] for c in cands]
    new_cost = _reverse_profile(edge_sql, new_ids, budget, directed)
    if not new_cost:
        return None
    new_nodes = set(new_cost)
    new_pop_by_node = _population_by_node(list(new_nodes))

    # 受影响人口 = 独占区
    excl_pop_by_node = _population_by_node(list(exclusive_nodes))
    affected = sum(excl_pop_by_node.values())

    # 恢复人口 = 独占区 ∩ 新址覆盖
    recovered_nodes = exclusive_nodes & new_nodes
    recovered_pop = sum(excl_pop_by_node.get(n, 0) for n in recovered_nodes)
    unrecovered_pop = max(0, affected - recovered_pop)

    # 新增覆盖 = 新址覆盖 − 旧设施覆盖
    added_nodes = new_nodes - old_nodes
    added_pop = sum(new_pop_by_node.get(n, 0) for n in added_nodes)

    net = recovered_pop + added_pop - affected

    result = {
        "old_poi_id": old_poi_id,
        "old_facility_id": old_facility_id,
        "category": category,
        "new_lat": new_lat, "new_lng": new_lng,
        "mode": mode,
        "time_budget_min": time_budget_min,
        "tier": tier,
        "affected_population": affected,
        "recovered_population": recovered_pop,
        "unrecovered_population": unrecovered_pop,
        "added_population": added_pop,
        "net_change": net,
        "affected_polygon": None,
        "recovered_polygon": None,
        "added_polygon": None,
    }
    if exclusive_nodes:
        result["affected_polygon"] = _polygon_for_nodes(
            ok_column, list(exclusive_nodes), node_cost=old_cost,
            budget=budget, edge_cost_sql=edge_cost_sql)
    if recovered_nodes:
        result["recovered_polygon"] = _polygon_for_nodes(
            ok_column, list(recovered_nodes), node_cost=new_cost,
            budget=budget, edge_cost_sql=edge_cost_sql)
    if added_nodes:
        result["added_polygon"] = _polygon_for_nodes(
            ok_column, list(added_nodes), node_cost=new_cost,
            budget=budget, edge_cost_sql=edge_cost_sql)
    return result


def site_selection(category, mode="walk", time_budget_min=15,
                   bbox=None, n_candidates=10, extra_candidates=None,
                   w_fill=1.0, w_new=0.5, w_overlap=0.6, auto=True):
    """选址模拟: 给定类别与范围, 找出最优新增设施候选点。

    候选点来源:
      1. 自动 (auto=True): bbox 内盲区中的需求点 (hefei_residential_nearest
         小区, 优先盲区率高/人口多的小区), 取 Top n_candidates
      2. 手动: extra_candidates=[{lat,lng}] 用户指定候选点追加

    每个候选点评分:
      增量覆盖人口 fill_pop = 候选点覆盖 ∩ 当前盲区人口 (最重要: 填补盲区)
      新增覆盖人口 new_pop  = 候选点覆盖 − 现有同类覆盖 (纯新增)
      重叠人口   overlap_pop = 候选点覆盖 ∩ 现有同类覆盖 (与已有设施竞争)
      评分 = fill_pop*w_fill + new_pop*w_new − overlap_pop*w_overlap

    返回: candidates 排序列表 [{lat,lng,coverage_population,fill_population,
          new_population,overlap_population,score,source:'auto'|'manual'}]
    """
    import math
    bbox = bbox or [117.07, 31.68, 117.50, 32.07]
    if (len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
        raise ValueError("bbox 必须为 [minlng, minlat, maxlng, maxlat]")
    t = float(time_budget_min)
    if t <= 0:
        raise ValueError("time_budget_min 必须为正数")
    bounds = (bbox[0], bbox[1], bbox[2], bbox[3])

    layer = build_layer(mode)
    edge_sql, directed, ok_column, edge_cost_sql, budget, cpm = _edge_setup(layer, t)
    threshold_cost = t * cpm

    # 1. 现有同类设施成本剖面 (用于增量/重叠判定)
    rows = execute_query("""
        SELECT DISTINCT pn.node_id
        FROM poi_road_nodes pn
        JOIN hefei_poi p ON p.id = pn.poi_id
        WHERE p.category = %s AND pn.mode='walk'
    """, (category,))
    exist_ids = _start_ids_from_nodes([r[0] for r in rows])
    if not exist_ids:
        return None
    exist_cost = _reverse_profile(edge_sql, exist_ids, budget, directed)
    exist_nodes = {n for n, c in exist_cost.items() if c <= threshold_cost}
    exist_pop_by_node = _population_by_node(list(exist_nodes))
    exist_pop = sum(exist_pop_by_node.values())

    # 2. 候选点收集
    candidates = []

    # 2a. 自动: 盲区内的需求点 (住宅小区)
    if auto:
        auto = execute_query("""
            SELECT p.id, ST_X(p.geometry), ST_Y(p.geometry),
                   COALESCE(p.name, ''), rn.distance_m
            FROM hefei_poi p
            JOIN hefei_residential_nearest rn ON rn.poi_id = p.id
            WHERE p.category = 'residential'
              AND p.geometry && ST_MakeEnvelope(%s,%s,%s,%s,4326)
        """, (*bounds,))
        for pid, plng, plat, name, rndist in auto:
            candidates.append({
                "lat": float(plat), "lng": float(plng),
                "source": "auto", "name": name, "poi_id": pid,
            })
    # 2b. 手动追加
    for ec in (extra_candidates or []):
        if isinstance(ec, dict) and ec.get('lat') is not None and ec.get('lng') is not None:
            candidates.append({
                "lat": float(ec['lat']), "lng": float(ec['lng']),
                "source": "manual", "name": ec.get('name', '手动候选'),
            })

    if not candidates:
        return None

    # 2c. 空间去重: 同 300m 内候选只保留一个 (小区扎堆, 减少重复 Dijkstra)
    keep = []
    for c in candidates:
        dup = False
        for k in keep:
            if (abs(k["lat"] - c["lat"]) * 111000 < 300
                    and abs(k["lng"] - c["lng"]) * 94000 < 300):
                dup = True
                break
        if not dup:
            keep.append(c)
    candidates = keep

    # 3. 逐候选点评分 (并发: 候选点彼此独立, 连接池支持多线程)
    from concurrent.futures import ThreadPoolExecutor

    def _evaluate(c):
        cands, _ = adaptive_snap(layer, c["lat"], c["lng"], 150, 1)
        if not cands:
            return None
        cid = cands[0]["id"]
        cc = _reverse_profile(edge_sql, [cid], budget, directed)
        if not cc:
            return None
        c_nodes = {n for n, cost in cc.items() if cost <= threshold_cost}
        if not c_nodes:
            return None
        c_pop_by_node = _population_by_node(list(c_nodes))
        cov_pop = sum(c_pop_by_node.values())
        fill_nodes = {n for n in c_nodes if n not in exist_nodes}
        fill_pop = sum(c_pop_by_node.get(n, 0) for n in fill_nodes)
        overlap_nodes = {n for n in c_nodes if n in exist_nodes}
        overlap_pop = sum(exist_pop_by_node.get(n, 0) for n in overlap_nodes)
        score = fill_pop * w_fill + cov_pop * w_new - overlap_pop * w_overlap
        return {
            "lat": c["lat"], "lng": c["lng"],
            "name": c.get("name", ""),
            "poi_id": c.get("poi_id"),
            "source": c["source"],
            "coverage_population": cov_pop,
            "fill_population": fill_pop,
            "overlap_population": overlap_pop,
            "score": round(score, 1),
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [r for r in pool.map(_evaluate, candidates) if r]

    results.sort(key=lambda r: -r["score"])
    return {
        "category": category,
        "mode": mode,
        "time_budget_min": t,
        "exist_facility_count": len(set(r[0] for r in execute_query(
            "SELECT DISTINCT pn.poi_id FROM poi_road_nodes pn "
            "JOIN hefei_poi p ON p.id=pn.poi_id WHERE p.category=%s AND pn.mode='walk'",
            (category,)))),
        "exist_coverage_population": exist_pop,
        "total_population": total_population(),
        "candidates": results[:max(1, int(n_candidates))],
        "n_candidates": len(results),
    }
