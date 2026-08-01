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
from services.database import execute_query, execute_one


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
    def _edge_sql(self) -> str:
        """返回该模式可走边的 (id, source, target, cost, reverse_cost) 查询"""
        return f"""
            SELECT id, source, target, cost, reverse_cost FROM hefei_roads
            WHERE cost > 0 AND {self.ok_column}
        """

    # ── 坐标吸附: 找到最近的可走路网节点 ────────────────────────
    def snap_origin(self, lat: float, lng: float) -> dict:
        """单节点吸附: KNN 查最近 1 个可走节点"""
        row = execute_one("""
            SELECT v.id, v.x, v.y,
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
        EXISTS 子查询代替 JOIN 避免同一节点因关联多条边而重复出现"""
        radius_deg = radius_m / 111000.0
        rows = execute_query("""
            SELECT v.id, v.x, v.y,
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
              AND ST_DWithin(v.geometry, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s)
            ORDER BY ST_SetSRID(ST_MakePoint(%s, %s), 4326) <-> v.geometry
            LIMIT %s
        """.format(ok_column=self.ok_column), (lng, lat, lng, lat, radius_deg, lng, lat, max_nodes))
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
            SELECT dd.node, dd.agg_cost, v.x, v.y
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
                   ST_X(p.geometry) as lng, ST_Y(p.geometry) as lat
            FROM poi_road_nodes pn
            JOIN hefei_poi p ON p.id = pn.poi_id
            WHERE pn.mode = %s
              AND pn.node_id IN ({node_id_placeholders})
            ORDER BY p.id, pn.distance_m ASC
        """, (self.poi_mode, *node_ids))
        return [{
            "id": r[0], "name": r[1], "category": r[2], "sub_category": r[3],
            "address": r[4], "opentime_today": r[5], "rating": r[6], "cost": r[7],
            "node_id": r[8], "distance_m": float(r[9]),
            "lng": float(r[10]), "lat": float(r[11])
        } for r in rows]

    # ── 一体化: 多起点吸附 + Dijkstra + POI 查询 ──────────────────
    def compute_reachability(self, lat: float, lng: float, time_budget_min: float,
                             snap_radius_m: float = 150, snap_max_nodes: int = 3) -> dict:
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

        candidates = self.snap_origin_multi(lat, lng, snap_radius_m, snap_max_nodes)
        if not candidates:
            return None

        start_ids = [c['id'] for c in candidates]
        rows = execute_query("""
            SELECT dd.node, MIN(dd.agg_cost) as agg_cost, v.x, v.y
            FROM pgr_drivingDistance(%s, %s, %s, directed := %s) dd
            JOIN hefei_roads_vertices_pgr v ON v.id = dd.node
            WHERE dd.agg_cost <= %s
            GROUP BY dd.node, v.x, v.y
            ORDER BY agg_cost
        """, (self._edge_sql(), start_ids, distance_budget_m, self.directed, distance_budget_m))

        nodes = [{"node": r[0], "agg_cost": float(r[1]), "lng": float(r[2]), "lat": float(r[3])} for r in rows]

        node_ids = [n['node'] for n in nodes]
        pois = self.reachable_pois(node_ids)

        return {
            "origin": {"lat": lat, "lng": lng},
            "snap_candidates": candidates,
            "time_budget_min": time_budget_min,
            "distance_budget_m": round(distance_budget_m, 1),
            "reachable_nodes_count": len(nodes),
            "reachable_nodes": nodes,
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
