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

CONN_SUMMARY_BLOCK='
if command -v "$SS_CMD" >/dev/null 2>&1; then
    echo ""
    echo "--- 连接状态摘要 ---"
    "$SS_CMD" -s 2>/dev/null | head -8
fi'

if [[ -n "${JUMPSERVER_QUICK:-}" ]]; then
    CONN_SUMMARY_BLOCK='
echo ""
echo "[quick] 已跳过: 连接状态摘要 (ss -s)"'
fi

REMOTE_SCRIPT=$(cat <<'REMOTE_EOF'
IP_CMD=ip; command -v ip >/dev/null 2>&1 || IP_CMD=/sbin/ip; command -v "$IP_CMD" >/dev/null 2>&1 || IP_CMD=/usr/sbin/ip
SS_CMD=ss; command -v ss >/dev/null 2>&1 || SS_CMD=/sbin/ss; command -v "$SS_CMD" >/dev/null 2>&1 || SS_CMD=/usr/sbin/ss
NETSTAT=/bin/netstat; command -v netstat >/dev/null 2>&1 || NETSTAT=netstat

echo "--- 网络接口 IP ---"
if command -v "$IP_CMD" >/dev/null 2>&1; then
    "$IP_CMD" -4 addr show 2>/dev/null | grep -E "^[0-9]+:|inet "
elif command -v ifconfig >/dev/null 2>&1; then
    ifconfig 2>/dev/null | grep -E "^[a-z]|inet "
else
    echo "[采集失败] 未找到 ip/ifconfig 命令"
fi

echo ""
echo "--- 监听端口 ---"
# 先用当前账号采集；仅当缺少 Process/PID 且非 root 时才尝试 sudo
_collect_listen_ports() {
    local SS NETSTAT out
    SS=ss; command -v ss >/dev/null 2>&1 || SS=/sbin/ss
    NETSTAT=/bin/netstat; command -v netstat >/dev/null 2>&1 || NETSTAT=netstat

    if command -v "$SS" >/dev/null 2>&1; then
        out=$("$SS" -tlnp 2>/dev/null | tail -n +2)
        if [ -n "$out" ] && _output_has_process_info "$out"; then
            echo "$out"
            return
        fi
        if [ "$(id -u)" -eq 0 ]; then
            if [ -n "$out" ]; then
                echo "$out"
            else
                "$SS" -tln 2>/dev/null | tail -n +2
            fi
            return
        fi
        # 非 root 且缺少进程信息 → 按需提权
        run_privileged_pipe <<'EOS'
SS=ss; command -v ss >/dev/null 2>&1 || SS=/sbin/ss
NETSTAT=/bin/netstat; command -v netstat >/dev/null 2>&1 || NETSTAT=netstat
if command -v "$SS" >/dev/null 2>&1; then
    "$SS" -tlnp 2>/dev/null | tail -n +2
    if ! "$SS" -tlnp 2>/dev/null | tail -n +2 | grep -qE 'pid=|users:\('; then
        "$SS" -tln 2>/dev/null | tail -n +2
    fi
elif command -v "$NETSTAT" >/dev/null 2>&1; then
    echo "[source:netstat]"
    "$NETSTAT" -tlnp 2>/dev/null | tail -n +3 || "$NETSTAT" -tln 2>/dev/null | tail -n +3
else
    echo "[采集失败] 未找到 ss/netstat 命令"
fi
EOS
        return
    fi

    if command -v "$NETSTAT" >/dev/null 2>&1; then
        out=$("$NETSTAT" -tlnp 2>/dev/null | tail -n +3)
        if [ -n "$out" ] && _output_has_process_info "$out"; then
            echo "[source:netstat]"
            echo "$out"
            return
        fi
        if [ "$(id -u)" -eq 0 ]; then
            echo "[source:netstat]"
            echo "$out"
            [ -n "$out" ] || "$NETSTAT" -tln 2>/dev/null | tail -n +3
            return
        fi
        run_privileged_pipe <<'EOS'
NETSTAT=/bin/netstat; command -v netstat >/dev/null 2>&1 || NETSTAT=netstat
echo "[source:netstat]"
"$NETSTAT" -tlnp 2>/dev/null | tail -n +3 || "$NETSTAT" -tln 2>/dev/null | tail -n +3
EOS
        return
    fi

    echo "[采集失败] 未找到 ss/netstat 命令"
}
_collect_listen_ports

echo ""
echo "--- 连接统计 ---"
if command -v "$SS_CMD" >/dev/null 2>&1; then
    ESTAB=$("$SS_CMD" -tan 2>/dev/null | grep -c ESTAB || echo 0)
    LISTEN=$("$SS_CMD" -tln 2>/dev/null | tail -n +2 | wc -l)
    TOTAL=$("$SS_CMD" -tan 2>/dev/null | tail -n +2 | wc -l)
    TW=$("$SS_CMD" -tan state time-wait 2>/dev/null | tail -n +2 | wc -l)
    echo "已建立: $ESTAB | 监听中: $LISTEN | TIME_WAIT: $TW | 总连接: $TOTAL"
else
    echo "[采集失败] ss 不可用"
fi
REMOTE_EOF
)
REMOTE_SCRIPT+="${CONN_SUMMARY_BLOCK}"

run_remote_script "$TARGET" "$REMOTE_SCRIPT" true

echo ""
