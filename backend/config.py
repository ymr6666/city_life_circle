"""后端配置: 数据库连接 + 出行速度参数

所有值均可被环境变量覆盖 (部署/云服务器时不必改代码), 默认值为本地开发配置:
  CLC_DB_HOST / CLC_DB_PORT / CLC_DB_NAME / CLC_DB_USER / CLC_DB_PASSWORD
"""
import os


def _env(key, default):
    return os.environ.get(key, default)


DB_CONFIG = {
    "host": _env("CLC_DB_HOST", "localhost"),
    "port": int(_env("CLC_DB_PORT", "5432")),
    "dbname": _env("CLC_DB_NAME", "city_life_circle"),
    "user": _env("CLC_DB_USER", "postgres"),
    "password": _env("CLC_DB_PASSWORD", "admin"),
}

# 步行速度 (km/h)
WALK_SPEED_KMH = float(_env("CLC_WALK_KMH", "5.0"))

# 骑行速度 (km/h)
CYCLE_SPEED_KMH = float(_env("CLC_CYCLE_KMH", "15.0"))

# 驾车速度 (km/h)
DRIVE_SPEED_KMH = float(_env("CLC_DRIVE_KMH", "30.0"))

# 地铁速度 (km/h)
METRO_SPEED_KMH = float(_env("CLC_METRO_KMH", "35.0"))

# 公交速度 (km/h) —— 含进出站/停靠时间的平均车速
BUS_SPEED_KMH = float(_env("CLC_BUS_KMH", "20.0"))

# 合肥 bbox
HEFEI_BBOX = (117.07, 31.68, 117.50, 32.07)
