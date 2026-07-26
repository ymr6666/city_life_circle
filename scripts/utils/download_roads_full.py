import osmnx as ox
import geopandas as gpd
from sqlalchemy import create_engine

DB_URL = 'postgresql://postgres:admin@localhost:5432/city_life_circle'
engine = create_engine(DB_URL)

# 合肥市区范围（覆盖蜀山、包河、瑶海、庐阳、政务、滨湖等）
bbox = (117.1, 31.7, 117.5, 32.0)  # left, bottom, right, top

print(f'下载路网范围: {bbox}')
print('包含步行 + 行车所有道路类型...')

G = ox.graph_from_bbox(bbox=bbox, network_type='all')
nodes, edges = ox.graph_to_gdfs(G, nodes=True)

print(f'节点: {len(nodes)}, 边: {len(edges)}')

# 重置索引
edges = edges.reset_index()
nodes = nodes.reset_index()

# 先删旧表
from sqlalchemy import text
with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS hefei_roads CASCADE"))
    conn.execute(text("DROP TABLE IF EXISTS hefei_nodes CASCADE"))
    conn.execute(text("DROP TABLE IF EXISTS hefei_roads_vertices_pgr CASCADE"))
    conn.commit()

edges.to_postgis('hefei_roads', engine, if_exists='replace', index=False)
nodes.to_postgis('hefei_nodes', engine, if_exists='replace', index=False)
print('导入 PostGIS 完成')
