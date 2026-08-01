"""
驾车可达性引擎 (DriveLayer)

复用 CycleLayer 的方向感知逻辑 (directed + oneway 禁逆行), 差异:
  1. ok_column = drive_ok   (机动车可走的道路等级, 含 motorway/trunk 与桥梁/隧道)
  2. speed_kmh = 30.0
  3. poi_mode = 'drive'     (POI 挂接记录按驾车模式反查)

桥梁/立交说明:
  机动车必须能上桥过河、走快速路, 因此 drive_ok 不排除桥隧;
  "只能从匝道上下立交"由拓扑正确性保证 (高架与地面不共节点, 见 enrich_roads_tags 校验)。
"""
from .cycle_layer import CycleLayer


class DriveLayer(CycleLayer):
    speed_kmh = 30.0
    mode_name = "drive"
    ok_column = "drive_ok"
    poi_mode = "drive"
