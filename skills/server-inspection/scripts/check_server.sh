#!/bin/bash
# check_server.sh - JumpServer 堡垒机服务器监控 主入口
#
# 用法:
#   单台全量检查:  bash check_server.sh root@172.16.202.92
#   单台快速检查:  bash check_server.sh root@172.16.202.92 --quick
#   单台指定模块:  bash check_server.sh root@172.16.202.92 --module cpu
#   单台生成 HTML: bash check_server.sh root@172.16.202.92 --html [output.html]
#   列出所有模块:  bash check_server.sh --list-modules
#   批量巡检:      bash check_server.sh --all
#   批量生成 HTML: bash check_server.sh --all --html [dir/]
#   自定义配置目录: bash check_server.sh --config /path/to/config [其他参数]
#
# 模块列表（按执行顺序）:
#   02_cpu          CPU 与负载
#   03_memory       内存与 Swap
#   04_disk         磁盘、Inode、IO
#   05_process      进程分析
#   06_network      网络与端口

set -uo pipefail

# ── 路径初始化 ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULES_DIR="$SCRIPT_DIR/modules"
UTILS_DIR="$SCRIPT_DIR/utils"
CONFIG_DIR="${SCRIPT_DIR}/../config"
BASTION_CONF="$CONFIG_DIR/bastion.conf"
SERVERS_FILE="$CONFIG_DIR/servers.txt"

# ── 模块定义（顺序即执行顺序）────────────────────────────────
ALL_MODULES=(
    "02_cpu"
    "03_memory"
    "04_disk"
    "05_process"
    "06_network"
)

QUICK_MODULES=(
    "02_cpu"
    "03_memory"
    "04_disk"
)

# ── 颜色输出（无 TTY 时自动禁用）────────────────────────────
if [[ -t 1 ]]; then
    C_BOLD='\033[1m'
    C_GREEN='\033[0;32m'
    C_YELLOW='\033[0;33m'
    C_RED='\033[0;31m'
    C_RESET='\033[0m'
else
    C_BOLD=''
    C_GREEN=''
    C_YELLOW=''
    C_RED=''
    C_RESET=''
fi

log_info()    { echo -e "${C_GREEN}[INFO]${C_RESET} $*"; }
log_warn()    { echo -e "${C_YELLOW}[WARN]${C_RESET} $*"; }
log_error()   { echo -e "${C_RED}[ERROR]${C_RESET} $*" >&2; }
log_module()  { echo -e "${C_BOLD}▶ 执行模块: $*${C_RESET}"; }

# ── 查找 Python 命令 ──────────────────────────────────────────
find_python() {
    # Windows: 优先使用 managed Python，避免 Microsoft Store 占位符
    local managed_py="C:/Users/xuyuansheng/.workbuddy/binaries/python/versions/3.13.12/python.exe"
    if [[ -f "$managed_py" ]]; then
        echo "$managed_py"
    elif command -v python3 &>/dev/null; then
        echo "python3"
    elif python -c "print('ok')" &>/dev/null 2>&1; then
        echo "python"
    else
        echo ""
    fi
}

# ── 参数解析 ──────────────────────────────────────────────────
TARGET=""
BATCH_MODE=false
LIST_MODULES=false
SELECTED_MODULES=()
QUICK_MODE=false
HTML_MODE=false
HTML_OUTPUT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)
            BATCH_MODE=true
            shift
            ;;
        --list-modules)
            LIST_MODULES=true
            shift
            ;;
        --module)
            SELECTED_MODULES+=("$2")
            shift 2
            ;;
        --quick)
            QUICK_MODE=true
            shift
            ;;
        --html)
            HTML_MODE=true
            if [[ $# -gt 1 && "$2" != -* && "$2" != *@* ]]; then
                HTML_OUTPUT="$2"
                shift 2
            else
                HTML_OUTPUT=""
                shift
            fi
            ;;
        --config)
            CONFIG_DIR="$2"
            BASTION_CONF="$CONFIG_DIR/bastion.conf"
            SERVERS_FILE="$CONFIG_DIR/servers.txt"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -*)
            log_error "未知选项: $1"
            exit 1
            ;;
        *)
            if [[ -z "$TARGET" ]]; then
                TARGET="$1"
            fi
            shift
            ;;
    esac
