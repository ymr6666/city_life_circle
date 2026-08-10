@echo off
REM =====================================================================
REM  城市时域生活圈分析系统 - Windows 一键安装脚本
REM  功能: 创建Python虚拟环境+安装依赖 / 恢复数据库 / 复制人口瓦片 / 构建前端(可选)
REM  前提: PostgreSQL 13 + PostGIS + pgRouting 已安装并启动
REM  用法: 双击运行, 或命令行执行 install_windows.bat
REM =====================================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0..\.."

echo [1/5] 检查 Python...
python --version >nul 2>&1 || (echo [错误] 未找到 Python, 请先安装 Python 3.9+ & pause & exit /b 1)
echo       Python OK

echo [2/5] 检查 PostgreSQL 客户端 (psql / pg_restore)...
where psql >nul 2>&1 && where pg_restore >nul 2>&1
if errorlevel 1 (
  echo       未在 PATH 找到 psql/pg_restore, 请手动将它们加入 PATH 或按 Ctrl+C 取消后修改
  echo       (典型位置: C:\Program Files\PostgreSQL\13\bin)
  set "PG_BIN="
  set /p PG_BIN="请输入 PostgreSQL bin 目录路径(回车跳过): "
  if not "!PG_BIN!"=="" set "PATH=!PG_BIN!;!PATH!"
)
where psql >nul 2>&1 || (echo [错误] 仍无法找到 psql & pause & exit /b 1)

set "PGPASSWORD="
set /p PGPASSWORD="请输入 postgres 数据库密码: "

echo [3/5] 恢复数据库 (city_life_circle)...
psql -U postgres -h localhost -tc "SELECT 1 FROM pg_database WHERE datname='city_life_circle'" | findstr /C:"1" >nul || (
  psql -U postgres -h localhost -c "CREATE DATABASE city_life_circle;" || (echo [错误] 建库失败 & pause & exit /b 1)
)
pg_restore -U postgres -h localhost -d city_life_circle --no-owner --no-privileges --clean --if-exists "deploy\data\city_life_circle.dump"
if errorlevel 1 (echo [警告] 恢复命令报错, 请检查扩展 postgis/pgrouting 是否已安装 & pause & exit /b 1)
psql -U postgres -h localhost -d city_life_circle -c "CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS pgrouting;" >nul 2>&1
echo       数据库恢复完成

echo [4/5] 复制人口瓦片到 cache\pop_tiles...
if exist "cache\pop_tiles" rd /s /q "cache\pop_tiles"
if exist "deploy\data\pop_tiles" robocopy "deploy\data\pop_tiles" "cache\pop_tiles" /E /NFL /NDL /NJH >nul
if not exist "cache\pop_tiles" (echo [警告] 未找到 deploy\data\pop_tiles & pause)
echo       瓦片复制完成

echo [5/5] 后端依赖 (Python 虚拟环境)...
if not exist "backend\.venv" python -m venv backend\.venv
call backend\.venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>&1
pip install -r backend\requirements.txt || (echo [错误] 依赖安装失败 & pause & exit /b 1)
echo       后端依赖安装完成

echo.
echo ============================================================
echo  安装完成!
echo  启动: 运行 deploy\scripts\start_windows.bat
echo  访问: http://localhost:5000
echo  详细说明: docs\部署说明.md
echo ============================================================
pause
