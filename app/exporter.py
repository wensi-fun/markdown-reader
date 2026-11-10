# -*- coding: utf-8 -*-
"""导出模块：PDF 与 DOCX。

- PDF：复用 QTextDocument（已渲染的 HTML），通过 QPrinter 输出，样式与预览一致。
- DOCX：用 python-docx 依据 Markdown 结构生成，排版对齐正式文档规范：
  A4、宋体正文 10.5pt、1.5 倍行距、首行缩进 2 字符、页眉（文档标题）+
  页脚（第 X 页）、文档首个一级标题渲染为封面大标题、Table Grid 真表格。
"""
from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from PySide6 import QtCore, QtGui

# _strip_inline：复用 markdown_parser 的标题纯文本剥离（去除 ** ` 等标记）
from .markdown_parser import _strip_inline, extract_outline


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def export_pdf(document: QtGui.QTextDocument, path: str, page_size=None) -> None:
    """把已渲染的 QTextDocument 导出为 PDF。"""
    # 延迟导入：QtPrintSupport 仅在导出 PDF 时需要，避免拖慢程序启动
    from PySide6.QtPrintSupport import QPrinter

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)
    printer.setPageMargins(
        QtCore.QMarginsF(15, 15, 15, 15),
        QtGui.QPageLayout.Unit.Millimeter,
    )
    _prepare_images_for_print(document, printer)
    # 让文档按打印机页面尺寸排版
    document.print_(printer)


def _prepare_images_for_print(document: QtGui.QTextDocument, printer) -> None:
    """打印前处理图片：相对路径转绝对路径 + 按页面宽度换算显示尺寸。

    QTextDocument 在打印/PDF 设备上绘制图片时对相对 URL 的解析不可靠，
    会退化为 16x16 的 missing-image 图标（实测：绝对路径正常）；
    另外图片 width/height 的单位是打印文档坐标（96dpi 逻辑像素，
    Qt 内部按页面 point 尺寸 × 96/72 设置），需以 96dpi 为基准把超宽
    图片限制到页面可用宽度内，否则图片会溢出页面。

    行高说明：正文 1.9 倍行距会把图片行拉伸为“图片高×1.9”，需与预览
    一致地把含图块行高归 SingleHeight，否则图片下方出现大段留白。
    """
    base_dir = document.baseUrl().toLocalFile()
    # QTextDocument 打印坐标系为 96dpi 逻辑像素（与屏幕一致），图片像素 1:1 映射
    page_px = printer.pageLayout().paintRectPixels(96).width()
    if page_px <= 0:
        return
    # 修改前先强制完成首次布局（防 QTextDocument 惰性布局塌陷）
    document.documentLayout().documentSize()
    fixes = []
    img_blocks = []
    block = document.begin()
    while block.isValid():
        has_img = False
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isImageFormat():
                has_img = True
                imf = frag.charFormat().toImageFormat()
                name = imf.name()
                abs_path = name
                if base_dir and not os.path.isabs(name):
                    abs_path = os.path.normpath(os.path.join(base_dir, name))
                pix = document.resource(
                    QtGui.QTextDocument.ResourceType.ImageResource,
                    QtCore.QUrl(name))
                if isinstance(pix, QtGui.QPixmap) and pix.width() > 0:
                    w = min(float(pix.width()), float(page_px))
                    h = max(1.0, w * pix.height() / pix.width())
                    fixes.append((frag.position(), frag.length(), abs_path, w, h))
            it += 1
        if has_img:
            img_blocks.append(block.blockNumber())
        block = block.next()
    for pos, length, abs_path, w, h in fixes:
        new_fmt = QtGui.QTextImageFormat()
        new_fmt.setName(abs_path.replace("\\", "/"))
        new_fmt.setWidth(w)
        new_fmt.setHeight(h)
        cur = QtGui.QTextCursor(document)
        cur.setPosition(pos)
        cur.setPosition(pos + length, QtGui.QTextCursor.MoveMode.KeepAnchor)
        cur.setCharFormat(new_fmt)
    for block_no in img_blocks:
        blk = document.findBlockByNumber(block_no)
        if not blk.isValid():
            continue
        nbf = QtGui.QTextBlockFormat(blk.blockFormat())
        nbf.setLineHeight(
            0.0, QtGui.QTextBlockFormat.LineHeightTypes.SingleHeight.value)
        QtGui.QTextCursor(blk).setBlockFormat(nbf)
    # 修改后强制全文档重排，确保新格式完整生效
    document.markContentsDirty(0, document.characterCount())
    document.documentLayout().documentSize()


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
# 图片单独成行： ![alt](path)
_IMG_RE = re.compile(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$")
# 围栏代码块起始/结束： ``` 或 ~~~
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*(.*)$")


# ---- DOCX 样式常量（对齐参考文档的正式排版） ----
_CN_FONT = "宋体"          # 中文
_EN_FONT = "Times New Roman"  # 西文
_MONO_FONT = "Consolas"    # 代码
_BODY_SIZE = 10.5          # 正文字号（五号）
_INDENT_PT = 21.0          # 首行缩进 / 列表左缩进（两个字符）
_COVER_GAP = 8             # 封面标题前的空行数
_MAX_IMG_W_CM = 14.0       # 图片最大宽度
_MAX_IMG_H_CM = 20.0       # 图片最大高度
_LINK_COLOR = (0x09, 0x69, 0xDA)
_QUOTE_COLOR = (0x59, 0x59, 0x59)
_GRAY = (0x80, 0x80, 0x80)

# 标题层级 -> (字号, 段前间距, 段后间距)；一级标题 16pt（首个渲染为封面）
_HEADING_STYLE = {
    1: (16.0, 12, 6),
    2: (14.0, 8, 4),
    3: (12.0, 6, 3),
    4: (11.0, 4, 2),
    5: (10.5, 4, 2),
    6: (10.5, 4, 2),
}


def _set_font(run, size=None, bold=None, italic=None, color=None, mono=False) -> None:
    """设置 run 的字体：西文 Times New Roman / 代码 Consolas，中文宋体。"""
    from docx.oxml.ns import qn

    run.font.name = _MONO_FONT if mono else _EN_FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), _CN_FONT)
    if size is not None:
        run.font.size = _pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = _rgb(*color)


