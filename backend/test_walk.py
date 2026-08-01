"""
步行引擎命令行测试工具
用法:
    python test_walk.py                              # 默认: 市中心 15min
    python test_walk.py 31.83 117.25 30              # lat lng 分钟
    python test_walk.py 31.83 117.25 30 gcj02        # GCJ-02坐标
    python test_walk.py 31.83 117.25 30 bd09         # BD-09坐标
    python test_walk.py 31.83 117.25 30 --swap       # 尝试交换lat/lng
    python test_walk.py 31.83 117.25 30 gcj02 --swap # 组合使用
    python test_walk.py 31.83 117.25 30 --radius 300 # 起始吸附半径300m
    python test_walk.py 31.83 117.25 30 --mode metro  # 地铁+步行多模式
    python test_walk.py 31.83 117.25 30 --mode cycle # 骑行 (15km/h, 尊重单行道)

坐标系说明:
    路网 = WGS84, 高德/奥维 = GCJ-02 (偏移 ~650m), 百度 = BD-09
    如果坐标来自奥维/高德地图, 务必加 gcj02 参数
"""
import sys
import time
from collections import Counter
sys.path.insert(0, '.')

from engine.walk_layer import WalkLayer
from engine.metro_layer import MetroLayer
from engine.coord_utils import gcj02_to_wgs84, bd09_to_wgs84

# ====================================================================
# 参数解析
# ====================================================================
args = [a.lower() for a in sys.argv[1:]]

coord_sys = 'wgs84'
for tag in ('gcj02', 'gcj-02', 'gcj'):
    if tag in args:
        coord_sys = 'gcj02'
        args = [a for a in args if a != tag]
        break
for tag in ('bd09', 'bd-09', 'bd'):
    if tag in args:
        coord_sys = 'bd09'
        args = [a for a in args if a != tag]
        break

try_swap = False
if '--swap' in args:
    try_swap = True
    args.remove('--swap')

snap_radius = 150
if '--radius' in args:
    idx = args.index('--radius')
    snap_radius = float(args[idx + 1])
    args.pop(idx)
    args.pop(idx)

mode = 'walk'
if '--mode' in args:
    idx = args.index('--mode')
    mode = args[idx + 1]
    args.pop(idx)
    args.pop(idx)

# 提取数值参数
num_args = []
for a in args:
    try:
        num_args.append(float(a))
    except ValueError:
        pass

# ====================================================================
# 原始输入 + 坐标系转换（在识别 lat/lng 顺序之前做）
# ====================================================================
raw_a = num_args[0] if len(num_args) > 0 else 31.861
raw_b = num_args[1] if len(num_args) > 1 else 117.285
time_min = num_args[2] if len(num_args) > 2 else 15

# 分别对两种可能的顺序做坐标系转换，各生成一个 WGS84 (lat, lng) 候选
candidates = []

# 候选 1: 用户输入 (lat=A, lng=B)
if coord_sys == 'gcj02':
    wgs_lng, wgs_lat = gcj02_to_wgs84(raw_b, raw_a)
elif coord_sys == 'bd09':
    wgs_lng, wgs_lat = bd09_to_wgs84(raw_b, raw_a)
else:
    wgs_lat, wgs_lng = raw_a, raw_b
candidates.append({'label': 'lat,lng', 'lat': wgs_lat, 'lng': wgs_lng,
                   'raw_input': f'{raw_a}, {raw_b}'})

# 候选 2: 用户输入 (lng=B, lat=A) → 交换
if coord_sys == 'gcj02':
    wgs_lng, wgs_lat = gcj02_to_wgs84(raw_a, raw_b)
elif coord_sys == 'bd09':
    wgs_lng, wgs_lat = bd09_to_wgs84(raw_a, raw_b)
else:
    wgs_lat, wgs_lng = raw_b, raw_a
