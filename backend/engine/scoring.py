"""六维生活圈评分引擎 (三层透明评分)

层1 事实: 等时圈内各维度可达设施 (typecode 加权计数) + 最近设施距离 + 地铁/公交站数。
层2 权重: 用户自定义维度权重 + 家庭结构预设 (有老人/有小孩自动调权)。
层3 参考分: 各维度子分 0-100 + 综合分 (加权平均), 附依据明细。

维度 (数据支持的 5 维):
  medical   医疗   hospital(按 typecode 三甲/专科/诊所加权) + pharmacy
  education 教育   school_primary/junior/senior/college + kindergarten
  shopping  购物   supermarket/mall/market_food + street_commercial
  leisure   休闲   park/sports + street_pedestrian
  transit   交通   地铁站 + 公交站

评分公式 (每维):
  count_score = 100 * min(1, 加权计数 / cap)          # 数量达标分
  dist_score  = 100 * max(0, 1 - 最近设施距离 / dist_cap)  # 邻近便利分
  sub_score   = 0.7 * count_score + 0.3 * dist_score
综合分 = Σ (sub_score * weight) / Σ weight, 权重由用户值 × 家庭预设系数。
"""
from engine.poi_stats import _haversine_m
from services.database import execute_one

DIMENSION_LABEL = {
    "medical": "医疗",
    "education": "教育",
    "shopping": "购物",
    "leisure": "休闲",
    "transit": "交通",
}

# 维度 → (category, 每点权重) 列表
DIM_CATEGORIES = {
    "medical": [
        ("hospital", 1.0), ("pharmacy", 0.5),
    ],
    "education": [
        ("kindergarten", 1.0), ("school_primary", 1.0),
        ("school_junior", 1.2), ("school_senior", 1.2), ("school_college", 1.5),
    ],
    "shopping": [
        ("supermarket", 1.0), ("mall", 1.0), ("market_food", 1.0),
        ("street_commercial", 0.5),
    ],
    "leisure": [
        ("park", 1.0), ("sports", 1.0), ("street_pedestrian", 0.5),
    ],
    "transit": [],
}

# hospital typecode 加权: 三甲=3 / 综合及专科=2 / 诊所基层=1 (默认 1)
MEDICAL_TYPECODE_WEIGHT = {
    "090101": 3.0,   # 综合医院
    "090102": 2.0,   # 医院 (含卫生院)
    "090103": 2.0,
    "090200": 2.0,   # 专科
    "090201": 2.0,
    "090202": 2.0,
    "090203": 2.0,
    "090300": 1.0,   # 诊所
    "090900": 1.5,   # 社区卫生服务中心
    "090700": 1.5,   # 急救中心
}

# 各维度的数量达标阈值 (cap) 与 邻近距离阈值 (米)
DIM_CAPS = {
    "medical": 12,
    "education": 6,
    "shopping": 25,
    "leisure": 10,
    "transit": 30,
}
DIM_DIST_CAPS = {
    "medical": 1500,
    "education": 1200,
    "shopping": 1200,
    "leisure": 1000,
    "transit": 1000,
}

# 交通维度: 站点换算权重 (基于"起点附近步行可达的站", 与出行模式无关,
# 保证不同模式(步行/驾车/公交)的评分可横向比较)
METRO_STATION_WEIGHT = 3.0
BUS_STOP_WEIGHT = 0.5
# 统计范围: 地铁站 800m / 公交站 400m (步行接驳合理距离)
METRO_RADIUS_M = 800
BUS_RADIUS_M = 400

# 综合分 → 等级
GRADE_LEVELS = (
    (85, "优", "配套完善"),
    (70, "良", "配套良好"),
    (55, "中", "配套一般"),
    (0, "差", "配套薄弱"),
)


def grade_of(score):
    for threshold, label, _ in GRADE_LEVELS:
        if score >= threshold:
            return label
    return GRADE_LEVELS[-1][1]

# 家庭结构预设: 维度 → 权重系数 (默认 1.0)
FAMILY_PRESETS = {
    "none": {},
    "elderly": {"medical": 1.4, "transit": 1.3, "shopping": 0.9,
                "leisure": 0.9, "education": 0.6},
    "child": {"education": 1.5, "medical": 1.1, "leisure": 1.1,
              "shopping": 0.9, "transit": 1.0},
    "elderly+child": {"medical": 1.5, "transit": 1.3, "education": 1.4,
                      "leisure": 1.0, "shopping": 0.8},
}


