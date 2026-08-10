"""全城分析引擎 (citywide) —— 「全城分析」页后端

在覆盖引擎 (coverage) 基础上扩展三个宏观分析, 全部复用一次多源反向
Dijkstra 剖面 (虚拟超级节点, 全城 ~2-3s), 聚合成本低:

  1. blindzone_clusters  盲区聚类: 100m 盲区人口点 → 粗网格连通域 (并查集,
     8 邻域), 输出 top-N 连续盲区 {中心, 盲区人口, 栅格数, bbox, 凸包多边形}。
  2. mismatch_grid       错配分析: 六边形网格统计"人口 vs 设施数",
     z-score 差 = mismatch (>0 高人口低设施缺口, <0 设施冗余),
     附人均设施量 (fac_per_10k) 作参考。
  3. balance_metrics     均衡分析: 全城供需宏观指标 (覆盖率/盲区人口/
     人均设施量/最近设施距离 CDF p50/p75/p90)。
"""
import json
import statistics

from services.database import execute_query, execute_one
from engine.coverage import (
    POP_SNAP_MAX_M, _category_start_ids, _category_facility_filter,
    _reverse_profile, _population_by_node, _edge_setup, _slice_thresholds,
    total_population,
)
from engine.factory import build_layer

# 合肥全城 bbox
CITY_BBOX = [117.07, 31.68, 117.50, 32.07]


