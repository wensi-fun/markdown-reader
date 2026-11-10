# -*- coding: utf-8 -*-
"""右侧预览控件（docx 风格渲染）。

基于 ``QTextBrowser``（只读富文本）。提供：
- ``set_markdown_html(html, css)``：载入渲染后的 HTML 与主题 CSS。
- ``scroll_to_heading(index)``：滚动到第 index 个标题块（与大纲一一对应）。
- ``highlight_search(keyword)``：高亮全部匹配（当前匹配橙色、其余黄色），
  并滚动到第一个匹配处。
- ``find_next(keyword)``：回车查找下一个匹配（到尾后循环回绕）。
- ``clear_search()``：清除高亮。
"""
from __future__ import annotations

import os
from typing import List, Tuple

from PySide6 import QtCore, QtGui, QtWidgets

_FIRST_BG = "#ff9800"  # 当前匹配：橙色
_REST_BG = "#fff59d"   # 其余匹配：黄色


def set_doc_base_dir(doc: QtGui.QTextDocument, base_dir: str) -> None:
    """把文档的资源基准目录设为 base_dir（解析图片等相对路径资源）。"""
    if not base_dir:
        return
    base = os.path.normpath(base_dir).replace("\\", "/").rstrip("/") + "/"
    doc.setBaseUrl(QtCore.QUrl.fromLocalFile(base))


