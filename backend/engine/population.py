"""人口统计: 多边形内人口 (hefei_pop_grid 100m 点表, WGS84)

栅格来源: PopSE_China2020_100m.tif → scripts/utils/import_population.py 提取
"""

from services.database import execute_one


def population_in_geojson(geom_json, min_pop=None):
    """GeoJSON 多边形内总人口 (可选按人口下限过滤)
    返回 int; 多边形无效或表缺失时返回 0。"""
    if not geom_json:
        return 0
    filter_sql = ""
    if min_pop:
        filter_sql = f" AND population >= {int(min_pop)}"
    try:
        row = execute_one(f"""
            SELECT COALESCE(SUM(population), 0)
            FROM hefei_pop_grid
            WHERE ST_Covers(ST_GeomFromGeoJSON(%s), geometry){filter_sql}
        """, (geom_json,))
        return int(row[0]) if row else 0
    except Exception:
        return 0


def population_density(geom_json, dilate_m=150):
    """多边形内人口密度 (人/km²); 返回 (population, density)

    等时圈多边形由道路走廊 buffer 构成, 面积偏小会导致密度虚高。
    dilate_m 对多边形做外扩 (默认 150m, 近似街块宽度), 使其近似
    "生活圈"实际居住范围, 再计算人口与密度。"""
    if not geom_json:
        return 0, 0.0
    try:
        row = execute_one("""
            WITH p AS (
                SELECT ST_Buffer(ST_GeomFromGeoJSON(%s)::geography, %s)::geometry AS g
            )
            SELECT (SELECT COALESCE(SUM(population), 0) FROM hefei_pop_grid
                    WHERE ST_Covers(p.g, geometry)),
                   COALESCE(ST_Area(p.g::geography) / 1e6, 1.0)
            FROM p
        """, (geom_json, dilate_m))
        if not row:
            return 0, 0.0
        pop = int(row[0] or 0)
        area = float(row[1] or 1.0)
        return pop, round(pop / area, 1)
    except Exception:
        return 0, 0.0