def _add_runs(paragraph, text: str, size: float = _BODY_SIZE,
              base_bold: bool = False, base_color=None) -> None:
    """把含行内标记的文本写入段落（支持加粗/斜体/行内代码/链接）。"""
    for content, style in _tokenize_inline(text):
        if not content:
            continue
        run = paragraph.add_run(content)
        color = _LINK_COLOR if style.get("link") else base_color
        _set_font(
            run,
            size=size,
            bold=True if (base_bold or style.get("bold")) else None,
            italic=style.get("italic"),
            color=color,
            mono=style.get("code"),
        )


def _pt(x):
    from docx.shared import Pt
    return Pt(x)


def _rgb(r, g, b):
    from docx.shared import RGBColor
    return RGBColor(r, g, b)


def _tokenize_inline(text: str):
    """返回 [(内容, 样式字典), ...]。"""
    result = []
    # 先处理链接
    pos = 0
    pattern = re.compile(
        r"(\*\*.+?\*\*|__.+?__|\*[^*]+?\*|_[^_]+?_|`[^`]+?`|\[[^\]]*\]\([^)]*\))"
    )
    for m in pattern.finditer(text):
        if m.start() > pos:
            result.append((text[pos:m.start()], {}))
        seg = m.group(0)
        if seg.startswith("**") and seg.endswith("**"):
            result.append((seg[2:-2], {"bold": True}))
        elif seg.startswith("__") and seg.endswith("__"):
            result.append((seg[2:-2], {"bold": True}))
        elif seg.startswith("`") and seg.endswith("`"):
            result.append((seg[1:-1], {"code": True}))
        elif seg.startswith("["):
            lm = _LINK.match(seg)
            if lm:
                result.append((lm.group(1), {"link": True}))
            else:
                result.append((seg, {}))
        elif seg.startswith("*") and seg.endswith("*"):
            result.append((seg[1:-1], {"italic": True}))
        elif seg.startswith("_") and seg.endswith("_"):
            result.append((seg[1:-1], {"italic": True}))
        else:
            result.append((seg, {}))
        pos = m.end()
    if pos < len(text):
        result.append((text[pos:], {}))
    if not result:
        result.append((text, {}))
    return result


