# 对话总结：WebGIS 三维平台项目分析与学习指导

> 日期：2026-07-01
> 项目：地信242-第3组《系统代码》

---

## 一、项目概述

这是一个 **WebGIS 三维平台**，前端展示三维地图，后端提供 GIS 数据服务。

### 项目结构

```
系统代码/web-vue3/
├── webgis-api/          # 后端 ASP.NET Core 9 + PostgreSQL/PostGIS
│   ├── Controllers/     # 10 个 API 控制器
│   ├── Services/        # 业务逻辑（PostGIS 空间查询、JWT、分片上传等）
│   ├── Data/            # EF Core DbContext（仅 users 表）
│   ├── Models/          # User、GisApiResponse<T>
│   ├── DTOs/            # 请求/响应对象
│   ├── Sql/             # full_init.sql（8 张业务表建表脚本）
│   └── appsettings.json # 数据库连接串、JWT 配置
├── webgis-front/        # 前端 Vue 3 + Vite + Cesium + Element Plus
│   ├── src/views/       # Login.vue、Register.vue、MainLayout.vue
│   ├── src/components/  # MapView.vue、TopBar.vue 等
│   ├── src/stores/      # Pinia 状态管理（auth.js、mapRuntime.js）
│   ├── src/api/         # Axios 封装（request.js、gis.ts、auth.js）
│   ├── src/core/gisbox/ # GisBoxEngine.ts（Cesium 封装单例）
│   └── src/types/       # TypeScript 类型定义
└── WEBGIS_PLATFORM.md   # 项目文档
```

---

## 二、使用的技术栈

### 后端

| 技术 | 用途 |
|------|------|
| ASP.NET Core 9 | Web API 框架（跨平台，非 .NET Framework） |
| C# | 编程语言 |
| Npgsql (raw ADO.NET) | PostgreSQL 驱动，手写 SQL 执行空间查询 |
| EF Core 9 | ORM，仅用于 users 表 |
| PostGIS 3.6.2 | PostgreSQL 空间扩展（GEOS、PROJ 等） |
| JWT Bearer | 登录认证 |
| BCrypt.Net | 密码哈希 |
| Swagger | API 文档（/swagger） |

### 前端

| 技术 | 用途 |
|------|------|
| Vue 3 (Composition API) | 前端框架 |
| Vite 8 | 构建工具 |
| Cesium 1.108 | 三维地球渲染引擎 |
| Element Plus | UI 组件库 |
| Pinia | 状态管理 |
| Axios | HTTP 客户端（拦截器链） |
| SCSS | 样式方案 |

### 数据库

- PostgreSQL 13
- PostGIS 3.6.2（已安装在 webgis_system 数据库中）

---

## 三、代码风格评价

**总体评分：7.5/10**

### 优点
- 后端使用文件范围命名空间、record DTO、接口分离设计
- 全部 SQL 参数化防注入
- 统一 `GisApiResponse<T>` 响应格式
- JWT 仅存内存不落盘，安全意识好
- 前端全 `<script setup>` + SCSS scoped 模式统一

### 可改进点
- ORM 混用：EF Core 管 users，其余表用手写 ADO.NET
- MapView.vue ~860 行，30+ 命令全在 handleCommand 里
- TypeScript 增量引入未完成（.ts/.js 混用）
- 残留 3 个 .bak 备份文件在目录中
- `bin/` 和 `obj/` 编译缓存未清除即打包（导致 NuGet 路径锁死在别人的电脑上）

---

## 四、环境检测与修复

### 初始环境状态

| 组件 | 版本 | 状态 |
|------|------|------|
| Node.js | v24.15.0 | ✅ 已安装 |
| npm | 11.12.1 | ✅ 已安装 |
| .NET SDK | 9.0.305 | ✅ 已安装 |
| Visual Studio 2022 | Community 17.14.14 | ✅ 已安装 |
| PostgreSQL | 13（postgresql-x64-13） | ✅ 服务运行中 |
| PostGIS | 3.6.2 | ✅ 已安装到 webgis_system |
| psql | 位于 D:\PostgreSQL\bin\ | ⚠️ 不在 PATH |

### 后端修复记录

**问题：** `dotnet build` 失败，错误信息：
```
无法找到回退包文件夹“E:\C#\C\NuGetPackages”
```

**原因：** 打包者未清除 `obj/` 编译缓存。`project.assets.json` 中记录了原开发机的 NuGet 回退包路径，本机不存在。

**修复：**
1. 删除 `obj/` 和 `bin/` 目录
2. 执行 `dotnet restore` 重新下载所有 NuGet 包
3. 执行 `dotnet build` → 编译成功，0 错误 0 警告

### 启动验证成功

后端启动日志：
```
PostgreSQL 已连接：webgis_system
数据库表结构已就绪（full_init.sql）
Now listening on: http://localhost:5020
表记录数：users=0, vector_features=0, basemap_catalog=3, ...
```

前端 node_modules 也完整，可直接 `npm run dev` 启动。

### 当前环境确认

```
系统代码/web-vue3/webgis-front/ → npm run dev    (http://localhost:5173)
系统代码/web-vue3/webgis-api/   → dotnet run     (http://localhost:5020)
数据库                          → PostgreSQL 运行中，webgis_system 已创建
```

---

## 五、API 体系详解

### 10 个控制器

