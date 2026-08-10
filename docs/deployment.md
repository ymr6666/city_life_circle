# 城市时域生活圈分析系统 —— 部署说明

> 适用版本：V1.0（2026-08）
> 两种部署形态：**A. 本地运行（评委评审）** / **B. 云服务器在线访问**。
> 配套：`deploy/scripts/`（安装脚本）、`deploy/data/`（数据库备份与人口瓦片）、`deploy/docker/`（容器化方案）。

---

## 目录

- [一、环境要求](#一环境要求)
- [二、部署方案 A：本地运行（评委评审）](#二部署方案-a本地运行评委评审)
  - [A-1 一键脚本安装](#a-1-一键脚本安装)
  - [A-2 手动安装步骤（Windows）](#a-2-手动安装步骤windows)
  - [A-3 手动安装步骤（Linux / macOS）](#a-3-手动安装步骤linux--macos)
  - [A-4 数据库恢复说明](#a-4-数据库恢复说明)
  - [A-5 启动与访问](#a-5-启动与访问)
- [三、部署方案 B：云服务器在线访问](#三部署方案-b云服务器在线访问)
  - [B-1 Docker Compose 一键部署（推荐）](#b-1-docker-compose-一键部署推荐)
  - [B-2 手动部署（Nginx + waitress + systemd）](#b-2-手动部署nginx--waitress--systemd)
  - [B-3 HTTPS 与域名](#b-3-https-与域名)
  - [B-4 数据备份与迁移](#b-4-数据备份与迁移)
- [四、配置说明](#四配置说明)
- [五、目录结构](#五目录结构)
- [六、常见问题（FAQ）](#六常见问题faq)

---

## 一、环境要求

| 依赖 | 版本要求 | 说明 |
|---|---|---|
| PostgreSQL | 13.x | 数据库（PG 12-15 亦可，需与 PostGIS/pgRouting 版本匹配） |
| PostGIS | 3.x | 空间扩展 |
| pgRouting | 4.0.x | 最短路径扩展 |
| Python | 3.9+ | 后端运行（3.10/3.11 推荐） |
| Node.js | 16+ | 仅构建前端需要（部署包已含构建产物时可选） |
| npm | 8+ | 仅构建前端需要 |

> **Windows** 建议安装 EDB 版 PostgreSQL 13（自带 Stack Builder，可勾选 PostGIS）；pgRouting 需手动安装
> （可从 GitHub Releases 下载对应版本 `postgr esql-13-pgrouting-4.0.1`，注意 32/64 位匹配）。
> **Linux** 建议 `apt install postgresql-13 postgresql-13-postgis-3 postgresql-13-pgrouting`（Ubuntu 20.04+ 自带 pgrouting 包）。

---

## 二、部署方案 A：本地运行（评委评审）

### A-1 一键脚本安装

> 前提：已安装 PostgreSQL 13 + PostGIS + pgRouting，且能通过 `psql` 访问。
> 以下脚本假设数据库超级用户为 `postgres`、密码在脚本首次运行时交互输入或通过环境变量 `PGPASSWORD` 提供。

**Windows（双击运行或命令行执行）：**

```bat
:: 1. 初始化环境 + 恢复数据库（新建 city_life_circle 库并从部署包 dump 恢复）
deploy\scripts\install_windows.bat

:: 2. 启动后端（自动托管前端构建产物，默认 http://localhost:5000）
deploy\scripts\start_windows.bat
```

**Linux / macOS：**

```bash
# 1. 初始化环境 + 恢复数据库
bash deploy/scripts/install_linux.sh

# 2. 启动后端
bash deploy/scripts/start_linux.sh
```

> **推荐：全自动一键脚本（Linux，不依赖 Docker，含 apt 装依赖→建库恢复→低配调优→systemd 服务）**
>
> ```bash
> bash deploy/scripts/deploy_manual_linux.sh
> ```
> 适用于国内服务器（全程 apt/pip，不拉 Docker Hub）。卸载：
> `sudo systemctl disable --now city-life-circle && rm -rf <项目目录>`。

> 脚本会：创建 Python 虚拟环境并安装依赖 → 恢复数据库 → 复制人口瓦片 → （如无前端产物则执行 npm build）。
> 若网络受限（评委无外网），请直接使用部署包内 **已构建好的 `frontend/dist`**，脚本会自动跳过 npm 构建。

### A-2 手动安装步骤（Windows）

**① 恢复数据库**

```bat
set PGPASSWORD=你的密码
psql -U postgres -h localhost -c "CREATE DATABASE city_life_circle;"
pg_restore -U postgres -h localhost -d city_life_circle --no-owner --no-privileges deploy\data\city_life_circle.dump
:: 若 postgis/pgrouting 扩展未随 dump 建好，可先执行：
psql -U postgres -h localhost -d city_life_circle -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS pgrouting;"
```

**② 复制人口瓦片**

```bat
robocopy deploy\data\pop_tiles cache\pop_tiles /E
:: 或：xcopy /E /I /Y deploy\data\pop_tiles cache\pop_tiles
```

**③ 后端环境**

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**④ 前端构建（可选）**

```bat
cd frontend
npm install
npm run build          :: 生成 frontend/dist，后端将自动托管
```

> 部署包已含构建产物 `frontend/dist`，评委机无 Node 环境时跳过此步即可。

**⑤ 启动**

```bat
cd backend
set CLC_DB_PASSWORD=你的密码     :: 与 config.py 默认 admin 一致时可不设
python app.py
```

浏览器访问 **http://localhost:5000**。

### A-3 手动安装步骤（Linux / macOS）

```bash
# ① 恢复数据库
createdb -U postgres city_life_circle
pg_restore -U postgres -d city_life_circle --no-owner --no-privileges deploy/data/city_life_circle.dump
psql -U postgres -d city_life_circle -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS pgrouting;"

# ② 人口瓦片
mkdir -p cache && cp -r deploy/data/pop_tiles cache/pop_tiles

# ③ 后端
cd backend && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# ④ 前端（可选，部署包已含 dist）
cd ../frontend && npm install && npm run build

# ⑤ 启动
cd ../backend && python app.py
```

访问 **http://localhost:5000**。

### A-4 数据库恢复说明

- `deploy/data/city_life_circle.dump` 为 `pg_dump --format=custom` 备份，包含 **18 张表**的全部数据
  （路网 104,132 边、POI 21,243、地铁 169 站、公交 5,530 站、人口格 169,877 等）；
- 恢复使用 `--no-owner --no-privileges`，避免权限/属主不一致问题；
- dump 中已含 `CREATE EXTENSION postgis / pgrouting`（原库带扩展）；若目标机扩展路径不同导致报错，
  可先建库再手动 `CREATE EXTENSION`，或使用 `pg_restore -l` / `--clean` 调整。

### A-5 启动与访问

| 服务 | 默认地址 | 说明 |
|---|---|---|
| 系统入口 | http://localhost:5000 | 后端 `waitress` 直接托管 API + 前端页面 |
| API 健康检查 | http://localhost:5000/api/geocode?keywords=合肥南站 | 返回 JSON 即后端正常 |

- 首次打开：定位默认在合肥市中心（31.861, 117.285）；搜索/选点后点「生成生活圈」；
- 换机运行时数据库密码若不同，用环境变量覆盖（见 [四、配置说明](#四配置说明)）。

---

## 三、部署方案 B：云服务器在线访问

### B-1 Docker Compose 一键部署（推荐）

```bash
# 1. 上传部署包到服务器并解压，进入 docker 目录
cd deploy/docker

# 2. 配置密钥 (可选): 复制模板并填写 高德 key / 天地图 key / npm 镜像源
cp .env.example .env
nano .env        # 或 vim .env; 不填 key 也可, 对应功能自动降级

# 3. 一键启动（首次自动构建镜像并恢复数据）
#    新版插件:  docker compose up -d --build
#    旧版独立命令: docker-compose up -d --build   (v1, 兼容此 compose 文件)
docker-compose up -d --build
```

访问 **http://服务器IP:5000**。

`docker-compose.yml` 结构：

```
┌─────────────────────────────────────────────┐
│  service: db   postgis+pgRouting 13 镜像     │  ← 首次启动自动恢复 dump (数据卷持久化)
│  service: app  python:3.11 + waitress        │  ← 镜像内多阶段构建前端(注入天地图key)
│         │                                     │     + API + 静态页面 (:5000)
└─────────────────────────────────────────────┘
```

> 密钥注入：`deploy/docker/.env` 中的 `AMAP_KEY`（高德，运行时环境变量）与 `VITE_TIANDITU_KEY`
> （天地图，镜像构建时注入前端）。两者均可选，缺失自动降级（底图回退 OSM、地址搜索不可用）。
> 国内服务器若 npm 拉包慢，在 `.env` 设 `NPM_REGISTRY=https://registry.npmmirror.com`。

### B-2 手动部署（Nginx + waitress + systemd）

适用于不想用 Docker、已有服务器的场景：

```bash
# ① 安装 PostgreSQL + PostGIS + pgRouting、Python、Node（同第一节环境要求）
# ② 恢复数据库、复制人口瓦片（同 A-2/A-3 步骤）
# ③ 后端：venv + pip install，并注册 systemd 服务
```

`/etc/systemd/system/city-life-circle.service`：

```ini
[Unit]
Description=City Life Circle Backend
After=network.target postgresql.service

[Service]
User=www-data
WorkingDirectory=/opt/city-life-circle/backend
Environment=CLC_DB_PASSWORD=你的密码
ExecStart=/opt/city-life-circle/backend/.venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now city-life-circle
```

`/etc/nginx/sites-available/city-life-circle`：

```nginx
server {
    listen 80;
    server_name 你的域名或IP;

    # 静态前端（也可直接由后端托管，此配置二选一）
    root /opt/city-life-circle/frontend/dist;
    index index.html;
    location / { try_files $uri $uri/ /index.html; }

    # API 与瓦片反向代理到后端
    location /api/  { proxy_pass http://127.0.0.1:5000; }
    location /tiles/ { proxy_pass http://127.0.0.1:5000; }

    # 大响应/长计算接口
    proxy_read_timeout 120s;
    client_max_body_size 20m;
}
```

```bash
ln -s /etc/nginx/sites-available/city-life-circle /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

### B-3 HTTPS 与域名

使用 Let's Encrypt 免费证书：

```bash
apt install certbot python3-certbot-nginx
certbot --nginx -d 你的域名
```

> 前端代码里对底图/瓦片无协议硬编码，HTTP/HTTPS 均可用；天地图需在 `frontend/.env.local` 配置
> `VITE_TIANDITU_KEY` 后重新 `npm run build`（不配则自动回退 OSM）。

### B-4 数据备份与迁移

```bash
# 备份
pg_dump -h localhost -U postgres -d city_life_circle -Fc -f backup_$(date +%Y%m%d).dump
# 恢复
pg_restore -h localhost -U postgres -d city_life_circle --no-owner --no-privileges backup_xxx.dump
```

仓库内也提供 `scripts/utils/backup_db.py`（自动 `pg_dump` + 打包 cache + 清理旧备份）。

---

## 四、配置说明

后端所有配置均可通过**环境变量**覆盖（默认值为本地开发值），无需改代码：

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `CLC_DB_HOST` | `localhost` | 数据库地址 |
| `CLC_DB_PORT` | `5432` | 数据库端口 |
| `CLC_DB_NAME` | `city_life_circle` | 数据库名 |
| `CLC_DB_USER` | `postgres` | 数据库用户 |
| `CLC_DB_PASSWORD` | `admin` | 数据库密码（**部署时务必修改**） |
| `CLC_WALK_KMH` | `5.0` | 步行速度 km/h |
| `CLC_CYCLE_KMH` | `15.0` | 骑行速度 |
| `CLC_DRIVE_KMH` | `30.0` | 驾车速度 |
| `CLC_METRO_KMH` | `35.0` | 地铁速度 |
| `CLC_BUS_KMH` | `20.0` | 公交平均速度 |

前端：
- `frontend/.env.local` → `VITE_TIANDITU_KEY`（天地图 key，不配则回退 OSM 底图，不影响功能）；
- 高德 key（地理编码/逆地理编码）：由 `scripts/crawlers/config.py` 的 `AMAP_KEY` 或环境变量 `AMAP_KEY` 提供，
  缺失时仅影响"搜索地址/逆地理编码"，核心分析功能不受影响。

> **安全提醒**：演示环境请至少修改数据库密码；线上部署务必配置 HTTPS 并限制数据库仅监听内网。

---

## 五、目录结构

```
city-life-circle/
├── backend/            Flask 后端（引擎 + API）
├── frontend/           Vue 3 前端（src/ 源码，dist/ 构建产物）
├── scripts/            数据采集/处理脚本（爬虫、路网、挂接、导出、备份）
├── docs/               文档（作品介绍、部署说明、对接说明、项目结构等）
├── deploy/
│   ├── data/           数据库备份 city_life_circle.dump + 人口瓦片 pop_tiles/ + 参考导出 exports/
│   ├── scripts/        一键安装/启动脚本（Windows / Linux）
│   ├── docker/         Docker Compose 云部署方案
│   └── config.env.example
└── README.md           快速入门
```

---

## 六、常见问题（FAQ）

**Q1：恢复数据库时报 `extension "postgis" is not available`？**
目标机未安装 PostGIS / pgRouting 扩展，或安装路径未被识别。请先在目标 PostgreSQL 中安装对应扩展
（Windows 用 Stack Builder / 安装包；Linux 用 `apt install postgresql-13-postgis-3 postgresql-13-pgrouting`），
再 `CREATE EXTENSION postgis; CREATE EXTENSION pgrouting;` 后重试恢复。

**Q2：后端启动后页面能打开，但点「生成生活圈」报错？**
多为数据库未连通或扩展缺失。按 A-4 检查恢复日志；用 `curl "http://localhost:5000/api/geocode?keywords=合肥南站"` 验证。

**Q3：地图有底图但无人口密度图层？**
人口瓦片未复制到 `cache/pop_tiles`。执行部署包内的复制步骤，或重新运行 install 脚本。

**Q4：公交/地铁模式提示"公交数据未就绪"？**
数据库恢复不完整或表缺失。确认 `hefei_bus_stops / hefei_bus_line_stops / bus_stop_road_nodes`、
`hefei_metro_*` 等表存在并有数据（用 `\dt` 查看）。

**Q5：评委机无外网，`pip install` / `npm install` 失败？**
部署包已内置 `frontend/dist` 构建产物，前端无需安装 Node；后端如需离线，可在有网机器上
`pip download -r requirements.txt -d wheels/` 后随包分发，并用 `pip install --no-index --find-links wheels/ -r requirements.txt` 安装。

**Q6：端口被占用？**
后端端口默认 5000，可用环境变量无法改端口时，编辑 `backend/app.py` 末尾的 `run_production(app, host=..., port=...)`；
或改用 Nginx 反向代理其他端口。

**Q7：换了一台电脑，数据库密码不同？**
不必改代码，设 `CLC_DB_PASSWORD=新密码` 环境变量后重启后端即可。
