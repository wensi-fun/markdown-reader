@echo off
chcp 65001 >nul
title Markdown 阅读器
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.9 或更高版本，
    echo        安装时务必勾选 "Add Python to PATH"。
    echo        下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/2] 检查并安装依赖（首次运行需联网，请稍候）...
set MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
python -m pip install -r requirements.txt --disable-pip-version-check -i %MIRROR%
if errorlevel 1 (
    echo [提示] 镜像源不可用，改用官方源重试...
    python -m pip install -r requirements.txt --disable-pip-version-check
)
if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
)

echo [2/2] 启动 Markdown 阅读器...
python main.py %*
if errorlevel 1 pause
