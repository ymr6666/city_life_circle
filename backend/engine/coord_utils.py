"""WGS84 <-> GCJ-02 坐标转换"""
import math

PI = math.pi
X_PI = PI * 3000.0 / 180.0
A = 6378245.0  # 长半轴
EE = 0.00669342162296594323  # 偏心率平方


def _out_of_china(lng, lat):
    return lng < 72.004 or lng > 137.8347 or lat < 0.8293 or lat > 55.8271


def _transform_lat(lng, lat):
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat \
          + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * PI) + 20.0 * math.sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * PI) + 40.0 * math.sin(lat / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * PI) + 320 * math.sin(lat * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng, lat):
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng \
          + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * PI) + 20.0 * math.sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * PI) + 40.0 * math.sin(lng / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * PI) + 300.0 * math.sin(lng / 30.0 * PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng, lat):
    """WGS84 -> GCJ-02"""
    if _out_of_china(lng, lat):
        return lng, lat
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * PI
    magic = math.sin(rad_lat)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * PI)
    d_lng = (d_lng * 180.0) / (A / sqrt_magic * math.cos(rad_lat) * PI)
    return lng + d_lng, lat + d_lat


def gcj02_to_wgs84(lng, lat):
    """GCJ-02 -> WGS84 (迭代法)"""
    if _out_of_china(lng, lat):
        return lng, lat
    # 二分迭代反解
    wgs_lng, wgs_lat = lng, lat
    for _ in range(10):
        g_lng, g_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
        d_lng = g_lng - lng
        d_lat = g_lat - lat
        if abs(d_lng) < 1e-9 and abs(d_lat) < 1e-9:
            break
        wgs_lng -= d_lng
        wgs_lat -= d_lat
    return wgs_lng, wgs_lat


def bd09_to_wgs84(lng, lat):
    """BD-09 -> WGS84"""
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * X_PI)
    gcj_lng = z * math.cos(theta)
    gcj_lat = z * math.sin(theta)
    return gcj02_to_wgs84(gcj_lng, gcj_lat)
