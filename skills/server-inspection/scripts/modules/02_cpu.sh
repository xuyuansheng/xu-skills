#!/bin/bash
# CPU 与负载
# 用法: bash 02_cpu.sh <user@ip>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../utils/remote_exec.sh"

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
    echo "用法: $0 <user@ip>"
    exit 1
fi

echo "============================================"
echo "  [02] CPU 与负载"
echo "============================================"

run_remote "$TARGET" \
    'echo "--- 系统负载 ---"' \
    'uptime' \
    'echo "CPU核数: $(nproc)"' \
    'echo ""' \
    'echo "--- 运行队列 ---"' \
    'vmstat 1 2 2>/dev/null | tail -1 || echo "vmstat 不可用"' \
    'echo ""' \
    'echo "--- CPU 使用率分布 ---"' \
    'top -bn1 2>/dev/null | grep -E "Cpu\\(s\\)|%Cpu" | head -1 || mpstat 1 1 2>/dev/null | tail -1 || echo "无法获取"' \
    'echo ""' \
    'echo "--- 每核 CPU (mpstat) ---"' \
    'mpstat -P ALL 1 1 2>/dev/null | tail -n +4 || echo "mpstat 不可用"' \
    'echo ""' \
    'echo "--- CPU Top 5 ---"' \
    'ps -eo pid,user,%cpu,%mem,comm --sort=-%cpu 2>/dev/null | head -6'

echo ""
