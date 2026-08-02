"""
通用多模式可达性引擎 (TransitLayer)

支持全部使用方式:
  单独道路模式:  walk / cycle / drive
  道路+公交耦合: walk+metro, walk+bus, walk+metro+bus
  (road_mode ∈ {walk,cycle,drive}, transit_modes ⊆ {metro,bus})

核心算法: 构建统一耦合图 (道路边 + 公交边 + 换乘边), 成本统一为时间(分钟),
         单次 pgr_drivingDistance 求解。

图结构:
  路网节点 ID:       1 ~ 42,785      (hefei_roads_vertices_pgr)
  地铁站节点 ID:     100,000 + station_id
  公交站节点 ID:     200,000 + stop_no
  道路边:   hefei_roads, cost_min = 长度(m) * 60 / (模式速度 m/h)
  地铁边:   hefei_metro_edges, cost_min = time_min
  公交边:   hefei_bus_line_stops 相邻站连线, cost_min = 直线距离 / 公交速度
  换乘边:   metro_station_road_nodes / bus_stop_road_nodes, 0 成本

单次 Dijkstra 即可得出: 步行/骑行/驾车可达的所有路网节点 + 可达公交站/地铁站
+ 出站后再可达的节点。公交数据未就绪时 raise ValueError 给出明确提示。
"""
from .base_layer import TransportLayer
from .walk_layer import WalkLayer
from .cycle_layer import CycleLayer
from .drive_layer import DriveLayer
from services.database import execute_query, execute_one
from config import (WALK_SPEED_KMH, CYCLE_SPEED_KMH,
                    DRIVE_SPEED_KMH, BUS_SPEED_KMH)

# 公交模式节点 ID 偏移 (避免与路网节点 1~42785 冲突)
METRO_OFFSET = 100000
BUS_OFFSET = 200000

# 各模式边 id 偏移 (仅用于区分 UNION ALL 中的边, 结果可忽略)
_METRO_EDGE_OFF = 300000
_BUS_EDGE_OFF = 400000
_METRO_XFER_OFF = 500000
_BUS_XFER_OFF = 600000

ROAD_SPEED_KMH = {
    "walk": WALK_SPEED_KMH,
    "cycle": CYCLE_SPEED_KMH,
    "drive": DRIVE_SPEED_KMH,
}


def _table_has_data(table: str) -> bool:
    try:
        return bool(execute_one(f"SELECT EXISTS(SELECT 1 FROM {table})")[0])
    except Exception:
        return False


