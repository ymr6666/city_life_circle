# 城市时域生活圈分析系统 — 项目完整总结

> 生成日期：2026-07-26
> 项目名称：城市时域生活圈分析系统

---

## 一、项目概述

### 定位与理念
- **居民个人视角**，回答"住在这里，我的生活怎么样"
- 不以全市宏观尺度为出发点，以用户地址为起点
- 输出个人专属生活圈诊断，非统计图表
- 有温度、有深度、为个人服务

### 核心功能
1. **正算**：输入地址 → 选择出行方式+时间 → 生成等时圈 → 圈内设施统计 → 评分卡
2. **反算**：选择设施 → 生成覆盖范围 → 多设施交集 = 最优居住选址
3. **多地点对比**：正反算地点自由组合，多圈同图展示，对比表格
4. **多模式交通**：步行 / 骑行 / 驾车 / 地铁 四种出行方式
5. **评分系统**：三层透明设计（事实数据 → 用户权重 → 参考分）

### 出行方式生活圈
| 方式 | 速度 | 路口惩罚 | 说明 |
|------|------|---------|------|
| 🚶 步行 | 5 km/h | 左转/直行 0.5min，右转 0 | 核心模式 |
| 🚲 骑行 | 15 km/h | 同步行 | 快速步行变体 |
| 🚗 驾车 | 30 km/h | 同步行 | WHERE 过滤道路类型 |
| 🚇 地铁 | 35 km/h | 无 | 站间时间 = 距离/速度 |

---

## 二、技术栈

```
前端:  Vue 3 + Leaflet / 高德 JSAPI（待定）
后端:  Python Flask
数据库: PostgreSQL 13 + PostGIS 3.6 + pgRouting 4.0.1
数据源: OpenStreetMap（路网+地铁）+ 高德 API（POI + 地理编码）
```

---

## 三、项目目录结构

```
E:\city-life-circle\
│
├── backend/                          # Flask 后端（待开发）
│   ├── app.py
│   ├── config.py
│   ├── engine/                       # 传播引擎核心
│   │   ├── propagation_engine.py     # 主循环
│   │   ├── base_layer.py             # TransportLayer 抽象基类
│   │   ├── walk_layer.py             # 步行层
│   │   ├── cycle_layer.py            # 骑行层
│   │   ├── drive_layer.py            # 驾车层
│   │   └── metro_layer.py            # 地铁层
│   ├── routes/                       # API 路由
│   │   ├── geocode.py
│   │   ├── isochrone.py
│   │   ├── reverse_isochrone.py
│   │   ├── poi_stat.py
│   │   └── score.py
│   └── services/
│       └── postgis.py
│
├── frontend/                         # Vue 3 前端（待开发）
│   └── src/
│
├── data/                             # 已导出数据文件
│   ├── 合肥路网/
│   │   ├── hefei_roads.shp/gpkg         (104,132 条路段)
│   │   ├── hefei_roads_nodes.shp/gpkg   (42,785 个节点)
│   │   └── hefei_roads_sample.geojson
│   ├── 合肥POI/
│   │   ├── hefei_poi.shp/gpkg           (6,567 条 POI)
│   │   └── hefei_poi.csv
│   └── 合肥地铁/
│       ├── hefei_metro_stations.shp/gpkg (169 站)
│       └── hefei_metro_edges.shp/gpkg    (183 条轨道)
│
├── shp/                              # ArcGIS 友好的纯英文路径副本
│
├── scripts/
│   ├── crawlers/                     # 爬虫代码
│   │   ├── config.py                 # API Key + 参数配置
│   │   ├── crawl_poi_v5_final.py     # POI 主爬虫 (v5 API)
│   │   ├── crawl_metro.py            # 地铁爬虫 (OSM Overpass)
│   │   ├── setup_tables_v2.py        # POI 建表（含 business/navi）
│   │   └── export_*.py               # 导出脚本
│   └── utils/                        # 路网下载/拓扑/检查工具
│
└── docs/                             # 项目文档
```

---

## 四、数据库设计

### PostgreSQL `city_life_circle`

#### 路网表
```sql
hefei_roads (95,924 rows)                -- 步行+行车+骑行共用
  id, u, v, osmid, highway, name, length, oneway,
  source, target, cost, reverse_cost,
  geometry (LineString, EPSG:4326)

hefei_roads_vertices_pgr (42,785 rows)   -- 路网顶点
  id, osm_id, x, y, geometry (Point)

hefei_nodes (42,785 rows)               -- 原始OSM节点
  osmid, x, y, geometry
```

