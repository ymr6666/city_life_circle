"""
骑行可达性引擎 (CycleLayer)

基于 WalkLayer 复用同一套吸附/可达/POI 反查逻辑, 差异:
  1. ok_column = cycle_ok   (在 walk 基础上排除 steps 与步行天桥)
  2. speed_kmh = 15.0
  3. directed = True, 且对 oneway 路段 reverse_cost = -1 (禁逆行)

单行道编码说明 (osmnx MultiDiGraph):
  - 双向路: 表里两条记录 (reversed False/True), 各代表一个方向, 直接可用
  - 单向路: 一条记录 (oneway='True', reversed='False'), 需 reverse_cost=-1 禁逆行
  注: 合肥部分单行道允许非机动车双向 (OSM oneway:bicycle 字段已抓取到
  hefei_roads.oneway_bicycle), 如需更精细可在此覆盖:
    WHERE oneway_bicycle NOT IN ('no', ...)  则允许该段双向骑行
"""
from .walk_layer import WalkLayer
from services.database import execute_query


class CycleLayer(WalkLayer):
    speed_kmh = 15.0
    mode_name = "cycle"
    ok_column = "cycle_ok"
    directed = True
    poi_mode = "walk"  # 复用步行 POI 挂接 (骑行网络 ⊂ 步行网络)

    def _edge_sql(self, swap: bool = False) -> str:
        """骑行边: 尊重单行道, oneway 路段禁逆行
        swap=True 时交换 source/target (反算用)"""
        s, t = ("target", "source") if swap else ("source", "target")
        return f"""
            SELECT id, {s} AS source, {t} AS target, cost,
                   CASE WHEN oneway LIKE '%True%' AND COALESCE(reversed,'') != 'True'
                        THEN -1 ELSE reverse_cost END AS reverse_cost
            FROM hefei_roads
            WHERE cost > 0 AND {self.ok_column}
        """