def _add_page_field(paragraph) -> None:
    """在段落中插入「第 X 页」页码域（PAGE field）。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    _set_font(paragraph.add_run("第 "), size=9)
    run = paragraph.add_run()
    _set_font(run, size=9)
    f1 = OxmlElement("w:fldChar")
    f1.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    f2 = OxmlElement("w:fldChar")
    f2.set(qn("w:fldCharType"), "end")
    run._element.append(f1)
    run._element.append(instr)
    run._element.append(f2)
    _set_font(paragraph.add_run(" 页"), size=9)


def _set_outline_level(paragraph, level: int) -> None:
    """写入 Word 大纲级别（供导航窗格 / 自动目录识别）。"""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    ol = OxmlElement("w:outlineLvl")
    ol.set(qn("w:val"), str(max(0, level - 1)))
    paragraph._p.get_or_add_pPr().append(ol)


def _setup_section(doc, header_text: str) -> None:
    """A4 页面 + 页眉（文档标题）+ 页脚（第 X 页）。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.top_margin, sec.bottom_margin = Cm(2.5), Cm(2.5)
    sec.left_margin, sec.right_margin = Cm(3.0), Cm(2.5)

    hdr = sec.header
    hdr.is_linked_to_previous = False
    hp = hdr.paragraphs[0]
    hp.text = ""
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_font(hp.add_run(header_text), size=9)

    ftr = sec.footer
    ftr.is_linked_to_previous = False
    fp = ftr.paragraphs[0]
    fp.text = ""
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_page_field(fp)


def _read_image_size(path: str) -> Optional[Tuple[int, int]]:
    """轻量读取图片像素尺寸（PNG/BMP/GIF/JPEG 头部解析），失败返回 None。"""
    def _jpeg_size(f) -> Optional[Tuple[int, int]]:
        f.seek(2)
        while True:
            b = f.read(1)
            if not b:
                return None
            if b != b"\xff":
                continue
            marker = f.read(1)
            while marker == b"\xff":
                marker = f.read(1)
            if not marker:
                return None
            m = marker[0]
            if m == 0xDA:  # SOS 之后不再有 SOF 段
                return None
            if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                continue
            ln_b = f.read(2)
            if len(ln_b) < 2:
                return None
            ln = int.from_bytes(ln_b, "big")
            if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                data = f.read(5)
                if len(data) < 5:
                    return None
                return (int.from_bytes(data[3:5], "big"),
                        int.from_bytes(data[1:3], "big"))
            f.seek(ln - 2, 1)

    try:
        with open(path, "rb") as f:
            head = f.read(26)
            if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
                return (int.from_bytes(head[16:20], "big"),
                        int.from_bytes(head[20:24], "big"))
            if head[:2] == b"BM" and len(head) >= 26:
                return (int.from_bytes(head[18:22], "little"),
                        int.from_bytes(head[22:26], "little"))
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return (int.from_bytes(head[6:8], "little"),
                        int.from_bytes(head[8:10], "little"))
            if head[:2] == b"\xff\xd8":
                return _jpeg_size(f)
    except OSError:
        return None
    return None


