"""导出挂接后的POI数据到 ArcGIS GPKG"""
import geopandas as gpd
from sqlalchemy import create_engine
from shapely.geometry import Point

engine = create_engine('postgresql://postgres:admin@localhost:5432/city_life_circle')

OUT = 'E:/city-life-circle/shp/snapped_pois.gpkg'

# ── Layer 1: POI 主数据 ──
df = gpd.read_postgis("""
    SELECT p.id, p.name, p.category, p.sub_category,
           p.canonical_poi_id,
           p.entr_location,
           ST_X(p.geometry) as poi_lng, ST_Y(p.geometry) as poi_lat,
           (p.entr_location IS NOT NULL AND p.entr_location != '') as has_entry,
           p.geometry
    FROM hefei_poi p
""", engine, geom_col='geometry')

# Parse entry coordinates for display
def parse_entry(s):
    try:
        lng, lat = s.split(',')
        return float(lng), float(lat)
    except:
        return None, None

coords = [parse_entry(s) for s in df['entr_location']]
df['entry_lng'] = [c[0] if c[0] else 0 for c in coords]
df['entry_lat'] = [c[1] if c[1] else 0 for c in coords]

gdf_poi = gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')
gdf_poi.to_file(OUT, layer='poi_data', driver='GPKG')
print(f"Layer poi_data: {len(gdf_poi)} POIs")

# ── Layer 2: 挂接点 (Poi-to-Road snaps) ──
df_snap = gpd.read_postgis("""
    SELECT pn.poi_id, pn.node_id, pn.mode, pn.distance_m,
           p.name as poi_name, p.category,
           v.geometry
    FROM poi_road_nodes pn
    JOIN hefei_roads_vertices_pgr v ON v.id = pn.node_id
    JOIN hefei_poi p ON p.id = pn.poi_id
""", engine, geom_col='geometry')

gdf_snap = gpd.GeoDataFrame(df_snap, geometry='geometry', crs='EPSG:4326')
gdf_snap.to_file(OUT, layer='snap_points', driver='GPKG')
modes = gdf_snap['mode'].value_counts().to_dict()
print(f"Layer snap_points: {len(gdf_snap)} points (walk={modes.get('walk',0)} drive={modes.get('drive',0)})")

# ── Layer 3: 高德入口引导点 ──
entry_rows = []
for _, r in df.iterrows():
    e = parse_entry(r['entr_location'])
    if e[0] is not None:
        entry_rows.append({
            'poi_id': r['id'], 'poi_name': r['name'], 'category': r['category'],
            'geometry': Point(e[0], e[1])
        })

gdf_entry = gpd.GeoDataFrame(entry_rows, geometry='geometry', crs='EPSG:4326')
gdf_entry.to_file(OUT, layer='entry_points', driver='GPKG')
print(f"Layer entry_points: {len(gdf_entry)} entry points")

print(f"\nDone: {OUT}")
print("ArcGIS Pro 三层:")
print("  poi_data    - POI主坐标(紫色)")
print("  entry_points - 高德入口引导点(绿色)")
print("  snap_points  - 路网挂接点(红色walk / 蓝色drive)")
