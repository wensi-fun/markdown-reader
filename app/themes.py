# -*- coding: utf-8 -*-
"""主题（配色）定义。

固定使用白色主题（light）：
- ``palette``: 各控件背景/前景色（供 QSS 使用）
- ``preview_css``: 预览区（QTextDocument）的样式表
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Theme:
    name: str
    label: str
    palette: Dict[str, str] = field(default_factory=dict)
    preview_css: str = ""


# 通用预览 CSS 片段（与配色无关的排版）
def _preview_css(p: Dict[str, str]) -> str:
    """根据调色板生成预览区 CSS。"""
    return f"""
    body {{
        font-family: "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif;
        font-size: 15px;
        line-height: 1.9;
        color: {p['text']};
        background-color: {p['preview_bg']};
        margin: 28px 40px;
    }}
    /* 注意：Qt 不会把 body 的 line-height 继承给段落块（block），
       因此段落/列表/引用等块级元素需逐一显式声明行距，否则回退为默认行高（偏挤）。 */
    p {{ margin: 16px 0; line-height: 1.9; }}

    h1, h2, h3, h4, h5, h6 {{
        font-weight: 600;
        line-height: 1.3;
        margin-top: 1.2em;
        margin-bottom: 0.5em;
        color: {p['heading']};
    }}
    h1 {{ font-size: 2.0em; border-bottom: 2px solid {p['hr']}; padding-bottom: 0.3em; }}
    h2 {{ font-size: 1.6em; border-bottom: 1px solid {p['hr']}; padding-bottom: 0.25em; }}
    h3 {{ font-size: 1.35em; }}
    h4 {{ font-size: 1.15em; }}
    h5 {{ font-size: 1.0em; }}
    h6 {{ font-size: 0.9em; color: {p['muted']}; }}

    a {{ color: {p['link']}; text-decoration: none; }}

    strong {{ font-weight: 700; }}
    em {{ font-style: italic; }}

    code {{
        font-family: "Cascadia Code", Consolas, "Courier New", monospace;
        font-size: 0.92em;
        background-color: {p['code_bg']};
        color: {p['code_fg']};
        padding: 2px 5px;
        border-radius: 4px;
    }}
    pre {{
        font-family: "Cascadia Code", Consolas, "Courier New", monospace;
        font-size: 0.92em;
        background-color: {p['codeblock_bg']};
        color: {p['code_fg']};
        border: 1px solid {p['border']};
        border-radius: 6px;
        padding: 12px 14px;
        line-height: 1.55;
        white-space: pre-wrap;
    }}
    pre code {{ background-color: transparent; padding: 0; }}

    blockquote {{
        margin: 16px 0;
        padding: 6px 16px;
        color: {p['muted']};
        background-color: {p['quote_bg']};
        border-left: 4px solid {p['quote_border']};
        line-height: 1.9;
    }}

    ul, ol {{ margin: 12px 0; padding-left: 26px; }}
    li {{ margin: 8px 0; line-height: 1.9; }}

    hr {{
        border: none;
        border-top: 1px solid {p['hr']};
        margin: 22px 0;
    }}

    table {{
        border-collapse: collapse;
        margin: 14px 0;
        width: 100%;
    }}
    th, td {{
        border: 1px solid {p['border']};
        padding: 7px 12px;
        text-align: left;
        line-height: 1.6;
    }}
    th {{
        background-color: {p['table_head_bg']};
        font-weight: 600;
    }}
    tr:nth-child(even) td {{ background-color: {p['table_alt_bg']}; }}

    /* 图片宽度由 PreviewView._fit_images 按可视区缩放（Qt 不支持 max-width） */
    """


def _make_palette() -> Dict[str, str]:
    """生成白色主题调色板。"""
    return {
        "window_bg": "#ffffff",
        "panel_bg": "#ffffff",
        "outline_bg": "#fafafa",
        "editor_bg": "#ffffff",
        "preview_bg": "#ffffff",
        "toolbar_bg": "#f5f5f7",
        "text": "#24292f",
        "muted": "#6a737d",
        "heading": "#1b1f23",
        "link": "#0969da",
        "border": "#d8dee4",
        "hr": "#e1e4e8",
        "code_bg": "#f0f1f3",
        "code_fg": "#cf222e",
        "codeblock_bg": "#f6f8fa",
        "quote_bg": "#f6f8fa",
        "quote_border": "#d0d7de",
        "table_head_bg": "#f0f1f3",
        "table_alt_bg": "#fafbfc",
        "selection": "#b6d7ff",
        "outline_sel_bg": "#d7e6fb",
        "outline_sel_fg": "#0b2545",
        "search_all": "#fff59d",
        "search_first": "#ff9800",
    }


THEMES: Dict[str, Theme] = {
    "light": Theme(name="light", label="白色主题", palette=_make_palette()),
}
THEMES["light"].preview_css = _preview_css(THEMES["light"].palette)


def get_theme(name: str = "light") -> Theme:
    return THEMES.get(name, THEMES["light"])


def build_qss(p: Dict[str, str]) -> str:
    """生成主窗口全局 QSS（控制各控件配色）。"""
    return f"""
    QMainWindow, QWidget#CentralWidget {{
        background-color: {p['window_bg']};
    }}
    QToolBar#MainToolBar {{
        background-color: {p['toolbar_bg']};
        border-bottom: 1px solid {p['border']};
        padding: 4px 6px;
        spacing: 6px;
    }}
    QToolBar#MainToolBar QToolButton {{
        color: {p['text']};
        padding: 5px 10px;
        border-radius: 5px;
    }}
    QToolBar#MainToolBar QToolButton:hover {{
        background-color: {p['outline_sel_bg']};
    }}
    QToolBar#MainToolBar QToolButton:checked {{
        background-color: {p['outline_sel_bg']};
        color: {p['outline_sel_fg']};
    }}
    QLineEdit#SearchBox {{
        background-color: {p['editor_bg']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 5px;
        padding: 4px 8px;
        selection-background-color: {p['selection']};
    }}
    QLabel#StatusLabel {{
        color: {p['muted']};
        padding: 2px 8px;
    }}
    QSplitter::handle {{
        background-color: {p['border']};
    }}
    QTreeWidget#OutlineTree {{
        background-color: {p['outline_bg']};
        color: {p['text']};
        border: none;
        outline: none;
        padding: 6px 4px;
    }}
    QTreeWidget#OutlineTree::item {{
        padding: 3px 4px;
        border-radius: 4px;
    }}
    QTreeWidget#OutlineTree::item:hover {{
        background-color: {p['table_alt_bg']};
    }}
    QTreeWidget#OutlineTree::item:selected {{
        background-color: {p['outline_sel_bg']};
        color: {p['outline_sel_fg']};
    }}
    QPlainTextEdit#Editor, QTextBrowser#Preview {{
        background-color: {p['editor_bg']};
        color: {p['text']};
        border: none;
        selection-background-color: {p['selection']};
        padding: 10px 16px;
    }}
    QPlainTextEdit#Editor {{
        font-family: "Cascadia Code", Consolas, "Courier New", monospace;
        font-size: 14px;
        line-height: 1.7;
    }}
    QLabel#OutlineTitle {{
        color: {p['muted']};
        font-weight: 600;
        padding: 0;
    }}
    QToolButton#OutlineToggle {{
        color: {p['muted']};
        border: none;
        border-radius: 4px;
        padding: 1px 7px;
        font-size: 10px;
    }}
    QToolButton#OutlineToggle:hover {{
        background-color: {p['outline_sel_bg']};
        color: {p['outline_sel_fg']};
    }}
    """
