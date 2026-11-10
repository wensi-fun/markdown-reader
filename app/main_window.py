# -*- coding: utf-8 -*-
"""主窗口：整合工具栏、大纲、编辑/预览、查找、主题、导出、拖拽打开。"""
from __future__ import annotations

import os
from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from . import __version__, exporter
from .editor import MarkdownEditor
from .history import FileHistory
from .markdown_parser import Heading, detect_encoding, extract_outline, markdown_to_html, read_text_file
from .outline import OutlineTree
from .preview import PreviewView, set_doc_base_dir
from .themes import build_qss, get_theme

WELCOME_MD = """# 欢迎使用 Markdown 阅读器

这是一个 **Typora 风格** 的双栏 Markdown 阅读器 / 编辑器。

## 功能一览

- 左栏：按层级缩进的**大纲**，点击即可跳转；标题行末尾按钮一键全部收起/展开
- 顶部：在「编辑」（源码）与「预览」（渲染）之间切换；**F11** 隐藏/恢复工具栏
- 查找：**Ctrl+F**，当前匹配**橙色**、其余匹配**黄色**，回车查找下一个；大纲命中标题同步标黄
- 打开：拖拽文件或点「打开文件」（自动识别编码）；**Ctrl+H** 查看最近打开的文件
- 图片：正文中的本地图片（相对路径）直接在预览区渲染，超宽图片自动缩放
- 导出：PDF 与 DOCX（正式排版：宋体正文、1.5 倍行距、页眉页码、封面大标题、真表格）

### 代码块示例

```python
def hello(name):
    # 代码块内的 # 不会干扰大纲
    print(f"Hello, {name}!")
```

### 引用与表格

> 这是一段引用文字。

| 功能 | 状态 |
| --- | --- |
| 大纲 | ✅ |
| 查找 | ✅ |

---

现在，试试编辑左侧文本，或打开一个 .md 文件吧！
"""


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Markdown 阅读器")
        self.resize(1180, 760)
        self.setAcceptDrops(True)

        self._current_path: Optional[str] = None
        self._theme_name = "light"  # 固定白色主题
        self.history = FileHistory()
        self._headings: List[Heading] = []
        self._mode = "preview"  # preview / source
        self._syncing_outline = False
        self._outline_collapsed = False  # 大纲是否处于「全部收起」状态
        self._outline_current = -1       # 当前大纲高亮索引（预览滚动同步用）
        self._suppress_outline_sync = False  # 点击跳转期间暂停「滚动 → 大纲」同步

        # 防抖：编辑后延迟刷新
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(220)
        self._refresh_timer.timeout.connect(self._refresh_from_editor)

        self._build_ui()
        self._build_toolbar()
        self._apply_theme()

        # 载入欢迎内容
        self._load_markdown(WELCOME_MD, path=None, encoding="utf-8")

    # ==================================================================
    # UI 构建
    # ==================================================================
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)

        # ---- 左：大纲 ----
        left = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # 标题行：「大纲」+ 全部收起/展开切换按钮
        title_row = QtWidgets.QWidget()
        title_row.setObjectName("OutlineTitleRow")
        row_layout = QtWidgets.QHBoxLayout(title_row)
        row_layout.setContentsMargins(10, 8, 6, 4)
        row_layout.setSpacing(4)
        self.outline_title = QtWidgets.QLabel("大纲")
        self.outline_title.setObjectName("OutlineTitle")
        row_layout.addWidget(self.outline_title)
        row_layout.addStretch(1)
        self.outline_toggle_btn = QtWidgets.QToolButton()
        self.outline_toggle_btn.setObjectName("OutlineToggle")
        self.outline_toggle_btn.setText("▲")
        self.outline_toggle_btn.setToolTip("全部收起")
        self.outline_toggle_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.outline_toggle_btn.clicked.connect(self._toggle_outline_expand)
        row_layout.addWidget(self.outline_toggle_btn)
        left_layout.addWidget(title_row)

        self.outline = OutlineTree()
        self.outline.headingClicked.connect(self._on_outline_clicked)
        left_layout.addWidget(self.outline, 1)

        # ---- 右：编辑/预览 堆叠 ----
        self.stack = QtWidgets.QStackedWidget()
        self.editor = MarkdownEditor()
        self.editor.textChanged.connect(self._on_editor_changed)
        self.editor.cursorPositionChanged.connect(self._on_editor_cursor)
        self.preview = PreviewView()
        # 预览滚动 → 大纲高亮当前所在章节（与点击后的选中效果一致）
        self.preview.verticalScrollBar().valueChanged.connect(self._on_preview_scrolled)
        self.stack.addWidget(self.editor)    # index 0 = 编辑
        self.stack.addWidget(self.preview)   # index 1 = 预览
        self.stack.setCurrentWidget(self.preview)  # 默认展示阅读界面（预览）

        self.splitter.addWidget(left)
        self.splitter.addWidget(self.stack)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([280, 900])
        self.splitter.setCollapsible(0, False)

        outer.addWidget(self.splitter, 1)

        # ---- 状态栏 ----
        self.status = QtWidgets.QLabel("就绪")
        self.status.setObjectName("StatusLabel")
        self.statusBar().addWidget(self.status)

    def _build_toolbar(self) -> None:
        tb = QtWidgets.QToolBar("MainToolBar")
        tb.setObjectName("MainToolBar")
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(18, 18))
        self.addToolBar(tb)
        self.toolbar = tb

        # 防止工具栏被误隐藏：禁用其「可见性切换」入口（配合 createPopupMenu）
        tb.toggleViewAction().setEnabled(False)

        # 打开文件
        act_open = QtGui.QAction("📂 打开文件", self)
        act_open.setToolTip("打开一个 Markdown 文件（Ctrl+O）")
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self.open_file_dialog)
        tb.addAction(act_open)

        # 历史记录：下拉列出最近打开的文件
        self.history_btn = QtWidgets.QToolButton()
        self.history_btn.setObjectName("HistoryButton")
        self.history_btn.setText("🕘 历史记录")
        self.history_btn.setToolTip("查看最近打开的文件（Ctrl+H）")
        self.history_btn.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.history_menu = QtWidgets.QMenu(self.history_btn)
        self.history_menu.aboutToShow.connect(self._rebuild_history_menu)
        self.history_btn.setMenu(self.history_menu)
        tb.addWidget(self.history_btn)

        tb.addSeparator()

        # 编辑 / 预览 切换（初始为「预览」阅读界面）
        self.act_toggle = QtGui.QAction("✏️ 编辑", self)
        self.act_toggle.setToolTip("当前为「预览」，点击切换到编辑视图（Ctrl+D）")
        self.act_toggle.setShortcut("Ctrl+D")
        self.act_toggle.triggered.connect(self.toggle_mode)
        tb.addAction(self.act_toggle)

        tb.addSeparator()

        # 查找
        tb.addWidget(QtWidgets.QLabel(" 查找："))
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setObjectName("SearchBox")
        self.search_box.setPlaceholderText("输入关键词，回车查找下一个…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.setFixedWidth(200)
        self.search_box.returnPressed.connect(self.find_next)
        self.search_box.textChanged.connect(self._on_search_text_changed)
        tb.addWidget(self.search_box)

        # 快捷键：Ctrl+F 聚焦查找框；F11 隐藏/显示工具栏；Ctrl+H 历史记录
        sc_find = QtGui.QShortcut(QtGui.QKeySequence.StandardKey.Find, self)
        sc_find.activated.connect(self.focus_search)

        sc_f11 = QtGui.QShortcut(QtGui.QKeySequence("F11"), self)
        sc_f11.activated.connect(self.toggle_toolbar)

        sc_hist = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+H"), self)
        sc_hist.activated.connect(self.show_history)

        tb.addSeparator()

        # 导出
        act_pdf = QtGui.QAction("📄 导出 PDF", self)
        act_pdf.triggered.connect(self.export_pdf_dialog)
        tb.addAction(act_pdf)

        act_docx = QtGui.QAction("📝 导出 DOCX", self)
        act_docx.triggered.connect(self.export_docx_dialog)
        tb.addAction(act_docx)

        tb.addSeparator()

        # 关于（版本信息 / 作者）
        act_about = QtGui.QAction("ℹ️ 关于", self)
        act_about.setToolTip("关于本软件（版本信息 / 作者）")
        act_about.triggered.connect(self.show_about)
        tb.addAction(act_about)

    # ==================================================================
    # 内容载入 / 刷新
    # ==================================================================
    def _load_markdown(self, text: str, path: Optional[str], encoding: str = "utf-8") -> None:
        self._current_path = path
        self._syncing_outline = True
        self.editor.setPlainText(text)
        self._syncing_outline = False
        self._refresh_from_editor()
        self._update_title(encoding)

    def _refresh_from_editor(self) -> None:
        """重新解析大纲并重渲染预览。"""
        text = self.editor.toPlainText()
        # 1) 大纲
        self._headings = extract_outline(text)
        self._outline_current = -1
        self.outline.rebuild(self._headings)
        # 2) 预览
        html = markdown_to_html(text)
        css = get_theme(self._theme_name).preview_css
        self.preview.set_markdown_html(html, css, self._current_base_dir())
        # 3) 若当前有查找关键词，重新应用高亮
        kw = self.search_box.text()
        if kw:
            self._apply_search_to_active(kw)
        # 4) 更新状态
        words = len(text)
        self.status.setText(
            f"标题 {len(self._headings)} 个 ｜ 字符 {words} ｜ "
            f"模式：{'预览（渲染）' if self._mode == 'preview' else '编辑（源码）'}"
        )
        # 5) 预览滚动位置与大纲同步
        self._on_preview_scrolled()

    def _update_title(self, encoding: str = "") -> None:
        name = os.path.basename(self._current_path) if self._current_path else "未命名"
        enc = f" ｜ 编码 {encoding}" if encoding else ""
        self.setWindowTitle(f"{name} - Markdown 阅读器")
        if encoding:
            self.status.setText(f"已打开 {name}{enc}")

    def _current_base_dir(self) -> str:
        """当前打开文件所在目录（用于解析相对路径图片等资源）。"""
        return os.path.dirname(self._current_path) if self._current_path else ""

    # ==================================================================
    # 模式切换
    # ==================================================================
    def toggle_mode(self) -> None:
        if self._mode == "preview":
            self._mode = "source"
            self.stack.setCurrentWidget(self.editor)
            self.act_toggle.setText("👁 预览")
            self.act_toggle.setToolTip("当前为「编辑」，点击切换到预览视图")
        else:
            self._mode = "preview"
            # 切到预览前确保内容最新
            self._refresh_from_editor()
            self.stack.setCurrentWidget(self.preview)
            self.act_toggle.setText("✏️ 编辑")
            self.act_toggle.setToolTip("当前为「预览」，点击切换到编辑视图")
        # 重新应用查找
        kw = self.search_box.text()
        if kw:
            self._apply_search_to_active(kw)
        self._refresh_status_mode()
        if self._mode == "preview":
            self._outline_current = -1
            self._on_preview_scrolled()

    def _refresh_status_mode(self) -> None:
        text = self.editor.toPlainText()
        self.status.setText(
            f"标题 {len(self._headings)} 个 ｜ 字符 {len(text)} ｜ "
            f"模式：{'预览（渲染）' if self._mode == 'preview' else '编辑（源码）'}"
        )

    # ==================================================================
    # 大纲交互
    # ==================================================================
    def _toggle_outline_expand(self) -> None:
        """大纲「全部收起 / 全部展开」切换（标题行末尾按钮）。"""
        self._outline_collapsed = not self._outline_collapsed
        if self._outline_collapsed:
            self.outline.collapseAll()
            self.outline_toggle_btn.setText("▼")
            self.outline_toggle_btn.setToolTip("全部展开")
        else:
            self.outline.expandAll()
            self.outline_toggle_btn.setText("▲")
            self.outline_toggle_btn.setToolTip("全部收起")

    def _on_outline_clicked(self, index: int) -> None:
        if index < 0 or index >= len(self._headings):
            return
        # 点击跳转引起的滚动不应反过来覆盖用户点击选中项：
        # 跳转期间抑制「滚动 → 大纲」同步，等最后一轮滚动事件处理完再恢复。
        self._outline_current = index
        self._suppress_outline_sync = True
        try:
            # 显式保持选中（真实点击由 QTreeWidget 选中，程序调用需手动同步）
            self.outline.highlight(index)
            h = self._headings[index]
            if self._mode == "source":
                self.editor.goto_line(h.line, center=True)
            else:
                self.preview.scroll_to_heading(index)
        finally:
            QtCore.QTimer.singleShot(0, self._end_outline_sync_suppression)

    def _end_outline_sync_suppression(self) -> None:
        """程序性滚动结束后恢复大纲跟随（下一轮事件循环）。"""
        self._suppress_outline_sync = False

    def _on_editor_cursor(self) -> None:
        """编辑器光标移动时，反向高亮对应大纲标题（最近的上方标题）。"""
        if self._syncing_outline or self._mode != "source":
            return
        line = self.editor.textCursor().blockNumber()
        idx = -1
        for i, h in enumerate(self._headings):
            if h.line <= line:
                idx = i
            else:
                break
        if idx >= 0:
            self._outline_current = idx
            self.outline.highlight(idx)

    def _on_preview_scrolled(self, _value: int = 0) -> None:
        """预览滚动时，大纲高亮当前所在章节（与点击后的选中效果一致）。"""
        if self._mode != "preview" or self._suppress_outline_sync:
            return
        idx = self.preview.current_heading_index()
        if idx < 0 or idx == self._outline_current:
            return
        self._outline_current = idx
        self.outline.highlight(idx)

    # ==================================================================
    # 编辑同步
    # ==================================================================
    def _on_editor_changed(self) -> None:
        if self._syncing_outline:
            return
        self._refresh_timer.start()

    # ==================================================================
    # 查找
    # ==================================================================
    def _on_search_text_changed(self, text: str) -> None:
        # 实时查找（空则清除）
        if not text:
            self.clear_search()
        else:
            self.do_search()

    def do_search(self) -> None:
        """实时查找：高亮全部匹配并跳到第一个。"""
        kw = self.search_box.text()
        if not kw:
            self.clear_search()
            return
        self._apply_search_to_active(kw)

    def find_next(self) -> None:
        """回车：跳到下一个匹配（到尾后循环回绕）。"""
        kw = self.search_box.text()
        if not kw:
            return
        if self._mode == "source":
            pos, total = self.editor.find_next(kw)
        else:
            pos, total = self.preview.find_next(kw)
        if total:
            self.status.setText(f"匹配 {pos}/{total} 处「{kw}」（回车查找下一个）")
        else:
            self.status.setText(f"未找到「{kw}」")

    def _apply_search_to_active(self, kw: str) -> None:
        if self._mode == "source":
            n = self.editor.highlight_search(kw)
        else:
            n = self.preview.highlight_search(kw)
        # 大纲同步高亮命中的标题（仅展示，不参与光标定位）
        self.outline.set_search_highlight(kw)
        if n:
            self.status.setText(f"找到 {n} 处匹配「{kw}」（回车查找下一个）")
        else:
            self.status.setText(f"未找到「{kw}」")

    def clear_search(self) -> None:
        self.editor.clear_search()
        self.preview.clear_search()
        self.outline.set_search_highlight("")
        if self.search_box.text():
            self.search_box.blockSignals(True)
            self.search_box.clear()
            self.search_box.blockSignals(False)
        self._refresh_status_mode()

    def focus_search(self) -> None:
        """聚焦查找框（Ctrl+F）。"""
        self.search_box.setFocus()
        self.search_box.selectAll()

    # ==================================================================
    # 主题（固定白色）
    # ==================================================================
    def _apply_theme(self) -> None:
        theme = get_theme(self._theme_name)
        self.setStyleSheet(build_qss(theme.palette))
        # 重新渲染预览以应用新 CSS
        html = markdown_to_html(self.editor.toPlainText())
        self.preview.set_markdown_html(html, theme.preview_css, self._current_base_dir())
        kw = self.search_box.text()
        if kw:
            self._apply_search_to_active(kw)

    # ==================================================================
    # 打开文件
    # ==================================================================
    def open_file_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "打开 Markdown 文件", "",
            "Markdown 文件 (*.md *.markdown *.mdown *.mkd);;文本文件 (*.txt);;所有文件 (*.*)",
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> None:
        try:
            text = read_text_file(path)
            enc = detect_encoding(path)
        except Exception as exc:  # pragma: no cover
            QtWidgets.QMessageBox.warning(self, "打开失败", f"无法打开文件：\n{exc}")
            return
        self._load_markdown(text, path=path, encoding=enc)
        self.history.record(path)
        self.status.setText(f"已打开 {os.path.basename(path)} ｜ 编码 {enc}")

    # ---- 历史记录 ----
    def _rebuild_history_menu(self) -> None:
        """每次弹出前重建历史菜单（最近打开的在最前）。"""
        self.history_menu.clear()
        items = self.history.items()
        if not items:
            act_empty = self.history_menu.addAction("（暂无历史记录）")
            act_empty.setEnabled(False)
            return
        names = [os.path.basename(p) for p in items]
        for p in items:
            name = os.path.basename(p)
            # 同名文件附加所在目录，避免混淆
            label = f"{name}    — {os.path.dirname(p)}" if names.count(name) > 1 else name
            act = self.history_menu.addAction(label)
            act.setToolTip(p)
            act.triggered.connect(
                lambda checked=False, path=p: self._open_from_history(path)
            )
        self.history_menu.addSeparator()
        act_clear = self.history_menu.addAction("🧹 清空历史记录")
        act_clear.triggered.connect(self._clear_history)

    def _open_from_history(self, path: str) -> None:
        """从历史菜单打开文件；文件不存在时提示并移除该记录。"""
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(
                self, "打开失败", f"文件不存在或已被移动：\n{path}"
            )
            self.history.remove(path)
            return
        self.open_path(path)

    def _clear_history(self) -> None:
        """清空历史记录（无需二次确认）。"""
        self.history.clear()
        self.status.setText("历史记录已清空")

    def show_history(self) -> None:
        """弹出历史记录菜单（Ctrl+H，与点击按钮效果一致）。"""
        pos = self.history_btn.mapToGlobal(
            QtCore.QPoint(0, self.history_btn.height())
        )
        self.history_menu.popup(pos)

    # ---- 拖拽 ----
    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path and os.path.isfile(path):
                self.open_path(path)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    # ==================================================================
    # 导出
    # ==================================================================
    def _default_export_name(self, ext: str) -> str:
        if self._current_path:
            base = os.path.splitext(self._current_path)[0]
            return base + ext
        return "未命名" + ext

    def _export_done_box(self, kind: str, path: str):
        """构造导出成功提示框：主按钮为「打开导出文件」。

        返回 (对话框, 打开按钮)，便于测试检查按钮文案。
        """
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Information)
        box.setWindowTitle("导出成功")
        box.setText(f"已导出 {kind}：\n{path}")
        btn_open = box.addButton(
            "打开导出文件", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        btn_close = box.addButton(
            "关闭", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_open)
        box.setEscapeButton(btn_close)
        return box, btn_open

    def _notify_export_done(self, kind: str, path: str) -> None:
        """导出成功提示：点「打开导出文件」用系统默认程序打开（等效双击）。"""
        box, btn_open = self._export_done_box(kind, path)
        box.exec()
        if box.clickedButton() is btn_open:
            if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path)):
                QtWidgets.QMessageBox.warning(
                    self, "打开失败", f"无法打开文件：\n{path}")

    def export_pdf_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出为 PDF", self._default_export_name(".pdf"), "PDF 文件 (*.pdf)"
        )
        if not path:
            return
        try:
            doc = QtGui.QTextDocument()
            doc.setDefaultStyleSheet(get_theme(self._theme_name).preview_css)
            set_doc_base_dir(doc, self._current_base_dir())
            doc.setHtml(markdown_to_html(self.editor.toPlainText()))
            exporter.export_pdf(doc, path)
        except Exception as exc:  # pragma: no cover
            QtWidgets.QMessageBox.warning(self, "导出失败", f"导出 PDF 失败：\n{exc}")
            return
        self.status.setText(f"已导出 PDF：{path}")
        self._notify_export_done("PDF", path)

    def export_docx_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出为 DOCX", self._default_export_name(".docx"),
            "Word 文档 (*.docx)"
        )
        if not path:
            return
        try:
            exporter.export_docx(self.editor.toPlainText(), path,
                                 base_dir=self._current_base_dir())
        except Exception as exc:  # pragma: no cover
            QtWidgets.QMessageBox.warning(self, "导出失败", f"导出 DOCX 失败：\n{exc}")
            return
        self.status.setText(f"已导出 DOCX：{path}")
        self._notify_export_done("DOCX", path)

    # ==================================================================
    # 杂项
    # ==================================================================
    def about_text(self) -> str:
        """「关于」对话框正文（HTML）。"""
        return (
            "<h3>Markdown 阅读器（Typora 风格）</h3>"
            f"<p>版本：{__version__}</p>"
            "<p>技术栈：Python 3 + PySide6（Qt 6）</p>"
        )

    def show_about(self) -> None:
        """工具栏「关于」：展示软件版本与作者信息。"""
        QtWidgets.QMessageBox.about(
            self, "关于 Markdown 阅读器", self.about_text())

    def toggle_toolbar(self) -> None:
        """F11：隐藏 / 显示顶部工具栏。"""
        self.toolbar.setVisible(self.toolbar.isHidden())
        if self.toolbar.isHidden():
            self.status.setText("工具栏已隐藏（按 F11 恢复）")
        else:
            self.status.setText("工具栏已显示")

    def createPopupMenu(self):  # noqa: N802 (Qt 回调命名)
        """禁用 QMainWindow 默认的工具栏右键弹出菜单。

        默认实现会提供「勾选/取消勾选工具栏」的菜单项，一旦误取消勾选
        工具栏便无法找回；此处直接禁用，保证工具栏始终可见。
        """
        return None
