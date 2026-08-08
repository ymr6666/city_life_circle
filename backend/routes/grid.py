"""六边形网格分级色彩 API: POST /api/grid

纯空间统计 (无 Dijkstra): 给定 bbox, 用 PostGIS ST_HexagonGrid 切六边形,
统计每格各分类设施数 + 地铁/公交站数, 计算综合评分/密度, 填色用。

请求 (JSON):
  {bbox: [minlng, minlat, maxlng, maxlat],
   cell_size_deg?: 0.01   # 六边形外接宽 (度, 0.01 ≈ 1km)
   metric?: "score"|"density"   # score=多维综合评分; density=单类/全部设施密度
   category?: "supermarket"     # metric=density 时可选, 单类密度
   }

响应: GeoJSON FeatureCollection, 每 feature:
  geometry: 六边形
  properties: {i, j, score, area_km2, counts:{category:n,...}, metro, bus, n_categories}
"""
from flask import Blueprint, request, jsonify

from services.database import execute_query
from engine.scoring import DIM_CATEGORIES, DIMENSION_LABEL, MEDICAL_TYPECODE_WEIGHT

grid_bp = Blueprint('grid', __name__)

MAX_CELLS = 20000

# 网格综合评分维度: 个人评分(5维) + 居住(人口密度), 网格为宏观视角故保留居住维度
GRID_DIMS = list(DIMENSION_LABEL) + ["living"]

# 每维密度达标阈值 (个/km², 用于网格综合评分)
DIM_DENSITY_CAPS = {
    "medical": 8.0,
    "education": 5.0,
    "shopping": 12.0,
    "leisure": 6.0,
    "transit": 10.0,
    "living": 12000.0,   # 人/km²
}
METRO_WEIGHT = 3.0
BUS_WEIGHT = 0.5


def _cell_score(counts, metro, bus, area_km2, population=0):
    """每格综合评分 (0-100): 各维密度达标度加权平均"""
    if area_km2 <= 0:
        return 0.0
    dim_dens = {}
    for dim, cats in DIM_CATEGORIES.items():
        total = 0.0
        for cat, w in cats:
            total += (counts.get(cat) or 0) * w
        dim_dens[dim] = total / area_km2
    dim_dens["transit"] = (metro * METRO_WEIGHT + bus * BUS_WEIGHT) / area_km2
    dim_dens["living"] = population / area_km2

    subs = []
    for dim in GRID_DIMS:
        subs.append(min(100.0, 100.0 * dim_dens[dim] / DIM_DENSITY_CAPS[dim]))
    return round(sum(subs) / len(subs), 1)


