#!/bin/bash
# remote_exec.sh - SSH 连接目标服务器（堡垒机 ProxyJump 或直连）
# 供各模块脚本 source 使用
#
# 连接模式（SSH_CONNECT_MODE）：
#   bastion  默认，经 JumpServer ProxyCommand 穿透（config/bastion.conf）
#   direct   直连目标服务器（需本机网络可达）
#
# 用法：
#   run_remote "root@172.16.202.92" "your command here"
#   run_remote "root@172.18.4.254:yourpassword" "cmd"   # 直连模式密码（需引号包裹含 $ 的密码）
#
# 目标格式（直连 + 密码）：
#   user@ipv4:password  例如 root@172.18.4.254:2wsx\$RFV（shell 中建议单引号）

# ── 定位配置文件 ─────────────────────────────────────────────
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_CONFIG_DIR="$(cd "${JUMPSERVER_CONFIG_DIR:-$_SCRIPT_DIR/../../config}" 2>/dev/null && pwd || echo "${JUMPSERVER_CONFIG_DIR:-$_SCRIPT_DIR/../../config}")"

BASTION_CONF="$_CONFIG_DIR/bastion.conf"

if [[ ! -f "$BASTION_CONF" ]]; then
    echo "[ERROR] 找不到配置文件: $BASTION_CONF" >&2
    if [[ -f "$_CONFIG_DIR/bastion.conf.example" ]]; then
        echo "[INFO]  首次使用请执行: cp config/bastion.conf.example config/bastion.conf" >&2
        echo "[INFO]  编辑 bastion.conf 填入堡垒机地址与账号（勿提交到 Git）" >&2
    fi
    exit 1
fi

# 保留命令行/环境变量传入的默认连接模式（source 前 export SSH_CONNECT_MODE=... 可覆盖 config 默认值）
_SAVED_DEFAULT_MODE="${SSH_CONNECT_MODE:-}"

source "$BASTION_CONF"

SSH_DEFAULT_CONNECT_MODE="${_SAVED_DEFAULT_MODE:-${SSH_CONNECT_MODE:-bastion}}"
SSH_CONNECT_MODE="$SSH_DEFAULT_CONNECT_MODE"
SSH_OPTS="${SSH_OPTS:-"-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o LogLevel=ERROR"}"

if [[ -z "${BASTION_HOST:-}" || -z "${BASTION_PORT:-}" || -z "${BASTION_USER:-}" ]]; then
    if [[ "$SSH_DEFAULT_CONNECT_MODE" == "bastion" ]]; then
        echo "[ERROR] 堡垒机模式需在 bastion.conf 中配置 BASTION_HOST / BASTION_PORT / BASTION_USER" >&2
        exit 1
    fi
fi

if [[ -n "${BASTION_HOST:-}" && -n "${BASTION_PORT:-}" && -n "${BASTION_USER:-}" ]]; then
    SSH_PROXY="ssh $SSH_OPTS -p $BASTION_PORT $BASTION_USER@$BASTION_HOST -W %h:%p"
else
    SSH_PROXY=""
fi

export SSH_CONNECT_MODE SSH_DEFAULT_CONNECT_MODE

# 解析后暂存（勿在 $(...) 子 shell 中调用 parse_ssh_target）
_SSH_PARSED_TARGET=""
_SSH_TARGET_PW=""

# 解析 user@host[:password] → _SSH_PARSED_TARGET / _SSH_TARGET_PW
parse_ssh_target() {
    local raw="$1"
    local user host_part host password

    _SSH_PARSED_TARGET="$raw"
    _SSH_TARGET_PW=""

    if [[ "$raw" != *"@"* ]]; then
        return 0
    fi

    user="${raw%%@*}"
    host_part="${raw#*@}"

    if [[ "$host_part" =~ ^([0-9]{1,3}(\.[0-9]{1,3}){3}):(.+)$ ]]; then
        host="${BASH_REMATCH[1]}"
        password="${BASH_REMATCH[3]}"
        _SSH_PARSED_TARGET="${user}@${host}"
        _SSH_TARGET_PW="$password"
        return 0
    fi

    if [[ "$host_part" == *:* && "$host_part" != *::* ]]; then
        host="${host_part%%:*}"
        password="${host_part#*:}"
        if [[ -n "$host" && -n "$password" ]]; then
            _SSH_PARSED_TARGET="${user}@${host}"
            _SSH_TARGET_PW="$password"
        fi
    fi
}

