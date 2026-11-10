# -*- coding: utf-8 -*-
"""核心逻辑自动化测试（离屏运行）。

运行：
    QT_QPA_PLATFORM=offscreen python tests/test_core.py

覆盖：大纲解析、Markdown 渲染、编码识别、查找高亮（当前匹配橙色/其余黄色）、
回车查找下一个（循环回绕）、标题定位、白色主题、PDF/DOCX 导出、最近文件历史记录、
预览图片（相对路径解析/超宽缩放）与正文行距。
"""
import os
import sys

# 确保终端输出编码兼容（避免 GBK 控制台打印 emoji 报 UnicodeEncodeError）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 让测试可直接运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from app import exporter  # noqa: E402
from app.editor import MarkdownEditor  # noqa: E402
from app.history import FileHistory  # noqa: E402
from app.markdown_parser import (  # noqa: E402
    detect_encoding,
    extract_outline,
    markdown_to_html,
    read_text_file,
)
from app.preview import (  # noqa: E402
    ImageViewerDialog,
    PreviewView,
    set_doc_base_dir,
)
from app.themes import get_theme  # noqa: E402

PASS = 0
FAIL = 0
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def _first_img_fmt(doc):
    """返回（首个图片格式，fragment 起点，所在 block 号）。"""
    block = doc.begin()
    fmt = None
    pos = -1
    blk_no = -1
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isImageFormat():
                fmt = frag.charFormat().toImageFormat()
                pos = frag.position()
                blk_no = block.blockNumber()
            it += 1
        block = block.next()
    return fmt, pos, blk_no


def test_outline():
    print("\n[1] 大纲解析")
    md = """# A
text
## B
### C
```python
# 代码注释不算标题
```
## D
E
===
"""
    hs = extract_outline(md)
    levels = [h.level for h in hs]
    texts = [h.text for h in hs]
    check("层级正确", levels == [1, 2, 3, 2, 1], str(levels))
    check("标题文本正确", texts == ["A", "B", "C", "D", "E"], str(texts))
    check("跳过代码块内 #", "代码注释不算标题" not in texts)
    check("行号单调递增", all(hs[i].line < hs[i + 1].line for i in range(len(hs) - 1)))
    # 行内标记剥离
    hs2 = extract_outline("## **粗** 与 `码` 与 [链](http://x)")
    check("剥离行内标记", hs2[0].text == "粗 与 码 与 链", repr(hs2[0].text))


def test_render():
    print("\n[2] Markdown 渲染")
    html = markdown_to_html("# Hi\n\n**bold** and `code`\n\n- a\n- b")
    check("生成 h1", "<h1" in html)
    check("生成 strong", "<strong>" in html)
    check("生成列表", "<li>" in html)
    check("空文本安全", markdown_to_html("") == "")

    # 代码块：合并为单个 block（U+2028 软换行），渲染为整段连续背景
    html_code = markdown_to_html("```\nline1\nline2\nline3\n```\n\n正文")
    check("代码块转软换行", "\u2028" in html_code and "</pre>" in html_code)
    pv = PreviewView()
    pv.set_markdown_html(html_code, "")
    doc = pv.document()
    code_idx = next(i for i in range(doc.blockCount())
                    if doc.findBlockByNumber(i).text().startswith("line1"))
    code_text = doc.findBlockByNumber(code_idx).text()
    check("代码块为单个 block",
          "\u2028line2" in code_text and "\u2028line3" in code_text,
          repr(code_text[:24]))
    check("正文仍为普通换行",
          doc.findBlockByNumber(code_idx).next().text() == "正文")

    # 复制：软换行还原为普通换行
    pv.selectAll()
    pv._copy_clean()
    clip = QtWidgets.QApplication.clipboard().text()
    check("复制还原普通换行",
          "\u2028" not in clip and "line1\nline2" in clip, repr(clip[:24]))


def test_encoding():
    print("\n[3] 编码识别")
    os.makedirs(TMP, exist_ok=True)
    p_gbk = os.path.join(TMP, "gbk.md")
    with open(p_gbk, "wb") as f:
        f.write("# 中文标题\n\n正文".encode("gbk"))
    check("GBK 识别", detect_encoding(p_gbk) in ("gbk", "gb18030"), detect_encoding(p_gbk))
    check("GBK 读取", "中文标题" in read_text_file(p_gbk))
    p_bom = os.path.join(TMP, "bom.md")
    with open(p_bom, "wb") as f:
        f.write("\ufeff# BOM 标题".encode("utf-8"))
    check("BOM 识别", detect_encoding(p_bom) == "utf-8-sig", detect_encoding(p_bom))
    check("BOM 读取无残留", read_text_file(p_bom).startswith("# BOM"))


