# -*- coding: utf-8 -*-
"""左侧/解码前编辑控件（Markdown 源码编辑）。

基于 ``QPlainTextEdit``。提供：
- 行号友好的等宽编辑体验。
- ``highlight_search(keyword)``：高亮全部匹配（当前匹配橙色、其余黄色），
  并把光标定位到第一个匹配。
- ``find_next(keyword)``：回车查找下一个匹配（到尾后循环回绕）。
- ``goto_line(line)``：跳到指定行并把该行置于视口顶部附近。
"""
from __future__ import annotations

from typing import List, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

_FIRST_BG = "#ff9800"  # 当前匹配：橙色
_REST_BG = "#fff59d"   # 其余匹配：黄色


class MarkdownEditor(QtWidgets.QPlainTextEdit):
    """Markdown 源码编辑器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Editor")
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._search_selections: List[QtWidgets.QTextEdit.ExtraSelection] = []
        self._match_cursors: List[QtGui.QTextCursor] = []
        self._keyword = ""
        self._current_match = -1

    # ------------------------------------------------------------------
    def goto_line(self, line: int, center: bool = True) -> None:
        """把光标定位到第 line 行（0-based）。"""
        block = self.document().findBlockByNumber(max(0, line))
        if not block.isValid():
            return
        cursor = QtGui.QTextCursor(block)
        self.setTextCursor(cursor)
        if center:
            self.centerCursor()
        else:
            self.ensureCursorVisible()

    # ------------------------------------------------------------------
    def highlight_search(self, keyword: str) -> int:
        """实时高亮全部匹配（当前匹配橙色、其余黄色），光标跳到首个。

        返回匹配总数。
        """
        if not keyword:
            self.clear_search()
            return 0
        self._scan_matches(keyword)
        if not self._match_cursors:
            return 0
        self._current_match = 0
        self._apply_match_formats()
        self._goto_current_match()
        return len(self._match_cursors)

    def find_next(self, keyword: str) -> Tuple[int, int]:
        """回车：选中下一个匹配（到尾后循环回绕）。

        返回 (当前序号 1-based, 匹配总数)；无匹配时返回 (0, 0)。
        """
        if not keyword:
            return (0, 0)
        if keyword != self._keyword or not self._match_cursors:
            # 关键词变化或尚未扫描：重新扫描，落到第一个匹配
            self._scan_matches(keyword)
            if not self._match_cursors:
                self._current_match = -1
                return (0, 0)
            self._current_match = 0
        else:
            # 找当前光标之后的下一个匹配，没有则回绕到第一个
            pos = self.textCursor().selectionEnd()
            nxt = 0
            for i, match in enumerate(self._match_cursors):
                if match.selectionStart() >= pos:
                    nxt = i
                    break
            self._current_match = nxt
        self._apply_match_formats()
        self._goto_current_match()
        return (self._current_match + 1, len(self._match_cursors))

    def match_count(self) -> int:
        return len(self._match_cursors)

    # ---- 内部 ----
    def _scan_matches(self, keyword: str) -> None:
        """扫描全部匹配位置（不改动光标与现有高亮）。"""
        self._keyword = keyword
        self._match_cursors = []
        doc = self.document()
        cursor = QtGui.QTextCursor(doc)
        while True:
            cursor = doc.find(keyword, cursor)
            if cursor.isNull():
                break
            self._match_cursors.append(QtGui.QTextCursor(cursor))

    def _apply_match_formats(self) -> None:
        """按当前匹配序号重新着色：当前橙色、其余黄色。"""
        first_fmt = QtGui.QTextCharFormat()
        first_fmt.setBackground(QtGui.QColor(_FIRST_BG))
        first_fmt.setForeground(QtGui.QColor("#000000"))

        rest_fmt = QtGui.QTextCharFormat()
        rest_fmt.setBackground(QtGui.QColor(_REST_BG))
        rest_fmt.setForeground(QtGui.QColor("#000000"))

        selections: List[QtWidgets.QTextEdit.ExtraSelection] = []
        for i, match in enumerate(self._match_cursors):
            sel = QtWidgets.QTextEdit.ExtraSelection()
            sel.cursor = match
            sel.format = first_fmt if i == self._current_match else rest_fmt
            selections.append(sel)
        self._search_selections = selections
        self.setExtraSelections(selections)

    def _goto_current_match(self) -> None:
        if 0 <= self._current_match < len(self._match_cursors):
            cursor = QtGui.QTextCursor(self._match_cursors[self._current_match])
            self.setTextCursor(cursor)
            self.centerCursor()

    def clear_search(self) -> None:
        self._match_cursors = []
        self._keyword = ""
        self._current_match = -1
        self._search_selections = []
        self.setExtraSelections([])
