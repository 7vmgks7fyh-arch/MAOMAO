@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" goto LAUNCH

echo ==================================================
echo   首次运行：正在为星辰猫猫桌宠准备 Python 环境...
echo ==================================================

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+ 并勾选 "Add Python to PATH"。
    pause
    exit /b 1
)

python -m venv .venv
if errorlevel 1 (
    echo [错误] 创建虚拟环境失败，请检查 Python 安装是否完整。
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\pip.exe" install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络连接后重试。
    pause
    exit /b 1
)

:LAUNCH
echo 正在召唤 Antigravity 星辰猫猫桌宠...
start "" ".venv\Scripts\pythonw.exe" "main.py"
exit /b 0
