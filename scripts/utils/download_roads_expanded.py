"""重新下载扩大版路网，覆盖全部地铁站"""
import osmnx as ox, time
import geopandas as gpd
from sqlalchemy import create_engine, text

DB_URL = 'postgresql://postgres:admin@localhost:5432/city_life_circle'
engine = create_engine(DB_URL)

# 新 bbox: 覆盖全部地铁站(+0.01° margin)
bbox = (117.07, 31.68, 117.50, 32.07)
print(f"下载路网 bbox: {bbox} (覆盖所有地铁站)")

ox.settings.timeout = 600
G = ox.graph_from_bbox(bbox=bbox, network_type='all')
nodes, edges = ox.graph_to_gdfs(G, nodes=True)
print(f"节点: {len(nodes)} 边: {len(edges)}")

edges = edges.reset_index()
nodes = nodes.reset_index()

# 删旧表 + 导入
with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS hefei_roads CASCADE"))
    conn.execute(text("DROP TABLE IF EXISTS hefei_nodes CASCADE"))
    conn.execute(text("DROP TABLE IF EXISTS hefei_roads_vertices_pgr CASCADE"))
    conn.commit()

edges.to_postgis('hefei_roads', engine, if_exists='replace', index=False)
nodes.to_postgis('hefei_nodes', engine, if_exists='replace', index=False)
print("导入 PostGIS 完成")