def test_search_highlight():
    print("\n[4] 查找高亮（当前匹配橙色 / 其余黄色）与回车查找下一个")
    ed = MarkdownEditor()
    ed.setPlainText("alpha beta alpha gamma alpha")
    n = ed.highlight_search("alpha")
    check("匹配计数=3", n == 3, str(n))
    sels = ed._search_selections
    check("高亮数量=3", len(sels) == 3, str(len(sels)))
    c0 = sels[0].format.background().color().name()
    c1 = sels[1].format.background().color().name()
    check("当前匹配为橙色", c0 == "#ff9800", c0)
    check("其余为黄色", c1 == "#fff59d", c1)

    # 回车 = 查找下一个：2 → 3 → 循环回绕 1
    pos, total = ed.find_next("alpha")
    check("回车跳到第 2 处", (pos, total) == (2, 3), f"{pos}/{total}")
    pos, total = ed.find_next("alpha")
    check("回车跳到第 3 处", (pos, total) == (3, 3), f"{pos}/{total}")
    pos, total = ed.find_next("alpha")
    check("循环回绕到第 1 处", (pos, total) == (1, 3), f"{pos}/{total}")
    sels2 = ed._search_selections
    check("橙色跟随当前匹配",
          sels2[0].format.background().color().name() == "#ff9800"
          and sels2[1].format.background().color().name() == "#fff59d",
          sels2[0].format.background().color().name())
    # 光标选中当前匹配
    sel_txt = ed.textCursor().selectedText()
    check("光标选中匹配文字", sel_txt == "alpha", sel_txt)

    pv = PreviewView()
    pv.set_markdown_html(markdown_to_html("x y x z x"), "")
    n2 = pv.highlight_search("x")
    check("预览匹配计数=3", n2 == 3, str(n2))
    check("预览当前匹配橙色", pv._search_selections[0].format.background().color().name() == "#ff9800")
    pos2, total2 = pv.find_next("x")
    check("预览回车下一个", (pos2, total2) == (2, 3), f"{pos2}/{total2}")
    check("预览橙色跟随", pv._search_selections[1].format.background().color().name() == "#ff9800")
    pv.clear_search()
    check("清除高亮", len(pv._search_selections) == 0)


def test_preview_heading_index():
    print("\n[5] 预览标题定位")
    pv = PreviewView()
    pv.set_markdown_html(markdown_to_html("# One\n\n## Two\n\n### Three\n\nbody"), "")
    check("标题块计数=3", pv.heading_count() == 3, str(pv.heading_count()))
    check("定位索引0", pv.scroll_to_heading(0) is True)
    check("定位索引2", pv.scroll_to_heading(2) is True)
    check("越界返回 False", pv.scroll_to_heading(99) is False)


def test_themes():
    print("\n[6] 主题（固定白色）")
    lt = get_theme("light")
    check("白色主题背景为白", lt.palette["preview_bg"] == "#ffffff", lt.palette["preview_bg"])
    check("未知主题名回退白色", get_theme("gray").name == "light", get_theme("gray").name)
    check("CSS 非空", bool(lt.preview_css))


