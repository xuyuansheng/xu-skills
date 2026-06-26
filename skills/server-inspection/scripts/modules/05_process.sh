#!/bin/bash
# 进程分析
# 用法: bash 05_process.sh <user@ip>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../utils/remote_exec.sh"

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
    echo "用法: $0 <user@ip>"
    exit 1
fi

echo "============================================"
echo "  [05] 进程分析"
echo "============================================"

run_remote "$TARGET" \
    'echo "--- 进程统计 ---"' \
    'TOTAL=$(ps -e 2>/dev/null | wc -l); ZOMBIE=$(ps aux 2>/dev/null | awk "\$8 ~ /Z/" | wc -l); RUNNING=$(ps -eo stat 2>/dev/null | grep -c "^R"); echo "总数: $TOTAL | 运行中: $RUNNING | 僵尸: $ZOMBIE"' \
    'echo ""' \
    'echo "--- 僵尸进程详情 ---"' \
    'ZOUT=$(ps aux 2>/dev/null | awk "\$8 ~ /Z/ {print}"); if [ -z "$ZOUT" ]; then echo "无僵尸进程"; else echo "$ZOUT"; fi' \
    'echo ""' \
    'echo "--- CPU Top 5 ---"' \
    'ps -eo pid,user,%cpu,%mem,comm --sort=-%cpu 2>/dev/null | head -6' \
    'echo ""' \
    'echo "--- 内存 Top 5 ---"' \
    'ps -eo pid,user,%cpu,%mem,rss,comm --sort=-%mem 2>/dev/null | head -6'

echo ""