def _resolve_bbox(bbox):
    if not bbox:
        return CITY_BBOX
    if (len(bbox) != 4 or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
        raise ValueError("bbox 必须为 [minlng, minlat, maxlng, maxlat]")
    return [float(x) for x in bbox]


def _reverse_profile_for(category, tier, mode, time_budget_min):
    """类别多源反向剖面 + 阈值换算, 返回 (node_cost, cpm, threshold_cost)"""
    start_ids = _category_start_ids(category, tier, mode='walk')
    if not start_ids:
        return None
    layer = build_layer(mode)
    edge_sql, directed, ok_column, edge_cost_sql, budget, cpm = _edge_setup(
        layer, time_budget_min)
    node_cost = _reverse_profile(edge_sql, start_ids, budget, directed)
    if not node_cost:
        return None
    return node_cost, cpm, time_budget_min * cpm


def _concave_hull(points):
    """点集凹包 GeoJSON (ST_ConcaveHull 贴合点云, 比凸包更贴近真实形状)。

    抽样到最多 3000 点; <3 点返回 None; 点数少时退化为凸包。
    """
    if len(points) < 3:
        return None
    step = max(1, len(points) // 3000)
    sample = points if step == 1 else points[::step]
    vals = ','.join(f"({lng:.6f},{lat:.6f})" for lng, lat in sample)
    # 点多用凹包(贴合), 点少(<8)用凸包避免凹包退化
    if len(sample) >= 8:
        sql = "ST_ConcaveHull(ST_Collect(geom), 0.8)"
    else:
        sql = "ST_ConvexHull(ST_Collect(geom))"
    row = execute_one(f"""
        SELECT ST_AsGeoJSON({sql})
        FROM (SELECT ST_SetSRID(ST_MakePoint(x, y), 4326) AS geom
              FROM (VALUES {vals}) AS t(x, y)) s
    """)
    if row and row[0]:
        try:
            return json.loads(row[0])
        except ValueError:
            return None
    return None


def _cluster_raw(pop_rows, covered, cell, connectivity, min_points, top_n):
    """粗网格连通域聚类 (并查集)。返回按盲区人口降序的簇列表 (含 _points)。

    pop_rows: [(lng, lat, population, node_id)]; covered: 已覆盖节点 set。
    connectivity: 4=rook / 8=queen。
    """
    conn = int(connectivity)
    if conn not in (4, 8):
        raise ValueError("connectivity 仅支持 4(rook) 或 8(queen)")
    parent = {}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    if conn == 4:
        neighbors = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    else:
        neighbors = [(di, dj) for di in (-1, 0, 1) for dj in (-1, 0, 1)
                     if not (di == 0 and dj == 0)]

    agg = {}  # key -> [pop, n_pts, sum_lng*pop, sum_lat*pop, points]
    for lng, lat, population, node_id in pop_rows:
        if node_id in covered or int(population or 0) <= 0:
            continue
        population = int(population)
        ci, cj = int(lng / cell), int(lat / cell)
        key = (ci, cj)
        if key not in parent:
            parent[key] = key
        for di, dj in neighbors:
            nb = (ci + di, cj + dj)
            if nb in parent:
                union(key, nb)
        d = agg.setdefault(key, [0, 0, 0.0, 0.0, []])
        d[0] += population
        d[1] += 1
        d[2] += lng * population
        d[3] += lat * population
        d[4].append((lng, lat))

    # 合并到根簇
    root_pts = {}
    root_agg = {}
    for key, d in agg.items():
        root = find(key)
        root_agg.setdefault(root, [0, 0, 0.0, 0.0])  # [pop, n_pts, slng, slat]
        a = root_agg[root]
        a[0] += d[0]
        a[1] += d[1]
        a[2] += d[2]
        a[3] += d[3]
        root_pts.setdefault(root, []).extend(d[4])

    clusters = []
    for root, (pop, n_pts, slng, slat) in root_agg.items():
        if n_pts < min_points:
            continue
        pts = root_pts[root]
        lngs = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        clusters.append({
            "population": int(pop),
            "n_points": n_pts,
            "centroid": {"lng": round(slng / pop, 6), "lat": round(slat / pop, 6)},
            "bbox": [round(min(lngs), 6), round(min(lats), 6),
                     round(max(lngs), 6), round(max(lats), 6)],
            "_points": pts,
        })
    clusters.sort(key=lambda c: -c["population"])
    return clusters[:max(1, int(top_n))]


def blindzone_clusters(category, mode="walk", time_budget_min=15, bbox=None,
                       tier=None, cluster_cell_deg=0.0025, min_points=5,
                       top_n=20, connectivity=4, max_blind_points=15000):
    """盲区聚类: 粗网格连通域 (并查集)。

    connectivity: 4=rook(共享边才连通, 推荐, 避免对角格把分散盲区连成整片)
                  8=queen(对角也算连通, 合并更激进)。
    返回 {clusters:[{id,rank,population,n_points,centroid,bbox,polygon}],
          features: 采样盲区点 (GeoJSON, 供底图), facilities, meta}
    """
    bbox = _resolve_bbox(bbox)
    t = float(time_budget_min)
    if t <= 0:
        raise ValueError("time_budget_min 必须为正数")
    cell = float(cluster_cell_deg)
    if cell <= 0:
        raise ValueError("cluster_cell_deg 必须为正数")
    conn = int(connectivity)
    if conn not in (4, 8):
        raise ValueError("connectivity 仅支持 4(rook) 或 8(queen)")
    bounds = (bbox[0], bbox[1], bbox[2], bbox[3])

    prof = _reverse_profile_for(category, tier, mode, t)
    if prof is None:
        return None
    node_cost, _cpm, threshold_cost = prof
    covered = {n for n, c in node_cost.items() if c <= threshold_cost}

    pop_rows = execute_query("""
        SELECT ST_X(g.geometry), ST_Y(g.geometry), g.population, n.node_id
        FROM hefei_pop_grid g
        JOIN hefei_pop_nearest n ON n.pop_id = g.id
        WHERE g.geometry && ST_MakeEnvelope(%s,%s,%s,%s,4326)
          AND n.distance_m <= %s
    """, (*bounds, POP_SNAP_MAX_M))

    clusters = _cluster_raw(pop_rows, covered, cell, conn, min_points, top_n)

    # 凹包 + 输出结构
    out = []
    total_blind = sum(c["population"] for c in clusters)
    for i, cl in enumerate(clusters):
        polygon = _concave_hull(cl.pop("_points"))
        out.append({
            "id": i + 1,
            "rank": i + 1,
            "population": cl["population"],
            "n_points": cl["n_points"],
            "centroid": cl["centroid"],
            "bbox": cl["bbox"],
            "polygon": polygon,
        })

    # 采样盲区点 (底图)
    n_pts = len(pop_rows)
    step = max(1, n_pts // max_blind_points) if n_pts > max_blind_points else 1
    feats = []
    sampled_pop = 0
    for k, (lng, lat, population, node_id) in enumerate(pop_rows):
        if node_id in covered or int(population or 0) <= 0:
            continue
        if k % step != 0:
            continue
        population = int(population)
        sampled_pop += population
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lng), float(lat)]},
            "properties": {"population": population, "tier": "盲区"},
        })

    return {
        "clusters": out,
        "features": {"type": "FeatureCollection", "features": feats},
        "meta": {
            "category": category, "mode": mode, "time_budget_min": t,
            "tier": tier, "cluster_cell_deg": cell, "bbox": bbox,
            "n_clusters": len(out), "blind_population": total_blind,
            "sampled_blind_population": sampled_pop,
        },
    }


