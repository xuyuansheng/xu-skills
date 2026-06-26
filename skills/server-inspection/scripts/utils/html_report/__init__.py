"""服务器巡检 HTML 报告生成包。"""
from .renderers import build_html
from .parsers import guess_status, parse_blocks, strip_decorations

__all__ = ["build_html", "guess_status", "parse_blocks", "strip_decorations"]
