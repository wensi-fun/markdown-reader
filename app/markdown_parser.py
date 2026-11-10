# -*- coding: utf-8 -*-
"""Markdown 解析工具。

职责：
1. 从 Markdown 源文本中提取标题大纲（层级 + 标题文本 + 在源码中的行号）。
2. 把 Markdown 渲染为 HTML（供预览区以 docx 风格展示）。
3. 提供编码自动识别读取，兼容 UTF-8 / UTF-8-BOM / GBK / GB18030 等。

本模块为纯逻辑，不依赖 Qt，便于单元测试。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

# 兼容两种 markdown 库的导入方式
try:  # 新版包名
    import markdown as _md_lib
except ImportError:  # pragma: no cover
    import markdown2 as _md_lib  # type: ignore


# ATX 标题：  # 标题、## 标题 ...（允许前导空格，允许行尾闭合 #）
_ATX_RE = re.compile(r"^ {0,3}(#{1,6})(\s+.*?)\s*#*\s*$")
# Setext 标题下划线： === 或 ---
_SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)\s*$")
# 围栏代码块起始/结束： ``` 或 ~~~（允许缩进与语言标记）
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# 行内 Markdown 标记（提取大纲纯文本时去掉）
_INLINE_TOKENS = [
    (re.compile(r"!\[([^\]]*)\]\([^)]*\)"), r"\1"),      # 图片 -> alt
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),        # 链接 -> 文本
    (re.compile(r"\*\*\*(.+?)\*\*\*"), r"\1"),
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"__(.+?)__"), r"\1"),
    (re.compile(r"\*(.+?)\*"), r"\1"),
    (re.compile(r"_(.+?)_"), r"\1"),
    (re.compile(r"~~(.+?)~~"), r"\1"),
    (re.compile(r"`([^`]*)`"), r"\1"),
]


@dataclass
class Heading:
    """一个标题节点。"""

    level: int      # 1-6
    text: str       # 去掉 Markdown 标记后的纯文本
    line: int       # 在源码中的行号（0-based）
    raw: str = ""   # 原始标题行


def _strip_inline(text: str) -> str:
    """去掉标题中的行内 Markdown 标记，得到纯文本。"""
    for pat, repl in _INLINE_TOKENS:
        text = pat.sub(repl, text)
    return text.strip()


def extract_outline(text: str) -> List[Heading]:
    """从 Markdown 文本中提取标题列表（按出现顺序）。

    会正确跳过围栏代码块内部的 ``#`` 行（例如 Python 注释），
    同时支持 ATX（``# 标题``）与 Setext（下划线式）两种标题。
    """
    headings: List[Heading] = []
    if not text:
        return headings

    lines = text.splitlines()
    in_fence = False
    fence_char = ""
    fence_len = 0
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # --- 处理围栏代码块状态 ---
        fence_m = _FENCE_RE.match(line)
        if fence_m:
            marker = fence_m.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_len:
                in_fence = False
            i += 1
            continue

        if in_fence:
            i += 1
            continue

        # --- ATX 标题 ---
        m = _ATX_RE.match(line)
        if m:
            level = len(m.group(1))
            title = _strip_inline(m.group(2))
            headings.append(Heading(level=level, text=title, line=i, raw=line))
            i += 1
            continue

        # --- Setext 标题（下一行为 === 或 ---） ---
        if line.strip() and i + 1 < n:
            nxt = lines[i + 1]
            sm = _SETEXT_RE.match(nxt)
            if sm and not _ATX_RE.match(line) and line.strip():
                level = 1 if sm.group(1).startswith("=") else 2
                title = _strip_inline(line.strip())
                headings.append(Heading(level=level, text=title, line=i, raw=line))
                i += 2  # 跳过标题行与下划线行
                continue

        i += 1

    return headings


# ---------------------------------------------------------------------------
# Markdown -> HTML
# ---------------------------------------------------------------------------

_MD_EXTENSIONS = [
    "fenced_code",
    "tables",
    "sane_lists",
    "nl2br",
    "codehilite",
    "toc",
    "attr_list",
    "md_in_html",
]

try:  # 新版 markdown 包
    _MD = _md_lib.Markdown(extensions=_MD_EXTENSIONS, output_format="html")
except Exception:  # pragma: no cover
    _MD = None


# 围栏代码块渲染后的 HTML：<pre ...>...</pre>
_PRE_RE = re.compile(r"<pre\b[^>]*>.*?</pre>", re.S)


def _merge_code_block_lines(html: str) -> str:
    """把 <pre> 代码块内部的换行合并为行分隔符（U+2028）。

    Qt 富文本引擎会把代码块中的每个 ``\\n`` 解析为独立段落（block），
    导致代码块渲染成“一行一个背景条”的栅栏效果。改用 U+2028（行分隔符）
    后整个代码块是单个 block，背景与边框连续呈现为一整块面板。
    """
    def repl(m: "re.Match[str]") -> str:
        return m.group(0).replace("\n", "\u2028")
    return _PRE_RE.sub(repl, html)


def markdown_to_html(text: str) -> str:
    """把 Markdown 文本渲染为 HTML 片段。"""
    if not text:
        return ""
    if _MD is not None:
        # Markdown 实例会被复用，需重置内部状态
        _MD.reset()
        return _merge_code_block_lines(_MD.convert(text))
    # 退化方案：markdown2
    return _merge_code_block_lines(_md_lib.markdown(text))  # type: ignore


# ---------------------------------------------------------------------------
# 文件读取（编码自动识别）
# ---------------------------------------------------------------------------

_ENCODINGS = ["utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1"]


def read_text_file(path: str) -> str:
    """读取文本文件，自动识别编码。

    优先 UTF-8（含 BOM），其次 GB18030/GBK，最后回退 latin-1（不会抛异常）。
    """
    with open(path, "rb") as f:
        raw = f.read()

    # BOM 快速判断
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le", errors="replace")
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be", errors="replace")

    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def detect_encoding(path: str) -> str:
    """探测文件编码名（用于状态栏提示）。"""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"