def cluster_assign_from_profile(node_cost, threshold_cost, bbox,
                                cluster_cell_deg=0.0025, min_points=3,
                                top_n=50, connectivity=4):
    """用已算好的反向剖面做盲区簇 (供选址候选归属, 省一次全城 Dijkstra)。

    node_cost: {node: cost} (site_selection 的 exist_cost); threshold_cost: 覆盖阈值。
    返回按盲区人口降序的簇列表 [{id, population, n_points, bbox}]。
    """
    cell = float(cluster_cell_deg)
    bounds = (bbox[0], bbox[1], bbox[2], bbox[3])
    covered = {n for n, c in node_cost.items() if c <= threshold_cost}
    pop_rows = execute_query("""
        SELECT ST_X(g.geometry), ST_Y(g.geometry), g.population, n.node_id
        FROM hefei_pop_grid g
        JOIN hefei_pop_nearest n ON n.pop_id = g.id
        WHERE g.geometry && ST_MakeEnvelope(%s,%s,%s,%s,4326)
          AND n.distance_m <= %s
    """, (*bounds, POP_SNAP_MAX_M))
    raw = _cluster_raw(pop_rows, covered, cell, connectivity, min_points, top_n)
    out = []
    for i, cl in enumerate(raw):
        out.append({
            "id": i + 1,
            "population": cl["population"],
            "n_points": cl["n_points"],
            "bbox": cl["bbox"],
        })
    return out


def cell_ij_for_point(cell_size_deg, bbox, lng, lat):
    """求某点在错配六边形网格中的 (i, j), 不在网格范围返回 None。"""
    row = execute_one("""
        SELECT (h).i, (h).j
        FROM ST_HexagonGrid(%s, ST_MakeEnvelope(%s,%s,%s,%s,4326)) h
        WHERE ST_Contains((h).geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
    """, (float(cell_size_deg), *bbox, float(lng), float(lat)))
    if row and row[0] is not None:
        return (int(row[0]), int(row[1]))
    return None