def test_export():
    print("\n[7] 导出 PDF / DOCX")
    md = """# 标题一

正文 **加粗** 与 `代码`。

## 列表

- 项一
- 项二

> 引用

| A | B |
| --- | --- |
| 1 | 2 |
"""
    pdf = os.path.join(TMP, "out.pdf")
    docx = os.path.join(TMP, "out.docx")

    doc = QtGui.QTextDocument()
    doc.setDefaultStyleSheet(get_theme("light").preview_css)
    doc.setHtml(markdown_to_html(md))
    exporter.export_pdf(doc, pdf)
    check("PDF 生成", os.path.exists(pdf) and os.path.getsize(pdf) > 500,
          f"{os.path.getsize(pdf) if os.path.exists(pdf) else 0} bytes")

    exporter.export_docx(md, docx)
    check("DOCX 生成", os.path.exists(docx) and os.path.getsize(docx) > 1000,
          f"{os.path.getsize(docx) if os.path.exists(docx) else 0} bytes")
    try:
        from docx import Document
        d = Document(docx)
        texts = "\n".join(p.text for p in d.paragraphs)
        check("DOCX 含标题文本", "标题一" in texts)
        check("DOCX 含列表项", "项一" in texts)
        check("DOCX 含表格", len(d.tables) >= 1, str(len(d.tables)))

        # 正式文档排版规范（对齐参考样式：A4/宋体/1.5 行距/页眉页码/封面）
        sec = d.sections[0]
        check("DOCX 页面 A4", abs(sec.page_width.cm - 21.0) < 0.1
              and abs(sec.page_height.cm - 29.7) < 0.1)
        check("DOCX 页眉为文档标题", sec.header.paragraphs[0].text == "标题一")
        check("DOCX 页脚含页码", "第" in sec.footer.paragraphs[0].text
              and "页" in sec.footer.paragraphs[0].text)
        check("DOCX 正文行距 1.5",
              d.styles["Normal"].paragraph_format.line_spacing == 1.5)
        cover = [p for p in d.paragraphs
                 if p.runs and p.runs[0].font.size and p.runs[0].font.size.pt == 26]
        check("DOCX 封面大标题", len(cover) == 1 and cover[0].text == "标题一")
        body = next(p for p in d.paragraphs if p.text.strip() == "正文 加粗 与 代码。")
        check("DOCX 正文首行缩进 21pt",
              body.paragraph_format.first_line_indent.pt == 21.0)
        check("DOCX 表格样式 Table Grid",
              d.tables[0].style.name == "Table Grid")
    except Exception as exc:
        check("DOCX 内容校验", False, str(exc))


def test_history():
    print("\n[8] 最近文件历史记录")
    # 隔离 QSettings：写入 _tmp 目录，不污染真实注册表
    QtCore.QSettings.setPath(
        QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope, TMP
    )
    h = FileHistory()
    h.clear()
    check("初始为空", h.items() == [])

    p1 = os.path.join(TMP, "hist1.md")
    p2 = os.path.join(TMP, "hist2.md")
    h.record(p1)
    check("记录一条", h.items() == [os.path.abspath(p1)], str(h.items()))
    h.record(p2)
    check("最新记录在最前", h.items()[0] == os.path.abspath(p2), str(h.items()))
    h.record(p1)
    check("重复打开去重并置顶",
          h.items() == [os.path.abspath(p1), os.path.abspath(p2)], str(h.items()))
    h.record(p1.upper())
    check("大小写不同视为同一文件", len(h.items()) == 2, str(h.items()))

    for i in range(30):
        h.record(os.path.join(TMP, f"hh{i}.md"))
    items = h.items()
    check("条数不超过上限", len(items) == FileHistory.MAX_ITEMS, str(len(items)))
    check("超限后保留最新",
          items[0] == os.path.abspath(os.path.join(TMP, "hh29.md")), items[0])

    h.remove(os.path.abspath(os.path.join(TMP, "hh29.md")))
    check("remove 生效",
          os.path.abspath(os.path.join(TMP, "hh29.md")) not in h.items())
    h.clear()
    check("清空生效", h.items() == [])