class PreviewView(QtWidgets.QTextBrowser):
    """预览视图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Preview")
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self._search_selections: List[QtWidgets.QTextEdit.ExtraSelection] = []
        self._heading_blocks: List[int] = []
        self._current_keyword = ""
        self._match_cursors: List[QtGui.QTextCursor] = []
        self._current_match = -1
        self._img_orig: dict = {}      # 图片名 -> 原始像素尺寸 (w, h)
        self._last_fit_width = 0       # 上次适配图片时的视口宽度
        self._refit_timer = QtCore.QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.timeout.connect(self._refit_images)

    # ------------------------------------------------------------------
    def set_markdown_html(self, html: str, css: str = "", base_dir: str = "") -> None:
        """载入 HTML（含主题 CSS）。

        :param base_dir: 打开的 md 文件所在目录，用于解析相对图片路径
        """
        doc = self.document()
        self._img_orig.clear()
        doc.setDefaultStyleSheet(css)
        set_doc_base_dir(doc, base_dir)
        self.setSearchPaths([os.path.normpath(base_dir)] if base_dir else [])
        self.setHtml(html or "<p></p>")
        # 强制完成首次布局：QTextDocument 布局是惰性的，若在布局尚未
        # 完成时修改文档，会导致其后文本块布局塌陷（高度 0、不绘制）
        doc.documentLayout().documentSize()
        self._fit_images()
        # 修改（图片缩放/行高归位）后强制全文档重排，确保新格式完整生效
        doc.markContentsDirty(0, doc.characterCount())
        doc.documentLayout().documentSize()
        self._rebuild_heading_index()
        self.clear_search()
        self._last_fit_width = self.viewport().width()

    def _fit_images(self) -> None:
        """把超出可视区域的图片按比例缩小（Qt 富文本不支持 CSS max-width），
        并把含图块的行高复位为 SingleHeight。

        正文的 1.9 倍行距同样作用于图片段落：Qt 会把图片行拉伸为
        “图片高 × 1.9”，图片绘制在行顶部，多出的 0.9 倍表现为图片下方的
        大段留白；复位为单倍行高后图片行紧贴图片实际高度。
        """
        doc = self.document()
        avail = self.viewport().width() - 80  # 减去 body 左右 margin（40px × 2）
        if avail <= 80:
            return
        fixes = []
        img_blocks = []
        block = doc.begin()
        while block.isValid():
            has_img = False
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().isImageFormat():
                    has_img = True
                    img_fmt = frag.charFormat().toImageFormat()
                    pix = doc.resource(
                        QtGui.QTextDocument.ResourceType.ImageResource,
                        QtCore.QUrl(img_fmt.name()))
                    if isinstance(pix, QtGui.QPixmap) and pix.width() > 0:
                        self._img_orig[img_fmt.name()] = (pix.width(), pix.height())
                        if pix.width() > avail:
                            fixes.append((frag.position(), frag.length(), img_fmt, pix))
                it += 1
            if has_img:
                img_blocks.append(block.blockNumber())
            block = block.next()
        for pos, length, img_fmt, pix in fixes:
            new_fmt = QtGui.QTextImageFormat()
            new_fmt.setName(img_fmt.name())
            new_fmt.setWidth(avail)
            new_fmt.setHeight(max(1, round(avail * pix.height() / pix.width())))
            cur = QtGui.QTextCursor(doc)
            cur.setPosition(pos)
            cur.setPosition(pos + length, QtGui.QTextCursor.MoveMode.KeepAnchor)
            cur.setCharFormat(new_fmt)
        # 含图块行高归 SingleHeight（需在图片缩放后执行：此时资源已入缓存，
        # 重排能拿到图片真实尺寸）
        for block_no in img_blocks:
            blk = doc.findBlockByNumber(block_no)
            if not blk.isValid():
                continue
            nbf = QtGui.QTextBlockFormat(blk.blockFormat())
            nbf.setLineHeight(
                0.0, QtGui.QTextBlockFormat.LineHeightTypes.SingleHeight.value)
            QtGui.QTextCursor(blk).setBlockFormat(nbf)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        """窗口宽度明显变化后（防拖拽抖动）重新适配图片尺寸。"""
        super().resizeEvent(event)
        if abs(self.viewport().width() - self._last_fit_width) >= 8:
            self._refit_timer.start(150)

    def _refit_images(self) -> None:
        """按当前视口宽度重新适配图片：超宽缩放、变宽后恢复原始尺寸。

        初次渲染时图片是按当时的视口宽度缩放的，窗口 resize 后若不重新
        适配，图片会保持旧尺寸（窗口变大时过小、变小时超出容器导致展示
        混乱）。
        """
        avail = self.viewport().width() - 80
        if avail <= 80:
            return
        doc = self.document()
        changes = []
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().isImageFormat():
                    imf = frag.charFormat().toImageFormat()
                    name = imf.name()
                    orig = self._img_orig.get(name)
                    if orig is None:
                        pix = doc.resource(
                            QtGui.QTextDocument.ResourceType.ImageResource,
                            QtCore.QUrl(name))
                        if isinstance(pix, QtGui.QPixmap) and pix.width() > 0:
                            orig = (pix.width(), pix.height())
                            self._img_orig[name] = orig
                    if orig and orig[0] > 0:
                        cur_w = imf.width()
                        if orig[0] > avail:
                            w = float(avail)
                            if abs(cur_w - w) > 0.5:
                                h = max(1.0, w * orig[1] / orig[0])
                                changes.append(
                                    (frag.position(), frag.length(), name, w, h))
                        elif cur_w > 0:
                            # 宽度已足够：恢复原始尺寸（清除显式宽高）
                            changes.append(
                                (frag.position(), frag.length(), name, 0.0, 0.0))
                it += 1
            block = block.next()
        self._last_fit_width = self.viewport().width()
        if not changes:
            return
        # 修改前先强制完成首次布局（防 QTextDocument 惰性布局塌陷）
        doc.documentLayout().documentSize()
        for pos, length, name, w, h in changes:
            new_fmt = QtGui.QTextImageFormat()
            new_fmt.setName(name)
            if w > 0:
                new_fmt.setWidth(w)
                new_fmt.setHeight(h)
            cur = QtGui.QTextCursor(doc)
            cur.setPosition(pos)
            cur.setPosition(pos + length, QtGui.QTextCursor.MoveMode.KeepAnchor)
            cur.setCharFormat(new_fmt)
        # 修改后强制全文档重排，确保新格式完整生效
        doc.markContentsDirty(0, doc.characterCount())
        doc.documentLayout().documentSize()

    # ------------------------------------------------------------------
    # 图片点击：浮窗放大查看
    # ------------------------------------------------------------------
    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """鼠标悬停在图片上时显示手型光标，提示可点击放大。"""
        super().mouseMoveEvent(event)
        pos = event.position().toPoint()
        if self.anchorAt(pos):
            return  # 链接光标由基类处理
        if self._image_at(pos) is not None:
            self.viewport().setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().setCursor(QtCore.Qt.CursorShape.IBeamCursor)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """左键点击图片：弹出浮窗放大查看（滚轮缩放，Esc / ✕ 关闭）。"""
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            imf = self._image_at(event.position().toPoint())
            if imf is not None:
                pix = self.document().resource(
                    QtGui.QTextDocument.ResourceType.ImageResource,
                    QtCore.QUrl(imf.name()))
                if isinstance(pix, QtGui.QPixmap) and not pix.isNull():
                    dlg = ImageViewerDialog(
                        pix, os.path.basename(imf.name()), self)
                    dlg.exec()
                    return
        super().mousePressEvent(event)

    def _image_at(self, pos: QtCore.QPoint):
        """返回指定视口位置处的图片格式；不在图片上时返回 None。"""
        cur = self.cursorForPosition(pos)
        fmt = cur.charFormat()
        if fmt.isImageFormat():
            return fmt.toImageFormat()
        # cursorForPosition 可能落在图片前一位：探测后一个字符
        probe = QtGui.QTextCursor(cur)
        probe.movePosition(QtGui.QTextCursor.MoveOperation.NextCharacter)
        fmt2 = probe.charFormat()
        if fmt2.isImageFormat():
            return fmt2.toImageFormat()
        return None

    def _rebuild_heading_index(self) -> None:
        """扫描文档，记录标题块在 block 序列中的位置，供大纲定位。"""
        self._heading_blocks = []
        doc = self.document()
        for i in range(doc.blockCount()):
            block = doc.findBlockByNumber(i)
            if block.blockFormat().headingLevel() > 0:
                self._heading_blocks.append(i)

    def heading_count(self) -> int:
        return len(self._heading_blocks)

    def current_heading_index(self) -> int:
        """返回视口当前所在章节的大纲索引（-1 表示无标题）。

        判定规则：
        1) 视口顶部就是标题块（如点击跳转后标题置顶）→ 直接取该标题；
        2) 否则取视口上部 1/4 处所在块之前（含）最近的标题，
           供滚动时大纲联动高亮使用。
        """
        if not self._heading_blocks:
            return -1
        # 1) 标题块位于视口顶部：点击跳转后的短章节也不会被下一节抢走
        top_block = self.cursorForPosition(QtCore.QPoint(8, 2)).blockNumber()
        if top_block in self._heading_blocks:
            return self._heading_blocks.index(top_block)
        # 2) 回退：视口上部 1/4 处最近的标题
        y = max(8, self.viewport().height() // 4)
        cur = self.cursorForPosition(QtCore.QPoint(8, y))
        block_no = cur.blockNumber()
        idx = -1
        for i, b in enumerate(self._heading_blocks):
            if b <= block_no:
                idx = i
            else:
                break
        return idx

    # ------------------------------------------------------------------
    def scroll_to_heading(self, index: int) -> bool:
        """滚动到第 index 个标题块并置于视口顶部附近。"""
        if index < 0 or index >= len(self._heading_blocks):
            return False
        block_no = self._heading_blocks[index]
        block = self.document().findBlockByNumber(block_no)
        cursor = QtGui.QTextCursor(block)
        self.setTextCursor(cursor)
        # 让标题滚到靠近顶部的位置
        self.verticalScrollBar().setValue(0)  # 先复位，避免累积误差
        self.ensureCursorVisible()
        # 再精确滚动到该块顶部
        rect = self.cursorRect(cursor)
        sb = self.verticalScrollBar()
        sb.setValue(sb.value() + rect.top() - 10)
        return True

    # ------------------------------------------------------------------
    def highlight_search(self, keyword: str) -> int:
        """高亮全部匹配（当前匹配橙色、其余黄色），滚动到第一个匹配处。

        返回匹配总数（0 表示未找到）。
        """
        if not keyword:
            self.clear_search()
            return 0
        self._scan_matches(keyword)
        if not self._match_cursors:
            self._current_match = -1
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
        if keyword != self._current_keyword or not self._match_cursors:
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
        """扫描全部匹配位置（不改动滚动位置）。"""
        self._current_keyword = keyword
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
            self._scroll_cursor_to_center(cursor)

    def _apply_extra_selections(self) -> None:
        self.setExtraSelections(list(self._search_selections))

    def _scroll_cursor_to_center(self, cursor: QtGui.QTextCursor) -> None:
        self.ensureCursorVisible()
        rect = self.cursorRect(cursor)
        sb = self.verticalScrollBar()
        target = sb.value() + rect.top() - self.viewport().height() // 3
        sb.setValue(max(sb.minimum(), min(sb.maximum(), target)))

    def clear_search(self) -> None:
        self._match_cursors = []
        self._current_keyword = ""
        self._current_match = -1
        self._search_selections = []
        self.setExtraSelections([])

    def current_keyword(self) -> str:
        return self._current_keyword

    # ------------------------------------------------------------------
    # 复制：还原代码块的软换行（U+2028 -> 普通换行）
    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        """Ctrl+C / Ctrl+Insert：以普通换行复制选中文本。"""
        if event.matches(QtGui.QKeySequence.StandardKey.Copy):
            self._copy_clean()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        """右键菜单：只保留「复制 / 全选」，复制时还原换行符。"""
        menu = QtWidgets.QMenu(self)
        act_copy = menu.addAction("复制")
        act_copy.setEnabled(self.textCursor().hasSelection())
        act_copy.triggered.connect(self._copy_clean)
        menu.addSeparator()
        act_select = menu.addAction("全选")
        act_select.triggered.connect(self.selectAll)
        menu.exec(event.globalPos())

    def _copy_clean(self) -> None:
        """复制选中文本，把代码块的 U+2028 还原为普通换行。"""
        text = self.textCursor().selectedText().replace("\u2028", "\n")
        if text:
            QtWidgets.QApplication.clipboard().setText(text)


class _ViewerTitleBar(QtWidgets.QWidget):
    """图片浮窗的标题条：文件名 + 可拖动 + 右上角 ✕ 关闭按钮。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ImgViewerBar")
        self.setFixedHeight(38)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 6, 0)
        lay.setSpacing(8)
        lbl = QtWidgets.QLabel(title or "图片预览", self)
        lbl.setObjectName("ImgViewerTitle")
        lay.addWidget(lbl, 1)
        self._btn_full = QtWidgets.QPushButton("全屏", self)
        self._btn_full.setObjectName("ImgViewerFull")
        self._btn_full.setToolTip("全屏显示")
        self._btn_full.setFixedHeight(26)
        self._btn_full.setMinimumWidth(52)
        self._btn_full.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._btn_full.clicked.connect(self._on_fullscreen)
        lay.addWidget(self._btn_full, 0)
        btn = QtWidgets.QPushButton("✕", self)
        btn.setObjectName("ImgViewerClose")
        btn.setToolTip("关闭（Esc）")
        btn.setFixedSize(36, 26)
        btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self._on_close)
        lay.addWidget(btn, 0)
        self._drag_offset = None

    def _on_close(self) -> None:
        win = self.window()
        if win is not None:
            win.close()

    def _on_fullscreen(self) -> None:
        win = self.window()
        toggle = getattr(win, "toggle_fullscreen", None)
        if callable(toggle):
            toggle()

    def set_fullscreen_state(self, fullscreen: bool) -> None:
        """更新全屏按钮文案与提示。"""
        self._btn_full.setText("退出全屏" if fullscreen else "全屏")
        self._btn_full.setToolTip(
            "退出全屏（Esc）" if fullscreen else "全屏显示（Esc 退出）")

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint()
                - self.window().frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if (self._drag_offset is not None
                and event.buttons() & QtCore.Qt.MouseButton.LeftButton):
            self.window().move(
                event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class _ZoomView(QtWidgets.QGraphicsView):
    """浮窗内的图片视图：滚轮缩放（以鼠标为锚点）、按住拖动平移。"""

    _MIN_SCALE = 0.05
    _MAX_SCALE = 20.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ImgViewerCanvas")
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(
            QtWidgets.QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QtGui.QColor("#1e1e1e"))

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        """滚轮上滚放大、下滚缩小。"""
        delta = event.angleDelta().y()
        if delta > 0:
            self.apply_zoom(1.25)
        elif delta < 0:
            self.apply_zoom(0.8)
        event.accept()

    def apply_zoom(self, factor: float) -> None:
        """按 factor 缩放，限制在 5% ~ 2000%。"""
        target = self.transform().m11() * factor
        if target < self._MIN_SCALE or target > self._MAX_SCALE:
            return
        self.scale(factor, factor)


class ImageViewerDialog(QtWidgets.QDialog):
    """图片浮窗：点击预览区图片弹出。

    - 鼠标滚轮放大 / 缩小（5% ~ 2000%），以鼠标位置为锚点
    - 按住左键拖动平移；标题条可拖动移动窗口
    - Esc 或右上角 ✕ 关闭；首次显示自动适配窗口（小图保持 1:1）
    """

    def __init__(self, pixmap: QtGui.QPixmap, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("ImageViewerDialog")
        self.setWindowTitle(title or "图片预览")
        self.setWindowFlags(
            QtCore.Qt.WindowType.Dialog
            | QtCore.Qt.WindowType.FramelessWindowHint
        )
        self.setModal(True)
        self._fitted = False

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._title_bar = _ViewerTitleBar(title, self)
        lay.addWidget(self._title_bar)

        self._scene = QtWidgets.QGraphicsScene(self)
        self._item = self._scene.addPixmap(pixmap)
        self._scene.setBackgroundBrush(QtGui.QColor("#1e1e1e"))
        self._view = _ZoomView(self)
        self._view.setScene(self._scene)
        lay.addWidget(self._view, 1)

        self.setStyleSheet(
            "#ImageViewerDialog { background-color: #1e1e1e; }"
            "#ImgViewerBar { background-color: #2d2d30; }"
            "#ImgViewerTitle { color: #f0f0f0; font-size: 13px; }"
            "QPushButton#ImgViewerClose { color: #f0f0f0; background: transparent;"
            " border: none; border-radius: 4px; font-size: 13px; }"
            "QPushButton#ImgViewerClose:hover { background-color: #e81123; }"
            "QPushButton#ImgViewerFull { color: #f0f0f0; background: transparent;"
            " border: none; border-radius: 4px; font-size: 12px; }"
            "QPushButton#ImgViewerFull:hover { background-color: #3f3f46; }"
        )

        # 初始尺寸：父窗口的 80%（下限 560x420）
        pw = parent.width() if parent is not None else 800
        ph = parent.height() if parent is not None else 600
        self.resize(max(560, int(pw * 0.8)), max(420, int(ph * 0.8)))

    # ---- 生命周期 ----
    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            # 等布局完成后再 fit，确保视口尺寸已确定
            QtCore.QTimer.singleShot(0, self._fit_to_view)
            self._center_on_parent()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key.Key_Escape:
            if self.isFullScreen():
                self.toggle_fullscreen()  # 先退出全屏，再按一次 Esc 才关闭
            else:
                self.close()
            return
        super().keyPressEvent(event)

    # ---- 全屏 ----
    def toggle_fullscreen(self) -> None:
        """切换全屏 / 窗口显示（全屏时 Esc 先退出全屏）。"""
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self._title_bar.set_fullscreen_state(self.isFullScreen())
        # 视口尺寸变化后重新适配图片
        QtCore.QTimer.singleShot(0, self._fit_to_view)

    # ---- 内部 ----
    def _fit_to_view(self) -> None:
        """首次显示：图片适配窗口（小图不放大，保持 1:1）。"""
        self._view.fitInView(
            self._item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        if self._view.transform().m11() > 1.0:
            self._view.resetTransform()

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        geo = self.frameGeometry()
        geo.moveCenter(parent.window().frameGeometry().center())
        self.move(geo.topLeft())