def _add_docx_image(doc, alt: str, src: str, base_dir: Optional[str]) -> None:
    """插入图片：alt 作为居中加粗说明行，图片居中且限制最大宽/高。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    img_path = src
    if not os.path.isabs(src):
        img_path = os.path.normpath(os.path.join(base_dir, src)) if base_dir else src

    if alt.strip():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(3)
        _set_font(p.add_run(alt.strip()), size=10, bold=True)

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Pt(0)
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(6)

    if not os.path.exists(img_path):
        _set_font(p.add_run(f"[图片未找到: {os.path.basename(src)}]"),
                  size=9, italic=True, color=_GRAY)
        return

    w_cm = _MAX_IMG_W_CM
    px = _read_image_size(img_path)
    if px and px[0] > 0:
        ratio = px[1] / px[0]
        if w_cm * ratio > _MAX_IMG_H_CM:
            w_cm = _MAX_IMG_H_CM / ratio
    p.add_run().add_picture(img_path, width=Cm(w_cm))


def export_docx(markdown_text: str, path: str, title: str = "",
                base_dir: Optional[str] = None) -> None:
    """把 Markdown 文本导出为 DOCX（正式文档排版，样式见模块注释）。

    :param title: 页眉标题；为空时自动取文档首个一级标题，再退化为文件名
    :param base_dir: 图片相对路径的基准目录（通常为打开的 md 文件所在目录）
    """
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Pt

    doc = Document()

    # 页眉标题：参数优先 -> 文档首个一级标题 -> 文件名
    header_text = (title or "").strip()
    if not header_text:
        header_text = next(
            (h.text for h in extract_outline(markdown_text) if h.level == 1), "")
    if not header_text:
        header_text = os.path.splitext(os.path.basename(path))[0]
    _setup_section(doc, header_text)

    # 正文默认样式：宋体 + Times New Roman、10.5pt、1.5 倍行距
    style = doc.styles["Normal"]
    style.font.name = _EN_FONT
    style.font.size = Pt(_BODY_SIZE)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), _CN_FONT)
    style.paragraph_format.line_spacing = 1.5

    lines = markdown_text.splitlines()
    n = len(lines)
    i = 0
    in_code = False
    code_buf: List[str] = []
    cover_done = False

    def flush_code() -> None:
        nonlocal code_buf
        for code_line in code_buf:
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.left_indent = Pt(_INDENT_PT)
            p.paragraph_format.line_spacing = 1.3
            p.paragraph_format.space_after = Pt(0)
            _set_font(p.add_run(code_line), size=10.0, mono=True)
        code_buf = []

    while i < n:
        line = lines[i]

        # 围栏代码块
        if _FENCE_RE.match(line):
            if not in_code:
                in_code = True
            else:
                in_code = False
                flush_code()
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # 空行
        if not line.strip():
            i += 1
            continue

        # 水平分隔线（跳过，与参考文档一致）
        if re.match(r"^ {0,3}([-*_])(\s*\1){2,}\s*$", line):
            i += 1
            continue

        # 图片（单独成行）
        img_m = _IMG_RE.match(line.strip())
        if img_m:
            _add_docx_image(doc, img_m.group(1), img_m.group(2), base_dir)
            i += 1
            continue

        # 表格（当前行含 | 且下一行为分隔线）
        if "|" in line and i + 1 < n and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            table_lines = [line]
            j = i + 1
            while j < n and "|" in lines[j] and lines[j].strip():
                table_lines.append(lines[j])
                j += 1
            _add_docx_table(doc, table_lines)
            i = j
            continue

        # 标题
        hm = re.match(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if hm:
            level = len(hm.group(1))
            text = _strip_inline(hm.group(2))
            if level == 1 and not cover_done:
                # 文档首个一级标题 -> 居中大字号封面标题
                for _ in range(_COVER_GAP):
                    doc.add_paragraph()
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _set_font(p.add_run(text), size=26.0, bold=True)
                _set_outline_level(p, 1)
                cover_done = True
                i += 1
                continue
            size, before, after = _HEADING_STYLE.get(level, (10.5, 4, 2))
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(before)
            p.paragraph_format.space_after = Pt(after)
            _set_font(p.add_run(text), size=size, bold=True)
            _set_outline_level(p, level)
            i += 1
            continue

        # 无序列表
        um = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if um:
            indent = len(um.group(1)) // 2
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.left_indent = Pt(_INDENT_PT + 18 * indent)
            _add_runs(p, "• " + um.group(2))
            i += 1
            continue

        # 有序列表（保留原编号）
        om = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)
        if om:
            indent = len(om.group(1)) // 2
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.left_indent = Pt(_INDENT_PT + 18 * indent)
            _add_runs(p, f"{om.group(2)}. " + om.group(3))
            i += 1
            continue

        # 引用（左缩进 + 灰色文字）
        qm = re.match(r"^ {0,3}>\s?(.*)$", line)
        if qm:
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.left_indent = Pt(_INDENT_PT)
            _add_runs(p, qm.group(1), base_color=_QUOTE_COLOR)
            i += 1
            continue

        # 普通正文（首行缩进 2 字符）
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Pt(_INDENT_PT)
        _add_runs(p, line.strip())
        i += 1

    if in_code:
        flush_code()

    doc.save(path)


def _add_docx_table(doc, table_lines: List[str]) -> None:
    """把 Markdown 表格行渲染为 Table Grid 真表格（9pt 居中、首行加粗）。"""
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    rows: List[List[str]] = []
    for l in table_lines:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
            continue  # 分隔行
        rows.append(cells)
    if not rows:
        return

    ncols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=ncols)
    table.style = "Table Grid"
    for ri, row in enumerate(rows):
        for ci in range(ncols):
            text = row[ci] if ci < len(row) else ""
            p = table.cell(ri, ci).paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_runs(p, text, size=9.0, base_bold=(ri == 0))
    doc.add_paragraph()  # 表后留一段，避免与下文粘连
