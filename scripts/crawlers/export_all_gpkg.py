"""导出地铁 + POI 数据为 GeoPackage (ArcGIS Pro 原生格式)"""
import geopandas as gpd
from sqlalchemy import create_engine
import os

DB_URL = 'postgresql://postgres:admin@localhost:5432/city_life_circle'
engine = create_engine(DB_URL)

out = {
    "data/合肥地铁": [
        ("hefei_metro_stations", "SELECT id, name, line_name, is_transfer, geometry FROM hefei_metro_stations"),
        ("hefei_metro_edges", "SELECT id, line_name, station_from, station_to, distance_km, time_min, geometry FROM hefei_metro_edges"),
    ],
    "data/合肥POI": [
        ("hefei_poi", "SELECT id, name, category, sub_category, address, geometry FROM hefei_poi"),
    ],
}

for folder, tables in out.items():
    os.makedirs(folder, exist_ok=True)
    for name, sql in tables:
        path = f"{folder}/{name}.gpkg"
        gdf = gpd.read_postgis(sql, engine, geom_col='geometry')
        gdf.to_file(path, driver='GPKG', layer=name.replace('hefei_',''))
        print(f"{path}: {len(gdf)} features")

print("Done!")
