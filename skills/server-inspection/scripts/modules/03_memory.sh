#!/bin/bash
# 内存与 Swap
# 用法: bash 03_memory.sh <user@ip>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../utils/remote_exec.sh"

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
    echo "用法: $0 <user@ip>"
    exit 1
fi

echo "============================================"
echo "  [03] 内存与 Swap"
echo "============================================"

run_remote "$TARGET" \
    'echo "--- 内存总览 ---"' \
    'free -h' \
    'echo ""' \
    'echo "--- 内存使用率 ---"' \
    'free | awk "/Mem:/ {printf \"%.1f%%\n\", (\$3/\$2)*100}"' \
    'echo ""' \
    'echo "--- Swap 状态 ---"' \
    'swapon --show 2>/dev/null | tail -n +2 || echo "未启用"' \
    'echo ""' \
    'echo "--- 高内存进程 Top 5 ---"' \
    'ps -eo pid,user,%cpu,%mem,rss,comm --sort=-%mem 2>/dev/null | head -6'

echo ""