candidates.append({'label': 'lng,lat(交换)', 'lat': wgs_lat, 'lng': wgs_lng,
                   'raw_input': f'{raw_b}, {raw_a}'})

from engine.factory import build_layer
wl = build_layer(mode)

# ====================================================================
# 对每个候选做吸附尝试
# ====================================================================
def try_reachability(candidate):
    try:
        result = wl.compute_reachability(candidate['lat'], candidate['lng'], time_min, snap_radius)
    except ValueError as e:
        print(f"\n  [数据未就绪] {e}")
        sys.exit(1)
    if result:
        result['candidate'] = candidate
        return result
    return None

print()
print("=" * 70)
print("  诊断信息")
print("=" * 70)
print(f"  原始输入: A={raw_a}, B={raw_b}")
if coord_sys != 'wgs84':
    print(f"  坐标系: {coord_sys.upper()} -> WGS84")
print(f"  吸附半径: {snap_radius}m  (坐标误差容错)")

# 尝试候选
results = []
for c in candidates:
    if c['label'].startswith('lng,lat') and not try_swap:
        continue  # skip swap unless --swap specified or auto-swap needed
    r = try_reachability(c)
    if r:
        results.append(r)

print()
for r in results:
    c = r['candidate']
    snaps = r['snap_candidates']
    best_dist = snaps[0]['distance_m']
    if best_dist <= 200:
        marker = 'OK'
    elif best_dist > 1000:
        marker = '!! 距离很远'
    else:
        marker = '较远'
    print(f"  [{c['label']}] raw=({c['raw_input']})")
    if coord_sys != 'wgs84':
        print(f"    转换后 WGS84: lat={c['lat']:.6f}, lng={c['lng']:.6f}")
    print(f"    找到 {len(snaps)} 个候选节点, 最近 {best_dist:.0f}m {marker}")
    for ci in snaps:
        print(f"      #{ci['id']} ({ci['lng']:.5f}, {ci['lat']:.5f})  {ci['distance_m']:.0f}m")

# 如果第一个候选距离太远(或无结果)且没手动指定 --swap, 自动尝试交换
should_auto_swap = (
    not try_swap
    and (not results
         or (len(results) == 1 and results[0]['snap_candidates'][0]['distance_m'] > 1000))
)
if should_auto_swap:
    swap_c = candidates[1]  # the swapped version
    r2 = try_reachability(swap_c)
    if r2:
        if results:
            results.append(r2)
        else:
            results = [r2]

if not results:
    print("\n  错误: 附近无可步行的路网节点")
    print("  可能原因:")
    print("    1. 经纬度顺序反了 -> 试试 --swap")
    print("    2. 坐标系不对 -> 试试 gcj02")
    print("    3. 坐标不在合肥路网范围 -> 核对坐标")
    sys.exit(1)

# 选最近距离的
best = min(results, key=lambda r: r['snap_candidates'][0]['distance_m'])
c = best['candidate']
candidates_list = best['snap_candidates']

# bbox 检查
if not (31.68 <= c['lat'] <= 32.07 and 117.07 <= c['lng'] <= 117.50):
    dlat = (31.68 - c['lat']) if c['lat'] < 31.68 else (c['lat'] - 32.07) if c['lat'] > 32.07 else 0
    dlng = (117.07 - c['lng']) if c['lng'] < 117.07 else (c['lng'] - 117.50) if c['lng'] > 117.50 else 0
    print(f"\n  警告: WGS84坐标超出合肥路网范围!")
    print(f"  路网范围: lat 31.68~32.07, lng 117.07~117.50")
    print(f"  偏差: lat={dlat:.1f}deg, lng={dlng:.1f}deg")

if candidates_list[0]['distance_m'] > 200 and candidates_list[0]['distance_m'] <= 1000:
    print(f"\n  提示: 最近节点距离 {candidates_list[0]['distance_m']:.0f}m, 坐标精度较低")

