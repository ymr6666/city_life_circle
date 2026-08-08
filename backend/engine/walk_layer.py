"""
步行可达性引擎 (WalkLayer)
核心算法: pgRouting 的 pgr_drivingDistance (内置 Dijkstra 最短路径)

实现原理:
  1. 时间预算 → 距离预算: distance_m = time_min * 5km/h * 1000 / 60
  2. 用户坐标吸附到最近步行可用路网节点
  3. pgr_drivingDistance 从起点做 Dijkstra, 找出所有 agg_cost <= 距离预算的节点
  4. 通过 poi_road_nodes 表反查可达节点上的 POI
  5. 多起点容错: 在起点半径内取多个候选节点, 合并并集 (取各节点 min agg_cost)

道路过滤规则 (行人不可入):
  - 依赖 hefei_roads.walk_ok 布尔列 (由 scripts/utils/enrich_roads_tags.py 计算)
    · 排除 motorway/trunk 及 _link (绕城高速/快速路)
    · 排除高架 (bridge_class='elevated') 与车行隧道
    · 排除 access=private / foot=no 路段
    · 步行桥/普通过河桥可走 (bridge_class='footbridge'/'bridge')
  - 相比旧的散落过滤串, 分类逻辑集中在数据库侧, 一处定义, 便于可视化排查

道路成本模型:
  cost = reverse_cost = ST_Length(geometry::geography) —— 弧度距离(米)
  pgRouting 沿路网累加 cost, 得到每个节点的精确步行距离 (agg_cost)
  步行方向无关 (directed := false), 行人在任何道路可双向行走
"""
from .base_layer import TransportLayer
from services.database import (execute_query, execute_one, execute_one_fresh,
                               execute_query_fresh)

import json
import math

# 自适应吸附的半径阶梯: 默认半径找不到时逐级放大 (点可能在校区/公园内部或坐标偏移)
ADAPTIVE_RADII = (150, 300, 500, 800)


def adaptive_snap(layer, lat: float, lng: float, base_radius_m: float = 150,
                  max_nodes: int = 3, max_radius_m: float = 800):
    """多级半径吸附容错。返回 (candidates, 实际使用的半径)。
    在稀疏路网区域(校区/公园内部)或坐标有偏移时, 自动放大吸附半径避免直接失败。"""
    radii = [base_radius_m]
    for r in ADAPTIVE_RADII:
        if r > base_radius_m and r <= max_radius_m:
            radii.append(r)
    for r in radii:
        cands = layer.snap_origin_multi(lat, lng, r, max_nodes)
        if cands:
            return cands, r
    return [], base_radius_m


def _polygon_area_m2(ring):
    """粗略多边形面积 (米²): 经纬度按 shoelace, 用 cos(mean_lat) 修正经度"""
    n = len(ring)
    if n < 3:
        return 0.0
    mean_lat = sum(p[1] for p in ring) / n
    k = 111320.0 * math.cos(math.radians(mean_lat))
    area = 0.0
    for i in range(n - 1):
        x1, y1 = (ring[i][0] * k, ring[i][1] * 111320.0)
        x2, y2 = (ring[i + 1][0] * k, ring[i + 1][1] * 111320.0)
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _fill_small_holes(coords, max_hole_frac=0.05):
    """填充多边形小洞: 内环面积 < 外环面积 * max_hole_frac 时移除。

    等时圈多边形由道路走廊 buffer 生成, 街区内部会留下孔洞 (看起来破碎)。
    街块通常远小于外环, 填充之; 大面积空洞 (湖泊/大公园) 保留。"""
    if len(coords) <= 1:
        return coords
    outer_area = _polygon_area_m2(coords[0])
    if outer_area <= 0:
        return coords
    kept = [coords[0]]
    for ring in coords[1:]:
        if _polygon_area_m2(ring) >= max_hole_frac * outer_area:
            kept.append(ring)
    return kept