#### POI 表
```sql
hefei_poi (6,567 rows)
  id, name, category, sub_category(typecode),
  address, tel,
  -- business 字段
  business_area, rating, cost, parking_type,
  opentime_today, opentime_week, tag, alias,
  -- navi 字段
  entr_location(入口引导点坐标), exit_location, navi_poiid,
  photos,
  geometry (Point, EPSG:4326)
```

#### 地铁表
```sql
hefei_metro_stations (169 站)
  id, name, line_name("1|2"表示换乘), is_transfer, geometry

hefei_metro_edges (183 条轨道)
  id, line_name, station_from→to, distance_km, time_min, geometry
```

---

## 五、核心算法：时间耗尽传播引擎

### 5.1 基本原理

从地址出发，沿路网逐步扩散。每走 dt=0.5 分钟检查一次：遇到地铁站入口 → 分叉进地铁网络 → 出站继续步行 → 直到时间预算耗尽 → 所有到过的节点包成多边形。

### 5.2 架构

```
              PropagationEngine（主循环, 步长 0.5min）
                    │
    ┌───────────────┼───────────────┐
    │               │               │
WalkLayer      MetroLayer      DriveLayer
speed=5        speed=35        speed=30
node_penalty   no_penalty      同步行
                               
CycleLayer      BusLayer（预留）
speed=15        接口待实现
```

### 5.3 统一 Layer 接口

```python
class TransportLayer:
    speed: float          # km/h
    edge_filter: str      # SQL WHERE（路网道路类型过滤）
    node_penalty: float   # 路口惩罚（min/个）

    def propagate(entry_nodes, time_budget, visited) -> (new_nodes, exits, consumed)
```

### 5.4 道路类型过滤

| 出行方式 | 允许的道路类型 | 禁止的 |
|---------|--------------|--------|
| 步行 | footway, pedestrian, path, steps, corridor, residential, living_street, service, tertiary, unclassified | motorway, trunk (及其links) |
| 骑行 | cycleway + 步行道路 | motorway, trunk |
| 驾车 | motorway, trunk, primary, secondary, tertiary (及其links) | footway, pedestrian, path, steps, cycleway |

### 5.5 地铁层传播（站内换乘支持）

```
进站 S_in
  ↓ 地铁网络 BFS/Dijkstra（站间耗时 = 距离 / 35km/h）
  ↓ 支持本线直达 + 换乘站切换线路
可达站点集 {S₁, S₂, ..., Sₙ}
  ↓ 每个站出站，剩余时间做步行扩散
全部辐射范围合并 → 地铁生活圈
```

### 5.6 POI 可达判定

```
POI 预先挂接到附近的路网节点 (poi_road_nodes 表)
传播引擎算出可达节点集 → POI 的注册节点在集合内 → POI 可达
```

POI 挂接搜索半径：
| 类型 | 半径 | 理由 |
|------|------|------|
| 三甲/大学/公园/购物中心 | 150m | 多出入口 |
| 小学/中学/超市 | 80m | 一个正门 |
| 诊所/便利店/幼儿园 | 30m | 临街 |

### 5.7 POI-to-Road-Node Snapping Strategy

POI is snapped to 1-5 nearby road network nodes based on radius. A POI is "reachable" if ANY of its registered nodes appears in the propagation engine's visited set.

---

## 六、数据获取流程

### 6.1 路网
```
OSM Overpass API → osmnx 下载 → PostGIS 导入
→ pgr_createTopology() 构建拓扑 (手动版, pgRouting 4.0.1 缺内置函数)
→ 用 osmid 关联 u/v 列到 source/target
→ 设置 cost = ST_Length(geometry::geography) 作为步行距离
```

### 6.2 POI
```
高德 POI 2.0 API (v5)
→ show_fields=business,navi 获取入口引导点+营业信息
→ 72格网格搜索 (hospital/supermarket/学校等 7类)
→ 城市级搜索 (≤200条的 5类)
→ 去重策略: (name, location) 内存去重, 不做空间聚类删除
→ 总请求 ~800次/次, 速率 ≤3次/秒
```

### 6.3 地铁
```
OSM Overpass API → 查询 subway route relations
→ 提取各线路 member stop 节点 → 按线路排序
→ 200m 空间聚类识别换乘站 (同站异名合并)
→ 构建 metro_edges (站间连线 + 距离 + 时间)
```

---

## 七、当前项目进度

### ✅ 已完成

| 模块 | 详情 |
|------|------|
| **数据库** | PostgreSQL + PostGIS 3.6 + pgRouting 4.0.1 |
| **路网** | 104k 路段，43k 节点，拓扑完成 |
| **POI** | 6,567 条，12 个分类，含 typecode + 入口引导点 |
| **地铁** | 7 条线，169 站，183 条轨道，20 个换乘站 |
| **所有数据已导出** | .shp / .gpkg / .csv / .geojson，纯英文路径可用 |