def test_preview_images():
    print("\n[9] 预览：相对路径图片与行距")
    # 构造场景：md 同级目录 plantuml/ 下放一张超宽图片
    img_dir = os.path.join(TMP, "plantuml")
    os.makedirs(img_dir, exist_ok=True)
    img_path = os.path.join(img_dir, "14-总体功能结构图.png")
    pix = QtGui.QPixmap(1600, 200)
    pix.fill(QtGui.QColor("#4a90d9"))
    check("测试图片生成", pix.save(img_path))

    md = "# 标题\n\n![总体功能结构图](plantuml/14-总体功能结构图.png)\n\n正文段落。\n"
    pv = PreviewView()
    pv.resize(900, 600)
    pv.show()
    QtWidgets.QApplication.processEvents()
    pv.set_markdown_html(markdown_to_html(md), get_theme("light").preview_css,
                         base_dir=TMP)

    doc = pv.document()
    res = doc.resource(QtGui.QTextDocument.ResourceType.ImageResource,
                       QtCore.QUrl("plantuml/14-总体功能结构图.png"))
    check("相对路径图片加载",
          isinstance(res, QtGui.QPixmap) and res.width() == 1600)

    # 超宽图片按可视宽度等比缩放
    img_fmt = None
    img_block_no = -1
    img_frag_pos = -1
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isImageFormat():
                img_fmt = frag.charFormat().toImageFormat()
                img_block_no = block.blockNumber()
                img_frag_pos = frag.position()
            it += 1
        block = block.next()
    avail = pv.viewport().width() - 80
    check("超宽图片按可视区缩放",
          img_fmt is not None and abs(img_fmt.width() - avail) < 2
          and round(img_fmt.height()) == round(avail * 200 / 1600),
          f"w={img_fmt.width() if img_fmt else None} avail={avail}")

    # 图片行高归位：含图块行高须为 SingleHeight，否则 1.9 倍行距会把图片行
    # 拉伸为“图片高 × 1.9”，多出的 0.9 倍表现为图片下方的大段留白
    img_block = doc.findBlockByNumber(img_block_no)
    ibf = img_block.blockFormat()
    check("图片块行高归位 SingleHeight",
          ibf.lineHeightType() == 0 and ibf.lineHeight() == 0,
          f"type={ibf.lineHeightType()} lh={ibf.lineHeight()}")

    # 图片块占位 ≈ 图片显示高度（既非 0 也非显示高 × 1.9）
    layout = doc.documentLayout()
    rect = layout.blockBoundingRect(img_block)
    show_h = round(avail * 200 / 1600)
    check("图片块高度≈显示高（无 1.9 倍拉伸）",
          abs(rect.height() - show_h) <= 2,
          f"h={rect.height():.1f} expect≈{show_h}")

    # 图后正文紧跟（间距为正常段距 ~16px，而非 0.9 × 图高的巨幅空白）
    nxt = img_block.next()
    gap = layout.blockBoundingRect(nxt).top() - rect.bottom()
    check("图后间距正常（无 0.9 倍图高留白）", 0 <= gap <= 40, f"gap={gap:.1f}")

    # 行距：正文块 1.9 倍行距 + 16px 段距（Qt 不继承 body 行距，需显式生效）
    idx = next(i for i in range(doc.blockCount())
               if doc.findBlockByNumber(i).text().startswith("正文段落"))
    bf = doc.findBlockByNumber(idx).blockFormat()
    check("正文行距 1.9 生效", bf.lineHeightType() == 1 and bf.lineHeight() >= 180,
          f"type={bf.lineHeightType()} lh={bf.lineHeight()}")
    check("正文段距 16px", bf.topMargin() == 16 and bf.bottomMargin() == 16)

    # ---- resize 重适配：变宽恢复原始尺寸 / 变窄重新缩放 ----
    pv.resize(1800, 700)
    QtWidgets.QApplication.processEvents()
    check("resize 宽度变化触发防抖定时器", pv._refit_timer.isActive(),
          f"last={pv._last_fit_width} now={pv.viewport().width()}")
    pv._refit_images()
    fmt_wide, _, _ = _first_img_fmt(doc)
    check("变宽后恢复原始尺寸",
          fmt_wide is not None and fmt_wide.width() == 0,
          f"w={fmt_wide.width() if fmt_wide else None}")

    pv.resize(700, 700)
    QtWidgets.QApplication.processEvents()
    pv._refit_images()
    fmt_narrow, _, _ = _first_img_fmt(doc)
    avail_n = pv.viewport().width() - 80
    check("变窄后重新缩放到可视区",
          fmt_narrow is not None and abs(fmt_narrow.width() - avail_n) < 2,
          f"w={fmt_narrow.width() if fmt_narrow else None} avail={avail_n}")

    # ---- 点击检测：_image_at 命中图片 / 非图片位置 ----
    img_block = doc.findBlockByNumber(img_block_no)
    brect = doc.documentLayout().blockBoundingRect(img_block)
    pt = QtCore.QPoint(
        int(brect.center().x()) - pv.horizontalScrollBar().value(),
        int(brect.center().y()) - pv.verticalScrollBar().value())
    hit = pv._image_at(pt)
    check("_image_at 命中图片",
          hit is not None and hit.name() == "plantuml/14-总体功能结构图.png",
          repr(hit.name()) if hit else "None")
    check("_image_at 非图片位置不误报",
          pv._image_at(QtCore.QPoint(3, 3)) is None)

    # 无基准目录：相对图片不加载
    pv2 = PreviewView()
    pv2.set_markdown_html(markdown_to_html(md), "")
    res2 = pv2.document().resource(QtGui.QTextDocument.ResourceType.ImageResource,
                                   QtCore.QUrl("plantuml/14-总体功能结构图.png"))
    check("无基准目录时不加载相对图片",
          not (isinstance(res2, QtGui.QPixmap) and not res2.isNull()))