# 从规范化 target 提取 IP/主机名（用于报告文件名）
target_host_ip() {
    local target="$1"
    local host="${target#*@}"
    if [[ "$host" =~ ^([0-9]{1,3}(\.[0-9]{1,3}){3})$ ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        echo "${host%%:*}"
    fi
}

# 为当前目标设置 SSH_TARGET_PASSWORD（由 check_server 或 run_remote 调用）
apply_target_auth() {
    local target="$1"
    local password="${2:-}"

    if [[ -z "$password" ]] && declare -p TARGET_PASSWORDS &>/dev/null 2>&1; then
        password="${TARGET_PASSWORDS["$target"]-}"
    fi

    if [[ -z "$password" && -n "${SSH_ASKPASS_FILE:-}" && -f "${SSH_ASKPASS_FILE:-}" ]]; then
        if [[ -z "${SSH_ACTIVE_TARGET:-}" || "${SSH_ACTIVE_TARGET}" == "$target" ]]; then
            password="$(cat "$SSH_ASKPASS_FILE")"
        fi
    fi

    if [[ -z "$password" && -n "${SSH_TARGET_PASSWORD:-}" ]]; then
        if [[ -z "${SSH_ACTIVE_TARGET:-}" || "${SSH_ACTIVE_TARGET}" == "$target" ]]; then
            return 0
        fi
    fi

    if [[ -n "$password" ]]; then
        if [[ "$SSH_CONNECT_MODE" != "direct" ]]; then
            echo "[WARN] 非直连目标 $target 忽略密码" >&2
            unset SSH_TARGET_PASSWORD
            return 0
        fi
        export SSH_TARGET_PASSWORD="$password"
        setup_ssh_password_file "$password"
    elif [[ -z "${SSH_TARGET_PASSWORD:-}" && -z "${SSH_ASKPASS_FILE:-}" ]]; then
        unset SSH_TARGET_PASSWORD
    fi
}

# 解析单台目标的连接模式（优先级：显式指定 > 含密码 > bastion.conf 默认）
resolve_target_connect_mode() {
    local target="$1"

    if declare -p TARGET_CONNECT_MODES &>/dev/null 2>&1; then
        if [[ -n "${TARGET_CONNECT_MODES[$target]+set}" ]]; then
            echo "${TARGET_CONNECT_MODES[$target]}"
            return 0
        fi
    fi
    if declare -p TARGET_PASSWORDS &>/dev/null 2>&1; then
        if [[ -n "${TARGET_PASSWORDS[$target]+set}" ]]; then
            echo "direct"
            return 0
        fi
    fi
    # 子进程继承的密码会话（模块脚本内 TARGET_PASSWORDS 不可用）
    if [[ -n "${SSH_TARGET_PASSWORD:-}${SSH_ASKPASS_FILE:-}" ]]; then
        if [[ -z "${SSH_ACTIVE_TARGET:-}" || "${SSH_ACTIVE_TARGET}" == "$target" ]]; then
            echo "direct"
            return 0
        fi
    fi
    echo "$SSH_DEFAULT_CONNECT_MODE"
}

set_target_connect_mode() {
    SSH_CONNECT_MODE="$1"
    export SSH_CONNECT_MODE
}

# 激活单台目标的连接模式与凭据（SSH / 模块执行前调用）
activate_ssh_target() {
    local target="$1"
    local mode password

    # 切换目标时清理上一台直连遗留的密码，避免误用 direct 模式连接堡垒机目标
    if [[ -n "${SSH_ACTIVE_TARGET:-}" && "${SSH_ACTIVE_TARGET}" != "$target" ]]; then
        cleanup_ssh_password_file
    fi

    mode="$(resolve_target_connect_mode "$target")"
    set_target_connect_mode "$mode"
    if [[ "$mode" != "direct" ]]; then
        cleanup_ssh_password_file
    fi
    apply_target_auth "$target"
    export SSH_ACTIVE_TARGET="$target"
}

# 将密码写入临时文件供 SSH_ASKPASS / 子进程使用（避免 Windows 丢环境变量）
setup_ssh_password_file() {
    local password="$1"

    if [[ -z "$password" ]]; then
        return 0
    fi

    if [[ -n "${SSH_ASKPASS_FILE:-}" && -f "${SSH_ASKPASS_FILE:-}" ]]; then
        rm -f "$SSH_ASKPASS_FILE" 2>/dev/null || true
    fi

    SSH_ASKPASS_FILE="$(mktemp "${TMPDIR:-/tmp}/jumpserver-ssh-pass.XXXXXX" 2>/dev/null || mktemp 2>/dev/null || echo "/tmp/jumpserver-ssh-pass-$$")"
    printf '%s' "$password" > "$SSH_ASKPASS_FILE"
    chmod 600 "$SSH_ASKPASS_FILE" 2>/dev/null || true
    export SSH_ASKPASS_FILE
    export SSH_TARGET_PASSWORD="$password"
}

cleanup_ssh_password_file() {
    if [[ -n "${SSH_ASKPASS_FILE:-}" && -f "${SSH_ASKPASS_FILE:-}" ]]; then
        rm -f "$SSH_ASKPASS_FILE" 2>/dev/null || true
    fi
    unset SSH_ASKPASS_FILE SSH_TARGET_PASSWORD
}

# 进程退出时清理密码临时文件（同一 shell 内只注册一次）
if [[ -z "${JUMPSERVER_TRAP_REGISTERED:-}" ]]; then
    trap cleanup_ssh_password_file EXIT
    JUMPSERVER_TRAP_REGISTERED=1
    export JUMPSERVER_TRAP_REGISTERED
fi

# 导出凭据供模块子进程使用（关联数组无法 export，必须显式传递）
export_ssh_session() {
    local target="$1"
    local password="${2:-${TARGET_PASSWORDS[$target]-}}"

    activate_ssh_target "$target"
    if [[ -n "$password" ]]; then
        setup_ssh_password_file "$password"
    elif [[ "$SSH_CONNECT_MODE" != "direct" ]]; then
        cleanup_ssh_password_file
    fi
    export SSH_CONNECT_MODE SSH_ACTIVE_TARGET="$target"
    [[ -n "${SSH_TARGET_PASSWORD:-}" ]] && export SSH_TARGET_PASSWORD
}

strip_target_quotes() {
    local s="$1"
    s="${s#\'}"; s="${s%\'}"
    s="${s#\"}"; s="${s%\"}"
    echo "$s"
}

# ── 过滤 SSH 无关警告 ─────────────────────────────────────────
_filter_ssh_noise() {
    grep -v -E "post-quantum|store now, decrypt later|WARNING: connection is not|server may need to be upgraded|openssh\.com/pq"
}

# ── 统一 SSH 调用（按连接模式附加 ProxyCommand / 密码）──────
_ssh_password_auth_available() {
    command -v sshpass >/dev/null 2>&1 && return 0
    [[ -f "$_SCRIPT_DIR/ssh_askpass.sh" ]] && return 0
    [[ -f "$_SCRIPT_DIR/ssh_password.py" ]] && _python_has_paramiko && return 0
    return 1
}

_python_has_paramiko() {
    local py
    py="$(_find_python_for_ssh)"
    [[ -n "$py" ]] && "$py" -c "import paramiko" 2>/dev/null
}

_find_python_for_ssh() {
    local managed_py="C:/Users/xuyuansheng/.workbuddy/binaries/python/versions/3.13.12/python.exe"
    if [[ -f "$managed_py" ]]; then
        echo "$managed_py"
    elif command -v python3 &>/dev/null; then
        echo "python3"
    elif command -v python &>/dev/null; then
        echo "python"
    else
        echo ""
    fi
}

_run_ssh_with_paramiko() {
    local target="$1"
    shift
    local py cmd rc

    py="$(_find_python_for_ssh)"
    if [[ -z "$py" ]] || ! "$py" -c "import paramiko" 2>/dev/null; then
        return 127
    fi

    if [[ $# -eq 1 && "$1" == "bash -s" ]]; then
        "$py" "$_SCRIPT_DIR/ssh_password.py" "$target" --script
        return $?
    fi

    cmd="$*"
    "$py" "$_SCRIPT_DIR/ssh_password.py" "$target" "$cmd"
    return $?
}

_run_ssh_with_password() {
    local -a ssh_args=("$@")
    local pw_opts="-o PreferredAuthentications=password -o PubkeyAuthentication=no -o NumberOfPasswordPrompts=1"

    if _python_has_paramiko; then
        _run_ssh_with_paramiko "${ssh_args[@]}"
        return $?
    fi

    if command -v sshpass >/dev/null 2>&1; then
        SSHPASS="$SSH_TARGET_PASSWORD" sshpass -e \
            ssh $SSH_OPTS $pw_opts "${ssh_args[@]}"
        return $?
    fi

    local askpass="$_SCRIPT_DIR/ssh_askpass.sh"
    if [[ ! -f "$askpass" ]]; then
        echo "[ERROR] 密码登录需要 paramiko、sshpass 或 ssh_askpass.sh" >&2
        echo "[INFO]  推荐: pip install paramiko" >&2
        return 1
    fi
    chmod +x "$askpass" 2>/dev/null || true

    DISPLAY="${DISPLAY:-:0}" SSH_ASKPASS="$askpass" SSH_ASKPASS_REQUIRE=force \
        ssh $SSH_OPTS $pw_opts -o KbdInteractiveAuthentication=no "${ssh_args[@]}"
}

_run_ssh() {
    if [[ -n "${SSH_TARGET_PASSWORD:-}${SSH_ASKPASS_FILE:-}" ]]; then
        if [[ "$SSH_CONNECT_MODE" != "direct" ]]; then
            echo "[ERROR] 密码登录仅支持直连模式" >&2
            return 1
        fi
        if [[ -z "${SSH_TARGET_PASSWORD:-}" && -n "${SSH_ASKPASS_FILE:-}" && -f "${SSH_ASKPASS_FILE:-}" ]]; then
            export SSH_TARGET_PASSWORD="$(cat "$SSH_ASKPASS_FILE")"
        fi
        if ! _ssh_password_auth_available; then
            echo "[ERROR] 密码登录需要 paramiko（pip install paramiko）、sshpass 或 SSH_ASKPASS" >&2
            return 1
        fi
        _run_ssh_with_password "$@"
        return $?
    fi

    if [[ "$SSH_CONNECT_MODE" == "direct" ]]; then
        ssh $SSH_OPTS "$@"
    else
        ssh $SSH_OPTS -o ProxyCommand="$SSH_PROXY" "$@"
    fi
}

ssh_connect_mode_label() {
    if [[ "$SSH_CONNECT_MODE" == "direct" ]]; then
        if [[ -n "${SSH_TARGET_PASSWORD:-}" ]]; then
            echo "SSH 直连 (密码)"
        else
            echo "SSH 直连"
        fi
    else
        echo "堡垒机 ${BASTION_USER}@${BASTION_HOST}:${BASTION_PORT}"
    fi
}

# ── 核心函数：在远程服务器执行命令 ─────────────────────────
run_remote() {
    local target="$1"
    shift
    local cmds=("$@")

    if [[ -z "$target" ]]; then
        echo "[ERROR] run_remote: 缺少目标服务器 user@ip" >&2
        return 1
    fi

    if [[ ${#cmds[@]} -eq 0 ]]; then
        echo "[ERROR] run_remote: 缺少要执行的命令" >&2
        return 1
    fi

    parse_ssh_target "$target"
    target="$_SSH_PARSED_TARGET"
    if [[ -n "${_SSH_TARGET_PW:-}" ]]; then
        if ! declare -p TARGET_PASSWORDS &>/dev/null 2>&1; then
            declare -gA TARGET_PASSWORDS
        fi
        TARGET_PASSWORDS["$target"]="$_SSH_TARGET_PW"
        setup_ssh_password_file "$_SSH_TARGET_PW"
    fi
    activate_ssh_target "$target"

    local cmd_str
    cmd_str="$(IFS=';'; echo "${cmds[*]}")"

    _run_ssh "$target" "$cmd_str" 2>&1 | _filter_ssh_noise
}

# ── 远程脚本公共前缀（PATH，不含提权）──────────────────────────
REMOTE_PATH_PREAMBLE='export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"'

# ── 远程提权辅助函数（按需嵌入，仅 run_privileged* 被调用时才实际 sudo）──
REMOTE_PRIVILEGE_HELPERS='
# 判断 ss/netstat 输出是否含 Process/PID 信息
_output_has_process_info() {
    echo "$1" | grep -qE "pid=|users:\\("
}

# 显式提权执行单条命令（调用方已确认需要更高权限）
run_privileged() {
    local cmd="$1"
    if [ "$(id -u)" -eq 0 ]; then
        eval "$cmd"
        return $?
    fi
    if command -v sudo >/dev/null 2>&1; then
        if sudo -n -i bash -c "$cmd" 2>/dev/null; then
            echo "[note:privilege] 已通过 sudo -i 提权采集"
            return 0
        fi
        if sudo -n bash -c "$cmd" 2>/dev/null; then
            echo "[note:privilege] 已通过 sudo 提权采集"
            return 0
        fi
    fi
    eval "$cmd"
    echo "[note:non-root] sudo 不可用或无权限，已用普通账号采集"
    return 0
}

# 显式提权执行脚本块（调用方已确认需要更高权限）
run_privileged_pipe() {
    local script
    script="$(cat)"
    if [ "$(id -u)" -eq 0 ]; then
        bash -s <<< "$script"
        return $?
    fi
    if command -v sudo >/dev/null 2>&1; then
        if sudo -n -i bash -s <<< "$script" 2>/dev/null; then
            echo "[note:privilege] 已通过 sudo -i 提权采集"
            return 0
        fi
        if sudo -n bash -s <<< "$script" 2>/dev/null; then
            echo "[note:privilege] 已通过 sudo 提权采集"
            return 0
        fi
    fi
    bash -s <<< "$script"
    echo "[note:non-root] sudo 不可用或无权限，已用普通账号采集"
    return 0
}'

REMOTE_PRIVILEGE_PREAMBLE="${REMOTE_PATH_PREAMBLE}"$'\n'"${REMOTE_PRIVILEGE_HELPERS}"

# ── 在远程执行脚本；with_helpers=true 时嵌入提权辅助函数（不自动 sudo）──
run_remote_script() {
    local target="$1"
    local script_body="$2"
    local with_helpers="${3:-false}"

    if [[ -z "$target" || -z "$script_body" ]]; then
        echo "[ERROR] run_remote_script: 缺少 target 或脚本内容" >&2
        return 1
    fi

    local full_script="$script_body"
    if [[ "$with_helpers" == "true" ]]; then
        full_script="${REMOTE_PATH_PREAMBLE}"$'\n'"${REMOTE_PRIVILEGE_HELPERS}"$'\n'"${script_body}"
    fi

    run_remote_heredoc "$target" "$full_script"
}

# ── 核心函数：在远程服务器执行多行脚本 ─────────────────────
run_remote_heredoc() {
    local target="$1"
    local heredoc_content="$2"

    if [[ -z "$target" ]]; then
        echo "[ERROR] run_remote_heredoc: 缺少目标服务器 user@ip" >&2
        return 1
    fi

    parse_ssh_target "$target"
    target="$_SSH_PARSED_TARGET"
    if [[ -n "${_SSH_TARGET_PW:-}" ]]; then
        if ! declare -p TARGET_PASSWORDS &>/dev/null 2>&1; then
            declare -gA TARGET_PASSWORDS
        fi
        TARGET_PASSWORDS["$target"]="$_SSH_TARGET_PW"
        setup_ssh_password_file "$_SSH_TARGET_PW"
    fi
    activate_ssh_target "$target"

    if [[ "$SSH_CONNECT_MODE" == "direct" ]] && [[ -n "${SSH_TARGET_PASSWORD:-}${SSH_ASKPASS_FILE:-}" ]] && _python_has_paramiko; then
        local py
        py="$(_find_python_for_ssh)"
        printf '%s' "$heredoc_content" | "$py" "$_SCRIPT_DIR/ssh_password.py" "$target" --script 2>&1 | _filter_ssh_noise
        return $?
    fi

    _run_ssh "$target" "bash -s" 2>&1 <<EOF | _filter_ssh_noise
$heredoc_content
EOF
}

# ── 确认连接到的服务器 IP ───────────────────────────────────
confirm_server() {
    local target="$1"
    run_remote "$target" "hostname -I 2>/dev/null || hostname"
}

# ── 连接测试 ─────────────────────────────────────────────────
test_ssh_connection() {
    local target="$1"
    _run_ssh "$target" "echo OK" >/dev/null 2>&1
}
