"""合肥地铁数据爬取 (OSM Overpass API)
获取地铁线路 route relations → 提取站点顺序 → 建 stations + edges 表
"""
import requests, time, psycopg2
from config import AMAP_KEY, DB_CONFIG

HEADERS = {"User-Agent": "city-life-circle/1.0 (student project)"}
OVER_URL = "https://overpass.kumi.systems/api/interpreter"
SLEEP = 0.5

# 合肥 bbox (扩展版，覆盖全部地铁)
BBOX = (117.07, 31.68, 117.50, 32.07)

conn = psycopg2.connect(**DB_CONFIG)
conn.set_client_encoding("UTF8")
cur = conn.cursor()


def overpass_query(query, timeout=60):
    for attempt in range(3):
        try:
            r = requests.post(OVER_URL, data={"data": query}, headers=HEADERS, timeout=timeout)
            return r.json()
        except Exception as e:
            print(f"  Retry {attempt+1}: {e}")
            time.sleep(5 * (attempt + 1))
    return None


# ========== Step 1: 获取所有地铁线路 route relations ==========
print("Step 1: 获取地铁线路...")
q1 = f"""[out:json][timeout:60];
rel({BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]})[route=subway];
out tags;
"""
data = overpass_query(q1)
if not data:
    print("  Overpass request failed!")
    exit(1)

# 解析线路信息: 去重(同一线路上行/下行只保留一条)
line_info = {}  # ref → {name, colour, relation_id}
for el in data["elements"]:
    tags = el.get("tags", {})
    ref = tags.get("ref", "")
    if not ref:
        continue
    if ref not in line_info:
        line_info[ref] = {
            "ref": ref,
            "name": tags.get("name", ""),
            "colour": tags.get("colour", ""),
            "relation_ids": [],
        }
    line_info[ref]["relation_ids"].append(el["id"])

for ref, info in sorted(line_info.items()):
    print(f"  Line {ref}: {info['name']} (colour={info['colour']}, {len(info['relation_ids'])} relations)")

# ========== Step 2: 逐线路取站点顺序 ==========
print("\nStep 2: 提取各线路站点顺序...")

all_stations = {}   # (name, lng, lat) → {osm_id, line_names, is_transfer}
line_stops = {}     # ref → [(name, lng, lat), ...]

for ref, info in sorted(line_info.items()):
    # 取第一条 relation（通常是最完整的那个方向）
    rel_id = info["relation_ids"][0]
    time.sleep(SLEEP)

    # 请求完整的 relation（包含 members）
    q2 = f"""[out:json][timeout:30];
rel({rel_id});
(._;>>;);
out geom;
"""
    data = overpass_query(q2, timeout=30)
    if not data:
        print(f"  Line {ref}: request failed, skipping")
        continue

    # 解析 member 站点（按顺序）
    elems = {el["id"]: el for el in data["elements"] if el["type"] == "node"}

    # 取 relation 对象
    rel_obj = None
    for el in data["elements"]:
        if el["type"] == "relation" and el["id"] == rel_id:
            rel_obj = el
            break
    if not rel_obj:
        print(f"  Line {ref}: relation not found in response")
        continue

    stops = []
    for member in rel_obj.get("members", []):
        if member.get("role") == "stop" and member["type"] == "node":
            node_id = member["ref"]
            if node_id in elems:
                node = elems[node_id]
                name = node.get("tags", {}).get("name", f"Station_{node_id}")
                lng = node.get("lon", 0)
                lat = node.get("lat", 0)
                stops.append((name, lng, lat))

    line_stops[ref] = stops
    print(f"  Line {ref}: {len(stops)} 站")

    # 加入全局站点集
    for name, lng, lat in stops:
        key = (name, round(lng, 5), round(lat, 5))
        if key in all_stations:
            all_stations[key]["line_names"].add(ref)
        else:
            all_stations[key] = {
                "name": name,
                "lng": lng,
                "lat": lat,
                "line_names": {ref},
            }

# 标记换乘站
for key, info in all_stations.items():
    info["is_transfer"] = len(info["line_names"]) > 1

print(f"\n总站点: {len(all_stations)}, 换乘站: {sum(1 for v in all_stations.values() if v['is_transfer'])}")

# ========== Step 3: 写入 PostGIS ==========
print("\nStep 3: 写入数据库...")

# 清空旧数据
cur.execute("DELETE FROM hefei_metro_edges")
cur.execute("DELETE FROM hefei_metro_stations")
conn.commit()

# 插入站点
station_map = {}  # key → db_id
for key, info in all_stations.items():
    cur.execute(
        """INSERT INTO hefei_metro_stations (name, line_name, is_transfer, sequence, geometry)
           VALUES (%s, %s, %s, 0, ST_SetSRID(ST_MakePoint(%s,%s), 4326)) RETURNING id""",
        (info["name"], "|".join(sorted(info["line_names"])),
         info["is_transfer"], info["lng"], info["lat"]),
    )
    sid = cur.fetchone()[0]
    station_map[key] = sid

conn.commit()
print(f"  站点入库: {len(station_map)}")

# 插入边: 每条线路上相邻站点连成边
edge_count = 0
for ref, stops in line_stops.items():
    for i in range(len(stops) - 1):
        name_a, lng_a, lat_a = stops[i]
        name_b, lng_b, lat_b = stops[i + 1]
        key_a = (name_a, round(lng_a, 5), round(lat_a, 5))
        key_b = (name_b, round(lng_b, 5), round(lat_b, 5))

        sid_a = station_map.get(key_a)
        sid_b = station_map.get(key_b)
        if sid_a is None or sid_b is None:
            continue

        # 距离 (km) 和 时间 (min) = 距离 / 35km/h * 60
        cur.execute(
            """SELECT ST_Distance(
                   ST_SetSRID(ST_MakePoint(%s,%s), 4326)::geography,
                   ST_SetSRID(ST_MakePoint(%s,%s), 4326)::geography
               ) / 1000.0""",
            (lng_a, lat_a, lng_b, lat_b),
        )
        dist_km = cur.fetchone()[0]
        time_min = dist_km / 35.0 * 60.0

        cur.execute(
            """INSERT INTO hefei_metro_edges
               (line_name, station_from, station_to, distance_km, time_min, geometry)
               VALUES (%s, %s, %s, %s, %s,
                       ST_SetSRID(ST_MakeLine(
                           ST_SetSRID(ST_MakePoint(%s,%s), 4326),
                           ST_SetSRID(ST_MakePoint(%s,%s), 4326)
                       ), 4326))""",
            (ref, sid_a, sid_b, round(dist_km, 3), round(time_min, 2),
             lng_a, lat_a, lng_b, lat_b),
        )
        edge_count += 1

conn.commit()

# ========== Step 4: 验证 ==========
print(f"  边入库: {edge_count}")
cur.execute("SELECT line_name, count(*) FROM hefei_metro_edges GROUP BY line_name ORDER BY line_name")
print("\n线路边统计:")
for r in cur.fetchall():
    print(f"  Line {r[0]}: {r[1]} edges")

cur.execute("SELECT line_name, count(*) FROM hefei_metro_stations GROUP BY line_name ORDER BY line_name")
print("\n线路站点统计:")
for r in cur.fetchall():
    print(f"  {r[0]:30s} {r[1]} stations")

cur.execute("SELECT count(*) FROM hefei_metro_stations WHERE is_transfer=true")
print(f"\n换乘站: {cur.fetchone()[0]}")

cur.close()
conn.close()
print("\nDone!")
