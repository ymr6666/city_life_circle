"""人口统计 API: POST /api/population/stat + /api/population/residential

区域人口统计 (圈选/多边形/bbox → 总人口/面积/密度/小区数)。
小区人口分布 (以住宅小区为单元, 按小区挂接路网节点聚合人口点)。

数据: hefei_pop_grid (100m 人口点表, 合肥约 623 万人) +
      hefei_pop_nearest (人口点→最近路网节点) +
      hefei_residential_nearest (小区→路网节点)。

注意: 小区人口为**估算**——把挂在同一路网节点的人口点归到该节点对应的小区;
一个节点可能对应多个小区, 该法会重复/丢失, 适合热力/对比, 非精确统计。
"""
from flask import Blueprint, request, jsonify

from services.database import execute_query, execute_one

population_bp = Blueprint('population', __name__)


def _parse_geom(data):
    """解析请求中的几何: bbox [minlng,minlat,maxlng,maxlat] 或 polygon GeoJSON。
    返回 (geom_sql, params, is_polygon)。"""
    bbox = data.get('bbox')
    polygon = data.get('polygon')
    if bbox and (isinstance(bbox, list) and len(bbox) == 4):
        b = [float(x) for x in bbox]
        if b[0] >= b[2] or b[1] >= b[3]:
            raise ValueError("bbox 必须为 [minlng,minlat,maxlng,maxlat]")
        return "ST_MakeEnvelope(%s,%s,%s,%s,4326)", b, False
    if polygon:
        import json
        return "ST_GeomFromGeoJSON(%s)", [json.dumps(polygon)], True
    return None, None, None


@population_bp.route('/api/population/stat', methods=['POST'])
def population_stat():
    """区域人口统计: 圈选区域 → 总人口/面积/密度/小区数/格点数。

    请求: {bbox: [minlng,minlat,maxlng,maxlat]} 或 {polygon: GeoJSON}
    响应: {population, area_km2, density_per_km2, pop_grid_points,
           residential_count, population_by_100m? }
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400
    geom_sql, geom_params, is_polygon = _parse_geom(data)
    if geom_sql is None:
        return jsonify({"error": "需要 bbox 或 polygon"}), 400

    params = list(geom_params)
    try:
        # 区域内总人口 + 格点数
        row = execute_one(f"""
            SELECT COALESCE(SUM(population),0), count(*)
            FROM hefei_pop_grid WHERE ST_Covers({geom_sql}, geometry)
        """, tuple(params))
        pop = int(row[0] or 0)
        pts = int(row[1] or 0)

        # 面积 (km²) + 密度
        row2 = execute_one(f"""
            SELECT COALESCE(ST_Area({geom_sql}::geography)/1e6, 0)
        """, tuple(params))
        area = float(row2[0] or 0)

        # 区域内小区数 (住宅 POI)
        params_r = list(params)
        row3 = execute_one(f"""
            SELECT count(*) FROM hefei_poi
            WHERE category='residential' AND ST_Covers({geom_sql}, geometry)
        """, tuple(params_r))
        resi = int(row3[0] or 0)

        # 区域内人口最大/最小/均值 (100m 格)
        params_s = list(params)
        row4 = execute_one(f"""
            SELECT COALESCE(round(avg(population)::numeric,1),0),
                   COALESCE(round(max(population)::numeric),0)
            FROM hefei_pop_grid WHERE ST_Covers({geom_sql}, geometry)
        """, tuple(params_s))

        return jsonify({
            "population": pop,
            "area_km2": round(area, 3),
            "density_per_km2": round(pop / area, 1) if area > 0 else 0,
            "pop_grid_points": pts,
            "residential_count": resi,
            "avg_cell_population": float(row4[0] or 0),
            "max_cell_population": float(row4[1] or 0),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@population_bp.route('/api/population/residential', methods=['POST'])
def population_residential():
    """小区人口分布: bbox 内小区 + 估算人口/密度。

    估算: 小区挂接节点 → 聚合挂在该节点上的人口点 (100m 格)。
    注: 一个路网节点可能挂多个小区, 人口会重复计入各小区 (粗口径,
    用于热力/对比)。返回前 N 个 (limit, 默认 500)。

    请求: {bbox?, limit?}
    响应: {total_population, n_residential, items:[{id,name,lng,lat,
           population, sub_category}]}
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "missing JSON body"}), 400
    limit = int(data.get('limit', 500))
    bbox = data.get('bbox')
    if bbox and (isinstance(bbox, list) and len(bbox) == 4):
        b = [float(x) for x in bbox]
        if b[0] >= b[2] or b[1] >= b[3]:
            return jsonify({"error": "bbox 非法"}), 400
        bbox_sql = "p.geometry && ST_MakeEnvelope(%s,%s,%s,%s,4326)"
        bbox_params = b
    else:
        bbox_sql = "TRUE"
        bbox_params = []

    # 每小区: 挂接节点 → 该节点聚合人口
    rows = execute_query(f"""
        SELECT p.id, p.name,
               ST_X(p.geometry), ST_Y(p.geometry),
               COALESCE(SUM(g.population), 0) AS pop,
               COALESCE(p.sub_category, '')
        FROM hefei_poi p
        JOIN hefei_residential_nearest rn ON rn.poi_id = p.id
        LEFT JOIN hefei_pop_nearest pn ON pn.node_id = rn.node_id
        LEFT JOIN hefei_pop_grid g ON g.id = pn.pop_id
        WHERE p.category = 'residential' AND {bbox_sql}
        GROUP BY p.id, p.name, ST_X(p.geometry), ST_Y(p.geometry), p.sub_category
        ORDER BY pop DESC
        LIMIT %s
    """, (*bbox_params, limit))

    items = [{
        "id": r[0], "name": r[1], "lng": float(r[2]), "lat": float(r[3]),
        "population": int(r[4] or 0), "sub_category": r[5],
    } for r in rows]
    total = sum(x["population"] for x in items)

    return jsonify({
        "n_residential": len(items),
        "estimated_total_population": total,
        "items": items,
    })
