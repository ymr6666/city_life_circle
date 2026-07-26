"""建 POI 表 (扩展字段: business/navi/photos)"""
import psycopg2
from config import DB_CONFIG

SQL = """
DROP TABLE IF EXISTS hefei_poi CASCADE;
CREATE TABLE hefei_poi (
    id SERIAL PRIMARY KEY,
    name TEXT,
    category TEXT,
    sub_category TEXT,         -- typecode
    address TEXT,
    tel TEXT,
    -- business 字段
    business_area TEXT,
    rating TEXT,
    cost TEXT,
    parking_type TEXT,
    opentime_today TEXT,
    opentime_week TEXT,
    tag TEXT,
    alias TEXT,
    -- navi 字段
    entr_location TEXT,        -- 入口坐标 "lng,lat"
    exit_location TEXT,        -- 出口坐标
    navi_poiid TEXT,
    -- photos
    photos TEXT,               -- JSON 数组 ["url1","url2"]
    geometry GEOMETRY(Point, 4326)
);

CREATE INDEX idx_poi_category ON hefei_poi(category);
CREATE INDEX idx_poi_subcat ON hefei_poi(sub_category);
CREATE INDEX idx_poi_geom ON hefei_poi USING GIST(geometry);
"""

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()
cur.execute(SQL)
conn.commit()
cur.close()
conn.close()
print("hefei_poi 重建完成 (含 business/navi 字段)")