| 控制器 | 路由 | 功能 | 认证 |
|--------|------|------|------|
| AuthController | /api/auth | 注册/登录 | 匿名 |
| HealthController | /api/health | 健康检查 | 匿名 |
| BasemapController | /api/gis/basemaps | 底图列表 | 匿名 |
| VectorController | /api/gis/vectors | 矢量要素 CRUD + 空间分页 | JWT |
| VectorCrudCompatController | /api/crud/vector-features | 旧路由兼容 | 混合 |
| SpatialController | /api/gis/spatial | GeoJSON 导出 + 空间筛选 | 混合 |
| ModelAssetsController | /api/gis/models | 3D 模型列表/上传/位姿 | 混合 |
| ViewpointController | /api/gis/viewpoints | 视角书签 CRUD | JWT |
| UploadController | /api/gis/upload | 大文件分片上传 | JWT |
| SessionController | /api/session | 当前用户信息 | JWT |

### 统一响应格式

```json
{
  "success": true,
  "message": "ok",
  "data": { },
  "meta": { "page": 1, "pageSize": 50, "total": 100 }
}
```

### PostGIS 核心操作（亮点）

1. **GeoJSON 服务端生成**：在 PostgreSQL 内部用 `json_build_object` + `json_agg` 拼好 GeoJSON FeatureCollection，前端直接使用
2. **空间范围过滤**：`geom && ST_MakeEnvelope(minx, miny, maxx, maxy, 4326)` 实现 bbox 快速筛选
3. **空间数据写入**：`ST_SetSRID(ST_GeomFromGeoJSON(@geom), 4326)` 接收前端 GeoJSON 存入数据库
4. **输出**：`ST_AsGeoJSON(geom)::json` 将空间字段转为 JSON

---

## 六、数据库设计

### 8 张表一览

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| users | 用户 | id, username, password_hash(BCrypt) |
| vector_features | 矢量要素 | geom(Geometry,4326), layer_name, properties(JSONB) |
| draw_geometries | 用户绘制 | geom, user_id → users(id) **唯一外键** |
| admin_regions | 行政区划 | geom, adcode, level, parent_adcode |
| basemap_catalog | 底图配置 | code, url_template, is_default（预置 3 条数据） |
| gis_models | 3D 模型 | file_path, lon, lat, height_m, heading/pitch/roll/scale |
| gis_viewpoints | 视角书签 | lon, lat, height_m, heading, pitch, roll |
| upload_sessions | 分片上传 | file_name, chunk_size, status |

### 设计特点
- 仅 1 个外键（users → draw_geometries），ER 图不会成"蜘蛛网"
- "三维"字段本质只是 9 个普通小数（lon, lat, height, heading, pitch, roll, scale）
- 空间字段使用 GiST 索引加速查询
- JSONB 类型支持属性动态扩展

---

## 七、个人学习背景对照

### 已有经验
- ✅ 写过 PostGIS 手写 SQL
- ✅ 用 Flask 实现过前后端小项目
- ✅ 用 C# WinForms 连接过 MySQL 数据库
- ❌ 未接触过三维地图在网页上的展示
- ❌ Vue 3 前端不熟悉

### 核心认知
1. **后端返回值本质上仍是 JSON 文本**，传输简单数字和传输地理坐标没有区别，都只是字符串
2. **三维在数据库里就是 9 个普通小数**，不存在特殊类型
3. **地图显示由 Cesium 库完成**，不需要自己写绘制代码
4. **Cesium 不依赖 Vue 3**，纯 HTML + JS 也能用
5. **前端显示地图和后端返回数据是解耦的**，前端负责渲染，后端只提供数据
6. **ASP.NET Core 是跨平台的**（不是 .NET Framework），可在 Windows/Linux/macOS 运行
7. 这个项目的 API **可以用其他语言重写**（Python FastAPI、Node.js Express 等），核心是 PostGIS SQL

---

## 八、启动命令（明日可用）

### 1. 启动后端 API

```powershell
cd "D:\QQ_downloads\地信242-第3组\系统代码\系统代码\web-vue3\webgis-api"
dotnet run
```

访问：`http://localhost:5020`，Swagger：`http://localhost:5020/swagger`

### 2. 启动前端

```powershell
cd "D:\QQ_downloads\地信242-第3组\系统代码\系统代码\web-vue3\webgis-front"
npm run dev
```

访问：`http://localhost:5173`

### 3. 数据说明

| 数据 | 情况 |
|------|------|
| 底图（天地图影像/电子、OSM） | ✅ 已预置 |
| 用户数据 | ❌ 启动后注册 |
| 矢量要素 | ❌ 启动后通过前端绘制 + 入库 |
| 三维模型 | ❌ 需自行准备 .glb/.gltf 上传 |
| 行政区划 | ❌ 空表，需导入 |
| 视角书签 | ❌ 启动后保存 |

---

## 九、学习建议

| 技术 | 学习途径 | 优先级 |
|------|---------|--------|
| PostGIS SQL（ST_AsGeoJSON、ST_MakeEnvelope 等） | 已有基础，看 PostGisService.cs | ⭐⭐⭐ |
| ASP.NET Core 路由和依赖注入 | 对比 Flask 理解，看 Controllers + Program.cs | ⭐⭐⭐ |
| 统一 API 响应设计 | 直接参考 GisApiResponse.cs | ⭐⭐⭐ |
| JWT 认证 | 看 AuthController + JwtTokenService | ⭐⭐ |
| Vue 3 基础 | 如有精力再学，否则直接改现有代码 | ⭐⭐ |
| Cesium 三维地图 | 纯 HTML 也能跑，不必从 Vue 入手 | ⭐⭐ |

---

*本文档由 AI 助手自动生成，基于 2026-07-01 的对话记录整理。*
