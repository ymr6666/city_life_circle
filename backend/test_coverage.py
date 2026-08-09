"""
服务覆盖分析引擎命令行测试
用法:
    python test_coverage.py                                   # 默认: hospital 类别 5/10/15min
    python test_coverage.py --category hospital
    python test_coverage.py --category hospital --mode walk
    python test_coverage.py --category hospital --time 5,10,15
    python test_coverage.py --poi 6622,6623                   # 指定设施覆盖
    python test_coverage.py --exclusive 6622 --time 10        # 独占覆盖(关闭影响)
"""
import sys
import time

sys.path.insert(0, '.')
from engine.coverage import (category_coverage, facility_coverage,
                             exclusive_catchment)

args = sys.argv[1:]

def arg_val(key, default=None):
    if key in args:
        return args[args.index(key) + 1]
    return default

category = arg_val('--category', 'hospital')
mode = arg_val('--mode', 'walk')
time_str = arg_val('--time', '5,10,15')
poi_str = arg_val('--poi', None)
excl_str = arg_val('--exclusive', None)
time_budgets = [float(t) for t in time_str.split(',')]

print("=" * 70)
print(f"  服务覆盖分析  category={category} mode={mode} time={time_budgets}")
print("=" * 70)

t0 = time.time()
if excl_str:
    poi_ids = [int(x) for x in excl_str.split(',')]
    print(f"\n[独占覆盖] poi={poi_ids} time={time_budgets[0]}min")
    r = exclusive_catchment(poi_ids, mode=mode, time_budget_min=time_budgets[0])
    if r:
        print(f"  其他同类设施: {r['other_category']}")
        print(f"  独占节点: {r['exclusive_node_count']} 个")
        print(f"  受影响人口: {r['affected_population']:,} ({100*r['affected_population']/r['total_population']:.2f}% 总人口)")
        print(f"  总人口: {r['total_population']:,}")
        print(f"  polygon: {'有' if r['polygon'] else '无'}")
    else:
        print("  无结果")
    print(f"  耗时 {time.time()-t0:.1f}s")
    sys.exit(0)

if poi_str:
    poi_ids = [int(x) for x in poi_str.split(',')]
    print(f"\n[设施覆盖] poi={poi_ids} mode={mode}")
    r = facility_coverage(poi_ids, mode=mode, time_budgets=time_budgets)
    print(f"  总人口: {r['total_population']:,}")
    for f in r['facilities']:
        print(f"  {f['name'][:30]:30s} [{f['category']}] snap_ok={f['snap_ok']}")
        if f['snap_ok']:
            for t in f['thresholds']:
                print(f"    {t['time_budget_min']:>5.0f}min  覆盖人口 {t['covered_population']:>10,}  覆盖率 {t['coverage_rate']*100:5.2f}%  节点 {t['reachable_origins_count']:>6}")
    if r['combined']:
        print("  合计(并集):")
        for t in r['combined']['covered']:
            print(f"    {t['time_budget_min']:>5.0f}min  覆盖人口 {t['covered_population']:>10,}  覆盖率 {t['coverage_rate']*100:5.2f}%")
    print(f"  耗时 {time.time()-t0:.1f}s")
    sys.exit(0)

print(f"\n[类别覆盖] {category} mode={mode}")
r = category_coverage(category, mode=mode, time_budgets=time_budgets)
if r is None:
    print("  该类别无挂接数据")
    sys.exit(1)
print(f"  设施数: {r['facility_count']} 个")
print(f"  总人口: {r['total_population']:,}")
for t in r['thresholds']:
    print(f"    {t['time_budget_min']:>5.0f}min  覆盖人口 {t['covered_population']:>10,}  覆盖率 {t['coverage_rate']*100:5.2f}%  盲区人口 {t['blind_population']:>10,}")
print(f"  耗时 {time.time()-t0:.1f}s")
