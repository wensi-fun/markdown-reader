# -*- coding: utf-8 -*-
"""Markdown 阅读器（Typora 风格）—— 程序入口。

运行：
    python main.py [要打开的 .md 文件]
"""
import os
import sys

# 确保以脚本方式直接运行时能导入 app 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from app.main_window import MainWindow  # noqa: E402


def _resource_path(rel: str) -> str:
    """资源文件路径：兼容源码运行与 PyInstaller 打包（--onefile）后的环境。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def main() -> int:
    # 高 DPI 支持（Qt6 默认开启，这里显式设置缩放策略）
    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
        QtCore.Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Markdown Reader")
    app.setApplicationDisplayName("Markdown 阅读器")
    app.setOrganizationName("MarkdownReader")  # QSettings 历史记录持久化用
    app.setFont(QtGui.QFont("Microsoft YaHei", 10))

    # 应用图标（标题栏 / 任务栏）
    icon_path = _resource_path(os.path.join("assets", "icon.ico"))
    if os.path.isfile(icon_path):
        app.setWindowIcon(QtGui.QIcon(icon_path))

    win = MainWindow()

    # 命令行参数：直接打开某个文件
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args and os.path.isfile(args[0]):
        win.open_path(args[0])

    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
