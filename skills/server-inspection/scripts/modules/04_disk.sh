#!/bin/bash
# 磁盘与 Inode
# 用法: bash 04_disk.sh <user@ip>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../utils/remote_exec.sh"

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
    echo "用法: $0 <user@ip>"
    exit 1
fi

echo "============================================"
echo "  [04] 磁盘与 Inode"
echo "============================================"

run_remote "$TARGET" \
    'echo "--- 磁盘使用率 ---"' \
    'df -hP 2>/dev/null | grep -Ev "^Filesystem|tmpfs|devtmpfs|overlay" | head -20' \
    'echo ""' \
    'echo "--- Inode 使用率 ---"' \
    'df -iP 2>/dev/null | grep -Ev "^Filesystem|tmpfs|devtmpfs|overlay" | head -20' \
    'echo ""' \
    'echo "--- 高使用率挂载点 ---"' \
    'df -hP 2>/dev/null | tail -n +2 | grep -Ev "tmpfs|devtmpfs|overlay" | awk '\''{gsub(/%/,"",$5); if ($5+0>=50) print}'\'' | sort -k5 -rn | head -10 || true' \
    'df -hP 2>/dev/null | tail -n +2 | grep -Ev "tmpfs|devtmpfs|overlay" | awk '\''{gsub(/%/,"",$5); if ($5+0>=50) print $5}'\'' | head -1 | grep -q . || echo "无使用率≥50%的挂载点"'

echo ""