def _drop_small_parts(geojson, min_area_m2=20000, max_hole_frac=0.05):
    """去掉过小的碎块 (MultiPolygon 部分) 并填充小洞, 减少视觉噪点"""
    if not geojson:
        return geojson
    t = geojson.get("type")
    if t == "Polygon":
        if _polygon_area_m2(geojson["coordinates"][0]) < min_area_m2:
            return None
        return {"type": "Polygon",
                "coordinates": _fill_small_holes(geojson["coordinates"], max_hole_frac)}
    if t == "MultiPolygon":
        kept = [{"coordinates": _fill_small_holes(p, max_hole_frac), "type": "Polygon"}
                for p in geojson["coordinates"]
                if _polygon_area_m2(p[0]) >= min_area_m2]
        if not kept:
            return None
        parts = [p["coordinates"] for p in kept]
        if len(parts) == 1:
            return {"type": "Polygon", "coordinates": parts[0]}
        return {"type": "MultiPolygon", "coordinates": parts}
    return geojson


def _normalize_collection(geojson):
    """GeometryCollection → MultiPolygon (若为多个 Polygon 合并)"""
    if not geojson or geojson.get("type") != "GeometryCollection":
        return geojson
    rings = []
    for g in geojson.get("geometries", []):
        if g.get("type") == "Polygon":
            rings.append(g["coordinates"])
        elif g.get("type") == "MultiPolygon":
            rings.extend(g["coordinates"])
    if not rings:
        return None
    if len(rings) == 1:
        return {"type": "Polygon", "coordinates": rings[0]}
    return {"type": "MultiPolygon", "coordinates": rings}


def _edges_within_nodes(node_ids, ok_column, node_cost=None, budget=None,
                        edge_cost_sql=None):
    """可达节点集内的"预算内可遍历"道路边。

    仅包含两端点可达、且**从某一端沿该边能在预算内到达对端**的边。
    相比最短路径树边 (无环、稀疏→破碎) 更丰满; 相比"两端点都在集合内即收录"
    (会把两条可达走廊之间不可达的道路也填进来 → 过度填充) 更准确。

    - node_cost: {node: 到起点成本} (单模式为米, 耦合模式为分钟)
    - budget: 时间/距离预算
    - edge_cost_sql: 该边的成本表达式 (单模式 "r.cost"; 耦合模式
      "r.cost * 60.0 / speed_mh")
    未提供 node_cost/budget 时退化为"两端点都在集合内"。
    """
    if not node_ids or len(node_ids) < 2:
        return []
    if node_cost is not None and budget is not None:
        vals = ','.join(['(%s, %s)'] * len(node_ids))
        params = []
        for n in node_ids:
            params += [n, node_cost[n]]
        params += [budget, budget]
        rows = execute_query(f"""
            WITH nc(node, cost) AS (VALUES {vals})
            SELECT DISTINCT r.id
            FROM hefei_roads r JOIN nc ON nc.node = r.source OR nc.node = r.target
            WHERE r.cost > 0 AND r.{ok_column}
              AND ((nc.node = r.source AND nc.cost + {edge_cost_sql} <= %s)
                OR (nc.node = r.target AND nc.cost + {edge_cost_sql} <= %s))
        """, tuple(params))
        return [r[0] for r in rows]

    phs = ','.join(['%s'] * len(node_ids))
    rows = execute_query(f"""
        SELECT id FROM hefei_roads
        WHERE source IN ({phs}) AND target IN ({phs}) AND cost > 0 AND {ok_column}
    """, tuple(node_ids) * 2)
    return [r[0] for r in rows]