class TransitLayer(TransportLayer):
    speed_kmh = WALK_SPEED_KMH          # 道路接驳速度 (步行)
    mode_name = "transit"
    road_mode = "walk"                  # 道路模式: walk/cycle/drive
    transit_modes = ()                  # 公交模式子集: metro/bus
    poi_mode = "walk"

    def __init__(self, road_mode: str = "walk", transit_modes=(), mode_name: str = None):
        self.road_mode = road_mode
        self.transit_modes = tuple(transit_modes)
        if mode_name:
            self.mode_name = mode_name
        self.speed_kmh = ROAD_SPEED_KMH.get(road_mode, WALK_SPEED_KMH)
        # POI 反查模式: drive 用 drive 挂接, 其余复用 walk 挂接
        self.poi_mode = "drive" if road_mode == "drive" else "walk"
        self.road_layer = self._build_road_layer()

    def _build_road_layer(self):
        if self.road_mode == "cycle":
            return CycleLayer()
        if self.road_mode == "drive":
            return DriveLayer()
        return WalkLayer()

    # ── 数据就绪检查 ─────────────────────────────────────────
    def _check_data(self):
        missing = []
        if "metro" in self.transit_modes:
            for t in ("hefei_metro_edges", "hefei_metro_stations", "metro_station_road_nodes"):
                if not _table_has_data(t):
                    missing.append(t)
        if "bus" in self.transit_modes:
            for t in ("hefei_bus_stops", "hefei_bus_line_stops", "bus_stop_road_nodes"):
                if not _table_has_data(t):
                    missing.append(t)
        if missing:
            raise ValueError(
                f"公交数据未就绪, 缺少表: {', '.join(missing)}。"
                "请先完成: python crawl_bus.py --load 然后 python snap_bus_stops.py")

    # ── 边集 SQL ─────────────────────────────────────────────
    def _road_edge_sql(self) -> str:
        """道路边: 长度转分钟 (cycle/drive 尊重单行道)"""
        speed_mh = ROAD_SPEED_KMH[self.road_mode] * 1000.0
        ok_col = f"{self.road_mode}_ok"
        if self.road_mode == "walk":
            return f"""
                SELECT id, source, target,
                       cost * 60.0 / {speed_mh} AS cost,
                       reverse_cost * 60.0 / {speed_mh} AS reverse_cost
                FROM hefei_roads
                WHERE cost > 0 AND {ok_col}
            """
        return f"""
            SELECT id, source, target,
                   cost * 60.0 / {speed_mh} AS cost,
                   CASE WHEN oneway LIKE '%True%' AND COALESCE(reversed,'') != 'True'
                        THEN -1 ELSE reverse_cost * 60.0 / {speed_mh} END AS reverse_cost
            FROM hefei_roads
            WHERE cost > 0 AND {ok_col}
        """

    def _metro_edge_sql(self) -> str:
        return f"""
            SELECT {_METRO_EDGE_OFF} + id AS id,
                   {METRO_OFFSET} + station_from AS source,
                   {METRO_OFFSET} + station_to AS target,
                   time_min, time_min
            FROM hefei_metro_edges
        """

    def _metro_transfer_sql(self) -> str:
        return f"""
            SELECT {_METRO_XFER_OFF} + id AS id,
                   node_id, {METRO_OFFSET} + station_id, 0.0, 0.0
            FROM metro_station_road_nodes
        """

    def _bus_edge_sql(self) -> str:
        """公交边: 同一线路同一方向相邻站连线
        时间优先用 route_pos_m 差 (沿线路里程), 缺失时用几何直线距离 / 公交速度
        注意: UNION ALL 中不能直接跟 WITH, 故将 CTE 包在子查询内"""
        bus_speed_mh = BUS_SPEED_KMH * 1000.0
        return f"""
            SELECT {_BUS_EDGE_OFF} + ROW_NUMBER() OVER (ORDER BY be.line_id) AS id,
                   {BUS_OFFSET} + be.a_no AS source,
                   {BUS_OFFSET} + be.b_no AS target,
                   be.dist_m * 60.0 / {bus_speed_mh} AS cost,
                   be.dist_m * 60.0 / {bus_speed_mh} AS reverse_cost
            FROM (
                WITH ordered AS (
                    SELECT ls.line_id, ls.direction, s.stop_no, ls.route_pos_m,
                           ST_X(s.geometry) AS x, ST_Y(s.geometry) AS y,
                           ROW_NUMBER() OVER (PARTITION BY ls.line_id, ls.direction
                                              ORDER BY ls.sequence) AS rn
                    FROM hefei_bus_line_stops ls
                    JOIN hefei_bus_stops s ON s.id = ls.stop_id
                ), pairs AS (
                    SELECT a.line_id, a.stop_no AS a_no, b.stop_no AS b_no,
                           a.x AS ax, a.y AS ay, b.x AS bx, b.y AS by,
                           abs(COALESCE(a.route_pos_m, 0) - COALESCE(b.route_pos_m, 0)) AS dpos
                    FROM ordered a
                    JOIN ordered b ON a.line_id = b.line_id AND a.direction = b.direction
                                  AND b.rn = a.rn + 1
                )
                SELECT p.line_id, p.a_no, p.b_no,
                       CASE WHEN p.dpos > 0
                            THEN p.dpos
                            ELSE ST_Distance(ST_SetSRID(ST_MakePoint(p.ax, p.ay), 4326)::geography,
                                             ST_SetSRID(ST_MakePoint(p.bx, p.by), 4326)::geography)
                       END AS dist_m
                FROM pairs p
            ) AS be
        """

    def _bus_transfer_sql(self) -> str:
        return f"""
            SELECT {_BUS_XFER_OFF} + id AS id,
                   node_id, {BUS_OFFSET} + stop_no, 0.0, 0.0
            FROM bus_stop_road_nodes
        """

    def _build_combined_edge_sql(self) -> str:
        parts = [self._road_edge_sql()]
        if "metro" in self.transit_modes:
            parts += [self._metro_edge_sql(), self._metro_transfer_sql()]
        if "bus" in self.transit_modes:
            parts += [self._bus_edge_sql(), self._bus_transfer_sql()]
        return "\nUNION ALL\n".join(parts)

    # ── 基础接口 (委托道路层) ────────────────────────────────
    def snap_origin(self, lat: float, lng: float) -> dict:
        return self.road_layer.snap_origin(lat, lng)

    def snap_origin_multi(self, lat, lng, radius_m=150, max_nodes=3):
        return self.road_layer.snap_origin_multi(lat, lng, radius_m, max_nodes)

    def reachable_nodes(self, start_node_id: int, time_budget_min: float) -> list:
        return self.road_layer.reachable_nodes(start_node_id, time_budget_min)

    def reachable_pois(self, node_ids: list[int]) -> list:
        return self.road_layer.reachable_pois(node_ids)

    def get_distance_budget(self, time_budget_min: float) -> float:
        return time_budget_min * self.speed_kmh * 1000.0 / 60.0

    # ── 详情查询 ─────────────────────────────────────────────
    def _road_node_details(self, agg: dict) -> list:
        road = {nid: c for nid, c in agg.items() if nid < METRO_OFFSET}
        if not road:
            return []
        phs = ','.join(['%s'] * len(road))
        rows = execute_query(
            f"SELECT id, x, y FROM hefei_roads_vertices_pgr WHERE id IN ({phs})",
            tuple(road.keys()))
        coord = {r[0]: (float(r[1]), float(r[2])) for r in rows}
        return [{"node": nid, "agg_cost": c,
                 "lng": coord[nid][0], "lat": coord[nid][1]}
                for nid, c in sorted(road.items(), key=lambda kv: kv[1]) if nid in coord]

    def _metro_details(self, metro_ids: list, agg: dict) -> list:
        if not metro_ids:
            return []
        phs = ','.join(['%s'] * len(metro_ids))
        rows = execute_query(f"""
            SELECT id, name, line_name, is_transfer, ST_X(geometry), ST_Y(geometry)
            FROM hefei_metro_stations WHERE id IN ({phs})
        """, tuple(metro_ids))
        m = {r[0]: {"name": r[1], "line_name": r[2], "is_transfer": r[3],
                    "lng": float(r[4]), "lat": float(r[5])} for r in rows}
        return [{"id": sid,
                 "name": m[sid]["name"], "line_name": m[sid]["line_name"],
                 "is_transfer": m[sid]["is_transfer"],
                 "time_min": round(agg[METRO_OFFSET + sid], 2),
                 "lng": m[sid]["lng"], "lat": m[sid]["lat"]}
                for sid in metro_ids if sid in m]

    def _bus_details(self, stop_ids: list, agg: dict) -> list:
        if not stop_ids:
            return []
        phs = ','.join(['%s'] * len(stop_ids))
        rows = execute_query(f"""
            SELECT stop_no, name, ST_X(geometry), ST_Y(geometry)
            FROM hefei_bus_stops WHERE stop_no IN ({phs})
        """, tuple(stop_ids))
        m = {r[0]: (r[1], float(r[2]), float(r[3])) for r in rows}
        return [{"id": sid, "name": m[sid][0],
                 "time_min": round(agg[BUS_OFFSET + sid], 2),
                 "lng": m[sid][1], "lat": m[sid][2]}
                for sid in stop_ids if sid in m]

    # ── 端到端可达性计算 ─────────────────────────────────────
    def compute_reachability(self, lat: float, lng: float, time_budget_min: float,
                             snap_radius_m: float = 150, snap_max_nodes: int = 3) -> dict:
        """1. 吸附起点 → 2. 耦合图单次 Dijkstra → 3. 按节点偏移分离三类结果 → 4. POI 反查"""
        self._check_data()

        candidates = self.snap_origin_multi(lat, lng, snap_radius_m, snap_max_nodes)
        if not candidates:
            return None

        start_ids = [c['id'] for c in candidates]
        edge_sql = self._build_combined_edge_sql()

        # 道路模式为 walk 时方向无关; cycle/drive 需尊重单行道 (公交/换乘边本身双向)
        directed = self.road_mode != "walk"
        rows = execute_query("""
            SELECT dd.node, MIN(dd.agg_cost) as agg_cost
            FROM pgr_drivingDistance(%s, %s, %s, directed := %s) dd
            WHERE dd.agg_cost <= %s
            GROUP BY dd.node
            ORDER BY agg_cost
        """, (edge_sql, start_ids, time_budget_min, directed, time_budget_min))

        if not rows:
            return None

        agg = {}
        metro_ids = []
        bus_stop_ids = []
        for nid, cost in rows:
            agg[nid] = float(cost)
            if nid >= BUS_OFFSET:
                bus_stop_ids.append(nid - BUS_OFFSET)
            elif nid >= METRO_OFFSET:
                metro_ids.append(nid - METRO_OFFSET)

        road_nodes = self._road_node_details(agg)
        metro_stations = self._metro_details(metro_ids, agg) if "metro" in self.transit_modes else []
        bus_stops = self._bus_details(bus_stop_ids, agg) if "bus" in self.transit_modes else []

        road_node_ids = [n["node"] for n in road_nodes]
        pois = self.reachable_pois(road_node_ids)

        result = {
            "origin": {"lat": lat, "lng": lng},
            "snap_candidates": candidates,
            "time_budget_min": time_budget_min,
            "reachable_road_nodes_count": len(road_nodes),
            "reachable_road_nodes": road_nodes,
            "reachable_metro_stations_count": len(metro_stations),
            "reachable_metro_stations": metro_stations,
            "reachable_bus_stops_count": len(bus_stops),
            "reachable_bus_stops": bus_stops,
            "reachable_pois_count": len(pois),
            "pois": pois,
        }
        return result
