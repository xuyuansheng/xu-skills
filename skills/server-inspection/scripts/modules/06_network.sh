#!/bin/bash
# 网络与端口
# 用法: bash 06_network.sh <user@ip>

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../utils/remote_exec.sh"

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
    echo "用法: $0 <user@ip>"
    exit 1
fi

echo "============================================"
echo "  [06] 网络与端口"
echo "============================================"

run_remote "$TARGET" \
    'echo "--- 网络接口 IP ---"' \
    'ip -4 addr show 2>/dev/null | grep -E "^[0-9]+:|inet " || ifconfig 2>/dev/null | grep -E "^[a-z]|inet "' \
    'echo ""' \
    'echo "--- 监听端口 ---"' \
    'ss -tlnp 2>/dev/null | tail -n +2 || netstat -tlnp 2>/dev/null | tail -n +3' \
    'echo ""' \
    'echo "--- 连接统计 ---"' \
    'echo "已建立: $(ss -tun 2>/dev/null | grep -c ESTAB) | 监听中: $(ss -tln 2>/dev/null | tail -n +2 | wc -l) | 总连接: $(ss -tun 2>/dev/null | tail -n +2 | wc -l)"'

echo ""