def reachable_polygon_from_edges(edge_ids, buffer_m=30.0, simplify=0.00015,
                                 min_area_m2=20000, min_area_frac=0.05,
                                 seed_lines=None, seed_points=None):
    """可达路段 → 等时圈真实边界 (主方案)

    可达路段做街道宽度 buffer 后 union, 边界严格贴合道路网络走向,
    比"节点凸包/凹包"更平滑更真实。多模式下道路不连通的孤立区域
    自然保持分离 (MultiPolygon), 即公交/地铁走廊形成的可达孤岛。

    碎块过滤用动态面积阈值: 保留 >= min_area_m2 的所有块, 且至少保留
    最大块的 min_area_frac 比例 (随等时圈尺度自适应, 避免一刀切误删
    大孤岛或留下密集小碎点)。

    - edge_ids: 可达道路边 id 列表
    - buffer_m: buffer 宽度 (街道走廊)
    - simplify: ST_SimplifyPreserveTopology 容差 (度)
    - min_area_m2: 最小保留面积 (米²)
    - min_area_frac: 最大块的保留比例 (0.05 = 5%)
    - seed_lines: 额外吸附连线 [(lng1,lat1,lng2,lat2), ...] —— 把 POI
      到路网吸附点的连线也 buffer 进多边形, 保证覆盖范围包住 POI 本身
      (反算时 POI 常离道路几十到几百米, 否则会落在走廊间隙里)。
    - seed_points: 额外可达点 [(lng, lat), ...] —— 每个点 buffer 进多边形。
      POI 通常离道路 30~150m, 仅靠道路走廊会把它排除在圈外 ("可达但圈外")。
      把所有可达 POI 点位各 buffer buffer_m, 确保圈内设施视觉上都在圈内。
    """
    edge_ids = [int(e) for e in edge_ids if e is not None and e >= 0]
    if not edge_ids and not seed_lines and not seed_points:
        return None

    parts = []
    params = []
    if edge_ids:
        phs = ','.join(['%s'] * len(edge_ids))
        parts.append(
            f"SELECT ST_Buffer(geometry::geography, {buffer_m})::geometry AS g "
            f"FROM hefei_roads WHERE id IN ({phs})")
        params += edge_ids
    if seed_lines:
        vals = []
        for (x1, y1, x2, y2) in seed_lines:
            vals.append("(%s, %s, %s, %s)")
            params += [x1, y1, x2, y2]
        parts.append(
            "SELECT ST_Buffer(ST_MakeLine("
            "ST_SetSRID(ST_MakePoint(l.x1, l.y1), 4326), "
            "ST_SetSRID(ST_MakePoint(l.x2, l.y2), 4326))::geography, "
            f"{buffer_m})::geometry AS g "
            f"FROM (VALUES {','.join(vals)}) AS l(x1, y1, x2, y2)")
    if seed_points:
        vals = []
        for (x, y) in seed_points:
            vals.append("(%s, %s)")
            params += [x, y]
        parts.append(
            f"SELECT ST_Buffer(ST_SetSRID(ST_MakePoint(l.x, l.y), 4326)::geography, "
            f"{buffer_m})::geometry AS g "
            f"FROM (VALUES {','.join(vals)}) AS l(x, y)")

    try:
        # 用全新连接规避同一后端会话内 GEOS union/simplify 退化 (见 execute_one_fresh)
        row = execute_one_fresh(f"""
            WITH e AS (
                {" UNION ALL ".join(parts)}
            )
            SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_Union(g), {simplify})) FROM e
        """, tuple(params))
    except Exception:
        return None
    if row and row[0]:
        try:
            g = _normalize_collection(json.loads(row[0]))
            if not g or g.get("type") not in ("Polygon", "MultiPolygon"):
                return None
            rings = ([g["coordinates"]] if g["type"] == "Polygon"
                      else [p for p in g["coordinates"]])
            areas = [_polygon_area_m2(r[0]) for r in rings]
            thr = max(min_area_m2, min_area_frac * max(areas))
            return _drop_small_parts(g, thr)
        except (ValueError, KeyError):
            return None
    return None


