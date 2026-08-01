"""
出行模式 → 可达性引擎 工厂

支持的 mode 字符串 (大小写不敏感, 用 '+' 连接):
  单独道路:  'walk' | 'cycle' | 'drive'
  道路+公交: 'walk+metro' | 'walk+bus' | 'walk+metro+bus'
  也可简写别名: 'metro' = 'walk+metro', 'bus' = 'walk+bus'

规则:
  - 恰好 0 或 1 个道路模式 (walk/cycle/drive), 缺省为 walk
  - 0~n 个公交模式 (metro/bus)
  - 示例: 'cycle+metro' 可行 (骑行接驳地铁), 但成本/POI 反查按骑行模式
"""
from .walk_layer import WalkLayer
from .cycle_layer import CycleLayer
from .drive_layer import DriveLayer
from .transit_layer import TransitLayer

_ROAD_CLASSES = {"walk": WalkLayer, "cycle": CycleLayer, "drive": DriveLayer}
_TRANSIT_NAMES = {"metro", "bus"}


def parse_mode(mode: str):
    """解析 mode → (road_mode, transit_modes)。非法输入抛 ValueError。"""
    if not mode:
        return "walk", ()
    toks = [t.strip().lower() for t in str(mode).replace("_", "+").split("+")]
    road = [t for t in toks if t in _ROAD_CLASSES]
    transit = [t for t in toks if t in _TRANSIT_NAMES]
    unknown = [t for t in toks if t not in _ROAD_CLASSES and t not in _TRANSIT_NAMES]
    if unknown:
        raise ValueError(f"未知出行模式: {unknown} (支持 walk/cycle/drive/metro/bus 及 '+' 组合)")
    if len(road) > 1:
        raise ValueError(f"道路模式只能选一个 (walk/cycle/drive), 收到: {road}")
    road_mode = road[0] if road else "walk"
    return road_mode, tuple(transit)


def build_layer(mode: str) -> TransitLayer:
    """按 mode 构建引擎层"""
    road_mode, transit_modes = parse_mode(mode)
    if not transit_modes:
        return _ROAD_CLASSES[road_mode]()
    return TransitLayer(road_mode=road_mode, transit_modes=transit_modes,
                        mode_name=f"{road_mode}+{'+'.join(transit_modes)}")
