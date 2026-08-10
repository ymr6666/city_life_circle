# 城市时域生活圈分析系统 —— 评委运行指南

> 本指南只讲一件事：**在本机把系统跑起来并完成演示**。
> 不需要云服务器、不需要 Docker、不需要前端构建（部署包已含构建产物）。
> 全程约 10 分钟。更多细节见 `docs/deployment.md`。

---

## 一、需要预先安装的软件（3 个）

| 软件 | 版本 | 作用 |
|---|---|---|
| PostgreSQL | 12–16 | 数据库 |
| PostGIS + pgRouting | PostGIS 3.x / pgRouting 4.x | 空间与路径计算扩展（分析核心依赖） |
| Python | 3.9+ | 运行后端 |

**Windows**：装 EDB 版 PostgreSQL（安装向导里勾选 Stack Builder，用它装 PostGIS）；pgRouting 从 GitHub Releases 下载 `pgrouting-4.x` 对应你 PG 版本的文件安装。
**macOS**：`brew install postgresql@14 postgis pgrouting python`
**Linux (Ubuntu)**：`sudo apt install postgresql postgresql-14-postgis-3 postgresql-14-pgrouting python3-venv`

---

## 二、三步启动

### 第 1 步：解压部署包
```
城市时域生活圈分析系统_部署包（或 city-life-circle-deploy-*.zip）
```

### 第 2 步：一键初始化（建库 + 恢复数据 + 装依赖）
```
Windows:  双击 deploy\scripts\install_windows.bat     （按提示输入数据库密码）
Linux:    bash deploy/scripts/install_linux.sh
```
> 脚本会自动：创建 `city_life_circle` 库 → 恢复全部数据（路网/POI/地铁/公交/人口）→ 复制人口瓦片 → 安装后端依赖。
> 无外网也没关系——前端构建产物已在包内，脚本会跳过前端安装。

### 第 3 步：启动
```
Windows: 双击 deploy\scripts\start_windows.bat
Linux:   bash deploy/scripts/start_linux.sh
```
浏览器打开 **http://localhost:5000** 即进入系统。

> 数据库密码与默认不符时，启动前设环境变量 `CLC_DB_PASSWORD=你的密码` 即可，无需改代码。

---

## 三、两分钟演示路线（按这个点就够出效果）

1. **生活圈分析**（默认页）：
   - 顶部搜索框输入「合肥南站」→ 搜索；或点「在地图上点选位置」直接点地图；
   - 勾选「步行」和「地铁」，时间 30 分钟 →「生成生活圈」；
   - 看地图上的**真实路网形状等时圈**（含地铁走廊），右侧看设施统计与**宜居评分卡**；
   - 切到「反算选址」，加两个分析点后点「计算覆盖 / 选址」，看绿色**最优选址区**。
2. **分级色彩**：选「医院」，半径 5km →「生成」，看红→绿分级与图例。
3. **全城分析**：切到「全城分析」→「盲区识别」，类别选医院，15 分钟 → 生成，看覆盖/盲区人口。
4. **规划分析**：切到「规划分析」→ 加载研究范围 →「生成选址推荐」，看填补盲区的候选点与多方案对比图。

---

## 四、常见问题

| 现象 | 处理 |
|---|---|
| 一键脚本报"扩展 postgis/pgrouting 不存在" | 说明 PostGIS/pgRouting 没装好，按第一节装好再重跑脚本 |
| 页面能开，点「生成生活圈」报错 | 大概率数据库没恢复成功；重跑 install 脚本，或在 `deploy/data` 下有 `city_life_circle.dump` 时手动：`createdb city_life_circle` + `pg_restore -d city_life_circle deploy/data/city_life_circle.dump` |
| 地图没底图 | 无外网时天地图瓦片加载不出属正常，系统会自动回退 OSM；有网即正常 |
| 底部状态栏提示"地址搜索失败" | 高德 key 未配置（可选功能），不影响核心分析；直接用「在地图上点选位置」即可 |

---

## 五、系统是什么（30 秒介绍）

输入一个地址 → 选择出行方式与时间 → 系统在**真实路网**上算出"能到哪"（等时圈）→ 圈内设施统计 + **五维宜居评分**；反算可求"最优居住选址"；全城视角可看**服务盲区、供需错配**，并能模拟**设施新建/关闭/搬迁**对覆盖人口的影响。数据与算法全部自研（PostGIS + pgRouting），区别于商业网络分析软件。

详细架构、算法与数据规模见 `docs/project_intro.md`。