def reachable_polygon_geojson(coords, eps_deg=0.008, target=0.8, minpoints=3):
    """可达区域多边形 GeoJSON (兜底方案: 仅当边域重建失败时使用)

    多模式下可达区域不连续: 中心步行区 + 远郊站点周围的小块。
    做法: ST_ClusterDBSCAN 按空间聚类 (eps≈800m), 每簇求 ST_ConcaveHull,
    合并为 (Multi)Polygon。相比旧版 target 0.65 改为 0.8, 轮廓更平滑。

    - coords: [(lng, lat), ...] 可达路网节点
    - eps_deg: 聚类半径 (0.008 ≈ 800m)
    - target: ConcaveHull target_percent
    """
    if not coords or len(coords) < 3:
        return None
    lngs = [float(c[0]) for c in coords]
    lats = [float(c[1]) for c in coords]
    try:
        rows = execute_query("""
            WITH pts AS (
                SELECT lng, lat,
                       ST_ClusterDBSCAN(ST_SetSRID(ST_MakePoint(lng, lat), 4326), %s, %s) OVER () AS cid
                FROM unnest(%s::float[], %s::float[]) AS t(lng, lat)
            )
            SELECT cid, array_agg(lng), array_agg(lat)
            FROM pts WHERE cid IS NOT NULL GROUP BY cid
        """, (eps_deg, minpoints, lngs, lats))
        polys = []
        for cid, clng, clat in rows:
            if len(clng) < 3:
                continue
            row = execute_one("""
                SELECT ST_AsGeoJSON(
                    ST_SimplifyPreserveTopology(
                        ST_ConcaveHull(ST_Collect(ST_SetSRID(ST_MakePoint(lng, lat), 4326)), %s, true),
                        %s
                    )
                )
                FROM unnest(%s::float[], %s::float[]) AS t(lng, lat)
            """, (target, 0.00005, clng, clat))
            if row and row[0]:
                polys.append(json.loads(row[0]))
        if polys:
            if len(polys) == 1:
                return _drop_small_parts(polys[0], 1000)
            rings = []
            for p in polys:
                if p.get("type") == "Polygon":
                    rings.append(p["coordinates"])
                elif p.get("type") == "MultiPolygon":
                    rings.extend(p["coordinates"])
            g = {"type": "MultiPolygon", "coordinates": rings}
            return _drop_small_parts(g, 1000)
    except Exception:
        pass
    return None


