# 城市时域生活圈分析系统

> 输入一个地址，选择出行方式与时间，在真实路网上算出"你能走到哪、生活配套好不好"，
> 并提供全城设施布局诊断与规划建议。数据与算法全自研，现场可交互演示。

**功能**：多模式等时圈（步行/骑行/驾车/地铁/公交）· 五维宜居评分 · 反算最优选址 ·
人口分布 · 服务盲区与供需错配 · 选址/关闭/搬迁规划模拟。

**技术栈**：Vue 3 + Leaflet + ECharts ｜ Flask + waitress ｜ PostgreSQL + PostGIS + pgRouting

---

## 快速开始（3 步）

> 详细步骤见 [docs/部署说明.md](docs/部署说明.md)；完整介绍见 [docs/作品介绍与系统概述.md](docs/作品介绍与系统概述.md)。

**前置**：PostgreSQL 13 + PostGIS 3.x + pgRouting 4.x、Python 3.9+。

```bash
# ① 恢复数据库（deploy/data/city_life_circle.dump 为全量备份）
createdb -U postgres city_life_circle
pg_restore -U postgres -d city_life_circle --no-owner --no-privileges deploy/data/city_life_circle.dump

# ② 安装后端依赖
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# ③ 启动（前端构建产物 frontend/dist 已内置，后端直接托管）
python app.py
```

打开 **http://localhost:5000**。

> Windows 用户可直接运行 `deploy\scripts\install_windows.bat` 一键初始化，
> Linux/macOS 用 `bash deploy/scripts/install_linux.sh`。

---

## 本地开发

```bash
# 后端
cd backend && python app.py                 # http://localhost:5000

# 前端（Vite 开发服务器，代理 /api、/tiles 到 5000）
cd frontend && npm install && npm run dev   # http://localhost:5173
```

## 测试工具

```bash
cd backend
python test_walk.py 31.861 117.285 30 --mode walk+metro+bus   # 命令行可达性测试
```

## 文档索引

| 文档 | 说明 |
|---|---|
| [docs/作品介绍与系统概述.md](docs/作品介绍与系统概述.md) | 功能、架构、算法创新、数据规模 |
| [docs/部署说明.md](docs/部署说明.md) | 本地运行 + 云服务器部署（详细步骤） |
| [docs/项目结构与文件说明.md](docs/项目结构与文件说明.md) | 目录/引擎/API/数据表说明 |
| [docs/前端对接说明.md](docs/前端对接说明.md) | API 契约与坐标系说明 |

## 数据与版权

- 路网/地铁：OpenStreetMap（© OpenStreetMap contributors，ODbL）
- 设施 POI：高德地图开放平台（仅研究演示用）
- 公交：合肥公共交通官方数据平台 + 8684
- 人口：WorldPop 2020（100m 栅格）
- 底图：天地图 / OpenStreetMap
