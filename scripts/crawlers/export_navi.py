"""导出导航引导点 (entr_location) 为 SHP"""
import geopandas as gpd, pandas as pd
from sqlalchemy import create_engine

engine = create_engine('postgresql://postgres:admin@localhost:5432/city_life_circle')

# 从数据库读取有引导点的POI
df = pd.read_sql("""
    SELECT name, category, sub_category,
           entr_location, exit_location, navi_poiid, geometry
    FROM hefei_poi
    WHERE entr_location IS NOT NULL AND entr_location != ''
""", engine)

# 解析 entr_location "lng,lat" → Point geometry
from shapely.geometry import Point
def parse_point(s):
    try:
        lng, lat = s.split(",")
        return Point(float(lng), float(lat))
    except:
        return None

entr_geom = df["entr_location"].apply(parse_point)
df_gdf = gpd.GeoDataFrame(df.drop(columns="geometry"), geometry=entr_geom, crs="EPSG:4326")
df_gdf.columns = [c[:10] for c in df_gdf.columns]

# 导出
df_gdf.to_file("E:/city-life-circle/shp/hefei_poi_entr.shp", driver="ESRI Shapefile", encoding="utf-8")
print(f"导出入口引导点: {len(df_gdf)} 个 → shp/hefei_poi_entr.shp")

# 也导出没有引导点的POI主坐标(对比用)
# 也导出没有引导点的POI主坐标
gdf2 = gpd.read_postgis("""
    SELECT name, category, sub_category, geometry
    FROM hefei_poi WHERE entr_location IS NULL OR entr_location = ''
""", engine, geom_col="geometry")
gdf2.columns = [c[:10] for c in gdf2.columns]
gdf2.to_file("E:/city-life-circle/shp/hefei_poi_noentr.shp", driver="ESRI Shapefile", encoding="utf-8")
print(f"无引导点 POI: {len(gdf2)} 个 → shp/hefei_poi_noentr.shp")
