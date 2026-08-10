@echo off
REM =====================================================================
REM  城市时域生活圈分析系统 - Windows 启动脚本
REM  用法: 双击运行, 或命令行执行 start_windows.bat
REM =====================================================================
chcp 65001 >nul
cd /d "%~dp0..\.."

if not exist "backend\.venv\Scripts\activate.bat" (
  echo [错误] 尚未安装后端依赖, 请先运行 deploy\scripts\install_windows.bat
  pause & exit /b 1
)

echo 启动后端 (waitress, http://localhost:5000)...
call backend\.venv\Scripts\activate.bat
cd backend
set "PYTHONUNBUFFERED=1"
python app.py
