"""导出为 Shapefile (.shp)，仅读取数据库，不影响数据"""
import geopandas as gpd
from sqlalchemy import create_engine
import os

DB_URL = 'postgresql://postgres:admin@localhost:5432/city_life_circle'
engine = create_engine(DB_URL)

tasks = [
    ("data/合肥路网/hefei_roads",        "SELECT id, highway, name, length, geometry FROM hefei_roads"),
    ("data/合肥路网/hefei_roads_nodes",  "SELECT id, osm_id, geometry FROM hefei_roads_vertices_pgr"),
    ("data/合肥POI/hefei_poi",           "SELECT id, name, category, sub_category, address, geometry FROM hefei_poi"),
    ("data/合肥地铁/hefei_metro_stations","SELECT id, name, line_name, is_transfer, geometry FROM hefei_metro_stations"),
    ("data/合肥地铁/hefei_metro_edges",   "SELECT id, line_name, distance_km, time_min, geometry FROM hefei_metro_edges"),
]

for path, sql in tasks:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    gdf = gpd.read_postgis(sql, engine, geom_col='geometry')
    # 列名超过10字符的截断 (Shapefile 限制)
    gdf.columns = [c[:10] for c in gdf.columns]
    gdf.to_file(f"{path}.shp", driver='ESRI Shapefile', encoding='utf-8')
    print(f"{path}.shp: {len(gdf)} features")

print("Done!")