done

# ── 帮助信息 ──────────────────────────────────────────────────
show_help() {
    echo "用法: $0 [user@ip] [选项]"
    echo ""
    echo "选项:"
    echo "  user@ip            检查单台服务器"
    echo "  --all               批量巡检（读取 config/servers.txt）"
    echo "  --quick             快速检查（仅系统/CPU/内存/磁盘/进程）"
    echo "  --module <name>    执行指定模块（可多次使用）"
    echo "  --html [file]      生成 HTML 报告（可选指定输出文件）"
    echo "  --list-modules     列出所有可用模块"
    echo "  --config <dir>     指定配置目录（默认: ../config）"
    echo "  -h, --help         显示帮助"
    echo ""
    echo "示例:"
    echo "  $0 root@172.16.202.92"
    echo "  $0 root@172.16.202.92 --quick"
    echo "  $0 root@172.16.202.92 --module cpu --module memory"
    echo "  $0 root@172.16.202.92 --html report.html"
    echo "  $0 --all"
    echo "  $0 --all --html reports/"
}

# ── 列出模块 ──────────────────────────────────────────────────
if [[ "$LIST_MODULES" == "true" ]]; then
    echo "可用模块（按执行顺序）:"
    echo ""
    for mod in "${ALL_MODULES[@]}"; do
        mod_file="$MODULES_DIR/${mod}.sh"
        if [[ -f "$mod_file" ]]; then
            desc="$(grep '^# [^0-9]' "$mod_file" | head -1 | sed 's/^# //')"
            if [[ -z "$desc" ]]; then
                desc="$(grep '^# ' "$mod_file" | head -1 | sed 's/^# //')"
            fi
            printf "  %-10s %s\n" "$mod" "$desc"
        else
            printf "  %-10s %s\n" "$mod" "(文件不存在)"
        fi
    done
    echo ""
    echo "快速模式 (--quick) 包含: ${QUICK_MODULES[*]}"
    exit 0
fi

# ── 加载堡垒机配置 ───────────────────────────────────────────
if [[ ! -f "$BASTION_CONF" ]]; then
    log_error "找不到堡垒机配置文件: $BASTION_CONF"
    log_info "请先编辑 config/bastion.conf，填入堡垒机连接参数"
    exit 1
fi

source "$BASTION_CONF"

if [[ -z "${BASTION_HOST:-}" || -z "${BASTION_PORT:-}" || -z "${BASTION_USER:-}" ]]; then
    log_error "bastion.conf 缺少必要参数，请检查 BASTION_HOST / BASTION_PORT / BASTION_USER"
    exit 1
fi

SSH_OPTS="${SSH_OPTS:-"-o StrictHostKeyChecking=no -o ConnectTimeout=10"}"
SSH_PROXY="ssh $SSH_OPTS -p $BASTION_PORT $BASTION_USER@$BASTION_HOST -W %h:%p"

# ── 连接测试函数 ──────────────────────────────────────────────
test_connection() {
    local target="$1"
    log_info "测试连接: $target ..."
    if ssh $SSH_OPTS \
        -o ProxyCommand="$SSH_PROXY" \
        "$target" "echo OK" >/dev/null 2>&1; then
        log_info "连接成功: $target"
        return 0
    else
        log_error "连接失败: $target（请检查 IP、用户、网络、堡垒机权限）"
        return 1
    fi
}

