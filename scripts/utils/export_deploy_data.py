# -*- coding: utf-8 -*-
"""导出当前数据库为部署包参考数据 (GeoPackage + POI CSV) → deploy/data/exports

与旧导出脚本的区别: 直接读当前库 (WGS84, 21 类 21k+ POI), 英文路径, 供评委用
ArcGIS / QGIS / Excel 查看数据全貌。仅读取数据库, 不影响线上数据。
"""
import os
import geopandas as gpd
from sqlalchemy import create_engine

DB_URL = 'postgresql://postgres:admin@localhost:5432/city_life_circle'
engine = create_engine(DB_URL)

OUT = os.path.join(os.path.dirname(__file__), '..', '..', 'deploy', 'data', 'exports')
os.makedirs(OUT, exist_ok=True)

# (文件名, 表/查询, 是否也导 csv)
TASKS = [
    ("hefei_poi.gpkg",
     "SELECT id, name, category, sub_category, address, facility_id, facility_name, "
     "ST_X(geometry) AS lng, ST_Y(geometry) AS lat, geometry FROM hefei_poi", True),
    ("hefei_roads.gpkg",
     "SELECT id, osmid, highway, name, ref, length, oneway, bridge_class, "
     "walk_ok, cycle_ok, drive_ok, cost, geometry FROM hefei_roads", False),
    ("hefei_roads_nodes.gpkg",
     "SELECT id, osm_id, y AS lng, x AS lat, geometry FROM hefei_roads_vertices_pgr", False),
    ("hefei_metro_stations.gpkg",
     "SELECT id, name, line_name, is_transfer, ST_X(geometry) AS lng, ST_Y(geometry) AS lat, "
     "geometry FROM hefei_metro_stations", True),
    ("hefei_metro_edges.gpkg",
     "SELECT id, line_name, station_from, station_to, distance_km, time_min, geometry "
     "FROM hefei_metro_edges", False),
    ("hefei_bus_stops.gpkg",
     "SELECT id, stop_no, name, adcode, lng, lat, geometry FROM hefei_bus_stops", True),
    ("hefei_bus_lines.gpkg",
     "SELECT id, name, type, start_stop, end_stop, distance_km, geometry FROM hefei_bus_lines",
     False),
    ("hefei_pop_grid.gpkg",
     "SELECT id, population, ST_X(geometry) AS lng, ST_Y(geometry) AS lat, geometry "
     "FROM hefei_pop_grid", False),
]

for fname, sql, to_csv in TASKS:
    try:
        gdf = gpd.read_postgis(sql, engine, geom_col='geometry')
    except Exception as e:
        print(f"[skip] {fname}: {e}")
        continue
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    path = os.path.join(OUT, fname)
    gdf.to_file(path, driver='GPKG', layer=fname.split('.')[0].replace('hefei_', ''))
    print(f"{fname}: {len(gdf)} features")
    if to_csv:
        csv_path = os.path.join(OUT, fname.replace('.gpkg', '.csv'))
        cols = [c for c in gdf.columns if c != 'geometry']
        gdf[cols].to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"  -> {fname.replace('.gpkg', '.csv')}")

print("Done!")
