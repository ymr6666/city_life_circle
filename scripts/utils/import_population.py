# -*- coding: utf-8 -*-
"""人口栅格 → hefei_pop_grid 点表 (WGS84)

读取全国 100m 人口栅格 (PopSE_China2020_100m.tif, Albers/Krasovsky 投影),
裁剪合肥 bbox, 重投影到 WGS84, 每个非零像元落成一点:
  hefei_pop_grid (id serial, population int, geometry Point 4326)

用法:
  python import_population.py [--tif PATH] [--pad 0.02]
"""
import os
import sys
import time

# 指向 rasterio 自带 PROJ 数据库, 避免与 PostGIS 的旧 proj.db 冲突
_PROJ_DATA = r'C:\Users\yummy\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\rasterio\proj_data'
os.environ['PROJ_DATA'] = _PROJ_DATA
os.environ['PROJ_LIB'] = _PROJ_DATA

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawlers'))
from config import DB_CONFIG

import numpy as np
import psycopg2
from psycopg2.extras import execute_values
import rasterio
from rasterio.warp import transform_bounds, transform

SRC = r'C:\Users\yummy\Downloads\PopSE_China2020_100m\PopSE_China2020_100m.tif'
HEFEI_BBOX = (117.07, 31.68, 117.50, 32.07)   # minlng, minlat, maxlng, maxlat


def main():
    tif = SRC
    pad = 0.02
    if '--tif' in sys.argv:
        tif = sys.argv[sys.argv.index('--tif') + 1]
    if '--pad' in sys.argv:
        pad = float(sys.argv[sys.argv.index('--pad') + 1])

    bbox = (HEFEI_BBOX[0] - pad, HEFEI_BBOX[1] - pad,
            HEFEI_BBOX[2] + pad, HEFEI_BBOX[3] + pad)

    t0 = time.time()
    with rasterio.open(tif) as ds:
        src_crs = ds.crs
        # WGS84 bbox → Albers 窗口
        a = transform_bounds('EPSG:4326', src_crs, *bbox, densify_pts=21)
        win = rasterio.windows.from_bounds(*a, transform=ds.transform)
        # 取整窗口
        # 取整窗口 (已在栅格范围内)
        win = win.round_offsets()
        data = ds.read(1, window=win)
        src_tf = ds.window_transform(win)
        nodata = ds.nodata

    print(f'读取窗口 {data.shape}  (Albers), 耗时 {time.time()-t0:.1f}s')

    # 所有像元中心 (Albers) → 一次向量变换到 WGS84
    rows, cols = data.shape
    ys, xs = np.mgrid[0:rows, 0:cols].astype('float64')
    xs = xs * src_tf.a + src_tf.c + src_tf.a / 2
    ys = ys * src_tf.e + src_tf.f + src_tf.e / 2
    lngs, lats = transform(src_crs, 'EPSG:4326', xs.ravel(), ys.ravel())

    valid = (data.ravel() != nodata) & (data.ravel() > 0)
    pop_vals = data.ravel()[valid]
    lngs_v = np.array(lngs)[valid]
    lats_v = np.array(lats)[valid]
    print(f'非零像元: {len(pop_vals)} ({len(pop_vals)/(rows*cols)*100:.1f}%)')
    print(f'总人口: {int(pop_vals.sum())}  均值(非零): {pop_vals.mean():.1f}')

    # 写入数据库
    conn = psycopg2.connect(**DB_CONFIG)
    conn.set_client_encoding('UTF8')
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hefei_pop_grid (
            id BIGSERIAL PRIMARY KEY,
            population INTEGER,
            geometry GEOMETRY(Point, 4326)
        )
    """)
    cur.execute("TRUNCATE hefei_pop_grid")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hefei_pop_grid_geom ON hefei_pop_grid USING GIST(geometry)")
    conn.commit()

    t1 = time.time()
    batch = [(int(p), f'SRID=4326;POINT({lng:.6f} {lat:.6f})')
             for lng, lat, p in zip(lngs_v, lats_v, pop_vals)]
    execute_values(cur, """
        INSERT INTO hefei_pop_grid (population, geometry)
        VALUES %s
    """, batch, page_size=5000, template="(%s, ST_GeomFromEWKT(%s))")
    conn.commit()
    print(f'写入 {len(batch)} 点, 耗时 {time.time()-t1:.1f}s')

    cur.execute("SELECT count(*), coalesce(sum(population),0) FROM hefei_pop_grid")
    n, pop = cur.fetchone()
    print(f'\n表 hefei_pop_grid: {n} 点, 总人口 {pop}')
    cur.close()
    conn.close()
    print('完成!')


if __name__ == "__main__":
    main()
