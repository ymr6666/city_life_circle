"""设施等级标准 (standards)

锚点类别口径: 覆盖/盲区/关闭影响/选址分析按**设施等级**评估,
避免"三甲医院和诊所一视同仁"导致大医院关闭影响=0、盲区被基层网点淹没。

等级语义 (数字越大越高档):
  每类设施定义 typecode → 等级 的映射。分析时传 tier=N 表示
  "只统计等级 >= N 的设施", 例如:
    hospital tier=3 → 三甲/综合大医院 (090101/090100/090102)
    hospital tier=2 → + 专科医院 (0902xx)
    hospital tier=1 → + 诊所/基层 (0903xx/0905xx)

facility 分组: 同一 facility_id 的多部门/多楼栋 POI 在展示与统计时
按 facility 合并 (等级取组内最高等级)。
"""
from collections import defaultdict

# ── 医院等级 (医疗, 参照 MEDICAL_TYPECODE_WEIGHT 口径) ──────────
HOSPITAL_TIER = {
    "090101": 3,   # 综合医院(三甲)
    "090100": 3,   # 综合医院
    "090102": 3,   # 医院(含卫生院, 但可到综合)
    "090103": 3,
    "090200": 2,   # 专科医院
    "090201": 2,   # 专科
    "090202": 2,   # 口腔
    "090203": 2,   # 眼科
    "090204": 2,
    "090205": 2,
    "090206": 2,
    "090207": 2,
    "090208": 2,
    "090209": 2,
    "090210": 2,
    "090211": 2,
    "090300": 1,   # 诊所
    "090400": 2,   # 急救中心
    "090500": 1,   # 卫生院/门诊
    "090600": 1,
    "090700": 2,   # 社区卫生服务中心
    "090900": 1,
}
# 默认等级 (不传 tier 时): 全部纳入
HOSPITAL_DEFAULT_TIER = 1

# ── 各分析类别 → (typecode→等级 映射, 默认等级) ────────────────
CATEGORY_TIERS = {
    "hospital": (HOSPITAL_TIER, 1),
}

# 等级标签 (前端展示/API 返回)
TIER_LABELS = {
    3: "三甲/综合",
    2: "专科",
    1: "基层/全部",
}


def typecode_tier(category, sub_category):
    """某类别下 POI 的 typecode 等级; 无映射的类别/typecode 默认最高级 1。"""
    tier_map, _ = CATEGORY_TIERS.get(category, ({}, 1))
    if not tier_map or not sub_category:
        return 1
    # 组合 typecode "A|B" 取最高等级 (复合标签按更高档算)
    return max(tier_map.get(code.strip(), 1) for code in str(sub_category).split("|"))


def category_default_tier(category):
    """某类别分析默认等级 (不传时用)。"""
    _, default = CATEGORY_TIERS.get(category, ({}, 1))
    return default


def supported_tiers(category):
    """某类别支持的等级列表 (按高低排序), 用于前端下拉。"""
    tier_map, _ = CATEGORY_TIERS.get(category, ({}, 1))
    if not tier_map:
        return [1]
    return sorted(set(tier_map.values()), reverse=True)


def facility_tier(category, sub_category):
    """别名: 与 typecode_tier 相同 (语义为设施等级)。"""
    return typecode_tier(category, sub_category)
