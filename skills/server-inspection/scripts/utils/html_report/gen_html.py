#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI: 服务器检查结果 → HTML 报告。用法: python gen_html.py <input_dir> <output_html>"""
from __future__ import annotations

import json
import os
import sys

from .parsers import guess_status, parse_blocks, strip_decorations
from .renderers import build_html


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: python3 -m html_report.gen_html <input_dir> <output_html>")
        sys.exit(1)

    input_dir = sys.argv[1]
    output_html = sys.argv[2]

    meta_path = os.path.join(input_dir, "metadata.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)

    server_ip = meta.get("server_ip", "未知")
    hostname = meta.get("hostname", "未知")
    check_time = meta.get("check_time", "-")

    modules = []
    txt_files = sorted(
        f for f in os.listdir(input_dir) if f.startswith("module_") and f.endswith(".txt")
    )

    for tf in txt_files:
        key = tf[len("module_") : -len(".txt")]
        with open(os.path.join(input_dir, tf), encoding="utf-8", errors="replace") as f:
            text = f.read()
        text = strip_decorations(text)
        blocks = parse_blocks(text)
        status = guess_status(blocks)
        modules.append({"key": key, "status": status, "blocks": blocks})

    if not modules:
        modules.append({
            "key": "_empty",
            "status": "yellow",
            "blocks": [{"title": "", "content": "(未找到模块输出，请检查连接)"}],
        })

    html = build_html(server_ip, hostname, check_time, modules)
    os.makedirs(os.path.dirname(os.path.abspath(output_html)), exist_ok=True)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] HTML 报告已生成: {output_html}")


if __name__ == "__main__":
    main()
