# 城市时域生活圈分析系统 — 2026-08-08 前端重构与功能完善总结

> 本文档总结本次会话(2026-08-08)完成的全部工作,含问题修复、功能新增与技术决策。

---

## 一、背景

接手一个前后端已能跑通的 WebGIS 半成品项目。后端 Flask + PostGIS + pgRouting 可达性引擎、
前端 Vue3 + Leaflet 已有雏形。本次针对五大历史问题(左栏堆叠/多边形异常/选点不稳定/人口栅格未用/评分不实用)
进行系统重构,并响应多轮用户反馈迭代。

## 二、后端改动

### 2.1 多边形修复(核心)
- `walk_layer.py`:
  - 新增 `_edges_within_nodes()`: 仅收录"预算内可遍历"道路边(节点成本+边成本≤预算),
    相比最短路径树边(蛛网/破碎)更丰满,相比"两端点都在集合内"不过度填充。
  - `reachable_polygon_from_edges()` 新增 `seed_points`: 可达 POI 点位各 buffer 30m,
    解决"可达 POI 落在圈外"。
  - 多边形抽稀精度 6m→15m(顶点减半,提性能)。
- `reverse.py`: 反算覆盖/交集从"凸包填满"改为**道路走廊边域多边形**,体现不同交通方式形状差异。
- `transit_layer.py`: 公交/地铁模式同样用"预算内可遍历边",填充为连续面,不再破碎。

### 2.2 评分系统改造
- `scoring.py`: 六维→**五维**(去掉人口密度"居住"维度,改显示覆盖人口);
  **交通维度与出行模式无关**(统计起点周边 800m/400m 站),各模式分数可横向比较;
  综合分换算为**优/良/中/差**等级,返回 `grade/grade_desc`、`reachable_facilities_count`、`population`。
- `routes/grid.py`: 网格评分保留"居住"维度(宏观视角),`MAX_CELLS` 8000→20000。

### 2.3 新增接口与字段
- `routes/regeo.py` + `services/amap.py::regeo()`: **逆地理编码** WGS84→地址+最近POI。
- `routes/tiles.py`: `/tiles/pop/{z}/{x}/{y}.png` 人口栅格瓦片服务。
- `routes/isochrone.py`: 等时圈响应补充 `address/rating/cost/opentime_today/category`。
- `engine/poi_stats.py`: 设施条目带出 `category/rating/cost/opentime_today`。

### 2.4 人口栅格瓦片管道(替代六边形网格)
- `scripts/utils/build_pop_tiles.py`: 把 PopSE_China2020_100m(Albers 投影,位于 Downloads)
  重投影到 Web Mercator + 裁剪合肥 + 黄橙红色阶 + 切 XYZ 瓦片 z9-14 → `cache/pop_tiles/`。
  (修复系统级 PROJ_LIB 被 PostGIS 覆盖的问题。)

## 三、前端改动(Vue3 + Leaflet)

### 3.1 布局与交互重构
- 左栏精简为「定位 + 出行」两段;宜居评分/反算选址的**输入+按钮+结果全部并入右侧 Tab**,操作结果同屏。
- **多点分析**:分析点列表(显隐/切换/删除/清空),多圈同图,底部多地点对比表。
- **单点复选交通方式**:出行方式多选,一次生成多个交通方式的可达范围,不同颜色范围线同图显示。
- 模式 chip = **显隐开关**(✓ 勾掉某方式其缓冲区消失)+ 点击文字切换查看统计。

### 3.2 选点与标记
- 选点改为**容器级捕获监听**(点击任意位置包括已有标记都能取点)+ 十字光标。
- 位置/设施改用 `L.marker + divIcon`(DOM 标记,缩放跟随),`zoomAnimation:false` 防连续滚动偏移。
- 设施弹窗显示名称+地址;逆地理编码显示当前点地址。

### 3.3 缩放同步(关键)
- 移除 `preferCanvas`(canvas 缩放不同步)→ 用 SVG。
- 后因性能加 `updateWhenZooming:false` 又不连续 → **彻底改为缩放动画期间隐藏覆盖层、完成后显示**
  (`zoomstart/zoomend` 控制 `overlayPane/markerPane` 加 `zoom-hide`),与底图动画不再错位。
- 性能:点云 4000→1500、设施 400→150/类、公交 1000→400。

### 3.4 人口分布
- 人口 Tab 改为**预渲染栅格底图**(任意缩放无需重算),地图左下角常驻「人口密度」开关按钮,
  `store.popOn` 单一状态源,与人口页按钮、Tab 自动开启完全同步。

### 3.5 设施统计面板
- 三级展开:分类卡片 → 设施名称列表 → **设施详情固定在列表上方**(类型/评分/人均/营业时间)+ 地图定位。

### 3.6 修复的关键 Bug
- `makePoint` 返回原始对象导致 `pt.results` 写入绕过 Vue 响应式 → 改为返回 reactive 代理。
- `ScoreCard` 在 score 为 null 时 `echarts.init(null)` 抛错拖垮整个视图响应式 → 延迟初始化 + try/catch。
- `runScore` 存 score 无 iso,重绘访问 `.iso` 崩溃 → 全链路加守卫。
- 权重滑块显示不动(对象 v-for 值不追踪属性) → 直接读 `weights[k]` + `.number`。
- `StatsPanel` 选项式 `this.expandedCat` 读不到 script-setup ref → 并入 script setup。

## 四、实测结果(无头浏览器 CDP 验证)

- 6 种模式等时圈正常;walk+metro+bus 30min 覆盖约 188km² / 310 万人(多模式正确并集)。
- 评分:86.6 分 / 优;反算选址:263 起点覆盖。
- 多模式:步行+骑行+地铁 3 色范围线同图;勾掉某方式缓冲区即消失。
- 缩放:滚轮缩放期间覆盖层隐藏,完成后显示,不错位。
- 人口栅格瓦片:z9-14 约 1570 张,任意缩放直接可用。

## 五、数据/文件现状

- 数据库:hefei_pop_grid(100m 人口点表,169,877 行,已入库但主视觉改用栅格瓦片)。
- `cache/pop_tiles/`:人口瓦片(已 gitignore,可由 `build_pop_tiles.py` 再生)。
- 演示入口:`?demo=walk:15` / `?demo=walk%2Bmetro%2Bbus:30` 加载后自动生成生活圈。

## 六、技术决策备注

- 坐标系:全库 WGS84;高德数据入口处 GCJ→WGS84 单向转换;逆地理编码 WGS→GCJ。
- 缩放方案:SVG + 缩放期间隐藏覆盖层(不用 canvas,不用 updateWhenZooming:false)。
- 人口展示:栅格瓦片底图替代六边形网格(避免缩放重算、更细腻)。

## 七、后续建议(未实施)

- 全城视角模式:用图标/颜色 + 人口信息做全城分析(用户提出,当前人口 Tab 已提供基础)。
- 分级色彩 Tab 的评分/设施密度六边形网格若需细腻化,可考虑预计算瓦片。