def test_image_viewer():
    print("\n[10] 图片浮窗（点击放大 + 滚轮缩放 + Esc/✕ 关闭）")
    app = QtWidgets.QApplication.instance()
    pix = QtGui.QPixmap(800, 600)
    pix.fill(QtGui.QColor("#c0392b"))
    dlg = ImageViewerDialog(pix, "测试图片.png")
    dlg.show()
    for _ in range(3):
        app.processEvents()
    check("浮窗显示", dlg.isVisible())
    check("标题含文件名", "测试图片.png" in dlg.windowTitle())

    # 大图首次 fit 缩小（800x600 大于视口）
    m_fit = dlg._view.transform().m11()
    check("首次适配缩小", 0 < m_fit < 1.0, f"m11={m_fit:.3f}")

    # 滚轮放大 / 缩小
    before = dlg._view.transform().m11()
    dlg._view.wheelEvent(QtGui.QWheelEvent(
        QtCore.QPointF(100, 100), QtCore.QPointF(100, 100),
        QtCore.QPoint(0, 0), QtCore.QPoint(0, 120),
        QtCore.Qt.MouseButton.NoButton, QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.NoScrollPhase, False))
    after = dlg._view.transform().m11()
    check("滚轮上滚放大", after > before and abs(after - before * 1.25) < 1e-6,
          f"{before:.3f}->{after:.3f}")
    dlg._view.wheelEvent(QtGui.QWheelEvent(
        QtCore.QPointF(100, 100), QtCore.QPointF(100, 100),
        QtCore.QPoint(0, 0), QtCore.QPoint(0, -120),
        QtCore.Qt.MouseButton.NoButton, QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.NoScrollPhase, False))
    check("滚轮下滚缩小", abs(dlg._view.transform().m11() - before) < 1e-6,
          f"{dlg._view.transform().m11():.3f}")

    # 缩放上下限（5% ~ 2000%）
    for _ in range(60):
        dlg._view.apply_zoom(1.25)
    m_up = dlg._view.transform().m11()
    check("放大上限 2000%", 16.0 < m_up <= 20.0 + 1e-6, f"{m_up:.2f}")
    for _ in range(120):
        dlg._view.apply_zoom(0.8)
    m_dn = dlg._view.transform().m11()
    check("缩小下限 5%", 0.05 - 1e-6 <= m_dn <= 0.0625 + 1e-6, f"{m_dn:.4f}")

    # 全屏切换（按钮 + 全屏时 Esc 先退出全屏）
    dlg.toggle_fullscreen()
    app.processEvents()
    check("进入全屏", dlg.isFullScreen())
    check("全屏按钮文案变为退出全屏",
          dlg._title_bar._btn_full.text() == "退出全屏",
          dlg._title_bar._btn_full.text())
    dlg.keyPressEvent(QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier))
    app.processEvents()
    check("全屏时 Esc 退出全屏且不关闭",
          not dlg.isFullScreen() and dlg.isVisible())
    check("按 Esc 后按钮文案恢复",
          dlg._title_bar._btn_full.text() == "全屏",
          dlg._title_bar._btn_full.text())
    dlg._title_bar._btn_full.click()
    app.processEvents()
    check("全屏按钮进入全屏", dlg.isFullScreen())
    dlg._title_bar._btn_full.click()
    app.processEvents()
    check("再点按钮退出全屏", not dlg.isFullScreen() and dlg.isVisible())

    # Esc 关闭
    dlg.keyPressEvent(QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape,
        QtCore.Qt.KeyboardModifier.NoModifier))
    app.processEvents()
    check("Esc 关闭浮窗", not dlg.isVisible())

    # ✕ 按钮关闭
    dlg2 = ImageViewerDialog(pix, "x.png")
    dlg2.show()
    app.processEvents()
    btn = dlg2.findChild(QtWidgets.QPushButton, "ImgViewerClose")
    check("存在 ✕ 关闭按钮", btn is not None and btn.text() == "✕")
    btn.click()
    app.processEvents()
    check("✕ 关闭浮窗", not dlg2.isVisible())

    # 小图不放大（保持 1:1）
    small = QtGui.QPixmap(200, 150)
    small.fill(QtGui.QColor("#2980b9"))
    dlg3 = ImageViewerDialog(small, "small.png")
    dlg3.show()
    for _ in range(3):
        app.processEvents()
    m_small = dlg3._view.transform().m11()
    check("小图保持 1:1（不放大）", abs(m_small - 1.0) < 1e-6, f"m11={m_small:.3f}")
    dlg3.close()