def mismatch_grid(category, tier=None, bbox=None, cell_size_deg=0.01,
                  grid_type="hex"):
    """人口 vs 设施错配网格 (纯空间统计, 无 Dijkstra)。

    mismatch = z_pop - z_fac (clamp ±2): >0 高人口低设施 (缺口, 红),
    <0 设施冗余 (蓝), ≈0 均衡。附 fac_per_10k (每万人设施数) 作参考。
    """
    bbox = _resolve_bbox(bbox)
    cell = float(cell_size_deg)
    if cell <= 0:
        raise ValueError("cell_size_deg 必须为正数")
    # 网格数量上限保护 (防超大范围 × 过细格网导致响应巨大)
    est = (bbox[2] - bbox[0]) / cell * (bbox[3] - bbox[1]) / cell
    if est > 20000:
        raise ValueError(f"网格数量过大 ({int(est)} > 20000), 请增大格网尺寸或缩小范围")
    grid_func = 'ST_SquareGrid' if grid_type == 'square' else 'ST_HexagonGrid'
    bounds = (bbox[0], bbox[1], bbox[2], bbox[3])
    where, where_params = _category_facility_filter(category, tier)

    rows = execute_query(f"""
        WITH grid AS (
            SELECT (h).i AS i, (h).j AS j, (h).geom AS geom
            FROM {grid_func}(%s, ST_MakeEnvelope(%s,%s,%s,%s,4326)) h
        ),
        pop AS (
            SELECT g.i, g.j, COALESCE(SUM(p.population), 0) AS population
            FROM grid g LEFT JOIN hefei_pop_grid p ON ST_Contains(g.geom, p.geometry)
            GROUP BY g.i, g.j
        ),
        fac AS (
            SELECT g.i, g.j, count(p.id) AS fac_count
            FROM grid g JOIN hefei_poi p ON ST_Contains(g.geom, p.geometry)
            WHERE {where}
            GROUP BY g.i, g.j
        )
        SELECT g.i, g.j,
               COALESCE(pop.population, 0), COALESCE(fac.fac_count, 0),
               ST_AsGeoJSON(g.geom)
        FROM grid g
        LEFT JOIN pop ON pop.i = g.i AND pop.j = g.j
        LEFT JOIN fac ON fac.i = g.i AND fac.j = g.j
    """, (cell, *bounds, *where_params))

    cells = []
    for i, j, population, fac_count, g in rows:
        cells.append({
            "i": i, "j": j,
            "population": int(population),
            "fac_count": int(fac_count),
            "geom": json.loads(g),
        })

    if cells:
        mean_pop = statistics.mean(c["population"] for c in cells)
        std_pop = statistics.pstdev(c["population"] for c in cells) or 1.0
        mean_fac = statistics.mean(c["fac_count"] for c in cells)
        std_fac = statistics.pstdev(c["fac_count"] for c in cells) or 1.0
    else:
        mean_pop = std_pop = mean_fac = std_fac = 0.0

    features = []
    for c in cells:
        z_pop = (c["population"] - mean_pop) / std_pop if std_pop else 0.0
        z_fac = (c["fac_count"] - mean_fac) / std_fac if std_fac else 0.0
        mismatch = max(-2.0, min(2.0, z_pop - z_fac))
        per_10k = round(c["fac_count"] / (c["population"] / 10000.0), 2) \
            if c["population"] > 0 else 0.0
        features.append({
            "type": "Feature",
            "geometry": c["geom"],
            "properties": {
                "i": c["i"], "j": c["j"],
                "population": c["population"],
                "fac_count": c["fac_count"],
                "fac_per_10k": per_10k,
                "pop_z": round(z_pop, 2),
                "fac_z": round(z_fac, 2),
                "mismatch": round(mismatch, 2),
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "category": category, "tier": tier, "bbox": bbox,
            "cell_size_deg": cell, "grid_type": grid_type,
            "n_cells": len(features),
            "mean_pop": round(mean_pop, 1), "mean_fac": round(mean_fac, 2),
            "std_pop": round(std_pop, 1), "std_fac": round(std_fac, 2),
        },
    }


def balance_metrics(category, tier=None, mode="walk", time_budget_min=15,
                    bbox=None):
    """全城供需均衡宏观指标 (复用一次反向剖面 + 人口聚合)。

    返回 {coverage_rate, blind_population, blind_ratio, facility_count,
          facility_per_10k, population_per_facility,
          distance_minutes:{p50,p75,p90}, coverage_by_time:[...]}
    """
    bbox = _resolve_bbox(bbox)
    t = float(time_budget_min)
    if t <= 0:
        raise ValueError("time_budget_min 必须为正数")

    prof = _reverse_profile_for(category, tier, mode, t)
    if prof is None:
        return None
    node_cost, cpm, threshold_cost = prof

    total = total_population()
    pop_by_node = _population_by_node(list(node_cost))
    covered_pop = sum(pop_by_node.get(n, 0) for n, c in node_cost.items()
                      if c <= threshold_cost)

    # 设施数 (tier 过滤后, 按 facility 去重)
    where, where_params = _category_facility_filter(category, tier)
    row = execute_one(
        f"SELECT count(DISTINCT COALESCE(p.facility_id, p.id)) "
        f"FROM hefei_poi p WHERE {where}", tuple(where_params))
    facility_count = int(row[0]) if row and row[0] else 0

    # 最近设施时间分布 (人口加权 CDF): p50/p75/p90
    p50 = p75 = p90 = None
    cum = 0
    for n, c in sorted(node_cost.items(), key=lambda kv: kv[1]):
        cum += pop_by_node.get(n, 0)
        minutes = round(c / cpm, 1) if cpm else 0.0
        if p50 is None and cum >= 0.5 * total:
            p50 = minutes
        if p75 is None and cum >= 0.75 * total:
            p75 = minutes
        if p90 is None and cum >= 0.9 * total:
            p90 = minutes

    coverage_by_time = _slice_thresholds(node_cost, [5, 10, 15, 30],
                                         pop_by_node, cpm)
    for _t in coverage_by_time:
        _t["coverage_rate"] = round(_t["covered_population"] / total, 4) if total else 0.0

    return {
        "category": category, "tier": tier, "mode": mode,
        "time_budget_min": t, "bbox": bbox,
        "total_population": total,
        "coverage_population": covered_pop,
        "coverage_rate": round(covered_pop / total, 4) if total else 0.0,
        "blind_population": max(0, total - covered_pop),
        "blind_ratio": round(max(0.0, 1.0 - (covered_pop / total if total else 0.0)), 4),
        "facility_count": facility_count,
        "facility_per_10k": round(facility_count / (total / 10000.0), 2) if total else 0.0,
        "population_per_facility": round(total / facility_count, 0) if facility_count else None,
        "covered_pop_per_facility": round(covered_pop / facility_count, 0) if facility_count else None,
        "distance_minutes": {"p50": p50, "p75": p75, "p90": p90},
        "coverage_by_time": coverage_by_time,
    }
