"""可达性结果 LRU 缓存 (缓解 transit 模式重查询慢)

compute_reachability 对 (坐标, 模式, 时间) 是确定性的, 但 walk+metro+bus
单次可达 10-25s。用进程内 LRU 缓存相同查询, 重复请求秒回。
"""
from functools import lru_cache
from .factory import build_layer


@lru_cache(maxsize=128)
def _cached_reachability(lat_q, lng_q, mode, time_budget_min, snap_radius_m, snap_max_nodes):
    layer = build_layer(mode)
    return layer.compute_reachability(lat_q, lng_q, time_budget_min, snap_radius_m,
                                      snap_max_nodes)


def reachability_cached(lat, lng, mode, time_budget_min, snap_radius_m=150,
                        snap_max_nodes=1):
    """带缓存的等时圈计算入口。坐标取 4 位小数 (≈11m) 归并, 时间/半径/起点数取整。"""
    lat_q = round(float(lat), 4)
    lng_q = round(float(lng), 4)
    time_q = int(round(float(time_budget_min)))
    snap_q = int(round(float(snap_radius_m)))
    node_q = max(1, min(int(snap_max_nodes), 5))
    return _cached_reachability(lat_q, lng_q, mode, time_q, snap_q, node_q)


def cache_info():
    return _cached_reachability.cache_info()