# ── 生成 HTML 报告 ────────────────────────────────────────────
generate_html() {
    local temp_dir="$1"
    local output_file="$2"

    local py
    py="$(find_python)"
    if [[ -z "$py" ]]; then
        log_error "未找到 Python，无法生成 HTML 报告"
        return 1
    fi

    local gen_script="$UTILS_DIR/gen_html.py"
    if [[ ! -f "$gen_script" ]]; then
        log_error "未找到 gen_html.py: $gen_script"
        return 1
    fi

    # 转换 bash 路径为 Windows 路径（/c/... → C:/... 或直接使用）
    # 如果路径以 /c/ 开头，转换为 C:/
    local win_script="$gen_script"
    local win_temp="$temp_dir"
    local win_out="$output_file"
    if [[ "$gen_script" == /c/* ]]; then
        win_script="C:${gen_script#/c}"
    elif [[ "$gen_script" == /d/* ]]; then
        win_script="D:${gen_script#/d}"
    elif [[ "$gen_script" == /e/* ]]; then
        win_script="E:${gen_script#/e}"
    fi
    if [[ "$temp_dir" == /c/* ]]; then
        win_temp="C:${temp_dir#/c}"
    elif [[ "$temp_dir" == /d/* ]]; then
        win_temp="D:${temp_dir#/d}"
    elif [[ "$temp_dir" == /e/* ]]; then
        win_temp="E:${temp_dir#/e}"
    fi
    if [[ "$output_file" == /c/* ]]; then
        win_out="C:${output_file#/c}"
    elif [[ "$output_file" == /d/* ]]; then
        win_out="D:${output_file#/d}"
    elif [[ "$output_file" == /e/* ]]; then
        win_out="E:${output_file#/e}"
    fi

    "$py" "$win_script" "$win_temp" "$win_out"
}

# ── 执行模块函数（核心）─────────────────────────────────────
# 当 HTML_MODE 时：将每个模块输出保存到 temp_dir/module_XX_name.txt
# 当非 HTML_MODE 时：直接输出到终端
run_modules() {
    local target="$1"
    local temp_dir="${2:-}"
    local modules=("${@:3}")

    local check_time
    check_time="$(date '+%Y-%m-%d %H:%M:%S')"

    echo ""
    echo "############################################"
    echo "#  服务器: $target"
    echo "############################################"

    # 先确认服务器 IP 和主机名
    local reported_ip reported_hostname
    reported_ip="$(ssh $SSH_OPTS \
        -o ProxyCommand="$SSH_PROXY" \
        "$target" "hostname -I 2>/dev/null || hostname" 2>/dev/null | head -1 | xargs)"
    reported_hostname="$(ssh $SSH_OPTS \
        -o ProxyCommand="$SSH_PROXY" \
        "$target" "hostname" 2>/dev/null | head -1 | xargs)"

    if [[ -n "$reported_ip" ]]; then
        echo "  主机名/IP: $reported_hostname / $reported_ip"
        echo ""
    fi

    # HTML 模式：写入元数据
    if [[ "$HTML_MODE" == "true" && -n "$temp_dir" ]]; then
        cat > "$temp_dir/metadata.json" << METADATA
{
    "server_ip": "$target",
    "hostname": "$reported_hostname",
    "check_time": "$check_time"
}
METADATA
    fi

    # 执行各模块
    for mod in "${modules[@]}"; do
        local mod_file="$MODULES_DIR/${mod}.sh"
        if [[ ! -f "$mod_file" ]]; then
            log_warn "模块文件不存在: $mod_file，跳过"
            continue
        fi

        log_module "$mod"

        if [[ "$HTML_MODE" == "true" && -n "$temp_dir" ]]; then
            # HTML 模式：捕获输出到文件
            local out_file="$temp_dir/module_${mod}.txt"
            bash "$mod_file" "$target" > "$out_file" 2>&1
        else
            # 普通模式：直接输出
            bash "$mod_file" "$target"
        fi
    done

    # HTML 模式：生成报告
    if [[ "$HTML_MODE" == "true" && -n "$temp_dir" && -n "$HTML_OUTPUT" ]]; then
        log_info "正在生成 HTML 报告: $HTML_OUTPUT"
        generate_html "$temp_dir" "$HTML_OUTPUT"
    fi
}

# ── 单台模式 ──────────────────────────────────────────────────
if [[ "$BATCH_MODE" == "false" ]]; then
    if [[ -z "$TARGET" ]]; then
        show_help
        exit 1
    fi

    # 确定要执行的模块列表
    if [[ ${#SELECTED_MODULES[@]} -gt 0 ]]; then
        MODULES_TO_RUN=("${SELECTED_MODULES[@]}")
    elif [[ "$QUICK_MODE" == "true" ]]; then
        MODULES_TO_RUN=("${QUICK_MODULES[@]}")
    else
        MODULES_TO_RUN=("${ALL_MODULES[@]}")
    fi

    test_connection "$TARGET" || exit 1

    # HTML 模式：准备临时目录和输出文件
    TEMP_DIR=""
    if [[ "$HTML_MODE" == "true" ]]; then
        # 临时目录放在脚本同目录（Windows 可访问），避免 /tmp 路径 Python 无法读取
        TEMP_BASE="$SCRIPT_DIR/.jumpserver-temp"
        mkdir -p "$TEMP_BASE" 2>/dev/null
        TEMP_DIR="$TEMP_BASE/run_$(date '+%s')"
        mkdir -p "$TEMP_DIR" 2>/dev/null
        if [[ ! -d "$TEMP_DIR" ]]; then
            # 降级：用 HOME 目录
            TEMP_BASE="$HOME/.jumpserver-monitor/tmp"
            mkdir -p "$TEMP_BASE" 2>/dev/null
            TEMP_DIR="$TEMP_BASE/run_$(date '+%s')"
            mkdir -p "$TEMP_DIR" 2>/dev/null
        fi
        if [[ ! -d "$TEMP_DIR" ]]; then
            log_error "无法创建临时目录，HTML 报告生成失败"
            exit 1
        fi
        if [[ -z "$HTML_OUTPUT" ]]; then
            HTML_OUTPUT="jumpserver_report_${TARGET//@/_}_$(date '+%Y%m%d_%H%M%S').html"
        elif [[ "$HTML_OUTPUT" == */ ]]; then
            mkdir -p "$HTML_OUTPUT" 2>/dev/null
            HTML_OUTPUT="${HTML_OUTPUT}jumpserver_report_${TARGET//@/_}_$(date '+%Y%m%d_%H%M%S').html"
        elif [[ -d "$HTML_OUTPUT" ]]; then
            HTML_OUTPUT="$HTML_OUTPUT/jumpserver_report_${TARGET//@/_}_$(date '+%Y%m%d_%H%M%S').html"
        fi
        html_dir="$(dirname "$HTML_OUTPUT")"
        if [[ -n "$html_dir" && "$html_dir" != "." ]]; then
            mkdir -p "$html_dir" 2>/dev/null
        fi
        log_info "HTML 模式: 临时目录=$TEMP_DIR, 输出=$HTML_OUTPUT"
    fi

    run_modules "$TARGET" "$TEMP_DIR" "${MODULES_TO_RUN[@]}"

    if [[ "$HTML_MODE" != "true" ]]; then
        echo ""
        echo "============================================"
        echo "  检查完成: $TARGET"
        echo "============================================"
    fi

    # 清理临时目录
    if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
    fi

    exit 0
fi

# ── 批量巡检模式 ───────────────────────────────────────────────
if [[ "$BATCH_MODE" == "true" ]]; then
    if [[ ! -f "$SERVERS_FILE" ]]; then
        log_error "找不到服务器列表: $SERVERS_FILE"
        log_info "请编辑 config/servers.txt，每行一个 user@ip"
        exit 1
    fi

    # 确定模块列表
    if [[ ${#SELECTED_MODULES[@]} -gt 0 ]]; then
        MODULES_TO_RUN=("${SELECTED_MODULES[@]}")
    elif [[ "$QUICK_MODE" == "true" ]]; then
        MODULES_TO_RUN=("${QUICK_MODULES[@]}")
    else
        MODULES_TO_RUN=("${ALL_MODULES[@]}")
    fi

    # HTML 批量模式：确定输出目录
    HTML_DIR=""
    if [[ "$HTML_MODE" == "true" ]]; then
        if [[ -z "$HTML_OUTPUT" ]]; then
            HTML_DIR="./reports"
        elif [[ "$HTML_OUTPUT" == */ || "$HTML_OUTPUT" == *\\ ]]; then
            HTML_DIR="$HTML_OUTPUT"
        else
            # 指定了文件名但这是批量模式，当作目录
            HTML_DIR="$HTML_OUTPUT"
        fi
        mkdir -p "$HTML_DIR" 2>/dev/null
        log_info "批量 HTML 模式: 输出目录=$HTML_DIR"
    fi

    echo "============================================"
    echo "  批量巡检模式"
    echo "  堡垒机: ${BASTION_USER}@${BASTION_HOST}:${BASTION_PORT}"
    echo "  服务器列表: $SERVERS_FILE"
    if [[ ${#MODULES_TO_RUN[@]} -lt ${#ALL_MODULES[@]} ]]; then
        echo "  执行模块: ${MODULES_TO_RUN[*]}"
    else
        echo "  执行模块: 全部"
    fi
    if [[ "$HTML_MODE" == "true" ]]; then
        echo "  HTML 输出: $HTML_DIR"
    fi
    echo "============================================"

    failed_servers=()
    success_count=0
    html_reports=()

    while IFS= read -r line || [[ -n "$line" ]]; do
        # 跳过空行和注释
        line="$(echo "$line" | sed 's/#.*//' | xargs)"
        [[ -z "$line" ]] && continue

        if [[ "$line" != *"@"* ]]; then
            log_warn "跳过格式错误的行: $line"
            continue
        fi

        if test_connection "$line"; then
            if [[ "$HTML_MODE" == "true" ]]; then
                # 临时目录放在脚本目录下（Windows 可访问）
                TEMP_BASE="$SCRIPT_DIR/.jumpserver-temp"
                mkdir -p "$TEMP_BASE" 2>/dev/null
                TEMP_DIR="$TEMP_BASE/run_$(date '+%s')_$"
                mkdir -p "$TEMP_DIR" 2>/dev/null
                if [[ ! -d "$TEMP_DIR" ]]; then
                    TEMP_BASE="$HOME/.jumpserver-monitor/tmp"
                    mkdir -p "$TEMP_BASE" 2>/dev/null
                    TEMP_DIR="$TEMP_BASE/run_$(date '+%s')_$"
                    mkdir -p "$TEMP_DIR" 2>/dev/null
                fi
                if [[ ! -d "$TEMP_DIR" ]]; then
                    log_error "无法创建临时目录，跳过 $line"
                    continue
                fi
                ip_part="${line##*@}"
                html_file="$HTML_DIR/report_${ip_part}_$(date '+%Y%m%d_%H%M%S').html"
                HTML_OUTPUT="$html_file"
                run_modules "$line" "${MODULES_TO_RUN[@]}" "$TEMP_DIR"
                html_reports+=("$html_file")
                rm -rf "$TEMP_DIR" 2>/dev/null
            else
                run_modules "$line" "${MODULES_TO_RUN[@]}"
            fi
            ((success_count++))
        else
            failed_servers+=("$line")
        fi

    done < "$SERVERS_FILE"

    echo ""
    echo "============================================"
    echo "  批量巡检完成"
    echo "  成功: $success_count 台"
    if [[ ${#failed_servers[@]} -gt 0 ]]; then
        echo "  失败: ${#failed_servers[@]} 台"
        for s in "${failed_servers[@]}"; do
            echo "    - $s"
        done
    fi
    if [[ "$HTML_MODE" == "true" && ${#html_reports[@]} -gt 0 ]]; then
        echo "  HTML 报告:"
        for r in "${html_reports[@]}"; do
            echo "    - $r"
        done
    fi
    echo "============================================"
fi
