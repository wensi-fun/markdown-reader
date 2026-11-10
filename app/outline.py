# -*- coding: utf-8 -*-
"""左侧大纲树控件。

- 依据标题层级构建可折叠的树形结构，子级自动缩进。
- 点击某个标题时发出 ``headingClicked`` 信号（携带标题索引）。
- 支持 ``highlight(index)`` 让外部（如光标移动）同步高亮当前标题。
- 支持 ``set_search_highlight(keyword)``：把包含查找词的标题标黄，
  仅作为视觉提示（不影响点击跳转与光标）。
"""
from __future__ import annotations

from typing import List

from PySide6 import QtCore, QtGui, QtWidgets

from .markdown_parser import Heading

# 自定义数据角色：保存该条目对应的标题索引
HEADING_INDEX_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1

# 查找命中标题的背景色（与正文高亮的黄色一致，仅用于展示）
SEARCH_HL_COLOR = "#fff59d"


class OutlineTree(QtWidgets.QTreeWidget):
    """大纲树。"""

    headingClicked = QtCore.Signal(int)  # 参数：标题在 outline 列表中的索引

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("OutlineTree")
        self.setHeaderHidden(True)
        self.setIndentation(16)
        self.setAnimated(True)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._headings: List[Heading] = []
        self._index_by_item: dict = {}
        self._syncing = False
        self._search_keyword = ""

        self.itemClicked.connect(self._on_item_clicked)

    # ------------------------------------------------------------------
    def rebuild(self, headings: List[Heading]) -> None:
        """根据标题列表重建整棵树，尽量保持原展开状态与选中项。"""
        prev_expanded = self._collect_expanded_keys()
        prev_selected = self._selected_index()
        first_build = self.topLevelItemCount() == 0
        # 仅当文档结构（数量/层级/标题文字）完全一致时才沿用展开状态；
        # 打开另一份文档或增删标题时全部展开，避免大部分目录被折叠。
        same_structure = (
            len(headings) == len(self._headings)
            and [h.level for h in headings] == [h.level for h in self._headings]
            and [h.text for h in headings] == [h.text for h in self._headings]
        )

        self._syncing = True
        self.clear()
        self._headings = list(headings)
        self._index_by_item = {}

        # 用栈维护各层级的父节点
        stack: List[tuple] = []  # (level, QTreeWidgetItem)
        for idx, h in enumerate(headings):
            item = QtWidgets.QTreeWidgetItem([h.text or "(空标题)"])
            item.setData(0, HEADING_INDEX_ROLE, idx)
            item.setToolTip(0, f"{'#' * h.level} {h.text}")
            # 依据层级找到父节点
            while stack and stack[-1][0] >= h.level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(item)
            else:
                self.addTopLevelItem(item)
            stack.append((h.level, item))
            self._index_by_item[item] = idx

        # 恢复展开状态（首次构建默认全部展开；后续按之前的展开状态恢复）
        self.expandAll()
        if not first_build and same_structure:
            self._apply_expanded(prev_expanded)

        self._syncing = False
        self._apply_search_highlight()  # 重建后恢复查找高亮（如有）
        if prev_selected is not None and 0 <= prev_selected < len(headings):
            self.highlight(prev_selected)

    # ------------------------------------------------------------------
    def _collect_expanded_keys(self) -> set:
        # 用标题索引作为 key：编辑标题文字不会导致展开状态丢失
        keys = set()
        it = QtWidgets.QTreeWidgetItemIterator(self)
        while it.value():
            item = it.value()
            idx = item.data(0, HEADING_INDEX_ROLE)
            if item.isExpanded() and idx is not None:
                keys.add(int(idx))
            it += 1
        return keys

    def _apply_expanded(self, keys: set) -> None:
        it = QtWidgets.QTreeWidgetItemIterator(self)
        while it.value():
            item = it.value()
            idx = item.data(0, HEADING_INDEX_ROLE)
            if idx is not None and int(idx) not in keys:
                item.setExpanded(False)
            it += 1

    def _selected_index(self):
        items = self.selectedItems()
        if not items:
            return None
        return items[0].data(0, HEADING_INDEX_ROLE)

    def _item_by_index(self, index: int):
        for item, idx in self._index_by_item.items():
            if idx == index:
                return item
        return None

    # ------------------------------------------------------------------
    def set_search_highlight(self, keyword: str) -> None:
        """标出标题中包含查找词的条目（仅视觉提示，不参与光标定位）。"""
        self._search_keyword = (keyword or "").strip().lower()
        self._apply_search_highlight()

    def _apply_search_highlight(self) -> None:
        brush = QtGui.QBrush(QtGui.QColor(SEARCH_HL_COLOR))
        empty = QtGui.QBrush()
        it = QtWidgets.QTreeWidgetItemIterator(self)
        while it.value():
            item = it.value()
            hit = bool(self._search_keyword) and \
                self._search_keyword in item.text(0).lower()
            font = item.font(0)
            if font.bold() != hit:
                font.setBold(hit)  # 命中条目加粗，更醒目
                item.setFont(0, font)
            if hit:
                item.setBackground(0, brush)
            else:
                item.setBackground(0, empty)
            it += 1

    # ------------------------------------------------------------------
    def _on_item_clicked(self, item, column) -> None:
        if self._syncing:
            return
        idx = item.data(0, HEADING_INDEX_ROLE)
        if idx is not None:
            self.headingClicked.emit(int(idx))

    def highlight(self, index: int) -> None:
        """高亮指定索引的标题（不触发 headingClicked）。"""
        item = self._item_by_index(index)
        if item is None:
            return
        self._syncing = True
        # 展开全部祖先节点，确保选中项可见（目录收起时点击也应能看到焦点）
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.setCurrentItem(item)
        self.scrollToItem(item, QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter)
        self._syncing = False

    def clear_selection(self) -> None:
        self._syncing = True
        self.clearSelection()
        self.setCurrentItem(None)
        self._syncing = False
