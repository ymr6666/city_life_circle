import osmnx as ox
import geopandas as gpd
from sqlalchemy import create_engine

DB_URL = 'postgresql://postgres:admin@localhost:5432/city_life_circle'
engine = create_engine(DB_URL)

# 下载合肥路网
print('下载合肥路网...')
G = ox.graph_from_bbox(bbox=(117.15, 31.75, 117.4, 31.9), network_type='all')
nodes, edges = ox.graph_to_gdfs(G, nodes=True)

print(f'节点: {len(nodes)}, 边: {len(edges)}')

# 重置索引，保留 u,v,key 作为普通列
edges = edges.reset_index()
nodes = nodes.reset_index()

# 导入 edges
edges.to_postgis('hefei_roads', engine, if_exists='replace', index=False)
print('路网表 hefei_roads 导入完成')

# 导入 nodes
nodes.to_postgis('hefei_nodes', engine, if_exists='replace', index=False)
print('节点表 hefei_nodes 导入完成')
