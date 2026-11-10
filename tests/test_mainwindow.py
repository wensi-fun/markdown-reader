# -*- coding: utf-8 -*-
"""主窗口交互测试（离屏运行）。

覆盖：模式切换、编辑时大纲同步、大纲点击定位、大纲收起/展开、
查找（回车下一个 + 大纲高亮）、固定白色主题、打开文件。
"""
import os
import sys

# 确保终端输出编码兼容（避免 GBK 控制台打印 emoji 报 UnicodeEncodeError）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6 import QtCore, QtWidgets  # noqa: E402

from app.main_window import MainWindow  # noqa: E402

PASS = 0
FAIL = 0
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")

# 隔离 QSettings：历史记录写入 _tmp，不污染真实注册表
os.makedirs(TMP, exist_ok=True)
QtCore.QSettings.setPath(
    QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Scope.UserScope, TMP
)


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    app.processEvents()

    print("\n[1] 初始状态")
    check("默认预览模式", w._mode == "preview")
    check("默认展示阅读界面", w.stack.currentWidget() is w.preview)
    check("切换按钮初始文案", "编辑" in w.act_toggle.text(), w.act_toggle.text())
    check("欢迎内容有大纲", len(w._headings) >= 3, str(len(w._headings)))
    check("预览标题数一致", w.preview.heading_count() == len(w._headings),
          f"{w.preview.heading_count()} vs {len(w._headings)}")
    check("工具栏可见", not w.toolbar.isHidden())
    check("工具栏不可被隐藏", not w.toolbar.toggleViewAction().isEnabled())
    check("右键弹出菜单已禁用", w.createPopupMenu() is None)

    print("\n[2] 模式切换")
    w.toggle_mode()
    app.processEvents()
    check("切到源码", w._mode == "source" and w.stack.currentWidget() is w.editor)
    check("按钮文案更新", "预览" in w.act_toggle.text(), w.act_toggle.text())
    w.toggle_mode()
    app.processEvents()
    check("切回预览", w._mode == "preview" and w.stack.currentWidget() is w.preview)
    # F11 工具栏隐藏 / 恢复
    w.toggle_toolbar()
    check("F11 隐藏工具栏", w.toolbar.isHidden())
    w.toggle_toolbar()
    check("F11 恢复工具栏", not w.toolbar.isHidden())

    print("\n[3] 编辑实时同步大纲")
    w.editor.setPlainText("# 甲\n\n## 乙\n\n### 丙\n\n正文\n")
    w._refresh_from_editor()
    app.processEvents()
    check("大纲更新", [h.text for h in w._headings] == ["甲", "乙", "丙"],
          str([h.text for h in w._headings]))
    check("预览标题更新", w.preview.heading_count() == 3, str(w.preview.heading_count()))
    # 树结构层级：甲 是顶层，乙 是甲子节点，丙 是乙子节点
    top = w.outline.topLevelItemCount()
    check("树顶层只有 1 个", top == 1, str(top))
    check("乙是甲的子节点", w.outline.topLevelItem(0).childCount() == 1)

    print("\n[4] 大纲点击定位")
    w._on_outline_clicked(2)  # 丙
    app.processEvents()
    check("点击大纲无异常", True)
    # 源码模式定位
    w.toggle_mode()
    w._on_outline_clicked(0)
    check("源码定位到第0行", w.editor.textCursor().blockNumber() == 0,
          str(w.editor.textCursor().blockNumber()))

    print("\n[5] 查找（回车下一个 + 大纲高亮）")
    check("无独立✖清除按钮", all(a.text() != "✖" for a in w.toolbar.actions()))
    check("查找框自带清除按钮", w.search_box.isClearButtonEnabled())
    w.editor.setPlainText("# foo 标题\n\n## 其他\n\nfoo 正文 foo baz")
    w._refresh_from_editor()
    w.toggle_mode()  # 回预览
    w.search_box.setText("foo")
    w.do_search()
    app.processEvents()
    check("查找有结果", "找到 3 处" in w.status.text(), w.status.text())
    # 回车 = 查找下一个（循环回绕）
    w.find_next()
    check("回车跳到第 2 处", "匹配 2/3" in w.status.text(), w.status.text())
    w.find_next()
    w.find_next()
    check("循环回绕到第 1 处", "匹配 1/3" in w.status.text(), w.status.text())
    # 大纲高亮：含查找词的标题标黄（仅展示）
    top_foo = w.outline.topLevelItem(0)  # 「foo 标题」
    sub_other = top_foo.child(0)         # 「其他」
    check("大纲命中标题高亮",
          top_foo.background(0).color().name() == "#fff59d",
          top_foo.background(0).color().name())
    check("大纲命中标题加粗", top_foo.font(0).bold())
    check("大纲未命中标题无高亮",
          sub_other.background(0).style() == QtCore.Qt.BrushStyle.NoBrush)
    check("大纲未命中标题不加粗", not sub_other.font(0).bold())
    w.clear_search()
    check("清除查找", w.search_box.text() == "" and len(w.preview._search_selections) == 0)
    check("清除后大纲高亮同步移除",
          top_foo.background(0).style() == QtCore.Qt.BrushStyle.NoBrush)
    check("清除后命中标题取消加粗", not top_foo.font(0).bold())

    print("\n[6] 大纲全部收起 / 展开")
    w.editor.setPlainText("# 甲\n\n## 乙\n\n### 丙\n\n正文\n")
    w._refresh_from_editor()
    app.processEvents()
    check("初始全部展开", w.outline.topLevelItem(0).isExpanded())
    w._toggle_outline_expand()
    app.processEvents()
    top0 = w.outline.topLevelItem(0)
    check("点击后全部收起", not top0.isExpanded() and not top0.child(0).isExpanded())
    check("按钮变为 ▼", w.outline_toggle_btn.text() == "▼", w.outline_toggle_btn.text())
    w._toggle_outline_expand()
    app.processEvents()
    top0 = w.outline.topLevelItem(0)
    check("再点击全部展开", top0.isExpanded() and top0.child(0).isExpanded())
    check("按钮还原 ▲", w.outline_toggle_btn.text() == "▲", w.outline_toggle_btn.text())

    print("\n[7] 主题固定白色")
    check("主题固定 light", w._theme_name == "light", w._theme_name)
    check("无主题切换按钮", not hasattr(w, "act_theme"))

    print("\n[8] 打开文件（含 GBK）")
    os.makedirs(TMP, exist_ok=True)
    p = os.path.join(TMP, "open_gbk.md")
    with open(p, "wb") as f:
        f.write("# 打开测试\n\n## 小节\n\n内容内容".encode("gbk"))
    w.open_path(p)
    app.processEvents()
    check("标题已载入", [h.text for h in w._headings][0] == "打开测试",
          str([h.text for h in w._headings]))
    check("当前路径记录", w._current_path == p)

    # 端到端：打开引用相对路径图片的 md，预览区应加载该图片
    from PySide6 import QtGui
    sub = os.path.join(TMP, "imgs")
    os.makedirs(sub, exist_ok=True)
    pix = QtGui.QPixmap(300, 120)
    pix.fill(QtGui.QColor("#3aa76d"))
    pix.save(os.path.join(sub, "pic.png"))
    p_img = os.path.join(TMP, "open_img.md")
    with open(p_img, "w", encoding="utf-8") as f:
        f.write("# 图\n\n![示例](imgs/pic.png)\n")
    w.open_path(p_img)
    app.processEvents()
    res = w.preview.document().resource(
        QtGui.QTextDocument.ResourceType.ImageResource, QtCore.QUrl("imgs/pic.png"))
    check("打开文件后图片渲染",
          isinstance(res, QtGui.QPixmap) and res.width() == 300)

    # 未缩放的图片同样需行高归位（否则 1.9 倍行距在图下留白 0.9 × 图高）
    doc2 = w.preview.document()
    img_blk = None
    blk = doc2.begin()
    while blk.isValid():
        it = blk.begin()
        while not it.atEnd():
            fr = it.fragment()
            if fr.isValid() and fr.charFormat().isImageFormat():
                img_blk = blk
            it += 1
        blk = blk.next()
    bf2 = img_blk.blockFormat() if img_blk else None
    check("图片块行高归位 SingleHeight",
          bf2 is not None and bf2.lineHeightType() == 0 and bf2.lineHeight() == 0,
          f"type={bf2.lineHeightType() if bf2 else None} lh={bf2.lineHeight() if bf2 else None}")

    print("\n[9] 导出（走主窗口逻辑）")
    pdf = os.path.join(TMP, "mw.pdf")
    docx = os.path.join(TMP, "mw.docx")
    from app import exporter
    from app.markdown_parser import markdown_to_html
    from app.themes import get_theme
    from PySide6 import QtGui
    doc = QtGui.QTextDocument()
    doc.setDefaultStyleSheet(get_theme(w._theme_name).preview_css)
    doc.setHtml(markdown_to_html(w.editor.toPlainText()))
    exporter.export_pdf(doc, pdf)
    exporter.export_docx(w.editor.toPlainText(), docx)
    check("PDF 导出", os.path.getsize(pdf) > 500)
    check("DOCX 导出", os.path.getsize(docx) > 1000)

    # 导出成功框：主按钮「打开导出文件」（点击后用系统默认程序打开，等效双击）
    box, btn_open = w._export_done_box("DOCX", docx)
    check("导出成功框主按钮为「打开导出文件」",
          btn_open.text() == "打开导出文件", btn_open.text())
    check("导出成功框默认按钮为「打开导出文件」",
          box.defaultButton() is not None
          and box.defaultButton().text() == "打开导出文件")
    check("导出成功框提示文案含路径", docx in box.text())
    box.deleteLater()

    print("\n[10] 历史记录与 Ctrl+F")
    w.history.clear()
    w.activateWindow()
    w.focus_search()
    app.processEvents()
    check("Ctrl+F 聚焦查找框", w.search_box.hasFocus())
    w.search_box.clear()

    pa = os.path.join(TMP, "hist_a.md")
    pb = os.path.join(TMP, "hist_b.md")
    with open(pa, "w", encoding="utf-8") as f:
        f.write("# 历史 A\n\n内容 A")
    with open(pb, "w", encoding="utf-8") as f:
        f.write("# 历史 B\n\n内容 B")

    w.open_path(pa)
    w.open_path(pb)
    app.processEvents()
    hist = [os.path.normcase(p) for p in w.history.items()]
    check("打开文件后记录历史",
          hist[:2] == [os.path.normcase(os.path.abspath(pb)),
                       os.path.normcase(os.path.abspath(pa))],
          str(hist[:2]))

    w.open_path(pa)  # 重新打开 a：应置顶且不重复
    items = w.history.items()
    check("重开文件去重并置顶",
          os.path.normcase(items[0]) == os.path.normcase(os.path.abspath(pa))
          and sum(os.path.normcase(p) == os.path.normcase(os.path.abspath(pa))
                  for p in items) == 1,
          str(items))

    w._rebuild_history_menu()
    texts = [a.text() for a in w.history_menu.actions() if a.text()]
    check("菜单包含历史文件",
          os.path.basename(pa) in texts and os.path.basename(pb) in texts, str(texts))
    check("菜单包含清空项", any("清空" in t for t in texts), str(texts))

    # Ctrl+H 弹出历史菜单
    w.show_history()
    app.processEvents()
    check("Ctrl+H 弹出历史菜单", w.history_menu.isVisible())
    w.history_menu.close()

    # 点击菜单项（选 b）应打开对应文件
    act_b = next(a for a in w.history_menu.actions()
                 if a.text() == os.path.basename(pb))
    act_b.trigger()
    app.processEvents()
    check("点击菜单项打开对应文件",
          os.path.normcase(w._current_path) == os.path.normcase(pb),
          str(w._current_path))

    # 记录一个不存在的文件 → 打开时提示并自动移除
    missing = os.path.join(TMP, "missing.md")
    w.history.record(missing)
    orig_warning = QtWidgets.QMessageBox.warning
    QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: None)
    try:
        w._open_from_history(missing)
    finally:
        QtWidgets.QMessageBox.warning = orig_warning
    check("失效记录被移除",
          os.path.normcase(missing) not in [os.path.normcase(p) for p in w.history.items()])

    w._clear_history()
    check("清空历史", w.history.items() == [])

    print("\n[11] 预览图片点击检测与 resize 重适配")
    w.open_path(p_img)
    app.processEvents()
    doc3 = w.preview.document()
    img_blk_no = -1
    blk = doc3.begin()
    while blk.isValid():
        it = blk.begin()
        while not it.atEnd():
            fr = it.fragment()
            if fr.isValid() and fr.charFormat().isImageFormat():
                img_blk_no = blk.blockNumber()
            it += 1
        blk = blk.next()
    brect = doc3.documentLayout().blockBoundingRect(
        doc3.findBlockByNumber(img_blk_no))
    pt = QtCore.QPoint(
        int(brect.center().x()) - w.preview.horizontalScrollBar().value(),
        int(brect.center().y()) - w.preview.verticalScrollBar().value())
    hit = w.preview._image_at(pt)
    check("点击图片命中检测",
          hit is not None and "pic.png" in hit.name(),
          repr(hit.name()) if hit else "None")
    check("非图片位置不命中",
          w.preview._image_at(QtCore.QPoint(3, 3)) is None)

    # 窗口宽度变化 → 防抖定时器启动，重适配后记录当前视口宽度
    w.resize(1040, 700)
    app.processEvents()
    w.resize(1000, 700)
    app.processEvents()
    check("resize 触发重适配防抖", w.preview._refit_timer.isActive())
    w.preview._refit_images()
    check("重适配后记录视口宽度",
          w.preview._last_fit_width == w.preview.viewport().width(),
          f"{w.preview._last_fit_width} vs {w.preview.viewport().width()}")

    print("\n[12] 预览滚动 → 大纲跟随高亮")
    long_md = (
        "# 第一章\n\n" + ("第一章的正文段落。\n\n" * 18)
        + "## 1.1 Foo\n\n" + ("Foo 的内部段落内容。\n\n" * 18)
        + "## 1.2 Bar\n\n" + ("Bar 的内容段落。\n\n" * 18)
        + "### 1.2.1 Baz\n\n" + ("Baz 的内容段落。\n\n" * 18)
    )
    w.editor.setPlainText(long_md)
    w._refresh_from_editor()
    if w._mode == "source":
        w.toggle_mode()
    app.processEvents()
    check("初始滚到顶部高亮第一章", w._outline_current == 0, str(w._outline_current))
    check("滚动前高亮项为选中样式",
          w.outline.currentItem() is not None
          and w.outline.currentItem().text(0) == "第一章" 
          and bool(w.outline.selectedItems()),
          w.outline.currentItem().text(0) if w.outline.currentItem() else "None")
    # 滚动到 1.1 Foo 内部：左栏应显示当前到了 1.1 Foo
    w.preview.scroll_to_heading(1)
    app.processEvents()
    sb = w.preview.verticalScrollBar()
    sb.setValue(sb.value() + 120)  # 再往下滚进正文内部
    app.processEvents()
    check("滚动到 1.1 内部后大纲高亮 1.1 Foo",
          w.outline.currentItem() is not None
          and w.outline.currentItem().text(0) == "1.1 Foo",
          w.outline.currentItem().text(0) if w.outline.currentItem() else "None")
    check("高亮与点击效果一致（选中态）",
          bool(w.outline.selectedItems())
          and w.outline.selectedItems()[0].text(0) == "1.1 Foo")
    # 点击大纲后的同步不应把高亮改成其它项
    w._on_outline_clicked(2)
    app.processEvents()
    check("点击 1.2 Bar 后仍高亮该项",
          w.outline.currentItem() is not None
          and w.outline.currentItem().text(0) == "1.2 Bar",
          w.outline.currentItem().text(0) if w.outline.currentItem() else "None")
    # 滚到底部：高亮靠后的章节
    sb.setValue(sb.maximum())
    app.processEvents()
    check("滚到底部高亮靠后章节", w._outline_current >= 2, str(w._outline_current))

    print("\n[12b] 点击短章节/末章节不被滚动同步覆盖")
    short_md = (
        "# 1. 目录\n\n简短说明。\n\n"
        + "## 1.1 Foo\n\n" + ("Foo 内容段落。\n\n" * 30)
        + "## 1.2 Bar\n\n" + ("Bar 内容段落。\n\n" * 30)
        + "## 1.3 版本信息\n\n" + ("版本内容。\n\n" * 3)
    )
    w.editor.setPlainText(short_md)
    w._refresh_from_editor()
    app.processEvents()
    # 点击上层「1. 目录」：跳转后 1/4 视口处已进入 1.1，但焦点必须保持 1.
    w._on_outline_clicked(0)
    app.processEvents()
    check("点击短章节上层「1. 目录」后焦点不被 1.1 抢走",
          w.outline.currentItem() is not None
          and w.outline.currentItem().text(0) == "1. 目录",
          w.outline.currentItem().text(0) if w.outline.currentItem() else "None")
    # 点击末章节「1.3 版本信息」（文档底部无法置顶于视口，1/4 处仍在上一节）
    w._on_outline_clicked(3)
    app.processEvents()
    check("点击末章节后焦点保持在「1.3 版本信息」",
          w.outline.currentItem() is not None
          and w.outline.currentItem().text(0) == "1.3 版本信息",
          w.outline.currentItem().text(0) if w.outline.currentItem() else "None")
    # 手动滚动仍应跟随：滚回顶部 → 高亮第一章
    w.preview.verticalScrollBar().setValue(0)
    app.processEvents()
    check("手动滚回顶部后高亮第一章", w._outline_current == 0, str(w._outline_current))
    # 目录全部收起时点击子项：自动展开祖先，焦点可见
    w._toggle_outline_expand()  # 全部收起
    app.processEvents()
    w._on_outline_clicked(2)
    app.processEvents()
    cur_item = w.outline.currentItem()
    check("收起状态下点击子项自动展开并保持选中",
          cur_item is not None and cur_item.text(0) == "1.2 Bar"
          and cur_item.parent() is not None and cur_item.parent().isExpanded(),
          cur_item.text(0) if cur_item else "None")
    # 打开结构不同的文档后，大纲应全部展开（不沿用旧展开状态）
    w.editor.setPlainText("# 甲\n\n## 乙\n\n### 丙\n\n正文\n")
    w._refresh_from_editor()
    app.processEvents()
    top_new = w.outline.topLevelItem(0)
    check("结构变化后大纲全部展开",
          top_new.isExpanded() and top_new.childCount() == 1
          and top_new.child(0).isExpanded())

    print("\n[13] 关于（版本）")
    from app import __version__
    check("版本号已定义", bool(__version__), __version__)
    check("工具栏含关于按钮",
          any("关于" in a.text() for a in w.toolbar.actions()))
    about = w.about_text()
    check("关于信息含版本", __version__ in about, __version__)
    check("关于信息含软件名", "Markdown 阅读器" in about)

    print(f"\n==== 结果：{PASS} 通过 / {FAIL} 失败 ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