if best['candidate']['label'].startswith('lng,lat'):
    print(f"\n  提示: 经纬度顺序可能反了 (你传的可能是 lng,lat 而非 lat,lng)")

# ====================================================================
# 输出结果
# ====================================================================
r = best
print()
print("=" * 70)
print(f"  结果 (使用 {len(r['snap_candidates'])} 个起点合并, mode={mode})")
print("=" * 70)

print(f"\n  时间预算: {time_min} min  ({r.get('distance_budget_m', '')}m)")
if r.get('distance_budget_m') is not None:
    print(f"  可达节点: {r['reachable_nodes_count']} 个")
    if r.get('reachable_nodes'):
        print(f"  最远覆盖: {r['reachable_nodes'][-1]['agg_cost']:.0f}m")
else:
    print(f"  可达路网节点: {r['reachable_road_nodes_count']} 个")
    if r.get('reachable_metro_stations_count') is not None:
        print(f"  可达地铁站: {r['reachable_metro_stations_count']} 个")
    if 'bus' in mode or r.get('reachable_bus_stops_count', 0) > 0:
        print(f"  可达公交站: {r['reachable_bus_stops_count']} 个")

print(f"  可达 POI: {r['reachable_pois_count']} 个 (已去重)\n")

# 地铁站列表
if r.get('reachable_metro_stations'):
    print(f"  {'='*70}")
    print(f"  可达地铁站 ({r['reachable_metro_stations_count']} 个)")
    print(f"  {'-'*70}")
    for s in r['reachable_metro_stations'][:30]:
        xfer = ' [换乘]' if s.get('is_transfer') else ''
        lines = s.get('line_name', '') or ''
        print(f"    {s['name']:20s} {lines:15s} 需时 {s['time_min']:.1f}min{xfer}")
    if r['reachable_metro_stations_count'] > 30:
        print(f"    ... 还有 {r['reachable_metro_stations_count']-30} 个站")
    print()

# 公交站列表
if r.get('reachable_bus_stops'):
    print(f"  {'='*70}")
    print(f"  可达公交站 ({r['reachable_bus_stops_count']} 个)")
    print(f"  {'-'*70}")
    for s in r['reachable_bus_stops'][:30]:
        print(f"    {s['name']:20s} 需时 {s['time_min']:.1f}min")
    if r['reachable_bus_stops_count'] > 30:
        print(f"    ... 还有 {r['reachable_bus_stops_count']-30} 个站")
    print()

cat_counts = Counter(p['category'] for p in r['pois'])
cat_names = {
    'hospital': '医院', 'supermarket': '超市', 'park': '公园',
    'mall': '商场', 'school_primary': '小学', 'school_junior': '初中',
    'school_senior': '高中', 'school_college': '大学', 'kindergarten': '幼儿园',
    'market_food': '农贸', 'street_commercial': '商业街', 'street_pedestrian': '步行街',
}
print(f"  {'类别':10s} {'数量':>5s}")
print(f"  {'-'*20}")
for cat, cnt in cat_counts.most_common():
    print(f"  {cat_names.get(cat, cat):10s} {cnt:>5d}")

print(f"\n  {'类别':10s}  {''}")
print(f"  {'-'*80}")
for cat, cnt in cat_counts.most_common():
    items = sorted([p for p in r['pois'] if p['category'] == cat], key=lambda x: x.get('name') or '')
    print(f"\n  [{cat_names.get(cat, cat)}] {cnt} 个")
    for p in items:
        name = (p['name'] or '(none)')[:40]
        sub = p.get('sub_category', '') or ''
        dist = p.get('distance_m', 0)
        try:
            print(f"    {name:40s}  sub={sub:8s}  snap={dist:.0f}m")
        except UnicodeEncodeError:
            print(f"    {name.encode('gbk','replace').decode('gbk'):40s}  sub={sub.encode('gbk','replace').decode('gbk'):8s}  snap={dist:.0f}m")
