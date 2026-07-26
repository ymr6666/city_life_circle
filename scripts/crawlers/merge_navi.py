"""合并: 有引导点的用引导点，无引导点的用主坐标"""
import geopandas as gpd, pandas as pd
from shapely.geometry import Point
from sqlalchemy import create_engine

engine = create_engine('postgresql://postgres:admin@localhost:5432/city_life_circle')

df = pd.read_sql("""
    SELECT id, name, category, sub_category, address, tel,
           entr_location, exit_location, business_area, rating, cost,
           parking_type, opentime_today, alias, navi_poiid, photos,
           ST_X(geometry) as poi_lng, ST_Y(geometry) as poi_lat
    FROM hefei_poi
""", engine)

def entry_point(row):
    """有引导点用引导点, 超500m偏的还用主坐标"""
    entr = row.get("entr_location")
    if entr and "," in str(entr):
        try:
            elng, elat = str(entr).split(",")
            elng, elat = float(elng), float(elat)
            # 计算距离
            from math import radians, sin, cos, sqrt, asin
            dlon, dlat = radians(elng - row["poi_lng"]), radians(elat - row["poi_lat"])
            a = sin(dlat/2)**2 + cos(radians(row["poi_lat"])) * cos(radians(elat)) * sin(dlon/2)**2
            dist = 6371000 * 2 * asin(sqrt(a))
            if dist < 500:
                return elng, elat
        except:
            pass
    return row["poi_lng"], row["poi_lat"]

coords = df.apply(entry_point, axis=1)
df["entry_lng"] = coords.apply(lambda x: x[0])
df["entry_lat"] = coords.apply(lambda x: x[1])
df["geometry"] = [Point(lng, lat) for lng, lat in coords]
df["has_navi"] = df.apply(
    lambda r: r["entr_location"] is not None and str(r["entr_location"]) != "" and r["entry_lng"] != r["poi_lng"], axis=1)

gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")

# 保留完整字段名
cols_out = [c for c in gdf.columns if c not in ("geometry","entry_lng","entry_lat","poi_lng","poi_lat")
            or c in ("name","category","sub_category","entry_lng","entry_lat","has_navi","geometry")]
gdf = gdf[list(set(cols_out) | {"entry_lng","entry_lat","has_navi","geometry"})]

# SHP 列名限制 10 字符
name_map = {
    "entry_lng": "entry_lng", "entry_lat": "entry_lat",
    "has_navi": "has_navi", "sub_categ": "sub_categ",
    "business_": "business_", "parking_t": "parking_t",
    "opentime_t": "opentime_", "entr_locat": "entr_locat",
    "exit_locat": "exit_locat", "navi_poiid": "navi_poiid",
    "poi_lng": "poi_lng", "poi_lat": "poi_lat",
}
gdf_short = gdf.copy()
gdf_short.columns = [c[:10] for c in gdf_short.columns]

# 导出
gdf_short.to_file("E:/city-life-circle/shp/hefei_poi_merged.shp", driver="ESRI Shapefile", encoding="utf-8")
print(f"hefei_poi_merged.shp: {len(gdf_short)} points")
print(f"  has_navi=True: {gdf['has_navi'].sum()} (引导点作为坐标)")
print(f"  has_navi=False: {(~gdf['has_navi']).sum()} (主坐标兜底)")

# 更新数据库: 添加 entry_lng/entry_lat 列供以后使用
import psycopg2
conn = psycopg2.connect(host='localhost',port=5432,dbname='city_life_circle',user='postgres',password='admin')
cur = conn.cursor()
cur.execute("ALTER TABLE hefei_poi ADD COLUMN IF NOT EXISTS entry_lng DOUBLE PRECISION")
cur.execute("ALTER TABLE hefei_poi ADD COLUMN IF NOT EXISTS entry_lat DOUBLE PRECISION")
for _, row in gdf.iterrows():
    cur.execute("UPDATE hefei_poi SET entry_lng=%s, entry_lat=%s WHERE id=%s",
                (row["entry_lng"], row["entry_lat"], row["id"]))
conn.commit()
cur.close()
conn.close()
print("entry_lng/entry_lat written to DB")
