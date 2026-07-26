"""建表脚本：POI 表 + 地铁表 + 地铁边表"""
import psycopg2
from config import DB_CONFIG

SQL = """
CREATE TABLE IF NOT EXISTS hefei_poi (
    id SERIAL PRIMARY KEY,
    name TEXT,
    category TEXT,
    sub_category TEXT,
    address TEXT,
    tel TEXT,
    geometry GEOMETRY(Point, 4326)
);

CREATE INDEX IF NOT EXISTS idx_poi_category ON hefei_poi(category);
CREATE INDEX IF NOT EXISTS idx_poi_geom ON hefei_poi USING GIST(geometry);

CREATE TABLE IF NOT EXISTS hefei_metro_stations (
    id SERIAL PRIMARY KEY,
    name TEXT,
    line_name TEXT,
    is_transfer BOOLEAN DEFAULT FALSE,
    sequence INT,
    geometry GEOMETRY(Point, 4326)
);

CREATE INDEX IF NOT EXISTS idx_metro_stations_geom ON hefei_metro_stations USING GIST(geometry);
CREATE INDEX IF NOT EXISTS idx_metro_stations_line ON hefei_metro_stations(line_name);

CREATE TABLE IF NOT EXISTS hefei_metro_edges (
    id SERIAL PRIMARY KEY,
    line_name TEXT,
    station_from INT REFERENCES hefei_metro_stations(id),
    station_to INT REFERENCES hefei_metro_stations(id),
    distance_km DOUBLE PRECISION,
    time_min DOUBLE PRECISION,
    geometry GEOMETRY(LineString, 4326)
);

CREATE INDEX IF NOT EXISTS idx_metro_edges_line ON hefei_metro_edges(line_name);
CREATE INDEX IF NOT EXISTS idx_metro_edges_geom ON hefei_metro_edges USING GIST(geometry);
"""

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()
cur.execute(SQL)
conn.commit()
cur.close()
conn.close()
print("表创建完成: hefei_poi, hefei_metro_stations, hefei_metro_edges")
