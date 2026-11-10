# -*- coding: utf-8 -*-
"""最近打开文件的历史记录。

职责：
- 记录打开过的文件路径，按最近打开顺序排列（最近的在最前）。
- 同一文件不重复：路径规范化（Windows 下大小写不敏感）后相同即视为同一文件，
  再次打开时移动到最前。
- 限制最大条数 ``MAX_ITEMS``，超出时丢弃最旧的记录。
- 通过 ``QSettings`` 持久化（Windows 下存于注册表 HKCU\\Software\\MarkdownReader）。

本模块仅依赖 QtCore（QSettings），不依赖界面，便于单元测试。
"""
from __future__ import annotations

import os
from typing import List

from PySide6 import QtCore

_SETTINGS_ORG = "MarkdownReader"
_SETTINGS_APP = "MarkdownReader"
_KEY = "history/files"


class FileHistory:
    """最近打开文件列表（排序 / 去重逻辑 + QSettings 持久化）。"""

    MAX_ITEMS = 20

    def __init__(self) -> None:
        self._settings = QtCore.QSettings(_SETTINGS_ORG, _SETTINGS_APP)

    # ------------------------------------------------------------------
    def items(self) -> List[str]:
        """返回历史路径列表（最近打开的在最前）。"""
        raw = self._settings.value(_KEY, [])
        if raw is None:
            return []
        if isinstance(raw, str):  # 兼容单值存储
            raw = [raw] if raw else []
        return [str(p) for p in raw]

    def record(self, path: str) -> None:
        """记录一次打开：去重后插到最前，并应用数量上限。"""
        path = os.path.abspath(path)
        key = os.path.normcase(path)
        rest = [p for p in self.items() if os.path.normcase(os.path.abspath(p)) != key]
        self._save([path] + rest)

    def remove(self, path: str) -> None:
        """移除指定路径（例如文件已被移动 / 删除时）。"""
        key = os.path.normcase(os.path.abspath(path))
        self._save(
            [p for p in self.items() if os.path.normcase(os.path.abspath(p)) != key]
        )

    def clear(self) -> None:
        """清空全部历史记录。"""
        self._settings.remove(_KEY)

    # ------------------------------------------------------------------
    def _save(self, paths: List[str]) -> None:
        self._settings.setValue(_KEY, paths[: self.MAX_ITEMS])
