import geopandas as gpd
from sqlalchemy import create_engine
import os

DB_URL = 'postgresql://postgres:admin@localhost:5432/city_life_circle'
engine = create_engine(DB_URL)
out_dir = r'E:\city-life-circle'

# 从 PostGIS 读取路网
sql = "SELECT id, u, v, highway, name, length, geometry FROM hefei_roads"
gdf = gpd.read_postgis(sql, engine, geom_col='geometry')

# 导出为 GeoPackage（ArcGIS 直接打开）
path = os.path.join(out_dir, 'hefei_roads.gpkg')
gdf.to_file(path, driver='GPKG', layer='roads')
print(f'已导出: {path} ({len(gdf)} 条路段)')

# 也导出一个简化的 GeoJSON 备用
gdf_small = gdf.head(500)
path2 = os.path.join(out_dir, 'hefei_roads_sample.geojson')
gdf_small.to_file(path2, driver='GeoJSON')
print(f'已导出: {path2} (前500条)')

# 导出节点
sql2 = "SELECT id, osm_id, x, y, geometry FROM hefei_roads_vertices_pgr"
nodes = gpd.read_postgis(sql2, engine, geom_col='geometry')
path3 = os.path.join(out_dir, 'hefei_roads_nodes.gpkg')
nodes.to_file(path3, driver='GPKG', layer='nodes')
print(f'已导出: {path3} ({len(nodes)} 个节点)')
