# 对话总结 — 数据准备阶段

## 背景
城市生活圈分析系统，数据层已全部就绪。

## 本次对话完成的工作

### 1. 数据恢复 — 去重误删后补爬
- 去重脚本 `dedup_poi.py` 用 300m DBSCAN 聚类把医院从 2,511 砍到 714
- 重新爬取医院 POI，恢复到 2,511 条
- 确认数据完整性：6,567 POI，12 个分类

### 2. 进入点（entry）vs POI 对比
- entry 点覆盖率：5,144/6,567 = 78%
- 356 个 entry 找不到匹配 POI 名称 → 分析确认为编码/名称差异
- 208 个是远离同类 POI 的孤点（含 121 个乡镇卫生室）
- 157 个在 300m 内有幸存同类 POI（去重误杀，以医院为主）

### 3. 多楼栋医院分组
- 利用 `address` 字段（"XX医院内"、"XX院区" 等模式）识别多楼栋
- 41 家医院有多个楼栋 POI，按 address 自动分组
- 每组选门诊楼为 canonical，`canonical_poi_id` 字段标记
- 单楼栋医院 canonical_poi_id = 自身 id
- 非医院 POI 的 canonical_poi_id = NULL

### 4. POI-路网节点挂接 `snap_poi_v2.py`
**挂接源优先级**：
- 有 `entr_location` → 解析为 Point 挂接
- 无 entry → 用 POI 自身 `geometry`

**双模式挂接**（poi_road_nodes 表的 mode 字段）：
- **walk**: snap 到步行可用道路顶点（排除 motorway/trunk）
- **drive**: snap 到驾车可用道路顶点（排除 footway/path/steps）

**类别参数**：
| 类别 | 搜索半径 | 最多节点 |
|------|---------|---------|
| hospital, park, mall, school_college | 150m | 5 |
| school_primary, junior, senior, supermarket | 80m | 3 |
| market_food, kindergarten | 50m | 2 |
| street_commercial, street_pedestrian | 30m | 1 |

**医院特殊处理**：
- 只挂接 canonical POI
- 非 canonical 复制 canonical 的挂接记录
- bbox 过滤：(117.07, 31.68, 117.50, 32.07)，排除 196 个界外 POI

**挂接结果**：
- walk: 10,389 条 link，覆盖 6,371 POI（97%）
- drive: 10,909 条 link，覆盖 6,371 POI（97%）
- 挂接距离中位数：~100m，85% 在 200m 内
- 最大挂接距离：4,123m（bbox 过滤后）

### 5. 数据导出
- `snapped_pois.gpkg`：poi_data + entry_points + snap_points 三图层，可在 ArcGIS 查看
- 导出脚本：`scripts/utils/export_snapped_pois.py`

### 6. 项目整理
- 临时分析文件归档到 `_archive/`
- GitHub 仓库：https://github.com/ymr6666/city_life_circle
- 已排除：config.py（API key）、_archive/、cache/、ArcGIS 内部文件
- 已上传：所有源码 + POI + 地铁 + 路网数据

---

## 数据库关键表

| 表 | 说明 |
|---|---|
| `hefei_poi` | 6,567 POI，新增 `canonical_poi_id` 列 |
| `hefei_roads` | 104,132 条路段 |
| `hefei_roads_vertices_pgr` | 42,785 个路网节点 |
| `hefei_metro_stations` | 169 个地铁站 |
| `hefei_metro_edges` | 183 条轨道连线 |
| `poi_road_nodes` | POI-路网挂接表，mode=walk/drive |

---

## 下一步开发（按文档优先级）

1. Flask 后端骨架 + WalkLayer → isochrone API
2. MetroLayer → 多模式传播
3. POI 统计 + 评分 API
4. Vue 3 前端
