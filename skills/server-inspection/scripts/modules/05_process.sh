#!/bin/bash
# 进程分析
# 用法: bash 05_process.sh <user@ip>

set -uo pipefail

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
    'TOTAL=$(ps -e 2>/dev/null | tail -n +2 | wc -l); ZOMBIE=$(ps -eo stat 2>/dev/null | tail -n +2 | awk "\$1 ~ /Z/ {c++} END{print c+0}"); RUNNING=$(ps -eo stat 2>/dev/null | tail -n +2 | awk "\$1 ~ /^R/ {c++} END{print c+0}"); DSTATE=$(ps -eo stat 2>/dev/null | tail -n +2 | awk "\$1 ~ /D/ {c++} END{print c+0}"); SLEEP=$(ps -eo stat 2>/dev/null | tail -n +2 | awk "\$1 ~ /^S/ {c++} END{print c+0}"); echo "总数: $TOTAL | 运行中: $RUNNING | 睡眠: $SLEEP | D状态: $DSTATE | 僵尸: $ZOMBIE"' \
    'echo ""' \
    'echo "--- D 状态进程 ---"' \
    'DOUT=$(ps -eo pid,ppid,stat,cmd 2>/dev/null | awk "NR>1 && \$3 ~ /D/ {print}"); if [ -z "$DOUT" ]; then echo "无 D 状态进程"; else echo "$DOUT"; fi' \
    'echo ""' \
    'echo "--- 僵尸进程详情 ---"' \
    'ZOUT=$(ps -eo pid,ppid,user,stat,cmd 2>/dev/null | awk "NR>1 && \$4 ~ /Z/ {print}"); if [ -z "$ZOUT" ]; then echo "无僵尸进程"; else echo "$ZOUT"; fi'

if [[ -z "${JUMPSERVER_QUICK:-}" ]]; then
    run_remote "$TARGET" \
        'echo ""' \
        'echo "--- CPU Top 5 ---"' \
        'ps -eo pid=,user=,%cpu=,%mem=,args= --sort=-%cpu 2>/dev/null | head -5 | awk '"'"'BEGIN{print "  PID USER %CPU %MEM 服务/命令"} {cmd=$0; sub(/^[0-9]+ +[^ ]+ +[^ ]+ +[^ ]+ +/,"",cmd); if(length(cmd)>120) cmd=substr(cmd,1,117)"..."; printf "  %8s %-12s %6s %6s %s\n", $1,$2,$3,$4,cmd}'"'"'' \
        'echo ""' \
        'echo "--- 内存 Top 5 ---"' \
        'ps -eo pid=,user=,%cpu=,%mem=,rss=,args= --sort=-%mem 2>/dev/null | head -5 | awk '"'"'BEGIN{print "  PID USER %CPU %MEM RSS 服务/命令"} {cmd=$0; sub(/^[0-9]+ +[^ ]+ +[^ ]+ +[^ ]+ +[0-9]+ +/,"",cmd); if(length(cmd)>100) cmd=substr(cmd,1,97)"..."; printf "  %8s %-12s %6s %6s %8s %s\n", $1,$2,$3,$4,$5,cmd}'"'"''
else
    echo "[quick] 已跳过: CPU Top 5、内存 Top 5"
fi

echo ""
