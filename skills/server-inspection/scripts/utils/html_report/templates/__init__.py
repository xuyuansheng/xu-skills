"""HTML 模板资源加载。"""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).resolve().parent
_COLOR_PREFIX = "@C:"


def load_css(colors: dict[str, str]) -> str:
    tpl = (_DIR / "report.css").read_text(encoding="utf-8")
    for key, val in colors.items():
        tpl = tpl.replace(f"{_COLOR_PREFIX}{key}@", val)
    return "<style>\n" + tpl + "\n</style>"


def load_tab_js() -> str:
    return "<script>\n" + (_DIR / "tabs.js").read_text(encoding="utf-8") + "\n</script>"