### POI 分类统计

| 分类 | 数量 | typecode 示例 |
|------|------|-------------|
| 🏥 医院 | 2,511 | 090101(三甲), 090300(诊所), 090102(卫生院)... |
| 🛒 超市 | 1,951 | 060400 |
| 🌳 公园 | 335 | 110100 |
| 🛍️ 商场 | 332 | 060100 |
| 🎒 小学 | 332 | 141203 |
| 🏬 商业街 | 210 | 061000 |
| 🎓 大学 | 200 | 141201 |
| 🥬 农贸 | 197 | 060703 |
| 🍼 幼儿园 | 188 | 141204 |
| 🎒 高中 | 146 | 141202 |
| 🎒 初中 | 137 | 141202 |
| 🚶 步行街 | 28 | 061001 |

### ❌ 待开发

| 优先级 | 模块 | 预估时间 |
|--------|------|---------|
| ⭐⭐⭐ | Flask 后端骨架 | 半天 |
| ⭐⭐⭐ | 传播引擎 (WalkLayer + Metrolayer) | 3-4 天 |
| ⭐⭐⭐ | `/api/isochrone` / `/api/reverse-isochrone` | 1 天 |
| ⭐⭐⭐ | `/api/poi-stat` / `/api/score` / `/api/geocode` | 1 天 |
| ⭐⭐⭐ | POI-路网节点挂接 (`poi_road_nodes` 表) | 1 天 |
| ⭐⭐ | Vue 3 前端 (组员 A) | 并行进行 |
| ⭐ | 文档 + PPT (组员 B) | 全程 |

---

## 八、API 设计

| 端点 | 方法 | 输入 | 输出 |
|------|------|------|------|
| `/api/geocode` | GET | 地址文本 | 经纬度 |
| `/api/isochrone` | POST | 坐标 + 出行方式 + 时间预算 | 等时圈 GeoJSON |
| `/api/reverse-isochrone` | POST | 设施坐标 + 出行方式 + 时间 | 覆盖范围 GeoJSON |
| `/api/poi-stat` | POST | 多边形 GeoJSON | 分类 POI 统计 |
| `/api/score` | POST | 坐标 + 用户权重 + 家庭结构 | 综合评分 |

---

## 九、关键技术参数汇总

| 参数 | 值 |
|------|-----|
| 传播步长 dt | 0.5 min |
| 步行速度 | 5 km/h |
| 骑行速度 | 15 km/h |
| 驾车速度 | 30 km/h |
| 地铁速度 | 35 km/h |
| 路口惩罚（左转/直行） | 0.5 min |
| 路口惩罚（右转） | 0 |
| 等地铁/进站/出站时间 | MVP 忽略 |
| 坡度影响 | MVP 忽略 |
| POI typecode 区分三甲/卫生院 | 评分加权用 |
| entr_location 引导点覆盖率 | 78% |
| 路网 bbox | (117.07, 31.68, 117.50, 32.07) |

---

## 十、评分系统设计

### 三层透明
```
层1: 事实数据（客观）—— "步行15分钟内有2家三甲、3所小学、1个地铁站..."
层2: 权重调节（用户）—— 滑块拖动+勾选"有老人/有小孩"自动调整权重
层3: 参考分（仅供参考）—— 综合宜居指数 78/100
```

### typecode 评分加权
```sql
-- 医疗评分
SUM(CASE WHEN sub_category='090101' THEN 3   -- 三甲
         WHEN sub_category='090200' THEN 2   -- 专科
         WHEN sub_category='090300' THEN 1   -- 诊所
    END) AS medical_score
```

---

## 十一、与竞品的差异化

| | ArcGIS Network Analyst | 本系统 |
|--|----------------------|--------|
| 实现方式 | 点工具 | 算法设计 |
| 多模式耦合 | ❌ 步行+地铁混合 | ✅ 核心能力 |
| 比赛答辩 | 录屏演示 | 现场可交互 |
| 创新深度 | 工具使用者 | 算法实现者 |

---

## 十二、后续开发顺序建议

```
第一优先（你）：
  ① Flask 项目 + config.py
  ② WalkLayer → 主循环 → 第一个 isochrone API 跑通
  ③ MetroLayer → 多模式传播
  ④ POI-路网挂接 + poi-stat + score API

第二优先（组员 A）：
  ① 搭 Vue 3 项目 + 底图显示
  ② 搜索框 + 等时圈显示
  ③ 多圈叠加 + 对比表格

第三优先（组员 B）：
  ① 技术文档
  ② 演示 PPT
  ③ 录制演示视频
```

---

*本文档由对话自动整理生成，供项目开发参考使用。*
