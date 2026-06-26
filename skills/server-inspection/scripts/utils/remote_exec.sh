#!/bin/bash
# remote_exec.sh - 通过 JumpServer 堡垒机 ProxyJump 连接目标服务器
# 供各模块脚本 source 使用
#
# 用法（在其他脚本中）：
#   source "$(dirname "$0")/utils/remote_exec.sh"
#   run_remote "root@172.16.202.92" "your command here"
#   run_remote "root@172.16.202.92" "cmd1" "cmd2" "cmd3"

# ── 定位配置文件 ─────────────────────────────────────────────
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_CONFIG_DIR="$(cd "$_SCRIPT_DIR/../../config" && pwd)"

BASTION_CONF="$_CONFIG_DIR/bastion.conf"

if [[ ! -f "$BASTION_CONF" ]]; then
    echo "[ERROR] 找不到堡垒机配置文件: $BASTION_CONF" >&2
    exit 1
fi

source "$BASTION_CONF"

SSH_OPTS="${SSH_OPTS:-"-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o LogLevel=ERROR"}"
SSH_PROXY="ssh $SSH_OPTS -p $BASTION_PORT $BASTION_USER@$BASTION_HOST -W %h:%p"

# ── 核心函数：在远程服务器执行命令 ─────────────────────────
run_remote() {
    local target="$1"
    shift
    local cmds=("$@")

    if [[ -z "$target" ]]; then
        echo "[ERROR] run_remote: 缺少目标服务器 user@ip" >&2
        return 1
    fi

    # 拼接多条命令
    local cmd_str
    if [[ ${#cmds[@]} -eq 0 ]]; then
        echo "[ERROR] run_remote: 缺少要执行的命令" >&2
        return 1
    fi

    cmd_str="$(IFS=';'; echo "${cmds[*]}")"

    ssh $SSH_OPTS \
        -o ProxyCommand="$SSH_PROXY" \
        "$target" "$cmd_str" 2>&1 | grep -v -E "post-quantum|store now, decrypt later|WARNING: connection is not|server may need to be upgraded|openssh\.com/pq"
}

# ── 核心函数：在远程服务器执行多行脚本 ─────────────────────
run_remote_heredoc() {
    local target="$1"
    local heredoc_content="$2"

    if [[ -z "$target" ]]; then
        echo "[ERROR] run_remote_heredoc: 缺少目标服务器 user@ip" >&2
        return 1
    fi

    ssh $SSH_OPTS \
        -o ProxyCommand="$SSH_PROXY" \
        "$target" "bash -s" 2>&1 <<EOF | grep -v -E "post-quantum|store now, decrypt later|WARNING: connection is not|server may need to be upgraded|openssh\.com/pq"
$heredoc_content
EOF
}

# ── 确认连接到的服务器 IP ───────────────────────────────────
confirm_server() {
    local target="$1"
    local reported_ip
    reported_ip="$(run_remote "$target" "hostname -I 2>/dev/null || hostname")"
    echo "$reported_ip"
}