class WalkLayer(TransportLayer):
    speed_kmh = 5.0
    mode_name = "walk"

    # 使用的可达列 (hefei_roads.{ok_column} 布尔列)
    ok_column = "walk_ok"
    # 是否尊重单行道 (步行不需要)
    directed = False
    # POI 挂接记录的模式 (骑行复用步行挂接, 因骑行网络 ⊂ 步行网络)
    poi_mode = "walk"

    # ── 边集 SQL: pgRouting 在每个查询里动态过滤道路类型 ────────
    def _edge_sql(self, swap: bool = False) -> str:
        """返回该模式可走边的 (id, source, target, cost, reverse_cost) 查询
        swap=True 时交换 source/target → 反算 (求"哪些起点能到达目标")"""
        s, t = ("target", "source") if swap else ("source", "target")
        return f"""
            SELECT id, {s} AS source, {t} AS target, cost, reverse_cost FROM hefei_roads
            WHERE cost > 0 AND {self.ok_column}
        """

    # ── 坐标吸附: 找到最近的可走路网节点 ────────────────────────
    # 注意: hefei_roads_vertices_pgr 列 x=纬度, y=经度 (rebuild_topo 的 y AS x, x AS y 所致),
    #       故 SELECT 用 v.y AS lng, v.x AS lat 保证输出 lng/lat 正确
    def snap_origin(self, lat: float, lng: float) -> dict:
        """单节点吸附: KNN 查最近 1 个可走节点"""
        row = execute_one("""
            SELECT v.id, v.y AS lng, v.x AS lat,
                   ST_Distance(
                       ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                       v.geometry::geography
                   ) as dist_m
            FROM hefei_roads_vertices_pgr v
            JOIN hefei_roads r ON r.source = v.id OR r.target = v.id
            WHERE r.{ok_column}
            ORDER BY ST_SetSRID(ST_MakePoint(%s, %s), 4326) <-> v.geometry
            LIMIT 1
        """.format(ok_column=self.ok_column), (lng, lat, lng, lat))
        if row:
            return {"id": row[0], "lng": row[1], "lat": row[2], "distance_m": float(row[3])}
        return None

    # ── 多节点吸附: 坐标误差容错 ─────────────────────────────────
    def snap_origin_multi(self, lat: float, lng: float, radius_m: float = 150, max_nodes: int = 3) -> list:
        """多节点吸附: 在指定半径内取最近的 N 个可走节点
        用于坐标精度不足时 (如 2 位小数 ≈ ±500m 误差) 的容错处理
        EXISTS 子查询代替 JOIN 避免同一节点因关联多条边而重复出现
        注意: ST_DWithin 用 geography(米) 保证圆半径不受纬度经度换算影响"""
        rows = execute_query("""
            SELECT v.id, v.y AS lng, v.x AS lat,
                   ST_Distance(
                       ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
                       v.geometry::geography
                   ) as dist_m
            FROM hefei_roads_vertices_pgr v
            WHERE EXISTS (
                SELECT 1 FROM hefei_roads r
                WHERE (r.source = v.id OR r.target = v.id)
                  AND r.{ok_column}
            )
              AND ST_DWithin(v.geometry::geography,
                             ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)
            ORDER BY ST_SetSRID(ST_MakePoint(%s, %s), 4326) <-> v.geometry
            LIMIT %s
        """.format(ok_column=self.ok_column), (lng, lat, lng, lat, radius_m, lng, lat, max_nodes))
        return [{"id": r[0], "lng": r[1], "lat": r[2], "distance_m": float(r[3])} for r in rows]

    # ── 时间→距离换算 ──────────────────────────────────────────
    def get_distance_budget(self, time_budget_min: float) -> float:
        """时间预算 (分钟) 转换为步行距离 (米)"""
        return time_budget_min * self.speed_kmh * 1000.0 / 60.0

    # ── 核心: 单起点 Dijkstra 可达节点 ──────────────────────────
    def reachable_nodes(self, start_node_id: int, time_budget_min: float) -> list:
        """pgRouting pgr_drivingDistance: 从单一路网节点出发做 Dijkstra
        edge_sql 作为参数传入 pgRouting, 在数据库端动态过滤道路类型
        返回所有 agg_cost <= distance_budget_m 的节点"""
        distance_budget_m = self.get_distance_budget(time_budget_min)
        rows = execute_query("""
            SELECT node, edge, agg_cost
            FROM pgr_drivingDistance(%s, %s, %s, directed := %s)
            WHERE agg_cost <= %s
            ORDER BY agg_cost
        """, (self._edge_sql(), start_node_id, distance_budget_m, self.directed, distance_budget_m))
        return [{"node": r[0], "edge": -1 if r[1] == -1 else r[1], "agg_cost": float(r[2])} for r in rows]

    # ── 单起点可达节点 (含坐标) ───────────────────────────────
    def reachable_nodes_with_coords(self, start_node_id: int, time_budget_min: float) -> list:
        """同上, 但 JOIN hefei_roads_vertices_pgr 获取每个节点的经纬度"""
        distance_budget_m = self.get_distance_budget(time_budget_min)
        rows = execute_query("""
            SELECT dd.node, dd.agg_cost, v.y AS lng, v.x AS lat
            FROM pgr_drivingDistance(%s, %s, %s, directed := %s) dd
            JOIN hefei_roads_vertices_pgr v ON v.id = dd.node
            WHERE dd.agg_cost <= %s
            ORDER BY dd.agg_cost
        """, (self._edge_sql(), start_node_id, distance_budget_m, self.directed, distance_budget_m))
        return [{"node": r[0], "agg_cost": float(r[1]), "lng": float(r[2]), "lat": float(r[3])} for r in rows]

    # ── POI 反查: 可达节点 → 可达 POI ───────────────────────────
    def reachable_pois(self, node_ids: list[int]) -> list:
        """通过 poi_road_nodes 表, 查找挂在可达路网节点上的 POI
        DISTINCT ON (p.id) 确保每 POI 只出现一次 (取 snap 距离最近那条)
        去重原因: 一个 POI 可能挂 1-5 个路网节点, 多个节点同时可达时旧逻辑会重复输出"""
        if not node_ids:
            return []
        node_id_placeholders = ','.join(['%s'] * len(node_ids))
        rows = execute_query(f"""
            SELECT DISTINCT ON (p.id)
                   p.id, p.name, p.category, p.sub_category,
                   p.address, p.opentime_today, p.rating, p.cost,
                   pn.node_id, pn.distance_m,
                   ST_X(p.geometry) as lng, ST_Y(p.geometry) as lat,
                   COALESCE(p.facility_id, p.id) as facility_id,
                   COALESCE(p.facility_name, p.name) as facility_name,
                   ST_X(COALESCE(f.geometry, p.geometry)) as fac_lng,
                   ST_Y(COALESCE(f.geometry, p.geometry)) as fac_lat,
                   COALESCE(f.sub_category, p.sub_category) as fac_sub_category
            FROM poi_road_nodes pn
            JOIN hefei_poi p ON p.id = pn.poi_id
            LEFT JOIN hefei_poi f ON f.id = p.facility_id
            WHERE pn.mode = %s
              AND pn.node_id IN ({node_id_placeholders})
            ORDER BY p.id, pn.distance_m ASC
        """, (self.poi_mode, *node_ids))
        return [{
            "id": r[0], "name": r[1], "category": r[2], "sub_category": r[3],
            "address": r[4], "opentime_today": r[5], "rating": r[6], "cost": r[7],
            "node_id": r[8], "distance_m": float(r[9]),
            "lng": float(r[10]), "lat": float(r[11]),
            "facility_id": r[12], "facility_name": r[13],
            "fac_lng": float(r[14]), "fac_lat": float(r[15]),
            "fac_sub_category": r[16],
        } for r in rows]

    # ── 一体化: 多起点吸附 + Dijkstra + POI 查询 ──────────────────
    def compute_reachability(self, lat: float, lng: float, time_budget_min: float,
                             snap_radius_m: float = 150, snap_max_nodes: int = 1) -> dict:
        """端到端的可达性计算 (test_walk.py / API 调用入口)

        流程:
          1. 多起点吸附: 在起点 radius 米内找 max_nodes 个可走节点
          2. 多起点 Dijkstra: pgr_drivingDistance 支持 ARRAY 起点,
             一次查询返回所有起点的可达集
          3. GROUP BY node, MIN(agg_cost): 同一节点被多个起点覆盖时取最优路径
          4. POI 反查 + 去重

        pgr_drivingDistance(start_vids => ARRAY[...]) 的多起点语法:
          pgRouting 内部对每个起点运行 Dijkstra, 返回统一的 (node, agg_cost) 结果集
          相比多次单起点查询, 减少了网络 IO 和 Python 端合并开销
        """
        distance_budget_m = self.get_distance_budget(time_budget_min)

        candidates, snap_radius_used = adaptive_snap(self, lat, lng, snap_radius_m, snap_max_nodes)
        if not candidates:
            return None

        start_ids = [c['id'] for c in candidates]
        # Dijkstra 用全新连接规避复用连接退化 (execute_query_fresh)
        rows = execute_query_fresh("""
            SELECT dd.node, dd.edge, dd.agg_cost
            FROM pgr_drivingDistance(%s, %s, %s, directed := %s) dd
            WHERE dd.agg_cost <= %s
        """, (self._edge_sql(), start_ids, distance_budget_m, self.directed, distance_budget_m))

        if not rows:
            return None

        # 聚合节点最优成本 + 收集可达边 (多边形用)
        node_cost = {}
        edges = set()
        for node, edge, cost in rows:
            if node not in node_cost or cost < node_cost[node]:
                node_cost[node] = float(cost)
            if edge is not None and edge >= 0:
                edges.add(edge)

        phs = ','.join(['%s'] * len(node_cost))
        coord_rows = execute_query(f"""
            SELECT id, y AS lng, x AS lat FROM hefei_roads_vertices_pgr WHERE id IN ({phs})
        """, tuple(node_cost.keys()))
        coord = {r[0]: (float(r[1]), float(r[2])) for r in coord_rows}
        nodes = [{"node": nid, "agg_cost": node_cost[nid],
                  "lng": coord[nid][0], "lat": coord[nid][1]}
                 for nid in sorted(node_cost, key=lambda k: node_cost[k]) if nid in coord]

        node_ids = [n['node'] for n in nodes]
        pois = self.reachable_pois(node_ids)

        # 等时圈真实边界: 可达路段 buffer 重建 (主), 节点凹包兜底
        #  - 边集用"预算内可遍历边", 圈更丰满且不越界
        #  - 可达 POI 点位各 buffer 30m, 保证"可达"的设施都落在圈内
        seed_lines = [(lng, lat, c['lng'], c['lat']) for c in candidates]
        all_edges = _edges_within_nodes(node_ids, self.ok_column,
                                        node_cost=node_cost, budget=distance_budget_m,
                                        edge_cost_sql="r.cost") or list(edges)
        seed_points = [(p['lng'], p['lat']) for p in pois[:1200]]
        polygon = reachable_polygon_from_edges(all_edges, seed_lines=seed_lines,
                                               seed_points=seed_points) or \
                  reachable_polygon_geojson([(n['lng'], n['lat']) for n in nodes])

        return {
            "origin": {"lat": lat, "lng": lng},
            "snap_candidates": candidates,
            "snap_radius_m": snap_radius_used,
            "time_budget_min": time_budget_min,
            "distance_budget_m": round(distance_budget_m, 1),
            "reachable_nodes_count": len(nodes),
            "reachable_nodes": nodes,
            "polygon": polygon,
            "reachable_pois_count": len(pois),
            "pois": pois,
        }

    # ── 等时圈 GeoJSON 生成 ────────────────────────────────────
    def get_edge_geojson(self, start_node_id: int, time_budget_min: float) -> dict:
        """从 Dijkstra 结果中提取所有经过的边, 转为 GeoJSON FeatureCollection
        PostgreSQL json_build_object 在数据库端完成序列化, 避免 Python 端大量几何对象转换"""
        distance_budget_m = self.get_distance_budget(time_budget_min)
        row = execute_one("""
            SELECT json_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(json_agg(
                    json_build_object(
                        'type', 'Feature',
                        'geometry', ST_AsGeoJSON(r.geometry)::json,
                        'properties', json_build_object(
                            'id', r.id, 'name', r.name, 'highway', r.highway,
                            'cost', dd.cost, 'agg_cost', dd.agg_cost
                        )
                    )
                ), '[]'::json)
            )
            FROM pgr_drivingDistance(%s, %s, %s, directed := %s) dd
            JOIN hefei_roads r ON r.id = dd.edge
            WHERE dd.agg_cost <= %s
        """, (self._edge_sql(), start_node_id, distance_budget_m, self.directed, distance_budget_m))
        return row[0] if row else {"type": "FeatureCollection", "features": []}
