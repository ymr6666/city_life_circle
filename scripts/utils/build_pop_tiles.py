# -*- coding: utf-8 -*-
"""PopSE_China2020_100m 人口栅格 → 合肥 XYZ 瓦片 (Web Mercator EPSG:3857)

用途: 前端将人口密度作为"底图图层"直接叠加, 缩放任意级别都无需重新计算。

流程:
  1. 把 Albers 投影的全国栅格 重投影 + 裁剪 → 合肥 EPSG:3857 中间 GeoTIFF
  2. 按 XYZ (z/x/y) 切成 PNG 瓦片, 人口值域 → 黄橙红连续色阶, 0 值透明

产物: cache/pop_tiles/{z}/{x}/{y}.png
用法: python build_pop_tiles.py [zmin] [zmax]
依赖: rasterio / numpy / PIL
"""
import os
import math
import sys
from pathlib import Path

# 覆盖系统级 PROJ_LIB (指向 PostGIS 旧版 proj.db) — 必须在导入 rasterio 前
_PREFIX = Path(sys.prefix)
_R_PROJ = _PREFIX / "Lib" / "site-packages" / "rasterio" / "proj_data"
if _R_PROJ.exists():
    os.environ["PROJ_DATA"] = str(_R_PROJ)
    os.environ["PROJ_LIB"] = str(_R_PROJ)

import rasterio
import numpy as np
from rasterio.warp import transform_bounds, reproject, Resampling
from rasterio.windows import from_bounds

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "cache"
# 合肥 bbox (WGS84, 含外扩)
HEFEI_BBOX = (116.95, 31.55, 117.62, 32.20)
# 全国人口栅格 (PopSE 2020 100m)
POP_TIF = Path(r"C:\Users\yummy\Downloads\PopSE_China2020_100m\PopSE_China2020_100m.tif")
# 中间产物 (EPSG:3857)
INTERMEDIATE = CACHE_DIR / "hefei_pop_3857.tif"
TILE_DIR = CACHE_DIR / "pop_tiles"

TILE_SIZE = 256
WORLD = 20037508.342789244  # Web Mercator 半幅

# 人口色阶 (每 90m 格人口数) → 黄橙红
RAMP_STOPS = (
    (0, (255, 255, 255), 0),
    (2, (255, 247, 224), 210),
    (8, (255, 237, 160), 215),
    (20, (254, 217, 118), 215),
    (50, (254, 178, 76), 220),
    (120, (253, 141, 60), 220),
    (250, (240, 59, 32), 225),
    (500, (189, 0, 38), 225),
)


def build_intermediate():
    if INTERMEDIATE.exists():
        return
    with rasterio.open(POP_TIF) as src:
        dst_bounds = transform_bounds("EPSG:4326", "EPSG:3857", *HEFEI_BBOX)
        res = 90.0
        width = int((dst_bounds[2] - dst_bounds[0]) / res) + 1
        height = int((dst_bounds[3] - dst_bounds[1]) / res) + 1
        dst_transform = rasterio.transform.from_origin(
            dst_bounds[0], dst_bounds[3], res, res)
        dst = np.zeros((height, width), dtype="float32")
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:3857",
            resampling=Resampling.average,
        )
        dst[np.abs(dst) > 100000] = 0
        dst = np.clip(dst, 0, 1000).astype("float32")
        profile = src.profile.copy()
        profile.update(driver="GTiff", crs="EPSG:3857",
                       transform=dst_transform, width=width, height=height,
                       dtype="float32", nodata=0)
        INTERMEDIATE.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(INTERMEDIATE, "w", **profile) as dst_ds:
            dst_ds.write(dst, 1)
        print(f"intermediate: {INTERMEDIATE} ({width}x{height})")


def colorize(data):
    """float32 → RGBA uint8 (0 值透明, 其余按色阶)"""
    out = np.zeros((*data.shape, 4), dtype="uint8")
    x = np.clip(data, 0, RAMP_STOPS[-1][0])
    levels = np.array([s[0] for s in RAMP_STOPS])
    for i in range(len(RAMP_STOPS) - 1):
        lo, hi = RAMP_STOPS[i], RAMP_STOPS[i + 1]
        m = (x >= lo[0]) & (x < hi[0])
        if hi[0] == lo[0]:
            continue
        k = ((x[m] - lo[0]) / (hi[0] - lo[0]))[:, None]
        rgb = np.array(lo[1], dtype=float) + (np.array(hi[1], dtype=float) - np.array(lo[1], dtype=float)) * k
        a = lo[2] + (hi[2] - lo[2]) * k[:, 0]
        out[m] = np.concatenate([rgb, a[:, None]], axis=1)
    # 最高档之上取最深色
    m = x >= RAMP_STOPS[-1][0]
    out[m] = (*RAMP_STOPS[-1][1], RAMP_STOPS[-1][2])
    out[(data <= 0)] = (0, 0, 0, 0)
    return out


def tile_bounds(z, x, y):
    n = 2 ** z
    w = 2 * WORLD / n
    left = -WORLD + x * w
    top = WORLD - y * w
    return left, top - w, left + w, top


def generate_tiles(zmin, zmax):
    import PIL.Image
    from PIL import Image
    with rasterio.open(INTERMEDIATE) as ds:
        dst_bounds = (ds.bounds.left, ds.bounds.bottom, ds.bounds.right, ds.bounds.top)
        for z in range(zmin, zmax + 1):
            n = 2 ** z
            x0 = int(math.floor((dst_bounds[0] + WORLD) / (2 * WORLD) * n))
            x1 = int(math.floor((dst_bounds[2] + WORLD) / (2 * WORLD) * n))
            y0 = int(math.floor((WORLD - dst_bounds[3]) / (2 * WORLD) * n))
            y1 = int(math.floor((WORLD - dst_bounds[1]) / (2 * WORLD) * n))
            count = 0
            for xt in range(x0, x1 + 1):
                for yt in range(y0, y1 + 1):
                    left, bottom, right, top = tile_bounds(z, xt, yt)
                    window = from_bounds(left, bottom, right, top, ds.transform)
                    data = ds.read(1, window=window, out_shape=(TILE_SIZE, TILE_SIZE),
                                   resampling=Resampling.bilinear)
                    rgba = colorize(data)
                    img = Image.fromarray(rgba, "RGBA")
                    d = TILE_DIR / str(z) / str(xt)
                    d.mkdir(parents=True, exist_ok=True)
                    img.save(d / f"{yt}.png", "PNG")
                    count += 1
            print(f"z{z}: {count} tiles")


def main():
    zmin = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    zmax = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    build_intermediate()
    generate_tiles(zmin, zmax)
    print("done")


if __name__ == "__main__":
    main()