@grid_bp.route('/api/grid', methods=['POST'])
def grid():
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400

    bbox = data.get('bbox')
    if (not isinstance(bbox, list) or len(bbox) != 4):
        return jsonify({"error": "bbox [minlng,minlat,maxlng,maxlat] required"}), 400
    minlng, minlat, maxlng, maxlat = (float(x) for x in bbox)
    if not (minlng < maxlng and minlat < maxlat):
        return jsonify({"error": "invalid bbox"}), 400

    cell = float(data.get('cell_size_deg', 0.01))
    if cell <= 0:
        return jsonify({"error": "cell_size_deg must be positive"}), 400

    metric = data.get('metric', 'score')
    if metric not in ('score', 'density', 'population'):
        return jsonify({"error": "metric must be 'score' or 'density' or 'population'"}), 400
    category = data.get('category')

    # 限制网格数量 (防超大范围)
    est_cols = (maxlng - minlng) / cell
    est_rows = (maxlat - minlat) / cell
    if est_cols * est_rows > MAX_CELLS:
        return jsonify({"error": f"cell count too large ({int(est_cols * est_rows)} > {MAX_CELLS}), "
                                 "increase cell_size_deg or shrink bbox"}), 400

    bounds = (minlng, minlat, maxlng, maxlat)
    hex_sql = (f"SELECT (h).i AS i, (h).j AS j, ST_AsGeoJSON((h).geom) AS g "
               f"FROM ST_HexagonGrid(%s, ST_MakeEnvelope(%s,%s,%s,%s,4326)) h")

    # 1. 六边形网格
    cells = execute_query(hex_sql, (cell, *bounds))
    cell_info = {}
    for i, j, g in cells:
        cell_info[(i, j)] = {"geom": g, "i": i, "j": j}

    if not cell_info:
        return jsonify({"type": "FeatureCollection", "features": []})

    # 2. POI 分类计数 (含 sub_category 供 hospital 加权)
    poi_rows = execute_query(f"""
        WITH hex AS (
            SELECT (h).i AS i, (h).j AS j, (h).geom AS geom
            FROM ST_HexagonGrid(%s, ST_MakeEnvelope(%s,%s,%s,%s,4326)) h
        )
        SELECT hex.i, hex.j, p.category, p.sub_category, count(*) AS n
        FROM hex JOIN hefei_poi p ON ST_Contains(hex.geom, p.geometry)
        GROUP BY hex.i, hex.j, p.category, p.sub_category
    """, (cell, *bounds))
    counts = {}
    for i, j, cat, sub, n in poi_rows:
        key = (i, j)
        d = counts.setdefault(key, {})
        d[cat] = d.get(cat, 0) + n
        # hospital typecode 加权累计 (分开记, 用于评分)
        if cat == "hospital" and sub:
            codes = (sub or '').split('|')
            w = max((MEDICAL_TYPECODE_WEIGHT.get(c, 1.0) for c in codes), default=1.0)
            d.setdefault("_hosp_weighted", 0.0)
            d["_hosp_weighted"] += w

    # 3. 地铁/公交站计数
    station_rows = execute_query(f"""
        WITH hex AS (
            SELECT (h).i AS i, (h).j AS j, (h).geom AS geom
            FROM ST_HexagonGrid(%s, ST_MakeEnvelope(%s,%s,%s,%s,4326)) h
        )
        SELECT hex.i, hex.j,
               (SELECT count(*) FROM hefei_metro_stations m WHERE ST_Contains(hex.geom, m.geometry)) AS metro,
               (SELECT count(*) FROM hefei_bus_stops b WHERE ST_Contains(hex.geom, b.geometry)) AS bus
        FROM hex
    """, (cell, *bounds))

    # 3b. 每格人口 (100m 人口点表)
    pop_rows = execute_query(f"""
        WITH hex AS (
            SELECT (h).i AS i, (h).j AS j, (h).geom AS geom
            FROM ST_HexagonGrid(%s, ST_MakeEnvelope(%s,%s,%s,%s,4326)) h
        )
        SELECT hex.i, hex.j, COALESCE(SUM(g.population), 0)
        FROM hex LEFT JOIN hefei_pop_grid g ON ST_Contains(hex.geom, g.geometry)
        GROUP BY hex.i, hex.j
    """, (cell, *bounds))

    # 4. 组装 feature
    import json as _json
    from engine.walk_layer import _polygon_area_m2

    area_km2 = None
    if cells:
        try:
            g0 = _json.loads(cells[0][2])
            area_km2 = _polygon_area_m2(g0["coordinates"][0]) / 1e6
        except Exception:
            area_km2 = cell * cell * 111.0 * 94.0  # 兜底估算

    station_map = {}
    for si, sj, sm, sb in station_rows:
        station_map[(si, sj)] = (sm, sb)
    pop_map = {}
    for pi, pj, pp in pop_rows:
        pop_map[(pi, pj)] = int(pp)

    features = []
    for (i, j), info in cell_info.items():
        cnt = counts.get((i, j), {})
        metro, bus = station_map.get((i, j), (0, 0))
        population = pop_map.get((i, j), 0)
        props = {
            "i": i, "j": j,
            "area_km2": round(area_km2, 3) if area_km2 else None,
            "counts": {k: v for k, v in cnt.items() if not k.startswith('_')},
            "n_categories": len([k for k in cnt if not k.startswith('_')]),
            "metro": metro, "bus": bus,
            "population": population,
        }
        if metric == 'density':
            if category:
                n = cnt.get(category, 0)
            else:
                n = sum(v for k, v in cnt.items() if not k.startswith('_'))
            dens = n / area_km2 if area_km2 else 0.0
            cap = DIM_DENSITY_CAPS.get(category, 8.0) if category else 10.0
            props["score"] = round(min(100.0, 100.0 * dens / cap), 1)
            props["density"] = round(dens, 1)
        elif metric == 'population':
            dens = population / area_km2 if area_km2 else 0.0
            props["density"] = round(dens, 0)
            props["score"] = round(min(100.0, 100.0 * dens / 12000.0), 1)  # 理想密度 1.2万人/km²
        else:
            c = dict(cnt)
            # hospital 用 typecode 加权数覆盖
            if "_hosp_weighted" in c:
                c["hospital"] = c["_hosp_weighted"]
            props["score"] = _cell_score(c, metro, bus, area_km2 or 1.0, population)

        features.append({
            "type": "Feature",
            "geometry": _json_loads(info["geom"]),
            "properties": props,
        })

    return jsonify({
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "bbox": bbox, "cell_size_deg": cell, "metric": metric,
            "category": category, "cell_area_km2": area_km2,
            "n_cells": len(features),
        },
    })


def _json_loads(s):
    import json
    return json.loads(s)
