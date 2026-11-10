@echo off
chcp 65001 >nul
title 打包 Markdown 阅读器为 EXE
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.9 或更高版本，
    echo        安装时务必勾选 "Add Python to PATH"。
    pause
    exit /b 1
)

echo [1/3] 安装运行依赖...
set MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
python -m pip install -r requirements.txt --disable-pip-version-check -i %MIRROR%
if errorlevel 1 (
    echo [提示] 镜像源不可用，改用官方源重试...
    python -m pip install -r requirements.txt --disable-pip-version-check
)
if errorlevel 1 goto :fail

echo [2/3] 安装 PyInstaller...
python -m pip install pyinstaller --disable-pip-version-check -i %MIRROR%
if errorlevel 1 (
    echo [提示] 镜像源不可用，改用官方源重试...
    python -m pip install pyinstaller --disable-pip-version-check
)
if errorlevel 1 goto :fail

echo [3/4] 打包 文件夹版（启动快，自用推荐）...
python -m PyInstaller --noconfirm --clean ^
    --name MarkdownReader ^
    --onedir ^
    --windowed ^
    --icon "assets\icon.ico" ^
    --add-data "assets\icon.ico;assets" ^
    --collect-all markdown ^
    --collect-all docx ^
    main.py
if errorlevel 1 goto :fail

echo [4/4] 打包 单文件版（方便单个文件分发）...
python -m PyInstaller --noconfirm --clean ^
    --name MarkdownReader ^
    --onefile ^
    --windowed ^
    --icon "assets\icon.ico" ^
    --add-data "assets\icon.ico;assets" ^
    --collect-all markdown ^
    --collect-all docx ^
    main.py
if errorlevel 1 goto :fail

echo.
echo [提示] 附上使用帮助文档...
if exist "使用帮助.md" (
    copy /y "使用帮助.md" "dist\使用帮助.md" >nul
    copy /y "使用帮助.md" "dist\MarkdownReader\使用帮助.md" >nul
)

echo 打包完成！产出两个版本：
echo   1. dist\MarkdownReader\MarkdownReader.exe  文件夹版：启动最快，整个文件夹一起用
echo   2. dist\MarkdownReader.exe                  单文件版：启动稍慢（需解压），发人方便
echo 均可复制到任意 Windows 电脑运行（目标机器无需安装 Python）。
echo 两个版本的旁边都已附带《使用帮助.md》，发人时请一起拷贝。
echo.
pause
exit /b 0

:fail
echo.
echo [错误] 打包失败，请查看上方输出定位问题。
pause
exit /b 1
