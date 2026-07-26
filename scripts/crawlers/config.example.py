# 高德 API 配置 (POI 2.0 v5)
# 复制此文件为 config.py 并填入真实 key
AMAP_KEY = "YOUR_AMAP_KEY"

# 数据库
DB_CONFIG = {
    "host": "localhost", "port": 5432, "dbname": "city_life_circle",
    "user": "postgres", "password": "YOUR_PASSWORD",
}

# POI 分类: keywords(单个) / types
POI_CATEGORIES_GRID = {
    "hospital":             [("医疗",  "090100|090200|090300|090400|090500")],
    "supermarket":          [("超市",  "060400")],
    "school_primary":       [("小学",  "141203")],
    "school_junior":        [("初中",  "141202")],
    "park":                 [("公园",  "110100")],
    "mall":                 [("购物中心","060100"), ("商场","060100")],
    "street_commercial":    [("特色商业街","061000")],
}

POI_CATEGORIES_CITY = {
    "kindergarten":         [("",      "141204")],
    "school_college":       [("",      "141201")],
    "school_senior":        [("高中",  "141202")],
    "market_food":          [("农副产品市场","060703")],
    "street_pedestrian":    [("步行街","061001")],
}

# typecode → 标签
TYPECODE_LABEL = {
    "090101": "三甲", "090100": "综合医院", "090102": "卫生院",
    "090200": "专科", "090300": "诊所", "090400": "急救", "090500": "药店",
    "141201": "大学", "141202": "中学", "141203": "小学", "141204": "幼儿园",
    "110101": "公园", "110100": "公园广场",
    "060101": "购物中心", "060100": "商场", "060400": "超市",
    "060703": "农贸", "061001": "步行街", "061000": "商业街",
}

# 合肥范围 (扩展版，覆盖全部地铁 + 路网)
HEFEI_BOUNDS = {
    "city": "合肥",
    "bbox": (117.07, 31.68, 117.50, 32.07),
    "grid_step": 0.05,
}
