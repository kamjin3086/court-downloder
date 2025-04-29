@echo off
setlocal

echo ============================================
echo  法院文书下载器 - 启动与依赖安装脚本
echo ============================================

set VENV_DIR=venv
set PYTHON_EXE=python

REM --- 检查 Python 环境 ---
echo Checking for Python...
%PYTHON_EXE% --version > NUL 2>&1
if %errorlevel% neq 0 (
    echo Error: Python not found or not added to PATH.
    echo Please install Python 3.10 or higher and ensure it's in PATH.
    goto EndScript
)
echo Python found.

REM --- 设置并激活虚拟环境 ---
echo Checking for virtual environment ('%VENV_DIR%')...
if not exist "%VENV_DIR%\Scripts\activate" (
    echo Creating virtual environment...
    %PYTHON_EXE% -m venv %VENV_DIR%
    if %errorlevel% neq 0 (
        echo Error: Failed to create virtual environment.
        goto EndScript
    )
    echo Virtual environment created.
) else (
    echo Virtual environment found.
)

echo Activating virtual environment...
call "%VENV_DIR%\Scripts\activate"
if %errorlevel% neq 0 (
    echo Error: Failed to activate virtual environment.
    goto EndScript
)

REM --- 安装/检查依赖 ---
echo Checking and installing dependencies from requirements.txt...
REM Using pip install ensures latest versions specified are installed
REM and verifies existing installations.
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo Error: Failed to install dependencies.
    goto EndScript
)
echo Dependencies are up to date.

REM --- 启动应用 ---
echo ============================================
echo Starting Court Downloader application...
echo Access at: http://localhost:8000 or http://127.0.0.1:8000
echo Press CTRL+C in this window to stop the server.
echo ============================================

uvicorn main:app --host 0.0.0.0 --port 8000

echo.
echo Application stopped.

:EndScript
echo.
pause
endlocal 