"""
公交+步行多模式可达性引擎 (BusLayer)

基于通用 TransitLayer: road_mode=walk, transit_modes=('bus',)
数据依赖: hefei_bus_stops / hefei_bus_line_stops / bus_stop_road_nodes
          (前两者由 crawl_bus.py --load 生成, 后者由 snap_bus_stops.py 生成)
数据未就绪时 compute_reachability 会抛出 ValueError 给出明确提示。
"""
from .transit_layer import TransitLayer


class BusLayer(TransitLayer):
    speed_kmh = 5.0
    mode_name = "bus"
    road_mode = "walk"
    transit_modes = ("bus",)
    poi_mode = "walk"

    def __init__(self):
        super().__init__(road_mode="walk", transit_modes=("bus",), mode_name="bus")


class WalkMetroBusLayer(TransitLayer):
    """步行 + 地铁 + 公交 全公交耦合"""
    speed_kmh = 5.0
    mode_name = "walk+metro+bus"
    road_mode = "walk"
    transit_modes = ("metro", "bus")
    poi_mode = "walk"

    def __init__(self):
        super().__init__(road_mode="walk", transit_modes=("metro", "bus"),
                         mode_name="walk+metro+bus")
