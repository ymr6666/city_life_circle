"""
地铁+步行多模式可达性引擎 (MetroLayer)

基于通用 TransitLayer: road_mode=walk, transit_modes=('metro',)
输出保持向后兼容字段:
  reachable_road_nodes_count / reachable_road_nodes
  reachable_metro_stations_count / reachable_metro_stations
  reachable_pois_count / pois
"""
from .transit_layer import TransitLayer


class MetroLayer(TransitLayer):
    speed_kmh = 5.0
    mode_name = "metro"
    road_mode = "walk"
    transit_modes = ("metro",)
    poi_mode = "walk"

    def __init__(self):
        super().__init__(road_mode="walk", transit_modes=("metro",), mode_name="metro")