def _weighted_count(category, pois_by_cat):
    """某 category 的可达 POI 加权计数 (hospital 按 typecode 加权)"""
    items = pois_by_cat.get(category) or []
    if category != "hospital":
        return len(items)
    total = 0.0
    for p in items:
        codes = (p.get("sub_category") or "").split("|")
        w = max((MEDICAL_TYPECODE_WEIGHT.get(c, 1.0) for c in codes), default=1.0)
        total += w
    return total


def _nearest_distance_m(lng, lat, category):
    """某 category 最近的设施距离 (直线距离, KNN, hefei_poi 表)"""
    row = execute_one("""
        SELECT ST_Distance(
            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, geometry::geography)
        FROM hefei_poi
        WHERE category = %s
        ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        LIMIT 1
    """, (lng, lat, category, lng, lat))
    if row and row[0] is not None:
        return float(row[0])
    return None


def _nearest_to_table_m(lng, lat, table, geom_col="geometry"):
    """某表 (地铁站/公交站) 最近点距离 (直线距离, KNN)"""
    row = execute_one(f"""
        SELECT ST_Distance(
            ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, {geom_col}::geography)
        FROM {table}
        ORDER BY {geom_col} <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
        LIMIT 1
    """, (lng, lat, lng, lat))
    if row and row[0] is not None:
        return float(row[0])
    return None


def _count_nearby_m(lng, lat, table, radius_m, geom_col="geometry"):
    """某表在指定半径内的点数 (直线距离, 交通便利度用)"""
    row = execute_one(f"""
        SELECT count(*) FROM {table}
        WHERE ST_DWithin({geom_col}::geography,
                         ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
    """, (lng, lat, radius_m))
    return int(row[0]) if row and row[0] else 0


def collect_facts(result, lng, lat):
    """从 isochrone 引擎结果提取各维度事实"""
    pois_by_cat = {}
    for poi in result.get("pois", []):
        pois_by_cat.setdefault(poi["category"], []).append(poi)

    facts = {}
    for dim, cats in DIM_CATEGORIES.items():
        weighted = sum(w * _weighted_count(c, pois_by_cat) for c, w in cats)

        # 最近距离: 取该维度下最近的类别
        nearest = None
        nearest_cat = None
        for c, _ in cats:
            d = _nearest_distance_m(lng, lat, c)
            if d is not None and (nearest is None or d < nearest):
                nearest, nearest_cat = d, c

        facts[dim] = {
            "weighted_count": round(weighted, 1),
            "nearest_distance_m": round(nearest, 0) if nearest else None,
            "nearest_category": nearest_cat,
            "categories": {c: len(pois_by_cat.get(c, [])) for c, _ in cats},
        }

    metro = len(result.get("reachable_metro_stations") or [])
    bus = len(result.get("reachable_bus_stops") or [])
    # 交通维度与出行模式无关: 统计"起点步行可达"的站 (800m/400m),
    # 保证步行/驾车/公交不同模式的评分可横向比较
    metro_near = _count_nearby_m(lng, lat, "hefei_metro_stations", METRO_RADIUS_M)
    bus_near = _count_nearby_m(lng, lat, "hefei_bus_stops", BUS_RADIUS_M)
    facts["transit"]["weighted_count"] = round(metro_near * METRO_STATION_WEIGHT
                                               + bus_near * BUS_STOP_WEIGHT, 1)
    facts["transit"]["categories"] = {"metro": metro_near, "bus": bus_near,
                                      "metro_reachable": metro, "bus_reachable": bus}
    # 最近站距: 站表直线距离 (与出行模式无关, 反映该点交通便利度)
    d_metro = _nearest_to_table_m(lng, lat, "hefei_metro_stations")
    d_bus = _nearest_to_table_m(lng, lat, "hefei_bus_stops")
    nearest = min(d for d in (d_metro, d_bus) if d is not None) \
        if any(d is not None for d in (d_metro, d_bus)) else None
    facts["transit"]["nearest_distance_m"] = round(nearest, 0) if nearest else None
    facts["transit"]["nearest_category"] = "metro" \
        if (nearest is not None and d_metro is not None and d_metro <= nearest) else "bus"

    # 覆盖人口 (100m 人口栅格): 作为展示事实, 不参与评分
    import json
    from engine.population import population_density
    poly = result.get("polygon")
    pop, dens = population_density(json.dumps(poly)) if poly else (0, 0.0)
    facts["population"] = {
        "population": pop,
        "density_per_km2": dens,
    }
    return facts


