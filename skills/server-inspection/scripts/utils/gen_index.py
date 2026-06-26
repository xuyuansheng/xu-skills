#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_index.py - 批量巡检报告目录页
用法: python3 gen_index.py <manifest.json> <output_index.html>
"""

import json
import os
import sys
from html import escape

C = {
    "bg": "#0d1117",
    "card": "#161b22",
    "border": "#30363d",
    "text": "#c9d1d9",
    "dim": "#8b949e",
    "accent": "#58a6ff",
    "green": "#3fb950",
    "yellow": "#d29922",
    "red": "#f85149",
    "th_bg": "#21262d",
    "row_alt": "#1c2128",
    "row": "#161b22",
}


def status_badge(status: str) -> str:
    mapping = {
        "ok": (C["green"], "正常"),
        "warn": (C["yellow"], "警告"),
        "fail": (C["red"], "失败"),
    }
    color, label = mapping.get(status, (C["dim"], status))
    return f'<span style="color:{color};font-weight:600;">● {label}</span>'


def build_index_html(data: dict) -> str:
    check_time = escape(data.get("check_time", "-"))
    reports = data.get("reports", [])
    failed = data.get("failed", [])
    output_dir = escape(data.get("output_dir", ""))
    total = len(reports) + len(failed)

    rows = ""
    for i, r in enumerate(reports):
        bg = C["row_alt"] if i % 2 else C["row"]
        fname = escape(r.get("file", ""))
        target = escape(r.get("target", ""))
        ip = escape(r.get("ip", ""))
        hostname = escape(r.get("hostname", "-"))
        status = r.get("status", "ok")
        rows += f"""
        <tr style="background:{bg};">
            <td><a href="{fname}" style="color:{C['accent']};text-decoration:none;">{ip}</a></td>
            <td>{hostname}</td>
            <td>{target}</td>
            <td>{status_badge(status)}</td>
            <td><a href="{fname}" style="color:{C['accent']};">查看报告 →</a></td>
        </tr>"""

    failed_rows = ""
    for i, f in enumerate(failed):
        bg = C["row_alt"] if i % 2 else C["row"]
        target = escape(f if isinstance(f, str) else f.get("target", ""))
        reason = escape(f.get("reason", "连接失败") if isinstance(f, dict) else "连接失败")
        failed_rows += f"""
        <tr style="background:{bg};">
            <td colspan="4">{target}</td>
            <td>{status_badge("fail")} {reason}</td>
        </tr>"""

    failed_section = ""
    if failed_rows:
        failed_section = f"""
<h2 style="color:{C['text']};margin-top:32px;">连接失败 ({len(failed)})</h2>
<table style="width:100%;border-collapse:collapse;margin-top:12px;">
    <thead>
        <tr style="background:{C['th_bg']};">
            <th colspan="4" style="padding:10px 14px;text-align:left;color:{C['dim']};">目标</th>
            <th style="padding:10px 14px;text-align:left;color:{C['dim']};">状态</th>
        </tr>
    </thead>
    <tbody>{failed_rows}</tbody>
</table>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>服务器巡检报告目录</title>
<style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        background: {C['bg']};
        color: {C['text']};
        line-height: 1.6;
        padding: 32px 24px;
    }}
    .container {{ max-width: 960px; margin: 0 auto; }}
    h1 {{ color: {C['text']}; font-size: 1.75rem; margin-bottom: 8px; }}
    .meta {{ color: {C['dim']}; font-size: 0.95rem; margin-bottom: 24px; }}
    .summary {{
        display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 28px;
    }}
    .card {{
        background: {C['card']};
        border: 1px solid {C['border']};
        border-radius: 10px;
        padding: 16px 24px;
        min-width: 140px;
    }}
    .card .num {{ font-size: 1.8rem; font-weight: 700; color: {C['accent']}; }}
    .card .lbl {{ color: {C['dim']}; font-size: 0.85rem; }}
    table {{ border: 1px solid {C['border']}; border-radius: 10px; overflow: hidden; }}
    th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid {C['border']}; }}
    th {{ background: {C['th_bg']}; color: {C['dim']}; font-weight: 600; }}
    tr:last-child td {{ border-bottom: none; }}
    a:hover {{ text-decoration: underline !important; }}
    .footer {{ margin-top: 40px; color: {C['dim']}; font-size: 0.85rem; text-align: center; }}
</style>
</head>
<body>
<div class="container">
    <h1>📋 服务器巡检报告目录</h1>
    <p class="meta">检查时间：{check_time} · 输出目录：{output_dir}</p>

    <div class="summary">
        <div class="card"><div class="num">{total}</div><div class="lbl">总计</div></div>
        <div class="card"><div class="num" style="color:{C['green']};">{len(reports)}</div><div class="lbl">成功</div></div>
        <div class="card"><div class="num" style="color:{C['red']};">{len(failed)}</div><div class="lbl">失败</div></div>
    </div>

    <h2 style="color:{C['text']};">巡检报告 ({len(reports)})</h2>
    <table style="width:100%;border-collapse:collapse;margin-top:12px;">
        <thead>
            <tr style="background:{C['th_bg']};">
                <th>IP</th>
                <th>主机名</th>
                <th>登录账号</th>
                <th>状态</th>
                <th>报告</th>
            </tr>
        </thead>
        <tbody>{rows if rows else f'<tr><td colspan="5" style="padding:14px;color:{C["dim"]};">无成功报告</td></tr>'}</tbody>
    </table>
    {failed_section}
    <p class="footer">由 JumpServer Monitor Skill 生成 · {check_time}</p>
</div>
</body>
</html>"""


def main():
    if len(sys.argv) < 3:
        print("用法: python3 gen_index.py <manifest.json> <output_index.html>")
        sys.exit(1)

    manifest_path = sys.argv[1]
    output_html = sys.argv[2]

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    html = build_index_html(data)
    os.makedirs(os.path.dirname(os.path.abspath(output_html)), exist_ok=True)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] 目录页已生成: {output_html}")


if __name__ == "__main__":
    main()
