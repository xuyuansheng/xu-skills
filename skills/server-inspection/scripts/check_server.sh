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
#   混合连接:       bash check_server.sh root@172.16.202.92 'root@ip:pass' --direct
#   默认连接模式见 config/bastion.conf 的 SSH_CONNECT_MODE
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

# --quick：仍跑 5 模块，但各模块跳过耗时子项（见 JUMPSERVER_QUICK=1）
QUICK_MODULES=(
    "02_cpu"
    "03_memory"
    "04_disk"
    "05_process"
    "06_network"
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

# ── 帮助信息 ──────────────────────────────────────────────────
show_help() {
    echo "用法: $0 [user@ip ...] [选项]"
    echo ""
    echo "选项:"
    echo "  user@ip            目标服务器；密码格式 user@ip:password（含特殊字符请加引号）"
    echo "                     在地址后加 --direct / --bastion 可指定该台连接方式"
    echo "  --all               批量巡检（读取 config/servers.txt，支持 @direct/@bastion 前缀）"
    echo "  --quick             快速检查（5 模块精简子项，终端模式；--html 时始终全量采集）"
    echo "  --module <name>    执行指定模块（可多次使用，如 02_cpu）"
    echo "  --html [dir/]      生成 HTML 报告（单台可指定文件；多台/批量输出到目录并生成 index.html）"
    echo "  --list-modules     列出所有可用模块"
    echo "  --config <dir>     指定配置目录（默认: ../config）"
    echo "  -h, --help         显示帮助"
    echo ""
    echo "示例:"
    echo "  $0 root@172.16.202.92"
    echo "  $0 root@172.16.202.92 'root@172.18.4.152:yourpass' --direct"
    echo "  $0 --all"
    echo "  $0 --all --html reports/"
}

# ── 参数解析 ──────────────────────────────────────────────────
TARGETS=()
TARGETS_RAW=()
TARGETS_RAW_MODE=()
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
        --direct)
            if [[ ${#TARGETS_RAW[@]} -eq 0 ]]; then
                log_error "--direct 须写在目标地址之后，例如: $0 'root@ip:pass' --direct"
                exit 1
            fi
            TARGETS_RAW_MODE[$((${#TARGETS_RAW[@]} - 1))]="direct"
            shift
            ;;
        --bastion)
            if [[ ${#TARGETS_RAW[@]} -eq 0 ]]; then
                log_error "--bastion 须写在目标地址之后，例如: $0 root@ip --bastion"
                exit 1
            fi
            TARGETS_RAW_MODE[$((${#TARGETS_RAW[@]} - 1))]="bastion"
            shift
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
            if [[ "$1" == *"@"* ]]; then
                TARGETS_RAW+=("$1")
                TARGETS_RAW_MODE+=("")
            else
                log_error "未知参数: $1（服务器地址需为 user@ip 格式）"
                exit 1
            fi
            shift
            ;;
    esac
done

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
    echo "快速模式 (--quick): 同上 5 模块，跳过 mpstat/vmstat/Top5 等耗时子项（--html 时不生效）"
    exit 0
fi

# ── 加载 SSH 连接配置（remote_exec.sh）────────────────────────
export JUMPSERVER_CONFIG_DIR="$(cd "$CONFIG_DIR" && pwd)"
# shellcheck source=utils/remote_exec.sh
source "$UTILS_DIR/remote_exec.sh"

declare -A TARGET_PASSWORDS
declare -A TARGET_CONNECT_MODES

# 从原始地址列表构建规范化 TARGETS，并登记密码/连接模式
register_targets_from_raw() {
    local -a raw_list=("$@")
    local -a mode_list=()
    local i raw norm pw mode

    if [[ ${#raw_list[@]} -eq ${#TARGETS_RAW_MODE[@]} && ${#TARGETS_RAW_MODE[@]} -gt 0 ]]; then
        mode_list=("${TARGETS_RAW_MODE[@]}")
    fi

    TARGETS=()
    for i in "${!raw_list[@]}"; do
        raw="$(strip_target_quotes "${raw_list[$i]}")"
        mode="${mode_list[$i]:-}"
        parse_ssh_target "$raw"
        norm="$_SSH_PARSED_TARGET"
        pw="${_SSH_TARGET_PW:-}"

        TARGETS+=("$norm")
        [[ -n "$pw" ]] && TARGET_PASSWORDS["$norm"]="$pw"
        [[ -n "$mode" ]] && TARGET_CONNECT_MODES["$norm"]="$mode"
    done
    return 0
}

# 解析 servers.txt 单行（支持 @direct / @bastion 前缀）
parse_servers_line() {
    local line="$1"
    local mode="" raw norm pw

    if [[ "$line" =~ ^@(direct|bastion)[[:space:]]+(.+)$ ]]; then
        mode="${BASH_REMATCH[1]}"
        line="${BASH_REMATCH[2]}"
    fi
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    raw="$(strip_target_quotes "$line")"
    [[ "$raw" != *"@"* ]] && return 1

    parse_ssh_target "$raw"
    norm="$_SSH_PARSED_TARGET"
    pw="${_SSH_TARGET_PW:-}"

    TARGETS+=("$norm")
    [[ -n "$pw" ]] && TARGET_PASSWORDS["$norm"]="$pw"
    [[ -n "$mode" ]] && TARGET_CONNECT_MODES["$norm"]="$mode"
    return 0
}

if [[ ${#TARGETS_RAW[@]} -gt 0 ]]; then
    register_targets_from_raw "${TARGETS_RAW[@]}"
fi

# ── 连接测试函数 ──────────────────────────────────────────────
test_connection() {
    local target="$1"
    export_ssh_session "$target"
    log_info "测试连接: $target [$(ssh_connect_mode_label)] ..."
    if test_ssh_connection "$target"; then
        log_info "连接成功: $target"
        return 0
    else
        log_error "连接失败: $target（$(ssh_connect_mode_label)，请检查 IP、用户、网络）"
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

# ── 创建临时目录 ──────────────────────────────────────────────
create_temp_dir() {
    local temp_base="$SCRIPT_DIR/.jumpserver-temp"
    mkdir -p "$temp_base" 2>/dev/null
    local temp_dir="$temp_base/run_$(date '+%s')_$$"
    mkdir -p "$temp_dir" 2>/dev/null
    if [[ ! -d "$temp_dir" ]]; then
        temp_base="$HOME/.jumpserver-monitor/tmp"
        mkdir -p "$temp_base" 2>/dev/null
        temp_dir="$temp_base/run_$(date '+%s')_$$"
        mkdir -p "$temp_dir" 2>/dev/null
    fi
    if [[ ! -d "$temp_dir" ]]; then
        return 1
    fi
    echo "$temp_dir"
}

# ── 解析批量 HTML 输出目录 ────────────────────────────────────
resolve_batch_html_dir() {
    local batch_ts="$1"
    local html_dir=""

    if [[ -z "$HTML_OUTPUT" ]]; then
        html_dir="./reports/run_${batch_ts}"
    elif [[ "$HTML_OUTPUT" == */ || "$HTML_OUTPUT" == *\\ ]]; then
        html_dir="${HTML_OUTPUT}run_${batch_ts}"
    elif [[ -d "$HTML_OUTPUT" ]]; then
        html_dir="$HTML_OUTPUT/run_${batch_ts}"
    else
        html_dir="$(dirname "$HTML_OUTPUT")/run_${batch_ts}"
        [[ "$(dirname "$HTML_OUTPUT")" == "." ]] && html_dir="./reports/run_${batch_ts}"
    fi

    mkdir -p "$html_dir" 2>/dev/null
    echo "$html_dir"
}

# ── 生成批量巡检目录页 index.html ─────────────────────────────
generate_index_html() {
    local manifest_file="$1"
    local index_file="$2"

    local py
    py="$(find_python)"
    if [[ -z "$py" ]]; then
        log_error "未找到 Python，无法生成目录页"
        return 1
    fi

    local gen_script="$UTILS_DIR/gen_index.py"
    if [[ ! -f "$gen_script" ]]; then
        log_error "未找到 gen_index.py: $gen_script"
        return 1
    fi

    local win_script="$gen_script"
    local win_manifest="$manifest_file"
    local win_index="$index_file"
    if [[ "$gen_script" == /e/* ]]; then win_script="E:${gen_script#/e}"; fi
    if [[ "$manifest_file" == /e/* ]]; then win_manifest="E:${manifest_file#/e}"; fi
    if [[ "$index_file" == /e/* ]]; then win_index="E:${index_file#/e}"; fi

    "$py" "$win_script" "$win_manifest" "$win_index"
}

# ── 批量/多台 HTML 巡检 ───────────────────────────────────────
run_multi_html_inspection() {
    local -n _targets=$1
    local modules=("${@:2}")

    local batch_ts check_time
    batch_ts="$(date '+%Y%m%d_%H%M%S')"
    check_time="$(date '+%Y-%m-%d %H:%M:%S')"

    local html_dir
    html_dir="$(resolve_batch_html_dir "$batch_ts")"
    log_info "批量 HTML 模式: 输出目录=$html_dir"

    echo "============================================"
    echo "  多台服务器 HTML 巡检"
    echo "  连接方式: 按目标（默认 ${SSH_DEFAULT_CONNECT_MODE}）"
    echo "  服务器数量: ${#_targets[@]}"
    echo "  输出目录: $html_dir"
    echo "============================================"

    local manifest_file="$html_dir/manifest.json"
    local reports_json="["
    local failed_json="["
    local success_count=0
    local html_reports=()
    local first_report=true
    local first_failed=true

    for line in "${_targets[@]}"; do
        if [[ "$line" != *"@"* ]]; then
            log_warn "跳过格式错误的地址: $line"
            continue
        fi

        if ! test_connection "$line"; then
            if [[ "$first_failed" == "true" ]]; then first_failed=false; else failed_json+=","; fi
            failed_json+="{\"target\":\"$line\",\"reason\":\"连接失败\"}"
            continue
        fi

        local temp_dir ip_part html_file reported_hostname
        temp_dir="$(create_temp_dir)" || {
            log_error "无法创建临时目录，跳过 $line"
            if [[ "$first_failed" == "true" ]]; then first_failed=false; else failed_json+=","; fi
            failed_json+="{\"target\":\"$line\",\"reason\":\"临时目录创建失败\"}"
            continue
        }

        ip_part="$(target_host_ip "$line")"
        html_file="$html_dir/report_${ip_part}.html"
        HTML_OUTPUT="$html_file"

        run_modules "$line" "$temp_dir" "${modules[@]}"

        reported_hostname=""
        if [[ -f "$temp_dir/metadata.json" ]]; then
            reported_hostname="$(grep -o '"hostname"[[:space:]]*:[[:space:]]*"[^"]*"' "$temp_dir/metadata.json" | head -1 | sed 's/.*"\([^"]*\)"$/\1/')"
        fi
        rm -rf "$temp_dir" 2>/dev/null

        html_reports+=("$html_file")
        ((success_count++))

        if [[ "$first_report" == "true" ]]; then first_report=false; else reports_json+=","; fi
        reports_json+=$(cat <<EOF
{"target":"$line","ip":"$ip_part","hostname":"$reported_hostname","file":"report_${ip_part}.html","status":"ok"}
EOF
)
    done

    reports_json+="]"
    failed_json+="]"

    cat > "$manifest_file" << MANIFEST
{
    "check_time": "$check_time",
    "output_dir": "$html_dir",
    "reports": $reports_json,
    "failed": $failed_json
}
MANIFEST

    local index_file="$html_dir/index.html"
    if [[ $success_count -gt 0 ]]; then
        generate_index_html "$manifest_file" "$index_file"
    elif [[ "$failed_json" != "[]" ]]; then
        generate_index_html "$manifest_file" "$index_file"
    fi

    echo ""
    echo "============================================"
    echo "  批量 HTML 巡检完成"
    echo "  成功: $success_count 台"
    echo "  输出目录: $html_dir"
    if [[ -f "$index_file" ]]; then
        echo "  目录页: $index_file"
    fi
    if [[ "$failed_json" != "[]" ]]; then
        echo "  部分服务器连接失败，详见 index.html"
    fi
    if [[ ${#html_reports[@]} -gt 0 ]]; then
        echo "  各 IP 报告:"
        for r in "${html_reports[@]}"; do
            echo "    - $r"
        done
    fi
    echo "============================================"
}

# ── 确定模块列表 ──────────────────────────────────────────────
# HTML 报告始终包含全部 5 模块（除非 --module 指定子集）
resolve_modules() {
    if [[ ${#SELECTED_MODULES[@]} -gt 0 ]]; then
        echo "${SELECTED_MODULES[@]}"
    elif [[ "$HTML_MODE" == "true" ]]; then
        echo "${ALL_MODULES[@]}"
    elif [[ "$QUICK_MODE" == "true" ]]; then
        echo "${QUICK_MODULES[@]}"
    else
        echo "${ALL_MODULES[@]}"
    fi
}

# ── 执行模块函数（核心）─────────────────────────────────────
# 当 HTML_MODE 时：将每个模块输出保存到 temp_dir/module_XX_name.txt
# 当非 HTML_MODE 时：直接输出到终端
run_modules() {
    local target="$1"
    local temp_dir="${2:-}"
    local modules=("${@:3}")

    # 终端快速模式：精简远程采集；HTML 报告始终全量
    if [[ "$QUICK_MODE" == "true" && "$HTML_MODE" != "true" ]]; then
        export JUMPSERVER_QUICK=1
    else
        unset JUMPSERVER_QUICK
    fi

    export_ssh_session "$target"

    local check_time
    check_time="$(date '+%Y-%m-%d %H:%M:%S')"

    echo ""
    echo "############################################"
    echo "#  服务器: $target"
    echo "############################################"

    # 先确认服务器 IP 和主机名
    local reported_ip reported_hostname
    reported_ip="$(run_remote "$target" "hostname -I 2>/dev/null || hostname" | head -1 | xargs)"
    reported_hostname="$(run_remote "$target" "hostname" | head -1 | xargs)"

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
            local out_file="$temp_dir/module_${mod}.txt"
            export_ssh_session "$target"
            bash "$mod_file" "$target" > "$out_file" 2>&1
        else
            export_ssh_session "$target"
            bash "$mod_file" "$target"
        fi
    done

    # HTML 模式：生成报告
    if [[ "$HTML_MODE" == "true" && -n "$temp_dir" && -n "$HTML_OUTPUT" ]]; then
        log_info "正在生成 HTML 报告: $HTML_OUTPUT"
        generate_html "$temp_dir" "$HTML_OUTPUT"
    fi
}

# ── 单台 / 多台模式 ───────────────────────────────────────────
if [[ "$BATCH_MODE" == "false" ]]; then
    if [[ ${#TARGETS[@]} -eq 0 ]]; then
        show_help
        exit 1
    fi

    read -ra MODULES_TO_RUN <<< "$(resolve_modules)"

    # 多台 + HTML → 每台独立报告 + index.html
    if [[ ${#TARGETS[@]} -gt 1 && "$HTML_MODE" == "true" ]]; then
        run_multi_html_inspection TARGETS "${MODULES_TO_RUN[@]}"
        exit 0
    fi

    # 多台无 HTML → 逐台终端输出
    if [[ ${#TARGETS[@]} -gt 1 ]]; then
        failed_servers=()
        success_count=0
        for TARGET in "${TARGETS[@]}"; do
            if test_connection "$TARGET"; then
                run_modules "$TARGET" "" "${MODULES_TO_RUN[@]}"
                ((success_count++))
            else
                failed_servers+=("$TARGET")
            fi
        done
        echo ""
        echo "============================================"
        echo "  多台巡检完成: 成功 $success_count / ${#TARGETS[@]}"
        if [[ ${#failed_servers[@]} -gt 0 ]]; then
            echo "  失败:"
            for s in "${failed_servers[@]}"; do echo "    - $s"; done
        fi
        echo "============================================"
        exit 0
    fi

    TARGET="${TARGETS[0]}"
    test_connection "$TARGET" || exit 1

    TEMP_DIR=""
    if [[ "$HTML_MODE" == "true" ]]; then
        TEMP_DIR="$(create_temp_dir)" || {
            log_error "无法创建临时目录，HTML 报告生成失败"
            exit 1
        }
        if [[ -z "$HTML_OUTPUT" ]]; then
            HTML_OUTPUT="jumpserver_report_${TARGET//@/_}_$(date '+%Y%m%d_%H%M%S').html"
            HTML_OUTPUT="${HTML_OUTPUT//:/_}"
        elif [[ "$HTML_OUTPUT" == */ ]]; then
            mkdir -p "$HTML_OUTPUT" 2>/dev/null
            HTML_OUTPUT="${HTML_OUTPUT}jumpserver_report_$(target_host_ip "$TARGET")_$(date '+%Y%m%d_%H%M%S').html"
        elif [[ -d "$HTML_OUTPUT" ]]; then
            HTML_OUTPUT="$HTML_OUTPUT/jumpserver_report_$(target_host_ip "$TARGET")_$(date '+%Y%m%d_%H%M%S').html"
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

    if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
        rm -rf "$TEMP_DIR"
    fi

    exit 0
fi

# ── 批量巡检模式（--all，读取 servers.txt）────────────────────
if [[ "$BATCH_MODE" == "true" ]]; then
    if [[ ! -f "$SERVERS_FILE" ]]; then
        log_error "找不到服务器列表: $SERVERS_FILE"
        if [[ -f "$CONFIG_DIR/servers.txt.example" ]]; then
            log_info "首次使用请执行: cp config/servers.txt.example config/servers.txt"
        fi
        log_info "编辑 servers.txt，每行一个 user@ip（勿将含密码的文件提交到 Git）"
        exit 1
    fi

    read -ra MODULES_TO_RUN <<< "$(resolve_modules)"

    BATCH_TARGETS=()
    TARGETS=()
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line%%#*}"
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        [[ -z "$line" ]] && continue
        parse_servers_line "$line" || log_warn "跳过无效行: $line"
    done < "$SERVERS_FILE"

    BATCH_TARGETS=("${TARGETS[@]}")

    if [[ ${#BATCH_TARGETS[@]} -eq 0 ]]; then
        log_error "servers.txt 中无有效服务器地址"
        exit 1
    fi

    if [[ "$HTML_MODE" == "true" ]]; then
        run_multi_html_inspection BATCH_TARGETS "${MODULES_TO_RUN[@]}"
        exit 0
    fi

    echo "============================================"
    echo "  批量巡检模式"
    echo "  连接方式: 按目标（默认 ${SSH_DEFAULT_CONNECT_MODE}）"
    echo "  服务器列表: $SERVERS_FILE"
    echo "============================================"

    failed_servers=()
    success_count=0
    for line in "${BATCH_TARGETS[@]}"; do
        if test_connection "$line"; then
            run_modules "$line" "" "${MODULES_TO_RUN[@]}"
            ((success_count++))
        else
            failed_servers+=("$line")
        fi
    done

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
    echo "============================================"
fi