def score_facts(facts, weights=None, family="none"):
    """事实 → 子分 + 综合分。weights: {dim: 相对权重}, family: 家庭结构预设。"""
    weights = weights or {}
    fam = FAMILY_PRESETS.get(family, {})

    sub_scores = {}
    for dim in DIMENSION_LABEL:
        f = facts.get(dim, {})
        count_score = 100.0 * min(1.0, (f.get("weighted_count") or 0) / DIM_CAPS[dim])
        nd = f.get("nearest_distance_m")
        if nd is None:
            dist_score = 100.0
        else:
            dist_score = 100.0 * max(0.0, 1.0 - nd / DIM_DIST_CAPS[dim])
        if dim == "transit":
            # 交通: 站距邻近 60% + 附近站数 40% (附近站数为步行可达范围内的站,
            # 与出行模式无关, 避免模式差异导致误判)
            sub_scores[dim] = round(0.6 * dist_score + 0.4 * count_score, 1)
        else:
            sub_scores[dim] = round(0.7 * count_score + 0.3 * dist_score, 1)

    # 综合权重 = 用户权重 × 家庭系数
    total_w = sum((weights.get(d, 1.0) or 1.0) * fam.get(d, 1.0)
                  for d in DIMENSION_LABEL)
    overall = 0.0
    for d in DIMENSION_LABEL:
        w = (weights.get(d, 1.0) or 1.0) * fam.get(d, 1.0)
        overall += sub_scores[d] * w
    overall = round(overall / total_w, 1) if total_w else 0.0
    return sub_scores, overall


def compute_score(lat, lng, mode, time_budget_min, weights=None, family="none",
                  snap_radius_m=150, snap_max_nodes=1):
    """完整评分: 跑等时圈 → 取事实 → 计分 → 返回可解释结果"""
    from engine.access_cache import reachability_cached
    result = reachability_cached(lat, lng, mode, time_budget_min, snap_radius_m,
                                 snap_max_nodes)
    if not result:
        return None

    facts = collect_facts(result, lng, lat)
    sub_scores, overall = score_facts(facts, weights, family)

    # 设施去重计数 (与 /api/isochrone 口径一致)
    try:
        from engine.poi_stats import build_facilities_by_category
        _fac = build_facilities_by_category(result.get('pois') or [], include_items=False)
        reachable_facilities_count = sum(v['count'] for v in _fac.values())
    except Exception:
        reachable_facilities_count = None

    # 多边形面积 (km²) 作为参考事实
    area_km2 = None
    poly = result.get("polygon")
    if poly:
        try:
            from engine.walk_layer import _polygon_area_m2
            if poly["type"] == "Polygon":
                area_km2 = _polygon_area_m2(poly["coordinates"][0]) / 1e6
            else:
                area_km2 = sum(_polygon_area_m2(p[0]) for p in poly["coordinates"]) / 1e6
            area_km2 = round(area_km2, 2)
        except Exception:
            area_km2 = None

    return {
        "mode": mode,
        "time_budget_min": time_budget_min,
        "origin": {"lat": lat, "lng": lng},
        "score": overall,
        "grade": grade_of(overall),
        "grade_desc": next((desc for t, _, desc in GRADE_LEVELS if overall >= t),
                           GRADE_LEVELS[-1][2]),
        "area_km2": area_km2,
        "reachable_pois_count": result.get("reachable_pois_count"),
        "reachable_facilities_count": reachable_facilities_count,
        "population": facts.get("population", {}).get("population", 0),
        "population_density_per_km2": facts.get("population", {}).get("density_per_km2", 0),
        "sub_scores": {
            d: {
                "score": sub_scores[d],
                "label": DIMENSION_LABEL[d],
                "facts": facts[d],
                "cap": DIM_CAPS[d],
            } for d in DIMENSION_LABEL
        },
        "weight_info": {
            "user_weights": {d: (weights or {}).get(d, 1.0) for d in DIMENSION_LABEL},
            "family": family,
        },
    }
