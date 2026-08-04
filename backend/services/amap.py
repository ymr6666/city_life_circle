"""高德 Web 服务客户端 (搜索 POI 2.0: /v5/place/text)

用途: 地名(关键词)→经纬度 地理编码, 供 /api/geocode 使用。

坐标系约定:
  高德 Web 服务返回的坐标均为 GCJ-02 (火星坐标)。本项目内部统一使用 WGS84
  (路网/地铁/公交/POI 全部 WGS84, 见 docs/对话交接_20260802.md 关键决策 #1),
  因此本模块在「高德响应边界处」做一次性 GCJ-02 → WGS84 转换:
    - 转换只发生在数据入口 (每次 geocode 查询), 存储与下游计算均用 WGS84;
    - 全流程杜绝 GCJ↔WGS 往返转换, 避免迭代反解带来的累积误差;
    - 若未来前端使用高德 JSAPI (GCJ-02 地图), 应采用 WGS84→GCJ02 单向正向
      转换 (误差可控) 做显示, 而非来回转换。

AMAP_KEY 解析优先级: 环境变量 AMAP_KEY → scripts/crawlers/config.py (gitignore 中的真实 key)。
"""
import os
from pathlib import Path

import requests

from engine.coord_utils import gcj02_to_wgs84

AMAP_PLACE_TEXT_URL = "https://restapi.amap.com/v5/place/text"
DEFAULT_REGION = "合肥"
MAX_PAGE_SIZE = 25


def _resolve_key():
    """解析高德 key: 环境变量优先, 其次读取 scripts/crawlers/config.py (含真实 key, gitignore)。

    用 importlib 按独立模块名加载, 避免与已加载的 backend/config.py (`from config import ...`)
    在 sys.modules 中冲突导致取错模块。
    """
    key = os.environ.get("AMAP_KEY")
    if key:
        return key.strip()
    try:
        cfg_file = Path(__file__).resolve().parents[2] / "scripts" / "crawlers" / "config.py"
        if cfg_file.is_file():
            import importlib.util
            spec = importlib.util.spec_from_file_location("_amap_crawlers_config", cfg_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            key = getattr(mod, "AMAP_KEY", None)
            if key and "YOUR" not in key:
                return key.strip()
    except Exception:
        pass
    return None


def _parse_location(location):
    """高德 location 字段: "lng,lat" → (lng, lat) 浮点数; 解析失败返回 (None, None)"""
    try:
        lng_str, lat_str = location.split(",")
        return float(lng_str), float(lat_str)
    except (ValueError, AttributeError):
        return None, None


def geocode_keywords(keywords, region=DEFAULT_REGION, limit=5, types=None):
    """搜索 POI 2.0 地名(关键词)查询, 返回 WGS84 坐标列表。

    Args:
        keywords: 地名/地址关键词 (如 "政务区万象城"、"望江西路"、"合肥南站")
        region:   限定城市, 默认 "合肥" (配合 city_limit=true 缩小范围)
        limit:    最多返回条数 (1~20)
        types:    可选高德 typecode 过滤 (如 "060100" 购物中心)

    Returns:
        [{name, address, typecode, type, adcode, city, district, lng, lat}]
        坐标已由 GCJ-02 单向转换为 WGS84。
    """
    key = _resolve_key()
    if not key:
        raise RuntimeError("高德 AMAP_KEY 未配置: 请设置环境变量 AMAP_KEY 或 scripts/crawlers/config.py")

    page_size = max(1, min(int(limit), MAX_PAGE_SIZE))
    params = {
        "key": key,
        "keywords": keywords,
        "region": region,
        "city_limit": "true",
        "page_size": page_size,
        "page_num": 1,
    }
    if types:
        params["types"] = types

    resp = requests.get(AMAP_PLACE_TEXT_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "1":
        raise RuntimeError(f"高德搜索失败: {data.get('info', 'unknown error')}")

    results = []
    for p in data.get("pois") or []:
        lng, lat = _parse_location(p.get("location", ""))
        if lng is None or lat is None:
            continue
        wlng, wlat = gcj02_to_wgs84(lng, lat)
        results.append({
            "name": p.get("name", ""),
            "address": p.get("address", ""),
            "typecode": p.get("typecode", ""),
            "type": p.get("type", ""),
            "adcode": p.get("adcode", ""),
            "city": p.get("cityname") or p.get("city") or "",
            "district": p.get("adname") or p.get("district") or "",
            "lng": round(wlng, 6),
            "lat": round(wlat, 6),
        })
    return results