def test_pdf_images():
    print("\n[11] PDF 导出图片（绝对路径改写 + 尺寸适配 + 无 missing 图标）")
    img_dir = os.path.join(TMP, "pdfimg")
    os.makedirs(img_dir, exist_ok=True)
    big = os.path.join(img_dir, "big.png")
    small = os.path.join(img_dir, "small.png")
    pb = QtGui.QPixmap(2000, 400)
    pb.fill(QtGui.QColor("#e67e22"))
    check("超宽测试图生成", pb.save(big))
    ps = QtGui.QPixmap(300, 200)
    ps.fill(QtGui.QColor("#27ae60"))
    check("小测试图生成", ps.save(small))

    md = "# 图导出\n\n![大图](pdfimg/big.png)\n\n![小图](pdfimg/small.png)\n"
    doc = QtGui.QTextDocument()
    doc.setDefaultStyleSheet(get_theme("light").preview_css)
    set_doc_base_dir(doc, TMP)
    doc.setHtml(markdown_to_html(md))
    doc.documentLayout().documentSize()

    from PySide6.QtPrintSupport import QPrinter
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    pdf = os.path.join(TMP, "img_export.pdf")
    printer.setOutputFileName(pdf)
    printer.setPageMargins(QtCore.QMarginsF(15, 15, 15, 15),
                           QtGui.QPageLayout.Unit.Millimeter)

    page_px = printer.pageLayout().paintRectPixels(96).width()
    exporter._prepare_images_for_print(doc, printer)

    names, widths, heights = [], [], []
    block_ok = True
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        has_img = False
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isImageFormat():
                has_img = True
                imf = frag.charFormat().toImageFormat()
                names.append(imf.name())
                widths.append(imf.width())
                heights.append(imf.height())
            it += 1
        if has_img:
            bf = block.blockFormat()
            block_ok = (block_ok and bf.lineHeightType() == 0
                        and bf.lineHeight() == 0)
        block = block.next()

    check("图片路径全部转为绝对路径",
          len(names) == 2 and all(os.path.isabs(n) for n in names),
          str([os.path.basename(n) for n in names]))
    check("超宽图限制到页面可用宽",
          len(widths) == 2 and abs(widths[0] - page_px) < 0.01,
          f"w={widths[0] if widths else None} page_px={page_px}")
    check("超宽图高度等比",
          abs(heights[0] - page_px * 400 / 2000) < 0.5, f"h={heights[0]}")
    check("不超宽图保持原始尺寸",
          abs(widths[1] - 300) < 0.01 and abs(heights[1] - 200) < 0.01,
          f"{widths[1]}x{heights[1]}")
    check("含图块行高归 SingleHeight", block_ok)

    # 端到端：真正打印为 PDF，检查图像对象尺寸
    # （曾有 bug：相对路径 → 全部退化为 16x16 missing-image 图标）
    doc.print_(printer)
    check("PDF 生成", os.path.exists(pdf) and os.path.getsize(pdf) > 500,
          f"{os.path.getsize(pdf) if os.path.exists(pdf) else 0} bytes")
    try:
        import pymupdf
        d = pymupdf.open(pdf)
        sizes = []
        for page in d:
            sizes += [(im[2], im[3]) for im in page.get_images(full=True)]
        d.close()
        icons = [s for s in sizes if s[0] <= 32 and s[1] <= 32]
        check("PDF 无 16x16 missing 图标", len(icons) == 0, str(sizes))
        check("PDF 含两张大图",
              len([s for s in sizes if s[0] >= 200]) == 2, str(sizes))
    except ImportError:
        print("  [SKIP] 未安装 pymupdf，跳过 PDF 图像对象检查")


def main():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    test_outline()
    test_render()
    test_encoding()
    test_search_highlight()
    test_preview_heading_index()
    test_themes()
    test_export()
    test_history()
    test_preview_images()
    test_image_viewer()
    test_pdf_images()
    print(f"\n==== 结果：{PASS} 通过 / {FAIL} 失败 ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
