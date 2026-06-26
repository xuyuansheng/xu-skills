#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_html.py - 服务器检查结果 → 可读 HTML 报告（指标卡片 + 详细解释）
用法: python3 gen_html.py <input_dir> <output_html>
"""

import json, os, sys, re
from datetime import datetime

# ═══════════════════════════════════════════════════════════════
#  配色
# ═══════════════════════════════════════════════════════════════
C = {
    "bg":       "#0d1117",
    "card":     "#161b22",
    "border":   "#30363d",
    "text":     "#c9d1d9",
    "dim":      "#8b949e",
    "accent":   "#58a6ff",
    "green":    "#3fb950",
    "yellow":   "#d29922",
    "red":      "#f85149",
    "pre_bg":   "#0d1117",
    "th_bg":    "#21262d",
    "row_alt":  "#1c2128",
    "row":      "#161b22",
}

# ═══════════════════════════════════════════════════════════════
#  指标知识库 — 每个指标配有通俗解释
# ═══════════════════════════════════════════════════════════════
METRIC_KB = {
    "02_cpu": {
        "系统负载": (
            "Load Average 是内核统计的<strong>系统负载平均值</strong>，包含正在用 CPU、等 CPU、等 IO 的进程。"
            "详细统计说明与排查步骤见上方卡片内指引。"
        ),
        "CPU 使用率分布": (
            "来自 <code>top -bn1</code> 的<strong>瞬时快照</strong>，展示 8 项 CPU 时间占比（合计 100%）。"
            "详细指标说明、阈值与排查步骤见上方卡片内指引；需结合 Load、运行队列、mpstat 交叉判断。"
        ),
        "每核 CPU (mpstat)": (
            "来自 <code>mpstat -P ALL 1 1</code> 的<strong>每核快照</strong>，用于发现单核热点与 IRQ 绑定不均。"
            "详细字段说明、阈值与排查步骤见上方卡片内指引。"
        ),
        "运行队列": (
            "来自 <code>vmstat 1 2</code> 的<strong>瞬时快照</strong>（非平均值），反映此刻 CPU 调度与 IO 阻塞状态。"
            "详细指标说明、阈值与排查步骤见上方卡片内指引；需结合 Load、wa/iowait 交叉判断。"
        ),
        "CPU Top 5": (
            "来自 <code>ps --sort=-%cpu</code> 的<strong>瞬时排行</strong>，列出当前 CPU 占用最高的 5 个进程。"
            "详细字段说明、多核解读与排查步骤见上方卡片内指引。"
        ),
    },
    "03_memory": {
        "内存总览": (
            "来自 <code>free -h</code> 的<strong>瞬时快照</strong>，展示物理内存与 Swap 用量。"
            "详细字段说明、available 解读与排查步骤见上方卡片内指引。"
        ),
        "Swap 状态": (
            "来自 <code>swapon --show</code>，展示 Swap 分区/文件及已用量。"
            "详细换出机制、si/so 观察与排查步骤见上方卡片内指引。"
        ),
        "高内存进程 Top 5": (
            "来自 <code>ps --sort=-%mem</code> 的<strong>瞬时排行</strong>，按 RSS 物理内存降序。"
            "详细字段说明、泄漏判断与排查步骤见上方卡片内指引。"
        ),
    },
    "04_disk": {
        "磁盘使用率": (
            "来自 <code>df -hP</code> 的<strong>只读快照</strong>，展示各挂载点空间使用，无磁盘遍历。"
            "详细字段说明、阈值与排查步骤见上方卡片内指引。"
        ),
        "Inode 使用率": (
            "来自 <code>df -iP</code> 的<strong>只读快照</strong>，展示各文件系统 inode 占用。"
            "详细说明与小文件过多场景排查见上方卡片内指引。"
        ),
        "高使用率挂载点": (
            "由 <code>df</code> 筛选使用率 ≥50% 的挂载点，<strong>不执行 du 扫描</strong>，对服务器无额外 IO 负担。"
            "目录级定位请在磁盘紧张时手动执行 du，详见卡片内指引。"
        ),
    },
    "05_process": {
        "进程统计": (
            "来自 <code>ps</code> 的<strong>瞬时快照</strong>，统计进程总数、运行中(R)与僵尸(Z)数量。"
            "详细状态说明与排查步骤见上方卡片内指引。"
        ),
        "僵尸进程详情": (
            "列出当前所有 <strong>Z 状态（僵尸）</strong>进程；无则显示正常。"
            "详细含义与父进程排查见上方卡片内指引。"
        ),
        "CPU Top 5": (
            "来自 <code>ps --sort=-%cpu</code> 的<strong>瞬时排行</strong>（进程模块视角）。"
            "详细字段说明与排查步骤见上方卡片内指引。"
        ),
        "内存 Top 5": (
            "来自 <code>ps --sort=-%mem</code> 的<strong>瞬时排行</strong>（进程模块视角）。"
            "详细 RSS 解读与排查步骤见上方卡片内指引。"
        ),
    },
    "06_network": {
        "网络接口 IP": (
            "来自 <code>ip -4 addr</code> 的<strong>只读快照</strong>，展示 IPv4 接口与地址。"
            "详细字段说明见上方卡片内指引。"
        ),
        "监听端口": (
            "来自 <code>ss -tlnp</code> 的<strong>瞬时快照</strong>，列出 TCP 监听端口与进程。"
            "详细字段说明与端口排查见上方卡片内指引。"
        ),
        "连接统计": (
            "来自 <code>ss</code> 的<strong>瞬时统计</strong>：已建立连接、监听端口数、总连接数。"
            "详细含义与异常排查见上方卡片内指引。"
        ),
    },
}

MODULE_NAMES = {
    "02_cpu":     ("⚡", "CPU 与负载"),
    "03_memory":  ("🧠", "内存与 Swap"),
    "04_disk":    ("💾", "磁盘与 Inode"),
    "05_process": ("📊", "进程分析"),
    "06_network": ("🌐", "网络与端口"),
}

# CPU 模块卡片展示顺序
CPU_BLOCK_ORDER = [
    "系统负载",
    "运行队列",
    "CPU 使用率分布",
    "每核 CPU (mpstat)",
    "CPU Top 5",
]

MEMORY_BLOCK_ORDER = [
    "内存总览",
    "Swap 状态",
    "高内存进程 Top 5",
]

DISK_BLOCK_ORDER = [
    "磁盘使用率",
    "Inode 使用率",
    "高使用率挂载点",
    "根分区大目录 Top 5",
]

PROCESS_BLOCK_ORDER = [
    "进程统计",
    "僵尸进程详情",
    "CPU Top 5",
    "内存 Top 5",
]

NETWORK_BLOCK_ORDER = [
    "网络接口 IP",
    "监听端口",
    "连接统计",
]

# mpstat 表头：中文名 + 英文字段
MPSTAT_COLUMNS = [
    ("CPU", ""),
    ("使用率", ""),
    ("用户态", "usr"),
    ("内核态", "sys"),
    ("IO等待", "iowait"),
    ("Steal", "steal"),
    ("空闲", "idle"),
    ("状态", ""),
]

# ═══════════════════════════════════════════════════════════════
#  CPU 指标元数据：key / 含义 / 阈值 / 排查方向
# ═══════════════════════════════════════════════════════════════
CPU_METRICS = [
    {"key": "us", "name": "用户态",    "desc": "应用程序代码执行（Nginx/Java/Python/MySQL等）",
     "good": "<50%",  "warn": ">70%",  "danger": ">90%",
     "fix": "top/pidstat 定位进程，可能死循环或计算密集"},
    {"key": "sy", "name": "内核态",    "desc": "系统调用/内核代码（文件IO、网络收发、进程调度）",
     "good": "<10%",  "warn": ">30%",  "danger": ">50%",
     "fix": "strace -c 查系统调用频率，排查驱动bug"},
    {"key": "ni", "name": "低优先级",  "desc": "被 nice 降权的用户态进程（nice值>0）",
     "good": "≈0%",   "warn": ">50%",  "danger": "—",
     "fix": "检查是否批量 nice 降权后台任务"},
    {"key": "id", "name": "空闲",      "desc": "CPU 什么都没干的时间，越高越空闲",
     "good": ">50%",  "warn": "<20%",  "danger": "<10%",
     "fix": "CPU 严重过载，需扩容或限流", "inverted": True},
    {"key": "wa", "name": "IO等待",    "desc": "CPU 在等磁盘读写完成（硬盘太慢CPU干等着）",
     "good": "<5%",   "warn": ">10%",  "danger": ">30%",
     "fix": "磁盘是瓶颈：iostat 查利用率，iotop 定位进程"},
    {"key": "hi", "name": "硬中断",    "desc": "硬件中断处理（网卡收包/磁盘控制器完成通知）",
     "good": "<5%",   "warn": ">5%",   "danger": ">10%",
     "fix": "查 /proc/interrupts，网卡/磁盘控制器异常"},
    {"key": "si", "name": "软中断",    "desc": "软IRQ（网络包处理/TCP协议栈/定时器回调）",
     "good": "<5%",   "warn": ">5%",   "danger": ">10%",
     "fix": "网络包风暴/DDoS，ksoftirqd 高CPU，检查 RPS/RFS"},
    {"key": "st", "name": "Steal",     "desc": "VM被宿主机偷走的vCPU时间（宿主机CPU超卖）",
     "good": "=0%",   "warn": ">5%",   "danger": ">10%",
     "fix": "宿主机资源不足，降低超卖比或迁移VM"},
]

def parse_cpu_usage(content: str) -> dict[str, float] | None:
    """解析 '%Cpu(s): 0.4 us, 0.7 sy, ...' → {'us': 0.4, 'sy': 0.7, ...}"""
    m = re.search(r"%Cpu\(?s?\)?\s*:\s*([\d.,\s]+(?:us|sy|ni|id|wa|hi|si|st)[\d.,\s]+(?:(?:us|sy|ni|id|wa|hi|si|st)[\d.,\s]+)*)", content)
    if not m:
        return None
    line = m.group(1)
    result = {}
    for pair in re.finditer(r"([\d.]+)\s*(us|sy|ni|id|wa|hi|si|st)", line):
        result[pair.group(2)] = float(pair.group(1))
    return result if result else None

def cpu_status_light(key: str, val: float) -> str:
    """根据阈值返回状态色: green / yellow / red"""
    for m in CPU_METRICS:
        if m["key"] != key:
            continue
        if key == "id":
            return "green" if val > 50 else ("yellow" if val >= 20 else "red")
        if key == "ni":
            return "yellow" if val > 50 else "green"
        if key in ("wa", "hi", "si", "st"):
            return "red" if val > 10 else ("yellow" if val > 5 else "green")
        if key == "sy":
            return "red" if val > 50 else ("yellow" if val > 30 else "green")
        if key == "us":
            return "red" if val > 90 else ("yellow" if val > 70 else "green")
    return "green"

def parse_load_block(content: str) -> dict | None:
    """解析 uptime + CPU核数 → load1/5/15, cores, ratio"""
    m = re.search(r"load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)", content)
    if not m:
        return None
    cores_m = re.search(r"CPU核数:\s*(\d+)", content)
    cores = int(cores_m.group(1)) if cores_m else 0
    load1, load5, load15 = (float(m.group(i)) for i in range(1, 4))
    ratio = load1 / cores if cores > 0 else load1
    if ratio > 1.0:
        status, label = "red", "异常"
    elif ratio > 0.7:
        status, label = "yellow", "关注"
    else:
        status, label = "green", "正常"
    return {
        "load1": load1, "load5": load5, "load15": load15,
        "cores": cores, "ratio": ratio, "status": status, "label": label,
    }


def load_trend_hint(data: dict) -> str:
    """根据 Load 1/5/15 判断趋势"""
    l1, l5, l15 = data["load1"], data["load5"], data["load15"]
    if l1 > l5 * 1.15 and l5 >= l15 * 1.05:
        return "📈 负载<strong>上升</strong>（1min &gt; 5min ≥ 15min）— 关注是否持续走高"
    if l1 < l5 * 0.85 and l5 <= l15 * 0.95:
        return "📉 负载<strong>回落</strong>（1min &lt; 5min ≤ 15min）— 可能刚经历峰值，正在恢复"
    if max(l1, l5, l15) - min(l1, l5, l15) < 0.3:
        return "➡️ 负载<strong>平稳</strong> — 三个时段接近，非偶发尖峰"
    return "➡️ 对比三个时段：<strong>都高</strong>=持续排队；<strong>仅 1min 高</strong>=短时尖峰"


def render_load_stat_guide() -> str:
    """Load 统计说明（位于 Load/核数 下方，默认折叠）"""
    return f'''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 Load 统计说明</summary>
        <div class="load-guide-body">
            <p><b>Load Average</b> 来自 <code>uptime</code>，是过去一段时间里「活跃任务」的平均数量，<b>不是 CPU 使用率</b>。</p>
            <p><b>Load = 正在用 CPU 的进程 + 在等 CPU 的进程 + 在等 IO 的进程（D 状态）</b><br>
            内核无法把 IO 部分单独拆出，因此需结合 wa/iowait、b 等指标交叉判断。</p>
            <table class="load-ref-tbl">
                <tr><th>指标</th><th>含义</th></tr>
                <tr><td>Load 1min</td><td>过去 <b>1 分钟</b> 的平均负载</td></tr>
                <tr><td>Load 5min</td><td>过去 <b>5 分钟</b> 的平均负载</td></tr>
                <tr><td>Load 15min</td><td>过去 <b>15 分钟</b> 的平均负载</td></tr>
                <tr><td>Load/核数</td><td>Load 1min ÷ CPU 核数，<b>核心判断指标</b></td></tr>
            </table>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 &lt;0.7</span> 正常，基本无排队 &nbsp;
                <span class="kb-tag tag-warn">🟡 0.7~1.0</span> 关注，接近饱和 &nbsp;
                <span class="kb-tag tag-bad">🔴 &gt;1.0</span> 持续排队，算力或 IO 偏紧
            </p>
        </div>
    </details>'''


def render_load_high_guide(data: dict) -> str:
    """Load 偏高时的排查指引"""
    if data["status"] == "green":
        return ""
    ratio, cores = data["ratio"], data["cores"]
    example = ""
    if cores:
        example = (
            f"<p class=\"load-example\">例：{cores} 核机器 Load={data['load1']:.1f}，"
            f"Load/核={ratio:.2f}，"
            + ("平均有任务持续排队。" if ratio > 1 else "接近饱和，需观察趋势。")
            + "</p>"
        )
    level = "warn" if data["status"] == "yellow" else "bad"
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 Load 偏高 · 怎么分析问题</div>
        <div class="load-guide-body">
            {example}
            <ol class="load-guide-list">
                <li><b>确认是否「持续」偏高</b><br>
                    看 Load 1/5/15 是否<strong>都高且接近</strong> → 持续排队；仅 1min 高 → 短时尖峰，可先观察。</li>
                <li><b>区分 CPU 排队 vs IO 瓶颈</b>（Load 本身无法拆分，对照本页其他卡片）：
                    <ul>
                        <li><b>CPU 算力不足</b>：运行队列 <code>r</code> 高、<code>wa≈0</code>、CPU idle 低
                            → 看「CPU Top 5」「每核 CPU」定位进程</li>
                        <li><b>磁盘 IO 瓶颈</b>：<code>wa/iowait &gt;10%</code>、运行队列 <code>b&gt;0</code>、CPU idle 仍高
                            → Load 高由等 IO 导致，查磁盘模块 / <code>iostat</code></li>
                        <li><b>单核热点</b>：整体 Load 不高但某一核 90%+
                            → 单线程瓶颈，Load 会被其他空闲核拉低</li>
                    </ul>
                </li>
                <li><b>常用排查命令</b>：
                    <code>top</code> · <code>vmstat 1 5</code> · <code>mpstat -P ALL 1 3</code>
                    · <code>pidstat -u 1 5</code> · <code>iostat -x 1 3</code></li>
                <li><b>处理方向</b>：
                    CPU 紧 → 优化热点进程 / 扩容 / 限流；
                    IO 紧 → 优化磁盘读写 / 换 SSD / 查慢查询；
                    单核 → 多 worker / 线程池 / 检查绑核。</li>
            </ol>
        </div>
    </div>'''


def render_load_block(content: str) -> tuple[str, str]:
    """渲染系统负载卡片，返回 (body_html, summary_line)"""
    data = parse_load_block(content)
    if not data:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            content.strip().split("\n")[0][:80],
        )
    dot = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[data["status"]]
    cores_txt = f'{data["cores"]} 核' if data["cores"] else "核数未知"
    ratio_txt = f'{data["ratio"]:.2f}' if data["cores"] else "—"
    trend = load_trend_hint(data)
    body = f'''
    <div class="card-body">
        <div class="mem-usage-bar">
            <div class="mem-usage-item">
                <div class="mem-usage-header">
                    <span>{dot} Load/核数 ({ratio_txt})</span>
                    <span style="font-weight:600">{data["label"]}</span>
                </div>
            </div>
        </div>
        <div class="kv-card">
            <div class="kv-row"><span class="kv-key">Load 1min</span><span class="kv-val">{data["load1"]:.2f}</span></div>
            <div class="kv-row"><span class="kv-key">Load 5min</span><span class="kv-val">{data["load5"]:.2f}</span></div>
            <div class="kv-row"><span class="kv-key">Load 15min</span><span class="kv-val">{data["load15"]:.2f}</span></div>
            <div class="kv-row kv-avail"><span class="kv-key">CPU 核数</span><span class="kv-val">{cores_txt}</span></div>
            <div class="kv-row"><span class="kv-key">Load/核数</span><span class="kv-val">{ratio_txt}</span></div>
        </div>
        {render_load_stat_guide()}
        <div class="load-trend-hint">{trend}</div>
        {render_load_high_guide(data)}
    </div>'''
    summary = f'Load {data["load1"]:.2f}/{data["load5"]:.2f}/{data["load15"]:.2f} | {cores_txt} | Load/核={ratio_txt}'
    return body, summary


def mpstat_th_html(name: str, key: str = "") -> str:
    """mpstat 表头单元格：中文名 + 英文字段"""
    if key:
        return (
            f'<th class="cpu-th-name"><b>{escape_html(name)}</b>'
            f'<span class="cpu-col-key">{escape_html(key)}</span></th>'
        )
    return f"<th>{escape_html(name)}</th>"


def collect_cpu_anomalies(blocks: list[dict]) -> list[tuple[str, str]]:
    """收集 CPU 模块异常/关注项"""
    anomalies: list[tuple[str, str]] = []
    cores = 0

    for b in blocks:
        if b.get("_skip") or b["title"] != "系统负载":
            continue
        load = parse_load_block(b["content"])
        if load:
            cores = load.get("cores", 0)
            if load["status"] == "red":
                anomalies.append((
                    "red",
                    f'Load/核数 {load["ratio"]:.2f} > 1.0，CPU 持续排队',
                ))
            elif load["status"] == "yellow":
                anomalies.append((
                    "yellow",
                    f'Load/核数 {load["ratio"]:.2f} > 0.7，需关注负载趋势',
                ))
        break

    for b in blocks:
        if b.get("_skip"):
            continue
        title = b["title"]
        content = b["content"]

        if title == "运行队列":
            vm = parse_vmstat(content)
            if vm:
                if cores > 0 and vm["r"] > cores:
                    anomalies.append(("red", f'运行队列 r={vm["r"]} 超过 CPU 核数 {cores}'))
                elif cores > 0 and vm["r"] > cores * 0.7:
                    anomalies.append(("yellow", f'运行队列 r={vm["r"]} 接近饱和（核数 {cores}）'))
                if vm["wa"] > 10:
                    anomalies.append(("yellow", f'vmstat IO 等待 {vm["wa"]:.0f}% 偏高'))
                if vm["st"] > 5:
                    anomalies.append(("yellow", f'vmstat steal {vm["st"]:.0f}% VM 宿主机超卖'))

        elif title == "CPU 使用率分布":
            cpu = parse_cpu_usage(content)
            if cpu:
                for m in CPU_METRICS:
                    key = m["key"]
                    val = cpu.get(key, 0.0)
                    st = cpu_status_light(key, val)
                    if st == "red":
                        anomalies.append(("red", f'{m["name"]}({key}) {val:.1f}% 异常'))
                    elif st == "yellow":
                        anomalies.append(("yellow", f'{m["name"]}({key}) {val:.1f}% 需关注'))

        elif "mpstat" in title.lower() or "每核 CPU" in title:
            for r in parse_mpstat(content):
                if r["cpu"] == "all":
                    continue
                if r["status"] == "red":
                    anomalies.append(("red", f'CPU{r["cpu"]} 使用率 {r["usage"]:.1f}% 过高'))
                elif r["status"] == "yellow":
                    anomalies.append(("yellow", f'CPU{r["cpu"]} 使用率 {r["usage"]:.1f}% 偏高'))
                if r["steal"] > 5:
                    anomalies.append(("yellow", f'CPU{r["cpu"]} steal {r["steal"]:.1f}% VM 宿主机超卖'))
                if r["iow"] > 10:
                    anomalies.append(("yellow", f'CPU{r["cpu"]} iowait {r["iow"]:.1f}% IO 等待偏高'))

        elif title == "CPU Top 5":
            _, rows = parse_ps_lines(content)
            for r in rows[:3]:
                try:
                    cpu_val = float(r["cpu"])
                except (ValueError, KeyError):
                    continue
                if cpu_val > 90:
                    anomalies.append(("red", f'进程 {r["comm"]}(PID {r["pid"]}) CPU {cpu_val}% 过高'))
                elif cpu_val > 70:
                    anomalies.append(("yellow", f'进程 {r["comm"]}(PID {r["pid"]}) CPU {cpu_val}% 偏高'))

    return anomalies


def render_cpu_anomaly_summary(anomalies: list[tuple[str, str]]) -> str:
    """渲染 CPU 模块异常指标汇总（置于系统负载卡片之前）"""
    if not anomalies:
        return f'''
    <div class="cpu-anomaly-banner cpu-anomaly-ok">
        <div class="cpu-anomaly-title">📋 异常指标汇总</div>
        <div class="cpu-anomaly-none">🟢 无异常</div>
    </div>'''

    items = ""
    for level, msg in anomalies:
        dot = {"red": "🔴", "yellow": "🟡"}[level]
        items += f'<li class="cpu-anomaly-li-{level}">{dot} {escape_html(msg)}</li>'

    worst = "red" if any(l == "red" for l, _ in anomalies) else "warn"
    return f'''
    <div class="cpu-anomaly-banner cpu-anomaly-{worst}">
        <div class="cpu-anomaly-title">📋 异常指标汇总</div>
        <ul class="cpu-anomaly-list">{items}</ul>
    </div>'''


def parse_mpstat(content: str) -> list[dict]:
    """解析 mpstat -P ALL 输出为每核指标列表"""
    rows = []
    pat = re.compile(
        r"(?:\d{1,2}:\d{2}:\d{2}(?:\s+\S+)?\s+)?(all|\d+)\s+"
        r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)"
    )
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or "Average" in line or "%usr" in line or line.endswith("CPU"):
            continue
        m = pat.search(line)
        if not m:
            continue
        cpu = m.group(1)
        usr, _nice, sys, iow, _irq, _soft, steal, _guest, _gnice, idle = (
            float(m.group(i)) for i in range(2, 12)
        )
        usage = 100.0 - idle
        if usage > 90:
            status = "red"
        elif usage > 70:
            status = "yellow"
        else:
            status = "green"
        rows.append({
            "cpu": cpu, "usr": usr, "sys": sys, "iow": iow,
            "steal": steal, "idle": idle, "usage": usage, "status": status,
        })
    return rows


def render_mpstat_block(content: str, cores: int = 0) -> tuple[str, str]:
    """渲染每核 CPU 表格"""
    rows_data = parse_mpstat(content)
    if not rows_data:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            "mpstat 不可用",
        )
    rows_html = ""
    max_usage = 0.0
    hot_core = ""
    for r in rows_data:
        dot = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[r["status"]]
        if r["cpu"] != "all" and r["usage"] > max_usage:
            max_usage = r["usage"]
            hot_core = r["cpu"]
        rows_html += f'''
        <tr class="cpu-row cpu-{r["status"]}">
            <td><b>{escape_html(r["cpu"])}</b></td>
            <td>{r["usage"]:.1f}%</td>
            <td>{r["usr"]:.1f}%</td>
            <td>{r["sys"]:.1f}%</td>
            <td>{r["iow"]:.1f}%</td>
            <td>{r["steal"]:.1f}%</td>
            <td>{r["idle"]:.1f}%</td>
            <td>{dot}</td>
        </tr>'''
    thead = "".join(mpstat_th_html(name, key) for name, key in MPSTAT_COLUMNS)
    hint = render_mpstat_interpret_hint(rows_data, cores)
    body = f'''
    <div class="card-body">
    <table class="cpu-tbl">
        <thead><tr>{thead}</tr></thead>
        <tbody>{rows_html}</tbody>
    </table>
        {render_mpstat_stat_guide(cores)}
        <div class="load-trend-hint">{hint}</div>
        {render_mpstat_high_guide(rows_data)}
    </div>'''
    all_row = next((r for r in rows_data if r["cpu"] == "all"), rows_data[0])
    hot_hint = f" | 最热核 CPU{hot_core} {max_usage:.1f}%" if hot_core else ""
    summary = f'整体 {all_row["usage"]:.1f}%{hot_hint}'
    return body, summary


def parse_vmstat(content: str) -> dict | None:
    """解析 vmstat 最后一行"""
    line = content.strip().split("\n")[-1].strip()
    parts = line.split()
    if len(parts) < 17:
        return None
    try:
        return {
            "r": int(parts[0]), "b": int(parts[1]),
            "cs": int(parts[11]), "us": float(parts[12]),
            "sy": float(parts[13]), "id": float(parts[14]),
            "wa": float(parts[15]), "st": float(parts[16]) if len(parts) > 16 else 0.0,
        }
    except (ValueError, IndexError):
        return None


def vmstat_r_status(r: int, cores: int) -> str:
    """运行队列 r 的状态灯"""
    if cores > 0:
        if r > cores:
            return "red"
        if r > cores * 0.7:
            return "yellow"
        return "green"
    if r > 4:
        return "yellow"
    return "green"


def vmstat_b_status(b: int) -> str:
    """阻塞进程 b 的状态灯"""
    if b >= 5:
        return "red"
    if b > 0:
        return "yellow"
    return "green"


def vmstat_cs_status(cs: int) -> str:
    """上下文切换 cs 的状态灯（粗粒度）"""
    if cs > 50000:
        return "yellow"
    return "green"


def render_vmstat_stat_guide(cores: int = 0) -> str:
    """vmstat 运行队列统计说明（默认折叠）"""
    cores_hint = (
        f"本机 <b>{cores} 核</b>，r 持续 &gt; {cores} 表示可运行进程数超过 CPU 并行能力。"
        if cores else "需结合 CPU 核数判断：r 持续大于核数说明排队严重。"
    )
    return f'''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 vmstat 运行队列说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>vmstat 1 2</code> 的<strong>最后一行</strong>——先预热 1 秒，再取接下来 1 秒的统计。
            这是<strong>瞬时快照</strong>，与 Load Average（多时段平均）互补：Load 看趋势，vmstat 看此刻。</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>全称</th><th>含义</th></tr>
                <tr><td><b>r</b></td><td>running</td>
                    <td>运行队列长度：<strong>正在占用 CPU</strong> + <strong>就绪等 CPU</strong> 的进程数。
                    多核下 r 可接近核数仍属正常；<strong>持续 &gt; 核数</strong> 说明 CPU 排队。</td></tr>
                <tr><td><b>b</b></td><td>blocked</td>
                    <td>不可中断睡眠（<strong>D 状态</strong>）进程数，通常卡在<strong>等磁盘/存储 IO</strong> 完成。
                    无法被 kill -9；<strong>b &gt; 0 且持续</strong> 优先怀疑 IO 瓶颈或存储故障。</td></tr>
                <tr><td><b>cs</b></td><td>context switch</td>
                    <td>每秒<strong>上下文切换</strong>次数（CPU 在不同进程/线程间切换的频率）。
                    线程多、锁竞争、频繁系统调用时会升高；单看绝对值意义有限，<strong>突增或伴随 r 高</strong> 需关注。</td></tr>
                <tr><td><b>us/sy/id/wa/st</b></td><td>—</td>
                    <td>同一行的 CPU 时间占比（%）：用户态 / 内核态 / 空闲 / IO 等待 / 被偷（虚拟机）。
                    与上方「CPU 使用率分布」同源，此处为 vmstat 视角的瞬时快照。</td></tr>
            </table>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 r ≤ 核数×0.7</span> CPU 基本无排队 &nbsp;
                <span class="kb-tag tag-warn">🟡 r &gt; 核数×0.7</span> 接近饱和 &nbsp;
                <span class="kb-tag tag-bad">🔴 r &gt; 核数</span> 持续排队，算力不足<br>
                <span class="kb-tag tag-good">🟢 b = 0</span> 无 IO 阻塞 &nbsp;
                <span class="kb-tag tag-warn">🟡 b &gt; 0</span> 有进程等 IO，观察是否持续 &nbsp;
                <span class="kb-tag tag-bad">🔴 b ≥ 5</span> 大量 D 状态，查磁盘/存储
            </p>
            <p>{cores_hint}</p>
            <p><b>与 Load 对照读法</b>（Load 无法区分 CPU 还是 IO，vmstat 可辅助拆分）：</p>
            <ul class="load-guide-list">
                <li><b>CPU 算力紧</b>：r 高、b≈0、wa≈0、id 低 → 进程抢 CPU，查「CPU Top 5」</li>
                <li><b>磁盘 IO 紧</b>：b&gt;0、wa&gt;10%、id 仍高 → CPU 空闲但在等盘，查磁盘模块 / <code>iostat -x 1</code></li>
                <li><b>混合/虚高 Load</b>：Load 高但 r 低、b 高 → 负载主要来自等 IO 的 D 状态进程</li>
            </ul>
            <p>🔧 持续观察：<code>vmstat 1 5</code> · 查 D 状态：<code>ps aux | awk '$8~/D/'</code>
            · 切换频率：<code>pidstat -w 1 5</code> · IO 详情：<code>iostat -x 1 3</code></p>
        </div>
    </details>'''


def render_vmstat_interpret_hint(data: dict, cores: int) -> str:
    """根据当前 vmstat 值给出解读提示"""
    r, b, wa, id_val = data["r"], data["b"], data["wa"], data["id"]
    hints: list[str] = []
    if cores > 0 and r > cores:
        hints.append(f"r={r} <strong>超过 {cores} 核</strong>，CPU 排队明显")
    elif cores > 0 and r > cores * 0.7:
        hints.append(f"r={r} 接近核数上限（{cores} 核），关注是否持续")
    elif r <= 1 and cores > 0:
        hints.append(f"r={r}，运行队列空闲，CPU 无排队")
    if b >= 5:
        hints.append(f"b={b}，大量进程处于 D 状态，优先排查磁盘/存储 IO")
    elif b > 0:
        hints.append(f"b={b}，有进程不可中断睡眠（等多为 IO），建议 <code>vmstat 1 5</code> 看是否持续")
    if wa > 10:
        hints.append(f"wa={wa:.0f}%，CPU 时间在等 IO，与 b 对照确认磁盘瓶颈")
    if id_val > 80 and r <= 2:
        hints.append("id 高且 r 低，CPU 整体空闲")
    if not hints:
        return "➡️ 运行队列与阻塞进程均在正常范围，建议结合 Load 趋势综合判断"
    return " · ".join(hints)


def render_vmstat_high_guide(data: dict, cores: int) -> str:
    """vmstat 异常时的排查指引"""
    r_st = vmstat_r_status(data["r"], cores)
    b_st = vmstat_b_status(data["b"])
    wa_high = data["wa"] > 10
    if r_st == "green" and b_st == "green" and not wa_high:
        return ""
    level = "bad" if r_st == "red" or b_st == "red" else "warn"
    cores_txt = f"{cores} 核" if cores else "未知核数"
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 运行队列异常 · 排查指引</div>
        <div class="load-guide-body">
            <p class="load-example">当前：r={data["r"]} b={data["b"]} cs={data["cs"]}/s
            · {cores_txt} · wa={data["wa"]:.0f}% id={data["id"]:.0f}%</p>
            <ol class="load-guide-list">
                <li><b>先确认是否持续</b>：单次快照可能偶发，执行 <code>vmstat 1 5</code> 看 5 行是否 r/b 持续偏高。</li>
                <li><b>区分 CPU 排队 vs IO 阻塞</b>：
                    <ul>
                        <li>r 高 + b≈0 + wa≈0 → CPU 算力不足，<code>top</code> / <code>pidstat -u 1 5</code> 定位热点进程</li>
                        <li>b&gt;0 + wa 高 → 磁盘/存储瓶颈，<code>iostat -x 1 3</code>、<code>iotop</code>（如有）</li>
                        <li>b&gt;0 + wa 低 → 可能 NFS/网络盘 hang，查 <code>dmesg</code>、挂载点状态</li>
                    </ul>
                </li>
                <li><b>查 D 状态进程</b>：<code>ps aux | awk '$8~/D/'</code> 或 <code>ps -eo pid,stat,cmd | grep ' D'</code></li>
                <li><b>cs 突增</b>：对比历史基线；线程池过大、锁竞争、频繁 GC 均可能导致，<code>pidstat -w 1 5</code> 看 per-process 切换。</li>
            </ol>
        </div>
    </div>'''


def render_vmstat_block(content: str, cores: int = 0) -> tuple[str, str]:
    """渲染运行队列卡片"""
    data = parse_vmstat(content)
    if not data:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            "vmstat 不可用",
        )
    r_st = vmstat_r_status(data["r"], cores)
    b_st = vmstat_b_status(data["b"])
    cs_st = vmstat_cs_status(data["cs"])
    r_dot = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[r_st]
    b_dot = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[b_st]
    cs_dot = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[cs_st]
    hint = render_vmstat_interpret_hint(data, cores)
    body = f'''
    <div class="card-body">
        <div class="kv-card">
            <div class="kv-row"><span class="kv-key">运行队列 r</span><span class="kv-val">{data["r"]} {r_dot}</span></div>
            <div class="kv-row"><span class="kv-key">阻塞进程 b</span><span class="kv-val">{data["b"]} {b_dot}</span></div>
            <div class="kv-row"><span class="kv-key">上下文切换 cs/s</span><span class="kv-val">{data["cs"]} {cs_dot}</span></div>
            <div class="kv-row"><span class="kv-key">CPU us/sy/id/wa/st</span>
                <span class="kv-val">{data["us"]:.0f}/{data["sy"]:.0f}/{data["id"]:.0f}/{data["wa"]:.0f}/{data["st"]:.0f}</span></div>
        </div>
        {render_vmstat_stat_guide(cores)}
        <div class="load-trend-hint">{hint}</div>
        {render_vmstat_high_guide(data, cores)}
    </div>'''
    summary = f'r={data["r"]} b={data["b"]} cs={data["cs"]}/s'
    return body, summary


def render_cpu_table(metrics: dict[str, float]) -> str:
    """将 8 个 CPU 指标渲染为完整 HTML 表格（值+阈值+排查）"""
    rows = ""
    for m in CPU_METRICS:
        key = m["key"]
        val = metrics.get(key, 0.0)
        color = cpu_status_light(key, val)
        dot  = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[color]
        rows += f'''
        <tr class="cpu-row cpu-{color}">
            <td class="cpu-col-name"><b>{m["name"]}</b><span class="cpu-col-key">{key}</span></td>
            <td class="cpu-col-val">{val:.1f}<span class="cpu-col-pct">%</span></td>
            <td class="cpu-col-light">{dot}</td>
            <td class="cpu-col-desc">{m["desc"]}</td>
            <td class="cpu-col-thresh">
                <span class="thresh-good">🟢 {m["good"]}</span>
                <span class="thresh-warn">⚠️ {m["warn"]}</span>
                <span class="thresh-danger">🔴 {m["danger"]}</span>
            </td>
            <td class="cpu-col-fix">🔧 {m["fix"]}</td>
        </tr>'''

    return f'''
    <table class="cpu-tbl">
        <thead><tr>
            <th class="cpu-th-name">指标</th>
            <th class="cpu-th-val">当前值</th>
            <th class="cpu-th-light">状态</th>
            <th class="cpu-th-desc">含义</th>
            <th class="cpu-th-thresh">阈值</th>
            <th class="cpu-th-fix">排查建议</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>'''


def render_cpu_usage_stat_guide() -> str:
    """CPU 使用率分布统计说明（默认折叠）"""
    metric_rows = ""
    for m in CPU_METRICS:
        metric_rows += f'''
                <tr><td><b>{m["name"]}</b> ({m["key"]})</td>
                    <td>{m["desc"]}</td>
                    <td><span class="thresh-good">🟢 {m["good"]}</span>
                        <span class="thresh-warn">⚠️ {m["warn"]}</span>
                        <span class="thresh-danger">🔴 {m["danger"]}</span></td></tr>'''
    return f'''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 CPU 使用率分布说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>top -bn1</code> 第一行 <code>%Cpu(s):</code>，是<strong>采样瞬间</strong>各 CPU 时间片的占比，<b>8 项之和 ≈ 100%</b>（ni 通常为 0）。</p>
            <p>这是<strong>整机汇总</strong>视角：所有核心的时间加总后按比例展示，无法看出单核热点——单核问题需看「每核 CPU (mpstat)」。</p>
            <table class="load-ref-tbl">
                <tr><th>指标</th><th>含义</th><th>阈值参考</th></tr>
                {metric_rows}
            </table>
            <p><b>快速读法</b>（对照本页其他卡片）：</p>
            <ul class="load-guide-list">
                <li><b>算力充足</b>：id 高、us+sy 低 → CPU 整体空闲</li>
                <li><b>应用 CPU 紧</b>：us 高、wa≈0、运行队列 r 高 → 查「CPU Top 5」定位进程</li>
                <li><b>磁盘 IO 紧</b>：wa 高、id 仍不低、b&gt;0 → CPU 在等盘，查磁盘模块</li>
                <li><b>内核/驱动问题</b>：sy 持续偏高 → <code>strace -c</code>、查内核日志</li>
                <li><b>网络风暴</b>：si 偏高 → 查 <code>ksoftirqd</code>、网卡流量、DDoS</li>
                <li><b>虚拟机 steal</b>：st&gt;0 → 宿主机超卖，联系云平台或迁移</li>
            </ul>
            <p>🔧 持续观察：<code>top -bn1</code> · <code>mpstat -P ALL 1 3</code>
            · <code>pidstat -u 1 5</code> · <code>vmstat 1 5</code></p>
        </div>
    </details>'''


def render_cpu_usage_interpret_hint(metrics: dict[str, float]) -> str:
    """根据 CPU 使用率分布给出解读提示"""
    hints: list[str] = []
    idle = metrics.get("id", 100.0)
    us = metrics.get("us", 0.0)
    wa = metrics.get("wa", 0.0)
    sy = metrics.get("sy", 0.0)
    si = metrics.get("si", 0.0)
    st = metrics.get("st", 0.0)
    usage = 100.0 - idle

    if idle > 80:
        hints.append(f"整体空闲 {idle:.1f}%，CPU 充裕（使用率 {usage:.1f}%）")
    elif idle < 10:
        hints.append(f"idle 仅 {idle:.1f}%，CPU 严重过载")
    elif idle < 20:
        hints.append(f"idle {idle:.1f}%，CPU 偏紧，需关注趋势")

    for key, val, label, thresh in [
        ("us", us, "用户态 us", 70), ("wa", wa, "IO 等待 wa", 10),
        ("sy", sy, "内核态 sy", 30), ("si", si, "软中断 si", 5), ("st", st, "steal st", 5),
    ]:
        st_color = cpu_status_light(key, val)
        if st_color == "red":
            hints.append(f"{label}={val:.1f}% 异常")
        elif st_color == "yellow":
            hints.append(f"{label}={val:.1f}% 需关注")

    if not hints:
        return "➡️ 各 CPU 时间占比均在正常范围"
    return " · ".join(hints)


def render_cpu_usage_high_guide(metrics: dict[str, float]) -> str:
    """CPU 使用率异常时的排查指引"""
    bad: list[tuple[str, dict, float]] = []
    for m in CPU_METRICS:
        val = metrics.get(m["key"], 0.0)
        st = cpu_status_light(m["key"], val)
        if st != "green":
            bad.append((st, m, val))
    if not bad:
        return ""
    level = "bad" if any(s == "red" for s, _, _ in bad) else "warn"
    items = "".join(
        f'<li><b>{m["name"]}({m["key"]})</b>={val:.1f}% — {m["fix"]}</li>'
        for _, m, val in bad
    )
    idle = metrics.get("id", 0.0)
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 CPU 使用率异常 · 排查指引</div>
        <div class="load-guide-body">
            <p class="load-example">当前整体使用率 {100 - idle:.1f}% · idle={idle:.1f}%</p>
            <ol class="load-guide-list">
                <li><b>确认是否持续</b>：单次 top 快照可能偶发，<code>top -bn1</code> 连跑几次或 <code>pidstat -u 1 5</code> 看趋势。</li>
                <li><b>异常项解读</b>：<ul>{items}</ul></li>
                <li><b>定位进程</b>：us 高 →「CPU Top 5」/ <code>pidstat -u 1 5</code>；
                    wa 高 → <code>iostat -x 1</code>、磁盘模块；
                    sy 高 → <code>strace -c -p &lt;pid&gt;</code>；
                    si 高 → <code>cat /proc/softirqs</code>、查网卡流量。</li>
            </ol>
        </div>
    </div>'''


def render_cpu_usage_block(content: str) -> tuple[str, str]:
    """渲染 CPU 使用率分布卡片"""
    cpu_data = parse_cpu_usage(content)
    if not cpu_data:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            content.strip().split("\n")[0][:80] if content.strip() else "无法获取",
        )
    idle_val = cpu_data.get("id", 0.0)
    usage_val = 100.0 - idle_val
    hint = render_cpu_usage_interpret_hint(cpu_data)
    body = f'''
    <div class="card-body">
        {render_cpu_table(cpu_data)}
        {render_cpu_usage_stat_guide()}
        <div class="load-trend-hint">{hint}</div>
        {render_cpu_usage_high_guide(cpu_data)}
    </div>'''
    summary = f"整体使用率 {usage_val:.1f}% | 空闲 {idle_val:.1f}%"
    return body, summary


def render_mpstat_stat_guide(cores: int = 0) -> str:
    """mpstat 每核 CPU 说明（默认折叠）"""
    cores_hint = (
        f"本机 <b>{cores} 核</b>：若某一核 idle 明显低于其他核（如单核 &lt;10% 而其余 &gt;90%），"
        f"可能存在单线程热点或 IRQ 未均衡。"
        if cores else "对比各核 idle：某一核明显偏低可能存在单线程热点或 IRQ 绑定不均。"
    )
    return f'''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 mpstat 每核 CPU 说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>mpstat -P ALL 1 1</code>：对所有 CPU 核心采样 <b>1 秒</b> 后输出平均值。
            <code>all</code> 行为整机汇总，<code>0~N</code> 为各物理/逻辑核。</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>含义</th></tr>
                <tr><td><b>使用率</b></td><td>100% − idle，该核繁忙程度</td></tr>
                <tr><td><b>usr</b></td><td>用户态时间占比（应用程序）</td></tr>
                <tr><td><b>sys</b></td><td>内核态时间占比（系统调用、调度）</td></tr>
                <tr><td><b>iowait</b></td><td>等磁盘 IO 完成的时间（该核视角）</td></tr>
                <tr><td><b>steal</b></td><td>虚拟机被宿主机偷走的 CPU 时间</td></tr>
                <tr><td><b>idle</b></td><td>该核空闲时间，<strong>越低越忙</strong></td></tr>
            </table>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 单核 &lt;70%</span> 正常 &nbsp;
                <span class="kb-tag tag-warn">🟡 70~90%</span> 该核偏忙 &nbsp;
                <span class="kb-tag tag-bad">🔴 &gt;90%</span> 单核热点，可能单线程瓶颈
            </p>
            <p>{cores_hint}</p>
            <p><b>典型场景</b>：</p>
            <ul class="load-guide-list">
                <li><b>单核热点</b>：1 核 idle&lt;10%、其余&gt;90% → 单线程应用、未多 worker 化</li>
                <li><b>IRQ 不均</b>：某几核 sys 高、usr 低 → 网卡中断未 RPS/RFS 均衡，查 <code>/proc/interrupts</code></li>
                <li><b>整体 vs 单核</b>：「CPU 使用率分布」idle 高但某核 mpstat 低 → 整体被空闲核拉低，Load 可能仍偏高</li>
            </ul>
            <p>🔧 持续观察：<code>mpstat -P ALL 1 5</code> · 线程级：<code>top -Hp &lt;pid&gt;</code>
            · 进程绑核：<code>taskset -cp &lt;pid&gt;</code> · 中断分布：<code>cat /proc/interrupts</code></p>
        </div>
    </details>'''


def render_mpstat_interpret_hint(rows_data: list[dict], cores: int = 0) -> str:
    """根据 mpstat 数据给出解读提示"""
    if not rows_data:
        return ""
    all_row = next((r for r in rows_data if r["cpu"] == "all"), None)
    per_core = [r for r in rows_data if r["cpu"] != "all"]
    hints: list[str] = []

    if all_row:
        if all_row["idle"] > 80:
            hints.append(f"整体 idle {all_row['idle']:.1f}%，CPU 充裕")
        elif all_row["usage"] > 90:
            hints.append(f"整体使用率 {all_row['usage']:.1f}%，CPU 过载")

    if per_core:
        usages = [r["usage"] for r in per_core]
        max_r = max(per_core, key=lambda r: r["usage"])
        min_r = min(per_core, key=lambda r: r["usage"])
        spread = max(usages) - min(usages)
        if spread > 50 and max_r["usage"] > 70:
            hints.append(
                f"核间差异大：CPU{max_r['cpu']} 最热 {max_r['usage']:.1f}%，"
                f"CPU{min_r['cpu']} 仅 {min_r['usage']:.1f}% — 可能存在单核热点"
            )
        elif max_r["usage"] > 90:
            hints.append(f"CPU{max_r['cpu']} 使用率 {max_r['usage']:.1f}%，单核热点")
        hot_iow = [r for r in per_core if r["iow"] > 10]
        if hot_iow:
            cores_str = ",".join(r["cpu"] for r in hot_iow[:3])
            hints.append(f"CPU{cores_str} iowait 偏高，该核等 IO")

    if not hints:
        return "➡️ 各核使用率分布均衡，无明显热点"
    return " · ".join(hints)


def render_mpstat_high_guide(rows_data: list[dict]) -> str:
    """mpstat 异常时的排查指引"""
    hot = [r for r in rows_data if r["cpu"] != "all" and r["status"] != "green"]
    if not hot:
        return ""
    level = "bad" if any(r["status"] == "red" for r in hot) else "warn"
    items = "".join(
        f'<li>CPU{r["cpu"]}：使用率 {r["usage"]:.1f}% '
        f'(usr={r["usr"]:.1f}% sys={r["sys"]:.1f}% iow={r["iow"]:.1f}%)</li>'
        for r in sorted(hot, key=lambda x: -x["usage"])[:5]
    )
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 单核 CPU 偏高 · 排查指引</div>
        <div class="load-guide-body">
            <p class="load-example">以下 CPU 核心使用率超过关注阈值：</p>
            <ul class="load-guide-list">{items}</ul>
            <ol class="load-guide-list">
                <li><b>usr 高</b>：该核跑满用户态应用 → <code>top -Hp &lt;pid&gt;</code> 找热点线程，考虑多 worker</li>
                <li><b>sys 高、usr 低</b>：内核/中断占用 → <code>cat /proc/interrupts</code>，检查 IRQ 亲和性、RPS</li>
                <li><b>iowait 高</b>：该核等 IO → <code>iostat -x 1</code>，与磁盘模块对照</li>
                <li><b>steal 高</b>：虚拟机资源争抢 → 联系宿主机/云平台</li>
            </ol>
        </div>
    </div>'''


def render_cpu_top_stat_guide(cores: int = 0) -> str:
    """CPU Top 5 说明（默认折叠）"""
    cores_note = (
        f"本机 <b>{cores} 核</b>：单进程 <code>%CPU</code> 理论最大约 <b>{cores * 100}%</b>"
        f"（多线程跑满所有核）。排行第一若仅 10~20% 通常不算高。"
        if cores else
        "<code>%CPU</code> 为多核累计值：N 核机器上单进程最大约 N×100%。"
    )
    return f'''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 CPU Top 5 说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>ps -eo pid,user,%cpu,%mem,comm --sort=-%cpu</code> 的<strong>瞬时快照</strong>，
            按 <code>%CPU</code> 降序取前 5。反映<strong>采样时刻</strong>谁最耗 CPU，非历史累计。</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>含义</th></tr>
                <tr><td><b>PID</b></td><td>进程 ID，<code>kill</code> / <code>strace -p</code> 等操作的目标</td></tr>
                <tr><td><b>USER</b></td><td>进程所属用户，排查权限与资源隔离</td></tr>
                <tr><td><b>%CPU</b></td><td>CPU 占用百分比（<strong>多核累计</strong>，见下方说明）</td></tr>
                <tr><td><b>%MEM</b></td><td>物理内存占用占总量比例（辅助判断是否为内存型进程）</td></tr>
                <tr><td><b>COMMAND</b></td><td>进程名/命令（Java 等可能只显示解释器名）</td></tr>
            </table>
            <p>{cores_note}</p>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 &lt;50%</span> 一般正常 &nbsp;
                <span class="kb-tag tag-warn">🟡 50~100%</span> 需关注（视核数） &nbsp;
                <span class="kb-tag tag-bad">🔴 &gt;100% 或持续高位</span> 算力消耗大，需定位原因
            </p>
            <p><b>常见原因</b>：</p>
            <ul class="load-guide-list">
                <li><b>Java</b>：Full GC、批处理、死循环、线程风暴 → <code>jstack &lt;pid&gt;</code>、GC 日志</li>
                <li><b>lua-runner / 脚本</b>：定时任务、配置热加载、异常循环</li>
                <li><b>sshd</b>：通常为堡垒机/巡检连接本身，短暂偏高可忽略</li>
                <li><b>ksoftirqd / 内核线程</b>：网络包处理、中断，查流量与 <code>/proc/softirqs</code></li>
            </ul>
            <p>🔧 深入排查：<code>top -p &lt;pid&gt;</code> · 线程级 <code>top -Hp &lt;pid&gt;</code>
            · <code>pidstat -u -p &lt;pid&gt; 1 5</code> · Java <code>jstack</code>/<code>async-profiler</code></p>
        </div>
    </details>'''


def render_cpu_top_interpret_hint(rows: list[dict], cores: int = 0) -> str:
    """根据 CPU Top 5 给出解读提示"""
    if not rows:
        return ""
    top = rows[0]
    hints: list[str] = []
    try:
        cpu_val = float(top["cpu"])
    except ValueError:
        return "➡️ 查看排行第一进程是否为本机预期业务"

    comm = top["comm"]
    per_core_pct = cpu_val / cores if cores > 0 else cpu_val

    if cpu_val < 20:
        hints.append(f"Top1 {comm}(PID {top['pid']}) CPU {cpu_val}%，整体占用不高")
    elif cpu_val >= 100:
        hints.append(f"Top1 {comm} CPU {cpu_val}%，多核并行或持续高负载")
    elif cores > 0 and per_core_pct > 70:
        hints.append(f"Top1 {comm} 约折合 {per_core_pct:.0f}%×单核，该进程较吃 CPU")
    else:
        hints.append(f"Top1 {comm}(PID {top['pid']}) CPU {cpu_val}%")

    high_count = sum(1 for r in rows if float(r["cpu"]) > 50)
    if high_count >= 3:
        hints.append(f"Top5 中有 {high_count} 个进程 CPU&gt;50%，整体算力压力偏大")

    java_rows = [r for r in rows if "java" in r["comm"].lower()]
    if java_rows and float(java_rows[0]["cpu"]) > 30:
        hints.append("Java 进程靠前，若突增可排查 GC / 批任务")

    return " · ".join(hints) if hints else "➡️ 进程 CPU 占用在正常范围"


def render_cpu_top_high_guide(rows: list[dict], cores: int = 0) -> str:
    """CPU Top 5 异常时的排查指引"""
    hot = []
    for r in rows:
        try:
            cpu_val = float(r["cpu"])
        except ValueError:
            continue
        threshold = 50 if cores <= 4 else 70
        if cpu_val >= threshold or cpu_val > 100:
            hot.append((r, cpu_val))
    if not hot:
        return ""
    level = "bad" if any(v > 100 or v > (cores * 80 if cores else 200) for _, v in hot) else "warn"
    items = "".join(
        f'<li><b>{r["comm"]}</b> PID={r["pid"]} USER={r["user"]} CPU={v}% MEM={r["mem"]}%</li>'
        for r, v in hot
    )
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 CPU 高占用进程 · 排查指引</div>
        <div class="load-guide-body">
            <ul class="load-guide-list">{items}</ul>
            <ol class="load-guide-list">
                <li><b>确认是否持续</b>：<code>pidstat -u -p &lt;pid&gt; 1 5</code> 或间隔多次 ps，排除瞬时尖峰。</li>
                <li><b>看线程</b>：<code>top -Hp &lt;pid&gt;</code> — 单线程 100% 多为热点 loop；多线程均匀高为并行计算。</li>
                <li><b>Java 进程</b>：<code>jstack &lt;pid&gt;</code> 看线程栈；查 GC 日志 / <code>jstat -gcutil &lt;pid&gt; 1000</code>。</li>
                <li><b>非预期进程</b>：核对 USER、启动命令 <code>ps -fp &lt;pid&gt;</code>，排查挖矿/异常脚本。</li>
                <li><b>处理方向</b>：优化代码 / 限流 / 扩容 / 调整定时任务窗口 / 临时 nice 降权。</li>
            </ol>
        </div>
    </div>'''


def render_cpu_top_block(content: str, cores: int = 0) -> tuple[str, str]:
    """渲染 CPU Top 5 卡片（含详细说明）"""
    columns, rows = parse_ps_lines(content)
    if not rows:
        return render_ps_top_table(content)

    thead = "".join(f"<th>{escape_html(c)}</th>" for c in columns)
    tbody = ""
    for idx, r in enumerate(rows):
        cls = "alt" if idx % 2 == 0 else ""
        cells = [r["pid"], r["user"], r["cpu"], r["mem"], r["comm"]]
        tds = "".join(f"<td>{escape_html(c)}</td>" for c in cells)
        tbody += f'<tr class="{cls}">{tds}</tr>'

    top = rows[0]
    summary = f'{top["comm"]} (PID {top["pid"]}) CPU {top["cpu"]}% MEM {top["mem"]}%'
    hint = render_cpu_top_interpret_hint(rows, cores)
    body = f'''
    <div class="card-body">
        <table class="tbl"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>
        {render_cpu_top_stat_guide(cores)}
        <div class="load-trend-hint">{hint}</div>
        {render_cpu_top_high_guide(rows, cores)}
    </div>'''
    return body, summary


# ═══════════════════════════════════════════════════════════════
#  通用解析
# ═══════════════════════════════════════════════════════════════

def strip_decorations(text: str) -> str:
    """移除模块脚本的装饰性输出，只保留数据内容"""
    lines = text.split("\n")
    cleaned = []
    skip_next_blank = False
    for line in lines:
        # 纯等号分隔线: ============================================
        if re.match(r"^={5,}$", line.strip()):
            skip_next_blank = True
            continue
        # 模块标题行:   [02] CPU 与负载
        if re.match(r"^\s*\[\d+[A-Za-z_]*\]\s+", line.strip()):
            skip_next_blank = True
            continue
        # 跟在装饰线后的空行跳过
        if skip_next_blank and line.strip() == "":
            skip_next_blank = False
            continue
        skip_next_blank = False
        cleaned.append(line)
    return "\n".join(cleaned)


def parse_blocks(text: str) -> list[dict]:
    """按 '--- XXX ---' 标题行拆分模块输出为 block 列表"""
    blocks = []
    lines = text.split("\n")
    cur_title = ""
    cur_lines: list[str] = []

    def flush():
        if cur_lines:
            content = "\n".join(cur_lines).strip()
            if content:
                blocks.append({"title": cur_title, "content": content})

    for line in lines:
        m = re.match(r"^-+\s*(.+?)\s*-+$", line)
        if m:
            flush()
            cur_title = m.group(1).strip()
            cur_lines = []
            continue
        cur_lines.append(line)

    flush()
    return blocks


def is_table_text(content: str) -> bool:
    """判断内容是否适合渲染为表格（多行、带列头）"""
    lines = [l for l in content.strip().split("\n") if l.strip()]
    return len(lines) >= 2 and len(lines[0].split()) >= 3


def is_ps_output(content: str) -> bool:
    """检测是否为 ps -eo 进程列表输出"""
    first = content.strip().split("\n")[0] if content.strip() else ""
    return bool(re.search(r"^\s*PID\s+USER", first, re.I))


def parse_ps_lines(content: str) -> tuple[list[str], list[dict]]:
    """解析 ps -eo 输出 → (列名, 行数据)"""
    lines = [l for l in content.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return [], []

    has_rss = "RSS" in lines[0].upper()
    if has_rss:
        columns = ["PID", "USER", "%CPU", "%MEM", "RSS", "COMMAND"]
        pat = re.compile(r"^\s*(\d+)\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(.*)$")
    else:
        columns = ["PID", "USER", "%CPU", "%MEM", "COMMAND"]
        pat = re.compile(r"^\s*(\d+)\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s+(.*)$")

    rows = []
    for line in lines[1:]:
        m = pat.match(line)
        if not m:
            continue
        if has_rss:
            rows.append({
                "pid": m.group(1), "user": m.group(2),
                "cpu": m.group(3), "mem": m.group(4),
                "rss": m.group(5), "comm": m.group(6).strip(),
            })
        else:
            rows.append({
                "pid": m.group(1), "user": m.group(2),
                "cpu": m.group(3), "mem": m.group(4),
                "comm": m.group(5).strip(),
            })
    return columns, rows


def render_ps_top_table(content: str) -> tuple[str, str]:
    """将 ps Top N 输出渲染为对齐的 HTML 表格"""
    columns, rows = parse_ps_lines(content)
    if not rows:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            content.strip().split("\n")[0][:80] if content.strip() else "",
        )

    thead = "".join(f"<th>{escape_html(c)}</th>" for c in columns)
    tbody = ""
    for idx, r in enumerate(rows):
        cls = "alt" if idx % 2 == 0 else ""
        if "rss" in r:
            cells = [r["pid"], r["user"], r["cpu"], r["mem"], r["rss"], r["comm"]]
        else:
            cells = [r["pid"], r["user"], r["cpu"], r["mem"], r["comm"]]
        tds = "".join(f"<td>{escape_html(c)}</td>" for c in cells)
        tbody += f'<tr class="{cls}">{tds}</tr>'

    body = (
        f'<div class="card-body"><table class="tbl">'
        f"<thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></div>"
    )
    top = rows[0]
    summary = f'{top["comm"]} (PID {top["pid"]}) CPU {top["cpu"]}% MEM {top["mem"]}%'
    return body, summary


def text_to_table(content: str) -> str:
    """将空格分隔的文本转为 HTML 表格"""
    lines = [l for l in content.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return f'<pre class="pre">{escape_html(content)}</pre>'

    # 拆分列
    rows = []
    for line in lines:
        cols = re.split(r"\s{2,}", line.strip())
        if len(cols) <= 1:
            cols = line.strip().split()
        rows.append(cols)

    max_cols = max(len(r) for r in rows)

    # 修复列对齐：如果数据行比表头多列（如 free -h 中的 "Mem:" 标签前缀），
    # 在表头左侧补空列，确保数值列与表头对齐
    header_cols = len(rows[0])
    if header_cols < max_cols:
        diff = max_cols - header_cols
        rows[0] = [""] * diff + rows[0]

    for r in rows:
        while len(r) < max_cols:
            r.append("")

    html = ['<table class="tbl">']
    # 表头
    html.append('<thead><tr>')
    for cell in rows[0]:
        html.append(f'<th>{escape_html(cell)}</th>')
    html.append('</tr></thead>')
    # 表体
    html.append('<tbody>')
    for idx, row in enumerate(rows[1:]):
        cls = "alt" if idx % 2 == 0 else ""
        html.append(f'<tr class="{cls}">')
        for cell in row:
            html.append(f'<td>{escape_html(cell)}</td>')
        html.append('</tr>')
    html.append('</tbody></table>')
    return "\n".join(html)


def escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ═══════════════════════════════════════════════════════════════
#  内存模块：解析 / 说明 / 渲染
# ═══════════════════════════════════════════════════════════════

def parse_free_h(content: str) -> dict | None:
    """解析 free -h 输出为结构化数据"""
    if not is_free_output(content):
        return None
    data: dict = {}
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or re.match(r"^\s*total\b", line, re.I):
            continue
        m = re.match(
            r"^(Mem|Swap):\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(\S+))?(?:\s+(\S+))?(?:\s+(\S+))?",
            line,
        )
        if not m:
            continue
        label = m.group(1)
        values = [g for g in m.groups()[1:] if g]
        if label == "Mem":
            keys = ["total", "used", "free", "shared", "buff_cache", "available"]
            fields = dict(zip(keys, values))
            total_gb = parse_mem_value(fields["total"])
            used_gb = parse_mem_value(fields["used"])
            avail_gb = parse_mem_value(fields.get("available", "0"))
            data["mem"] = {
                **fields,
                "total_gb": total_gb,
                "used_gb": used_gb,
                "avail_gb": avail_gb,
                "used_pct": used_gb / total_gb * 100 if total_gb else 0,
                "avail_pct": avail_gb / total_gb * 100 if total_gb else 0,
            }
        else:
            keys = ["total", "used", "free"]
            fields = dict(zip(keys, values))
            total_gb = parse_mem_value(fields["total"])
            used_gb = parse_mem_value(fields["used"])
            data["swap"] = {
                **fields,
                "total_gb": total_gb,
                "used_gb": used_gb,
                "used_pct": used_gb / total_gb * 100 if total_gb else 0,
            }
    return data if "mem" in data else None


def mem_rate_status(used_pct: float, avail_pct: float) -> tuple[str, str, str]:
    """内存状态：优先看 available，辅以 used"""
    if avail_pct < 10 or used_pct >= 90:
        return "red", "🔴", "危险"
    if avail_pct < 20 or used_pct >= 80:
        return "yellow", "🟡", "关注"
    return "green", "🟢", "正常"


def swap_rate_status(used_pct: float) -> tuple[str, str, str]:
    if used_pct >= 60:
        return "red", "🔴", "危险"
    if used_pct >= 30:
        return "yellow", "🟡", "关注"
    return "green", "🟢", "正常"


def render_mem_overview_stat_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 内存总览说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>free -h</code> 的<strong>瞬时快照</strong>。
            Linux 内存管理会把空闲内存用作<strong>文件缓存</strong>，因此 <code>used</code> 偏高不一定代表内存不足。</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>含义</th></tr>
                <tr><td><b>total</b></td><td>物理内存总量</td></tr>
                <tr><td><b>used</b></td><td>已用 = 总量 − free − buff/cache（含应用 + 部分内核占用）</td></tr>
                <tr><td><b>free</b></td><td>完全未被使用的内存，通常很小属正常</td></tr>
                <tr><td><b>shared</b></td><td>tmpfs/shmem 等共享内存</td></tr>
                <tr><td><b>buff/cache</b></td><td>缓冲区 + 页缓存，<strong>可回收</strong>，内存紧张时内核会释放</td></tr>
                <tr><td><b>available</b></td><td><strong>核心指标</strong>：估算新进程可用内存（含可回收缓存），无需手动加 free+cache</td></tr>
            </table>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 available &gt;20%</span> 充裕 &nbsp;
                <span class="kb-tag tag-warn">🟡 10~20%</span> 需关注趋势 &nbsp;
                <span class="kb-tag tag-bad">🔴 &lt;10%</span> 可能触发 OOM Killer<br>
                <span class="kb-tag tag-good">🟢 used &lt;80%</span> 正常 &nbsp;
                <span class="kb-tag tag-warn">🟡 80~90%</span> 关注 &nbsp;
                <span class="kb-tag tag-bad">🔴 &gt;90%</span> 物理内存紧张
            </p>
            <p><b>常见误读</b>：used 高 + available 仍高 → 大量缓存，<strong>不是</strong>内存不足；
            free 很小 → Linux 正常行为（尽量用满内存做缓存）。</p>
            <p>🔧 持续观察：<code>free -h</code> · <code>vmstat 1 5</code>（si/so 换页）
            · <code>cat /proc/meminfo</code> · 进程级 <code>ps aux --sort=-rss</code></p>
        </div>
    </details>'''


def render_mem_overview_interpret_hint(data: dict) -> str:
    mem = data["mem"]
    hints: list[str] = []
    if mem["avail_pct"] > 40:
        hints.append(f"available {mem['available']}（{mem['avail_pct']:.1f}%），新进程内存充裕")
    elif mem["avail_pct"] < 10:
        hints.append(f"available 仅 {mem['avail_pct']:.1f}%，OOM 风险高")
    elif mem["avail_pct"] < 20:
        hints.append(f"available {mem['avail_pct']:.1f}%，需关注内存趋势")

    if mem["used_pct"] >= 80 and mem["avail_pct"] < 30:
        hints.append(f"used {mem['used_pct']:.1f}% 偏高且 available 偏紧，排查大内存进程")

    if "swap" in data and data["swap"]["used_gb"] > 0:
        sp = data["swap"]["used_pct"]
        if sp >= 30:
            hints.append(f"Swap 已用 {data['swap']['used']}（{sp:.1f}%），存在换出")
        elif sp > 0:
            hints.append(f"Swap 轻量占用 {data['swap']['used']}，观察 si/so 即可")

    if not hints:
        return "➡️ 内存与 available 均在正常范围"
    return " · ".join(hints)


def render_mem_overview_high_guide(data: dict) -> str:
    mem = data["mem"]
    st, _, _ = mem_rate_status(mem["used_pct"], mem["avail_pct"])
    swap_st = "green"
    if "swap" in data:
        swap_st, _, _ = swap_rate_status(data["swap"]["used_pct"])
    if st == "green" and swap_st == "green":
        return ""
    level = "bad" if st == "red" or swap_st == "red" else "warn"
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 内存紧张 · 排查指引</div>
        <div class="load-guide-body">
            <p class="load-example">Mem used={mem["used"]}/{mem["total"]} · available={mem.get("available", "—")}
            · buff/cache={mem.get("buff_cache", "—")}</p>
            <ol class="load-guide-list">
                <li><b>确认是否持续</b>：<code>free -h</code> 间隔多次采样，或 <code>vmstat 1 5</code> 看 si/so 是否持续 &gt;0。</li>
                <li><b>定位大内存进程</b>：查看「高内存进程 Top 5」/ <code>ps aux --sort=-rss | head</code></li>
                <li><b>区分缓存 vs 真占用</b>：available 仍高 → 多为缓存，可观察；available 低 → 应用真实占满</li>
                <li><b>Swap 增长</b>：so 持续 &gt;0 → 物理内存不足，加内存 / 限流 / 调低 swappiness</li>
                <li><b>OOM 风险</b>：available &lt;10% 时查 <code>dmesg | grep -i oom</code>，准备扩容或杀进程</li>
            </ol>
        </div>
    </div>'''


def render_mem_overview_block(content: str) -> tuple[str, str]:
    data = parse_free_h(content)
    if not data:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            content.strip().split("\n")[0][:80] if content.strip() else "",
        )
    mem = data["mem"]
    hint = render_mem_overview_interpret_hint(data)
    body = f'''
    <div class="card-body">
        {render_free_output(content)}
        {render_mem_overview_stat_guide()}
        <div class="load-trend-hint">{hint}</div>
        {render_mem_overview_high_guide(data)}
    </div>'''
    summary = (
        f"使用率 {mem['used_pct']:.1f}% | 已用 {mem['used']} / 总量 {mem['total']}"
        f" | 可用 {mem.get('available', '—')}"
    )
    return body, summary


def parse_swapon(content: str) -> list[dict]:
    """解析 swapon --show 输出"""
    rows = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line == "未启用":
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        name, typ, size, used = parts[0], parts[1], parts[2], parts[3]
        prio = parts[4] if len(parts) > 4 else "—"
        size_gb = parse_mem_value(size)
        used_gb = parse_mem_value(used)
        used_pct = used_gb / size_gb * 100 if size_gb else 0
        rows.append({
            "name": name, "type": typ, "size": size, "used": used,
            "prio": prio, "size_gb": size_gb, "used_gb": used_gb, "used_pct": used_pct,
        })
    return rows


def render_swap_stat_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 Swap 状态说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>swapon --show</code>，列出已启用的 Swap 分区/文件及用量。
            Swap 是物理内存不足时，内核把<strong>不常用内存页</strong>换到磁盘的空间。</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>含义</th></tr>
                <tr><td><b>NAME</b></td><td>Swap 设备路径（分区 LVM 或 swap 文件）</td></tr>
                <tr><td><b>TYPE</b></td><td>partition（分区）或 file（文件）</td></tr>
                <tr><td><b>SIZE</b></td><td>Swap 总容量</td></tr>
                <tr><td><b>USED</b></td><td>当前已换出到 Swap 的数据量</td></tr>
                <tr><td><b>PRIO</b></td><td>使用优先级，数值越小越优先</td></tr>
            </table>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 &lt;30%</span> 轻量换出，通常可接受 &nbsp;
                <span class="kb-tag tag-warn">🟡 30~60%</span> 观察 si/so 趋势 &nbsp;
                <span class="kb-tag tag-bad">🔴 &gt;60%</span> 物理内存长期不足
            </p>
            <p><b>关键：看趋势而非绝对值</b> — Swap 有占用不代表当前有问题（可能是历史峰值残留）；
            需用 <code>vmstat 1</code> 观察 <b>si</b>（换入）和 <b>so</b>（换出）是否<strong>持续 &gt;0</strong>。</p>
            <ul class="load-guide-list">
                <li><b>so 持续 &gt;0</b>：正在大量换出，磁盘 IO 增加，性能下降，需加内存或限流</li>
                <li><b>si 高 so 低</b>：曾经换出，现在在换回，观察是否稳定</li>
                <li><b>swappiness</b>：默认 60，值越高越积极换出；可 <code>cat /proc/sys/vm/swappiness</code> 查看</li>
            </ul>
            <p>🔧 <code>vmstat 1 5</code> · <code>cat /proc/swaps</code>
            · <code>sysctl vm.swappiness</code></p>
        </div>
    </details>'''


def render_swap_interpret_hint(rows: list[dict]) -> str:
    if not rows:
        return "➡️ 未启用 Swap 或未获取到 Swap 信息"
    hints: list[str] = []
    total_used_pct = 0.0
    count = 0
    for r in rows:
        st, dot, label = swap_rate_status(r["used_pct"])
        count += 1
        total_used_pct += r["used_pct"]
        if st == "red":
            hints.append(f'{r["name"]} Swap 已用 {r["used"]}/{r["size"]}（{r["used_pct"]:.1f}%）偏高')
        elif st == "yellow" and r["used_gb"] > 0:
            hints.append(f'Swap 已用 {r["used"]}（{r["used_pct"]:.1f}%），建议观察 si/so')
        elif r["used_gb"] == 0:
            hints.append("Swap 未使用")
    if not hints:
        avg = total_used_pct / count if count else 0
        return f"Swap 平均使用率 {avg:.1f}%，在正常范围"
    return " · ".join(hints[:3])


def render_swap_high_guide(rows: list[dict]) -> str:
    hot = [r for r in rows if swap_rate_status(r["used_pct"])[0] != "green"]
    if not hot:
        return ""
    level = "bad" if any(swap_rate_status(r["used_pct"])[0] == "red" for r in hot) else "warn"
    items = "".join(
        f'<li><b>{r["name"]}</b> ({r["type"]}) {r["used"]}/{r["size"]} = {r["used_pct"]:.1f}%</li>'
        for r in hot
    )
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 Swap 占用偏高 · 排查指引</div>
        <div class="load-guide-body">
            <ul class="load-guide-list">{items}</ul>
            <ol class="load-guide-list">
                <li><b>是否正在换出</b>：<code>vmstat 1 5</code> — <b>so</b> 列持续 &gt;0 说明当下内存不足</li>
                <li><b>定位占内存进程</b>：「高内存进程 Top 5」/ <code>ps aux --sort=-rss</code></li>
                <li><b>Java/大数据</b>：查堆配置 (-Xmx)、堆外内存、缓存无上限</li>
                <li><b>处理</b>：扩容内存 / 限流 / 调优 JVM / 临时 <code>sysctl -w vm.swappiness=10</code>（重启失效）</li>
            </ol>
        </div>
    </div>'''


def render_swap_block(content: str) -> tuple[str, str]:
    rows = parse_swapon(content)
    if not rows:
        hint = "➡️ 未启用 Swap 或未获取到 Swap 信息"
        body = f'''
    <div class="card-body">
        <pre class="pre">{escape_html(content.strip() or "未启用")}</pre>
        {render_swap_stat_guide()}
        <div class="load-trend-hint">{hint}</div>
    </div>'''
        return body, content.strip().split("\n")[0][:80] if content.strip() else "未启用"

    table_rows = ""
    for idx, r in enumerate(rows):
        st, dot, _ = swap_rate_status(r["used_pct"])
        cls = "alt" if idx % 2 == 0 else ""
        table_rows += f'''<tr class="{cls}">
            <td>{escape_html(r["name"])}</td><td>{escape_html(r["type"])}</td>
            <td>{escape_html(r["size"])}</td><td>{escape_html(r["used"])} {dot}</td>
            <td>{escape_html(r["prio"])}</td></tr>'''
    hint = render_swap_interpret_hint(rows)
    total_used = sum(r["used_gb"] for r in rows)
    total_size = sum(parse_mem_value(r["size"]) for r in rows)
    summary = f"{len(rows)} 个 Swap · 已用 {total_used:.1f}G / {total_size:.1f}G"
    body = f'''
    <div class="card-body">
        <table class="tbl">
            <thead><tr><th>NAME</th><th>TYPE</th><th>SIZE</th><th>USED</th><th>PRIO</th></tr></thead>
            <tbody>{table_rows}</tbody>
        </table>
        {render_swap_stat_guide()}
        <div class="load-trend-hint">{hint}</div>
        {render_swap_high_guide(rows)}
    </div>'''
    return body, summary


def render_mem_top_stat_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 高内存进程 Top 5 说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>ps -eo pid,user,%cpu,%mem,rss,comm --sort=-%mem</code> 的<strong>瞬时快照</strong>，
            按 <code>%MEM</code> 降序取前 5。</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>含义</th></tr>
                <tr><td><b>PID</b></td><td>进程 ID</td></tr>
                <tr><td><b>USER</b></td><td>运行用户</td></tr>
                <tr><td><b>%CPU</b></td><td>CPU 占用（辅助判断是否 GC 导致 CPU+内存双高）</td></tr>
                <tr><td><b>%MEM</b></td><td>RSS 占物理内存总量的百分比</td></tr>
                <tr><td><b>RSS</b></td><td><strong>Resident Set Size</strong>：实际驻留物理内存（KB），<strong>排查内存问题看此列</strong></td></tr>
                <tr><td><b>COMMAND</b></td><td>进程名（Java 等可能只显示解释器名）</td></tr>
            </table>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 单进程 &lt;10%</span> 一般正常 &nbsp;
                <span class="kb-tag tag-warn">🟡 10~20%</span> 关注趋势 &nbsp;
                <span class="kb-tag tag-bad">🔴 &gt;20% 或持续增长</span> 可能泄漏或堆过大
            </p>
            <p><b>RSS vs VSZ</b>：RSS 是真实占用的物理内存；VSZ 是虚拟地址空间（含未映射/共享），通常 VSZ 远大于 RSS。</p>
            <p><b>常见场景</b>：</p>
            <ul class="load-guide-list">
                <li><b>Java</b>：-Xmx 过大、堆外/direct memory、Metaspace → <code>jmap -heap</code>、<code>jcmd &lt;pid&gt; VM.native_memory</code></li>
                <li><b>多个 Java 进程</b>：各自 4~6% 累加可能占满内存，需逐个看 -Xmx</li>
                <li><b>持续增长</b>：间隔多次 ps 对比 RSS，只升不降 → 疑似泄漏</li>
            </ul>
            <p>🔧 <code>ps -p &lt;pid&gt; -o rss,vsz,cmd</code> · <code>pmap -x &lt;pid&gt;</code>
            · Java <code>jmap -histo:live &lt;pid&gt;</code></p>
        </div>
    </details>'''


def render_mem_top_interpret_hint(rows: list[dict]) -> str:
    if not rows:
        return ""
    hints: list[str] = []
    top = rows[0]
    try:
        mem_val = float(top["mem"])
    except ValueError:
        return "➡️ 查看排行第一进程是否为预期业务"

    rss_kb = int(top.get("rss", 0) or 0)
    rss_gb = rss_kb / 1024 / 1024
    hints.append(f'Top1 {top["comm"]}(PID {top["pid"]}) %MEM {mem_val}% · RSS {rss_gb:.2f}G')

    high = [r for r in rows if float(r["mem"]) >= 10]
    if len(high) >= 3:
        hints.append(f"Top5 中 {len(high)} 个进程 %MEM≥10%，内存分散在多个进程")

    java_rows = [r for r in rows if "java" in r["comm"].lower()]
    if len(java_rows) >= 2:
        total_mem = sum(float(r["mem"]) for r in java_rows)
        hints.append(f"{len(java_rows)} 个 Java 进程合计约 {total_mem:.1f}% MEM")

    if mem_val < 10:
        hints.append("单进程占用不高，整体内存压力需结合「内存总览」判断")

    return " · ".join(hints)


def render_mem_top_high_guide(rows: list[dict]) -> str:
    hot = []
    for r in rows:
        try:
            mem_val = float(r["mem"])
        except ValueError:
            continue
        if mem_val >= 15:
            hot.append((r, mem_val, "red"))
        elif mem_val >= 10:
            hot.append((r, mem_val, "yellow"))
    if not hot:
        return ""
    level = "bad" if any(s == "red" for _, _, s in hot) else "warn"
    items = "".join(
        f'<li><b>{r["comm"]}</b> PID={r["pid"]} %MEM={v}% RSS={r.get("rss", "—")}KB</li>'
        for r, v, _ in hot
    )
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 高内存进程 · 排查指引</div>
        <div class="load-guide-body">
            <ul class="load-guide-list">{items}</ul>
            <ol class="load-guide-list">
                <li><b>确认是否持续增长</b>：间隔 5~10 分钟多次 <code>ps -p &lt;pid&gt; -o rss=</code>，RSS 只升不降 → 泄漏</li>
                <li><b>Java</b>：<code>jmap -heap &lt;pid&gt;</code> 看堆上限；<code>jstat -gcutil &lt;pid&gt; 1000</code> 看 GC</li>
                <li><b>内存映射</b>：<code>pmap -x &lt;pid&gt; | tail -1</code> 看 total RSS 构成</li>
                <li><b>处理</b>：调小 -Xmx / 重启泄漏进程 / 扩容 / 分实例部署</li>
            </ol>
        </div>
    </div>'''


def render_mem_top_block(content: str) -> tuple[str, str]:
    columns, rows = parse_ps_lines(content)
    if not rows:
        return render_ps_top_table(content)

    thead = "".join(f"<th>{escape_html(c)}</th>" for c in columns)
    tbody = ""
    for idx, r in enumerate(rows):
        cls = "alt" if idx % 2 == 0 else ""
        if "rss" in r:
            cells = [r["pid"], r["user"], r["cpu"], r["mem"], r["rss"], r["comm"]]
        else:
            cells = [r["pid"], r["user"], r["cpu"], r["mem"], r["comm"]]
        tds = "".join(f"<td>{escape_html(c)}</td>" for c in cells)
        tbody += f'<tr class="{cls}">{tds}</tr>'

    top = rows[0]
    summary = f'{top["comm"]} (PID {top["pid"]}) CPU {top["cpu"]}% MEM {top["mem"]}%'
    hint = render_mem_top_interpret_hint(rows)
    body = f'''
    <div class="card-body">
        <table class="tbl"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>
        {render_mem_top_stat_guide()}
        <div class="load-trend-hint">{hint}</div>
        {render_mem_top_high_guide(rows)}
    </div>'''
    return body, summary


def collect_memory_anomalies(blocks: list[dict]) -> list[tuple[str, str]]:
    anomalies: list[tuple[str, str]] = []
    for b in blocks:
        if b.get("_skip"):
            continue
        title, content = b["title"], b["content"]
        if title == "内存总览":
            data = parse_free_h(content)
            if data:
                mem = data["mem"]
                st, _, _ = mem_rate_status(mem["used_pct"], mem["avail_pct"])
                if st == "red":
                    anomalies.append((
                        "red",
                        f'available {mem["avail_pct"]:.1f}% 过低或 used {mem["used_pct"]:.1f}% 过高',
                    ))
                elif st == "yellow":
                    anomalies.append((
                        "yellow",
                        f'内存 used {mem["used_pct"]:.1f}% / available {mem["avail_pct"]:.1f}%，需关注',
                    ))
                if "swap" in data:
                    ss, _, _ = swap_rate_status(data["swap"]["used_pct"])
                    if ss == "red":
                        anomalies.append(("red", f'Swap 使用率 {data["swap"]["used_pct"]:.1f}% 过高'))
                    elif ss == "yellow" and data["swap"]["used_gb"] > 0:
                        anomalies.append(("yellow", f'Swap 已用 {data["swap"]["used"]}（{data["swap"]["used_pct"]:.1f}%）'))
        elif title == "Swap 状态":
            for r in parse_swapon(content):
                ss, _, _ = swap_rate_status(r["used_pct"])
                if ss == "red":
                    anomalies.append(("red", f'Swap {r["name"]} 已用 {r["used_pct"]:.1f}%'))
                elif ss == "yellow" and r["used_gb"] > 0:
                    anomalies.append(("yellow", f'Swap {r["name"]} 已用 {r["used"]}'))
        elif title == "高内存进程 Top 5":
            _, rows = parse_ps_lines(content)
            for r in rows[:3]:
                try:
                    mem_val = float(r["mem"])
                except ValueError:
                    continue
                if mem_val >= 20:
                    anomalies.append(("red", f'{r["comm"]}(PID {r["pid"]}) MEM {mem_val}% 过高'))
                elif mem_val >= 15:
                    anomalies.append(("yellow", f'{r["comm"]}(PID {r["pid"]}) MEM {mem_val}% 偏高'))
    return anomalies


def render_memory_anomaly_summary(anomalies: list[tuple[str, str]]) -> str:
    return render_cpu_anomaly_summary(anomalies)


# ═══════════════════════════════════════════════════════════════
#  磁盘模块：解析 / 说明 / 渲染（仅 df，无 du 扫描）
# ═══════════════════════════════════════════════════════════════

def disk_pct_status(pct: float) -> tuple[str, str, str]:
    if pct >= 90:
        return "red", "🔴", "危险"
    if pct >= 80:
        return "yellow", "🟡", "关注"
    return "green", "🟢", "正常"


def parse_df_lines(content: str, inode_mode: bool = False) -> list[dict]:
    """解析 df -hP / df -iP 输出"""
    rows: list[dict] = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line.lower().startswith("filesystem"):
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        mount = parts[-1]
        pct_str = parts[-2].rstrip("%")
        try:
            pct = float(pct_str)
        except ValueError:
            pct = 0.0
        if inode_mode:
            rows.append({
                "filesystem": parts[0],
                "inodes": parts[1],
                "iused": parts[2],
                "ifree": parts[3],
                "pct": pct,
                "mount": mount,
            })
        else:
            rows.append({
                "filesystem": parts[0],
                "size": parts[1],
                "used": parts[2],
                "avail": parts[3],
                "pct": pct,
                "mount": mount,
            })
    return rows


def is_df_output(content: str) -> bool:
    return bool(re.search(r"^\s*\S+\s+\S+\s+\S+\s+\S+\s+\d+%", content, re.MULTILINE))


def render_disk_usage_stat_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 磁盘使用率说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>df -hP</code> 的<strong>只读快照</strong>（读取文件系统元数据，不遍历目录），
            对服务器几乎无额外 IO 负担。</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>含义</th></tr>
                <tr><td><b>Filesystem</b></td><td>块设备 / LVM / 网络盘等</td></tr>
                <tr><td><b>Size</b></td><td>文件系统总容量</td></tr>
                <tr><td><b>Used</b></td><td>已用空间</td></tr>
                <tr><td><b>Avail</b></td><td>剩余可用（非 root 可见的可用量）</td></tr>
                <tr><td><b>Use%</b></td><td>已用百分比，<strong>核心关注指标</strong></td></tr>
                <tr><td><b>Mounted on</b></td><td>挂载点路径</td></tr>
            </table>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 &lt;80%</span> 正常 &nbsp;
                <span class="kb-tag tag-warn">🟡 80~90%</span> 建议清理 &nbsp;
                <span class="kb-tag tag-bad">🔴 ≥90%</span> 需立即处理，否则写入可能失败
            </p>
            <p><b>注意</b>：独立挂载的数据盘（如 <code>/data</code>）需单独看对应行；根分区 <code>/</code> 满不等于全盘满。</p>
            <p>🔧 目录级定位（<strong>手动</strong>，磁盘紧张时再跑）：<code>du -xsh /* 2>/dev/null | sort -rh | head</code></p>
        </div>
    </details>'''


def render_disk_usage_interpret_hint(rows: list[dict]) -> str:
    if not rows:
        return "➡️ 未解析到挂载点信息"
    hints: list[str] = []
    worst = max(rows, key=lambda r: r["pct"])
    root = next((r for r in rows if r["mount"] == "/"), None)
    hot = [r for r in rows if r["pct"] >= 80]
    if worst["pct"] < 50:
        hints.append(f"最高使用率 {worst['mount']} {worst['pct']:.0f}%，整体充裕")
    elif worst["pct"] >= 90:
        hints.append(f"{worst['mount']} 使用率 {worst['pct']:.0f}% 危险")
    elif worst["pct"] >= 80:
        hints.append(f"{worst['mount']} 使用率 {worst['pct']:.0f}% 需关注")
    if root and root["pct"] >= 80:
        hints.append(f"根分区 / 已用 {root['used']}/{root['size']}（{root['pct']:.0f}%）")
    if len(hot) > 1:
        hints.append(f"共 {len(hot)} 个挂载点 ≥80%")
    return " · ".join(hints) if hints else "➡️ 各挂载点空间使用正常"


def render_disk_usage_high_guide(rows: list[dict]) -> str:
    hot = [r for r in rows if disk_pct_status(r["pct"])[0] != "green"]
    if not hot:
        return ""
    level = "bad" if any(disk_pct_status(r["pct"])[0] == "red" for r in hot) else "warn"
    items = "".join(
        f'<li><b>{r["mount"]}</b> {r["used"]}/{r["size"]} ({r["pct"]:.0f}%) — {r["filesystem"]}</li>'
        for r in sorted(hot, key=lambda x: -x["pct"])
    )
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 磁盘空间紧张 · 排查指引</div>
        <div class="load-guide-body">
            <ul class="load-guide-list">{items}</ul>
            <ol class="load-guide-list">
                <li><b>确认趋势</b>：间隔多次 <code>df -hP /</code>，是否持续增长</li>
                <li><b>定位大目录</b>（手动，避免巡检脚本自动 du）：<code>du -xsh /* 2>/dev/null | sort -rh | head</code></li>
                <li><b>常见占用</b>：/var/log、/tmp、应用日志、core dump、Docker overlay</li>
                <li><b>清理</b>：logrotate、删旧日志/包缓存 <code>yum clean all</code>、归档冷数据</li>
                <li><b>扩容</b>：LVM 扩展、挂载新盘、迁移数据目录</li>
            </ol>
        </div>
    </div>'''


def render_disk_usage_block(content: str) -> tuple[str, str]:
    rows = parse_df_lines(content, inode_mode=False)
    if not rows:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            content.strip().split("\n")[0][:80] if content.strip() else "",
        )
    tbody = ""
    for r in rows:
        st, dot, _ = disk_pct_status(r["pct"])
        tbody += f'''<tr class="cpu-row cpu-{st}">
            <td>{escape_html(r["filesystem"])}</td>
            <td>{escape_html(r["size"])}</td><td>{escape_html(r["used"])}</td>
            <td>{escape_html(r["avail"])}</td>
            <td><b>{r["pct"]:.0f}%</b> {dot}</td>
            <td>{escape_html(r["mount"])}</td></tr>'''
    worst = max(rows, key=lambda r: r["pct"])
    summary = f'{len(rows)} 个挂载点 · 最高 {worst["mount"]} {worst["pct"]:.0f}%'
    body = f'''
    <div class="card-body">
        <table class="cpu-tbl">
            <thead><tr>
                <th>Filesystem</th><th>Size</th><th>Used</th><th>Avail</th><th>Use%</th><th>Mount</th>
            </tr></thead>
            <tbody>{tbody}</tbody>
        </table>
        {render_disk_usage_stat_guide()}
        <div class="load-trend-hint">{render_disk_usage_interpret_hint(rows)}</div>
        {render_disk_usage_high_guide(rows)}
    </div>'''
    return body, summary


def render_inode_stat_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 Inode 使用率说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>df -iP</code> 的<strong>只读快照</strong>。Inode 是文件的索引节点，
            <strong>每个文件/目录占用 1 个 inode</strong>（硬链接除外），与磁盘容量独立。</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>含义</th></tr>
                <tr><td><b>Inodes</b></td><td>inode 总数</td></tr>
                <tr><td><b>IUsed</b></td><td>已用 inode 数</td></tr>
                <tr><td><b>IFree</b></td><td>剩余 inode</td></tr>
                <tr><td><b>IUse%</b></td><td>已用百分比</td></tr>
            </table>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 &lt;80%</span> 正常 &nbsp;
                <span class="kb-tag tag-warn">🟡 80~90%</span> 关注 &nbsp;
                <span class="kb-tag tag-bad">🔴 ≥90%</span> 将无法创建新文件（即使还有磁盘空间）
            </p>
            <p><b>典型场景</b>：邮件队列小文件、session 文件、缓存目录、容器层大量小文件。</p>
            <p>🔧 定位目录（手动）：<code>find /path -xdev -type f | awk -F/ '{print NF}' | sort -n | tail</code>
            · 或 <code>ncdu</code> / 按目录统计文件数</p>
        </div>
    </details>'''


def render_inode_interpret_hint(rows: list[dict]) -> str:
    if not rows:
        return "➡️ 未解析到 inode 信息"
    worst = max(rows, key=lambda r: r["pct"])
    if worst["pct"] >= 90:
        return f'{worst["mount"]} inode {worst["pct"]:.0f}% 危险，无法创建新文件'
    if worst["pct"] >= 80:
        return f'{worst["mount"]} inode {worst["pct"]:.0f}% 需关注（IUsed {worst["iused"]}）'
    return f"各挂载点 inode 最高 {worst['pct']:.0f}%（{worst['mount']}），正常"


def render_inode_high_guide(rows: list[dict]) -> str:
    hot = [r for r in rows if disk_pct_status(r["pct"])[0] != "green"]
    if not hot:
        return ""
    level = "bad" if any(disk_pct_status(r["pct"])[0] == "red" for r in hot) else "warn"
    items = "".join(
        f'<li><b>{r["mount"]}</b> IUse {r["pct"]:.0f}% — IUsed {r["iused"]} / {r["inodes"]}</li>'
        for r in sorted(hot, key=lambda x: -x["pct"])
    )
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 Inode 紧张 · 排查指引</div>
        <div class="load-guide-body">
            <ul class="load-guide-list">{items}</ul>
            <ol class="load-guide-list">
                <li><b>找小文件密集目录</b>：mail/spool、/tmp、应用 cache、Docker</li>
                <li><b>统计</b>：<code>find /var/spool -xdev -type f | wc -l</code> 等</li>
                <li><b>清理</b>：过期 session、队列文件、临时文件；调整应用保留策略</li>
            </ol>
        </div>
    </div>'''


def render_inode_block(content: str) -> tuple[str, str]:
    rows = parse_df_lines(content, inode_mode=True)
    if not rows:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            content.strip().split("\n")[0][:80] if content.strip() else "",
        )
    tbody = ""
    for r in rows:
        st, dot, _ = disk_pct_status(r["pct"])
        tbody += f'''<tr class="cpu-row cpu-{st}">
            <td>{escape_html(r["filesystem"])}</td>
            <td>{escape_html(r["inodes"])}</td><td>{escape_html(r["iused"])}</td>
            <td>{escape_html(r["ifree"])}</td>
            <td><b>{r["pct"]:.0f}%</b> {dot}</td>
            <td>{escape_html(r["mount"])}</td></tr>'''
    worst = max(rows, key=lambda r: r["pct"])
    summary = f'最高 inode {worst["mount"]} {worst["pct"]:.0f}%'
    body = f'''
    <div class="card-body">
        <table class="cpu-tbl">
            <thead><tr>
                <th>Filesystem</th><th>Inodes</th><th>IUsed</th><th>IFree</th><th>IUse%</th><th>Mount</th>
            </tr></thead>
            <tbody>{tbody}</tbody>
        </table>
        {render_inode_stat_guide()}
        <div class="load-trend-hint">{render_inode_interpret_hint(rows)}</div>
        {render_inode_high_guide(rows)}
    </div>'''
    return body, summary


def render_disk_alert_stat_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 高使用率挂载点说明</summary>
        <div class="load-guide-body">
            <p>本卡片由 <code>df -hP</code> 筛选 <strong>Use% ≥ 50%</strong> 的挂载点，<b>不执行 du 目录扫描</b>，
            避免巡检对生产服务器产生额外磁盘 IO 与 CPU 开销。</p>
            <p><b>为何不用 du /</b>：<code>du</code> 需递归遍历目录下所有文件，大盘/深目录可能耗时数分钟并明显影响 IO。
            日常巡检以 <code>df</code> 只读元数据即可判断「是否紧张」。</p>
            <p><b>何时手动 du</b>：某挂载点 ≥80% 且需定位具体目录时，在业务低峰执行：</p>
            <ul class="load-guide-list">
                <li><code>du -xsh /* 2>/dev/null | sort -rh | head</code> — 仅当前文件系统一级目录</li>
                <li><code>du -xsh /var/* 2>/dev/null | sort -rh | head</code> — 深入单一路径</li>
                <li><code>-x</code> 不跨文件系统，避免重复统计挂载点</li>
            </ul>
        </div>
    </details>'''


def render_disk_alert_block(content: str) -> tuple[str, str]:
    text = content.strip()
    if not text or "无使用率" in text:
        hint = "🟢 无挂载点使用率 ≥50%，空间充裕"
        body = f'''
    <div class="card-body">
        <p style="padding:12px;color:{C["green"]};">{hint}</p>
        {render_disk_alert_stat_guide()}
        <div class="load-trend-hint">{hint}</div>
    </div>'''
        return body, "无 ≥50% 挂载点"

    if is_df_output(text):
        rows = parse_df_lines(text, inode_mode=False)
        if not rows:
            rows = []
        tbody = ""
        for r in rows:
            st, dot, _ = disk_pct_status(r["pct"])
            tbody += f'''<tr class="cpu-row cpu-{st}">
                <td>{escape_html(r["mount"])}</td>
                <td>{escape_html(r["used"])}/{escape_html(r["size"])}</td>
                <td><b>{r["pct"]:.0f}%</b> {dot}</td></tr>'''
        worst = max(rows, key=lambda r: r["pct"]) if rows else None
        summary = f'{len(rows)} 个 ≥50% · 最高 {worst["mount"]} {worst["pct"]:.0f}%' if worst else "高使用率挂载点"
        hint = render_disk_usage_interpret_hint(rows) if rows else ""
        body = f'''
    <div class="card-body">
        <table class="cpu-tbl">
            <thead><tr><th>Mount</th><th>Used/Size</th><th>Use%</th></tr></thead>
            <tbody>{tbody}</tbody>
        </table>
        {render_disk_alert_stat_guide()}
        <div class="load-trend-hint">{hint}</div>
        {render_disk_usage_high_guide(rows)}
    </div>'''
        return body, summary

    body = f'''
    <div class="card-body">
        <pre class="pre">{escape_html(text[:500])}</pre>
        {render_disk_alert_stat_guide()}
        <div class="load-trend-hint">➡️ 历史 du 数据；新巡检已改用 df 筛选，不再自动 du</div>
    </div>'''
    return body, text.split("\n")[0][:60]


def collect_disk_anomalies(blocks: list[dict]) -> list[tuple[str, str]]:
    anomalies: list[tuple[str, str]] = []
    for b in blocks:
        if b.get("_skip"):
            continue
        title, content = b["title"], b["content"]
        if title == "磁盘使用率":
            for r in parse_df_lines(content, False):
                st, _, _ = disk_pct_status(r["pct"])
                if st == "red":
                    anomalies.append(("red", f'{r["mount"]} 磁盘 {r["pct"]:.0f}% 已满'))
                elif st == "yellow":
                    anomalies.append(("yellow", f'{r["mount"]} 磁盘 {r["pct"]:.0f}% 偏高'))
        elif title == "Inode 使用率":
            for r in parse_df_lines(content, True):
                st, _, _ = disk_pct_status(r["pct"])
                if st == "red":
                    anomalies.append(("red", f'{r["mount"]} inode {r["pct"]:.0f}% 耗尽'))
                elif st == "yellow":
                    anomalies.append(("yellow", f'{r["mount"]} inode {r["pct"]:.0f}% 偏高'))
    return anomalies


def render_disk_anomaly_summary(anomalies: list[tuple[str, str]]) -> str:
    return render_cpu_anomaly_summary(anomalies)


# ═══════════════════════════════════════════════════════════════
#  进程模块：解析 / 说明 / 渲染
# ═══════════════════════════════════════════════════════════════

def parse_process_stats(content: str) -> dict | None:
    m = re.search(r"总数:\s*(\d+)\s*\|\s*运行中:\s*(\d+)\s*\|\s*僵尸:\s*(\d+)", content)
    if not m:
        return None
    return {"total": int(m.group(1)), "running": int(m.group(2)), "zombie": int(m.group(3))}


def zombie_status(count: int) -> tuple[str, str, str]:
    if count >= 10:
        return "red", "🔴", "异常"
    if count > 0:
        return "yellow", "🟡", "关注"
    return "green", "🟢", "正常"


def render_process_stats_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 进程统计说明</summary>
        <div class="load-guide-body">
            <p>数据来自远程 <code>ps</code> 命令的<strong>瞬时快照</strong>，反映采样时刻的进程概况。</p>
            <table class="load-ref-tbl">
                <tr><th>指标</th><th>含义</th></tr>
                <tr><td><b>总数</b></td><td><code>ps -e</code> 进程条目数（含内核线程、用户进程）</td></tr>
                <tr><td><b>运行中</b></td><td>STAT 以 <code>R</code> 开头的进程（正在 CPU 上运行或就绪）</td></tr>
                <tr><td><b>僵尸</b></td><td>STAT 含 <code>Z</code> 的僵尸进程数（已完成，等父进程回收）</td></tr>
            </table>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 僵尸 = 0</span> 正常 &nbsp;
                <span class="kb-tag tag-warn">🟡 1~9</span> 需关注父进程 &nbsp;
                <span class="kb-tag tag-bad">🔴 ≥10</span> 父进程 bug 或 systemd 异常
            </p>
            <p><b>僵尸进程</b>：不占 CPU/内存，但占用 PID；少量偶发可忽略，<strong>持续增长</strong>必须查父进程。</p>
            <p>🔧 <code>ps aux | awk '$8~/Z/'</code> · <code>ps -eo pid,ppid,stat,cmd | grep ' Z'</code>
            · 查父进程 <code>ps -fp &lt;ppid&gt;</code></p>
        </div>
    </details>'''


def render_process_stats_interpret_hint(data: dict) -> str:
    hints: list[str] = []
    zst, _, _ = zombie_status(data["zombie"])
    hints.append(f"进程总数 {data['total']}，运行中 {data['running']}")
    if data["zombie"] == 0:
        hints.append("无僵尸进程")
    elif zst == "red":
        hints.append(f"僵尸进程 {data['zombie']} 个，需立即排查")
    else:
        hints.append(f"僵尸进程 {data['zombie']} 个，建议查父进程")
    if data["total"] > 5000:
        hints.append("进程总数偏多，关注是否容器/线程泄漏")
    return " · ".join(hints)


def render_process_stats_high_guide(data: dict) -> str:
    zst, _, _ = zombie_status(data["zombie"])
    if zst == "green" and data["total"] <= 5000:
        return ""
    level = "bad" if zst == "red" else "warn"
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 进程异常 · 排查指引</div>
        <div class="load-guide-body">
            <p class="load-example">总数 {data["total"]} · 运行中 {data["running"]} · 僵尸 {data["zombie"]}</p>
            <ol class="load-guide-list">
                <li><b>僵尸进程</b>：查 PPID → <code>ps -fp &lt;ppid&gt;</code>，修复父进程 wait() 或重启父进程</li>
                <li><b>进程数过多</b>：容器节点查 <code>docker ps</code>；Java 查线程数 <code>ps -Lp &lt;pid&gt; | wc -l</code></li>
                <li><b>持续监控</b>：间隔多次采样，确认僵尸/总数是否增长</li>
            </ol>
        </div>
    </div>'''


def render_process_stats_block(content: str) -> tuple[str, str]:
    data = parse_process_stats(content)
    if not data:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            content.strip().split("\n")[0][:80] if content.strip() else "",
        )
    zst, zdot, zlabel = zombie_status(data["zombie"])
    body = f'''
    <div class="card-body">
        <div class="kv-card">
            <div class="kv-row"><span class="kv-key">进程总数</span><span class="kv-val">{data["total"]}</span></div>
            <div class="kv-row"><span class="kv-key">运行中 (R)</span><span class="kv-val">{data["running"]}</span></div>
            <div class="kv-row"><span class="kv-key">僵尸 (Z)</span><span class="kv-val">{data["zombie"]} {zdot}</span></div>
        </div>
        {render_process_stats_guide()}
        <div class="load-trend-hint">{render_process_stats_interpret_hint(data)}</div>
        {render_process_stats_high_guide(data)}
    </div>'''
    summary = f'总数: {data["total"]} | 运行中: {data["running"]} | 僵尸: {data["zombie"]}'
    return body, summary


def parse_zombie_lines(content: str) -> list[dict]:
    if "无僵尸进程" in content:
        return []
    rows = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line.upper().startswith("USER"):
            continue
        parts = line.split(None, 10)
        if len(parts) >= 11 and "Z" in parts[7]:
            rows.append({
                "user": parts[0], "pid": parts[1], "ppid": parts[2],
                "stat": parts[7], "cmd": parts[10],
            })
    return rows


def render_zombie_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 僵尸进程说明</summary>
        <div class="load-guide-body">
            <p><strong>僵尸进程 (Zombie)</strong>：子进程已退出，但父进程尚未调用 <code>wait()</code> 回收，
            内核保留 PID 和退出码。显示为 <code>&lt;defunct&gt;</code> 或 STAT 含 <code>Z</code>。</p>
            <p><b>特点</b>：不消耗 CPU/内存，但占用 PID；大量累积可能耗尽 PID 导致无法创建新进程。</p>
            <p><b>排查步骤</b>：</p>
            <ol class="load-guide-list">
                <li>记录僵尸 PID 与 PPID（父进程 ID）</li>
                <li><code>ps -fp &lt;ppid&gt;</code> 确认父进程是谁</li>
                <li>修复应用 bug 或重启/升级父进程；必要时 <code>kill -9 &lt;ppid&gt;</code>（谨慎）</li>
            </ol>
        </div>
    </details>'''


def render_zombie_block(content: str) -> tuple[str, str]:
    rows = parse_zombie_lines(content)
    if not rows:
        hint = "🟢 无僵尸进程，状态正常"
        body = f'''
    <div class="card-body">
        <p style="padding:12px;color:{C["green"]};">{hint}</p>
        {render_zombie_guide()}
        <div class="load-trend-hint">{hint}</div>
    </div>'''
        return body, "无僵尸进程"

    tbody = ""
    for r in rows:
        tbody += f'''<tr class="cpu-row cpu-yellow">
            <td>{escape_html(r["pid"])}</td><td>{escape_html(r["ppid"])}</td>
            <td>{escape_html(r["user"])}</td><td>{escape_html(r["stat"])}</td>
            <td>{escape_html(r["cmd"][:60])}</td></tr>'''
    body = f'''
    <div class="card-body">
        <table class="cpu-tbl">
            <thead><tr><th>PID</th><th>PPID</th><th>USER</th><th>STAT</th><th>COMMAND</th></tr></thead>
            <tbody>{tbody}</tbody>
        </table>
        {render_zombie_guide()}
        <div class="load-trend-hint">🟡 发现 {len(rows)} 个僵尸进程，请查 PPID 对应父进程</div>
        <div class="load-guide load-guide-warn">
            <div class="load-guide-title">🔍 僵尸进程 · 排查指引</div>
            <div class="load-guide-body">
                <ol class="load-guide-list">
                    <li>对每个 PPID 执行 <code>ps -fp &lt;ppid&gt;</code></li>
                    <li>若为 systemd 子进程，查 <code>journalctl -u &lt;service&gt;</code></li>
                    <li>持续新增 → 应用未正确 wait，需开发修复或重启父进程</li>
                </ol>
            </div>
        </div>
    </div>'''
    return body, f"{len(rows)} 个僵尸进程"


def collect_process_anomalies(blocks: list[dict]) -> list[tuple[str, str]]:
    anomalies: list[tuple[str, str]] = []
    for b in blocks:
        if b.get("_skip"):
            continue
        title, content = b["title"], b["content"]
        if title == "进程统计":
            data = parse_process_stats(content)
            if data:
                zst, _, _ = zombie_status(data["zombie"])
                if zst == "red":
                    anomalies.append(("red", f'僵尸进程 {data["zombie"]} 个'))
                elif zst == "yellow":
                    anomalies.append(("yellow", f'僵尸进程 {data["zombie"]} 个，需关注'))
        elif title == "僵尸进程详情":
            rows = parse_zombie_lines(content)
            if len(rows) >= 10:
                anomalies.append(("red", f"僵尸进程详情 {len(rows)} 条"))
            elif rows:
                anomalies.append(("yellow", f"存在 {len(rows)} 个僵尸进程"))
        elif title == "CPU Top 5":
            _, rows = parse_ps_lines(content)
            for r in rows[:2]:
                try:
                    if float(r["cpu"]) >= 100:
                        anomalies.append(("red", f'{r["comm"]}(PID {r["pid"]}) CPU {r["cpu"]}%'))
                    elif float(r["cpu"]) >= 70:
                        anomalies.append(("yellow", f'{r["comm"]}(PID {r["pid"]}) CPU {r["cpu"]}%'))
                except ValueError:
                    pass
        elif title == "内存 Top 5":
            _, rows = parse_ps_lines(content)
            for r in rows[:2]:
                try:
                    if float(r["mem"]) >= 20:
                        anomalies.append(("red", f'{r["comm"]}(PID {r["pid"]}) MEM {r["mem"]}%'))
                    elif float(r["mem"]) >= 15:
                        anomalies.append(("yellow", f'{r["comm"]}(PID {r["pid"]}) MEM {r["mem"]}%'))
                except ValueError:
                    pass
    return anomalies


def render_process_anomaly_summary(anomalies: list[tuple[str, str]]) -> str:
    return render_cpu_anomaly_summary(anomalies)


# ═══════════════════════════════════════════════════════════════
#  网络模块：解析 / 说明 / 渲染
# ═══════════════════════════════════════════════════════════════

def parse_ip_interfaces(content: str) -> list[dict]:
    interfaces: list[dict] = []
    current: dict | None = None
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\d+):\s+(\S+?):\s*<([^>]+)>", line)
        if m:
            if current:
                interfaces.append(current)
            flags = m.group(3)
            current = {
                "index": m.group(1), "name": m.group(2), "flags": flags,
                "addrs": [], "up": "UP" in flags, "loopback": "LOOPBACK" in flags,
            }
            continue
        if current:
            im = re.search(r"inet\s+(\S+)", line)
            if im:
                current["addrs"].append(im.group(1))
    if current:
        interfaces.append(current)
    return interfaces


def parse_ss_listen(content: str) -> list[dict]:
    rows: list[dict] = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line.startswith("LISTEN"):
            continue
        m = re.match(r"LISTEN\s+\S+\s+\S+\s+(\S+)\s+\S+(?:\s+(.*))?$", line)
        if not m:
            continue
        local = m.group(1)
        proc_raw = m.group(2) or ""
        proc_m = re.search(r'"([^"]+)"', proc_raw)
        proc = proc_m.group(1) if proc_m else "—"
        pid_m = re.search(r"pid=(\d+)", proc_raw)
        port = local.rsplit(":", 1)[-1] if ":" in local else local
        rows.append({
            "local": local, "port": port, "process": proc,
            "pid": pid_m.group(1) if pid_m else "",
        })
    return rows


def parse_conn_stats(content: str) -> dict | None:
    m = re.search(
        r"已建立:\s*(\d+)\s*\|\s*监听中:\s*(\d+)\s*\|\s*总连接:\s*(\d+)",
        content,
    )
    if not m:
        return None
    return {"estab": int(m.group(1)), "listen": int(m.group(2)), "total": int(m.group(3))}


def conn_estab_status(estab: int) -> tuple[str, str, str]:
    if estab >= 10000:
        return "red", "🔴", "异常"
    if estab >= 5000:
        return "yellow", "🟡", "关注"
    return "green", "🟢", "正常"


def render_network_iface_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 网络接口说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>ip -4 addr show</code> 的<strong>只读快照</strong>，列出 IPv4 地址绑定情况。</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>含义</th></tr>
                <tr><td><b>接口名</b></td><td>如 eth0、ens192、lo</td></tr>
                <tr><td><b>状态</b></td><td>UP=启用 · LOOPBACK=回环(127.0.0.1) · NO-CARRIER=网线未连接</td></tr>
                <tr><td><b>IPv4</b></td><td>CIDR 格式地址，如 172.28.243.181/24</td></tr>
            </table>
            <p><b>核对要点</b>：业务 IP 是否绑定在预期网卡；是否仅监听内网；lo 仅本机回环。</p>
            <p>🔧 <code>ip -4 addr</code> · <code>ip link show</code> · <code>ethtool eth0</code></p>
        </div>
    </details>'''


def render_network_iface_interpret_hint(ifaces: list[dict]) -> str:
    if not ifaces:
        return "➡️ 未解析到网络接口"
    hints: list[str] = []
    up = [i for i in ifaces if i["up"] and not i["loopback"]]
    for i in up:
        addrs = ", ".join(i["addrs"]) if i["addrs"] else "无 IPv4"
        hints.append(f'{i["name"]} {addrs}')
    down = [i for i in ifaces if not i["loopback"] and not i["up"]]
    if down:
        hints.append(f'{len(down)} 个非 lo 接口未 UP')
    return " · ".join(hints[:4]) if hints else "➡️ 仅 loopback 或无 IPv4 地址"


def render_network_iface_block(content: str) -> tuple[str, str]:
    ifaces = parse_ip_interfaces(content)
    if not ifaces:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            content.strip().split("\n")[0][:80] if content.strip() else "",
        )
    tbody = ""
    for i in ifaces:
        st = "green" if i["up"] or i["loopback"] else "yellow"
        dot = {"green": "🟢", "yellow": "🟡"}[st]
        addrs = ", ".join(i["addrs"]) if i["addrs"] else "—"
        flags_short = "UP" if i["up"] else "DOWN"
        if i["loopback"]:
            flags_short = "LOOPBACK"
        tbody += f'''<tr class="cpu-row cpu-{st}">
            <td><b>{escape_html(i["name"])}</b></td>
            <td>{flags_short} {dot}</td>
            <td>{escape_html(addrs)}</td></tr>'''
    primary = next((i for i in ifaces if i["up"] and not i["loopback"] and i["addrs"]), ifaces[0])
    addr0 = primary["addrs"][0] if primary.get("addrs") else "—"
    summary = f'{primary["name"]} {addr0}'
    body = f'''
    <div class="card-body">
        <table class="cpu-tbl">
            <thead><tr><th>接口</th><th>状态</th><th>IPv4</th></tr></thead>
            <tbody>{tbody}</tbody>
        </table>
        {render_network_iface_guide()}
        <div class="load-trend-hint">{render_network_iface_interpret_hint(ifaces)}</div>
    </div>'''
    return body, summary


def render_listen_ports_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 监听端口说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>ss -tlnp</code> 的<strong>瞬时快照</strong>：TCP 监听（<code>-tln</code>）+ 进程（<code>-p</code>）。</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>含义</th></tr>
                <tr><td><b>Local</b></td><td>绑定地址:端口；<code>*:80</code> 表示所有网卡；<code>127.0.0.1</code> 仅本机</td></tr>
                <tr><td><b>Port</b></td><td>端口号，对应服务入口</td></tr>
                <tr><td><b>Process</b></td><td>监听该端口的进程名与 PID</td></tr>
            </table>
            <p><b>安全核对</b>：22/SSH、80/443、3306、6379 等是否对公网暴露（<code>0.0.0.0</code> / <code>*</code>）；
            预期仅内网的服务应绑定具体 IP 或 127.0.0.1。</p>
            <p>🔧 <code>ss -tlnp</code> · <code>lsof -iTCP -sTCP:LISTEN</code></p>
        </div>
    </details>'''


def render_listen_ports_interpret_hint(rows: list[dict]) -> str:
    if not rows:
        return "➡️ 未检测到 TCP 监听端口"
    hints: list[str] = [f"共 {len(rows)} 个 TCP 监听端口"]
    wildcards = [r for r in rows if r["local"].startswith("*:") or r["local"].startswith("0.0.0.0:")]
    if wildcards:
        hints.append(f"{len(wildcards)} 个绑定所有网卡（*）")
    well_known = {"22": "SSH", "80": "HTTP", "443": "HTTPS", "3306": "MySQL", "6379": "Redis"}
    found = [well_known[r["port"]] for r in rows if r["port"] in well_known]
    if found:
        hints.append("含 " + "/".join(sorted(set(found))))
    return " · ".join(hints)


def render_listen_ports_block(content: str) -> tuple[str, str]:
    rows = parse_ss_listen(content)
    if not rows:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content[:2000])}</pre></div>',
            content.strip().split("\n")[0][:80] if content.strip() else "无监听",
        )
    rows_sorted = sorted(rows, key=lambda r: int(r["port"]) if r["port"].isdigit() else 99999)
    tbody = ""
    for r in rows_sorted:
        tbody += f'''<tr class="cpu-row cpu-green">
            <td>{escape_html(r["port"])}</td>
            <td>{escape_html(r["local"])}</td>
            <td>{escape_html(r["process"])}</td>
            <td>{escape_html(r["pid"])}</td></tr>'''
    summary = f"{len(rows)} 个监听端口"
    body = f'''
    <div class="card-body" style="max-height:420px;overflow-y:auto;">
        <table class="cpu-tbl">
            <thead><tr><th>Port</th><th>Local</th><th>Process</th><th>PID</th></tr></thead>
            <tbody>{tbody}</tbody>
        </table>
        {render_listen_ports_guide()}
        <div class="load-trend-hint">{render_listen_ports_interpret_hint(rows)}</div>
    </div>'''
    return body, summary


def render_conn_stats_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 连接统计说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>ss</code> 的<strong>瞬时统计</strong>，反映 TCP/UDP 连接概况。</p>
            <table class="load-ref-tbl">
                <tr><th>指标</th><th>含义</th></tr>
                <tr><td><b>已建立</b></td><td>ESTAB 状态连接数（活跃数据传输中）</td></tr>
                <tr><td><b>监听中</b></td><td>TCP LISTEN 端口数量</td></tr>
                <tr><td><b>总连接</b></td><td>所有 tcp/udp socket 条目（含 TIME_WAIT 等）</td></tr>
            </table>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 已建立 &lt;5000</span> 一般正常 &nbsp;
                <span class="kb-tag tag-warn">🟡 5000~10000</span> 关注 &nbsp;
                <span class="kb-tag tag-bad">🔴 ≥10000</span> 可能攻击或连接泄漏
            </p>
            <p><b>异常场景</b>：ESTAB 暴增 → SYN 洪水/CC 攻击/连接未关闭；需结合 <code>ss -s</code>、防火墙日志。</p>
            <p>🔧 <code>ss -s</code> · <code>ss -tan state established | wc -l</code>
            · <code>netstat -ant | awk '{print $6}' | sort | uniq -c</code></p>
        </div>
    </details>'''


def render_conn_stats_interpret_hint(data: dict) -> str:
    st, dot, label = conn_estab_status(data["estab"])
    hints = [
        f'已建立 {data["estab"]} {dot}',
        f'监听 {data["listen"]} · 总连接 {data["total"]}',
    ]
    if st != "green":
        hints.append(f"ESTAB 连接数{label}，建议 ss -s 进一步分析")
    elif data["estab"] < 500:
        hints.append("连接数正常")
    return " · ".join(hints)


def render_conn_stats_high_guide(data: dict) -> str:
    st, _, _ = conn_estab_status(data["estab"])
    if st == "green":
        return ""
    level = "bad" if st == "red" else "warn"
    return f'''
    <div class="load-guide load-guide-{level}">
        <div class="load-guide-title">🔍 连接数偏高 · 排查指引</div>
        <div class="load-guide-body">
            <p class="load-example">已建立 {data["estab"]} · 监听 {data["listen"]} · 总连接 {data["total"]}</p>
            <ol class="load-guide-list">
                <li><code>ss -s</code> 看 TCP 各状态分布（TIME_WAIT、SYN-RECV 等）</li>
                <li><code>ss -tan | awk '{{print $5}}' | sort | uniq -c | sort -rn | head</code> 看目标 IP 集中度</li>
                <li>应用连接池泄漏 → 查 Java/DB 连接池配置与 maxConnections</li>
                <li>疑似攻击 → 防火墙限流、WAF、查 nginx/access 日志</li>
            </ol>
        </div>
    </div>'''


def render_conn_stats_block(content: str) -> tuple[str, str]:
    data = parse_conn_stats(content)
    if not data:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            content.strip()[:80],
        )
    est_st, est_dot, est_label = conn_estab_status(data["estab"])
    body = f'''
    <div class="card-body">
        <div class="kv-card">
            <div class="kv-row"><span class="kv-key">已建立 (ESTAB)</span>
                <span class="kv-val">{data["estab"]} {est_dot}</span></div>
            <div class="kv-row"><span class="kv-key">监听中 (LISTEN)</span>
                <span class="kv-val">{data["listen"]}</span></div>
            <div class="kv-row"><span class="kv-key">总连接</span>
                <span class="kv-val">{data["total"]}</span></div>
        </div>
        {render_conn_stats_guide()}
        <div class="load-trend-hint">{render_conn_stats_interpret_hint(data)}</div>
        {render_conn_stats_high_guide(data)}
    </div>'''
    summary = f'已建立: {data["estab"]} | 监听中: {data["listen"]} | 总连接: {data["total"]}'
    return body, summary


def collect_network_anomalies(blocks: list[dict]) -> list[tuple[str, str]]:
    anomalies: list[tuple[str, str]] = []
    for b in blocks:
        if b.get("_skip"):
            continue
        title, content = b["title"], b["content"]
        if title == "连接统计":
            data = parse_conn_stats(content)
            if data:
                st, _, _ = conn_estab_status(data["estab"])
                if st == "red":
                    anomalies.append(("red", f'已建立连接 {data["estab"]} 过高'))
                elif st == "yellow":
                    anomalies.append(("yellow", f'已建立连接 {data["estab"]} 偏高'))
    return anomalies


def render_network_anomaly_summary(anomalies: list[tuple[str, str]]) -> str:
    return render_cpu_anomaly_summary(anomalies)


# ═══════════════════════════════════════════════════════════════
#  渲染
# ═══════════════════════════════════════════════════════════════

def is_free_output(content: str) -> bool:
    """检测是否为 free -h 输出（含 Mem:/Swap: 行）"""
    return bool(re.search(r"^\s*(Mem|Swap):\s+\d", content, re.MULTILINE))

def parse_mem_value(v: str) -> float:
    """将 '31G', '502M', '16M' 等转为 GB 单位浮点数"""
    m = re.match(r"([\d.]+)\s*([KMGT]?)", v, re.I)
    if not m:
        return 0.0
    num = float(m.group(1))
    unit = m.group(2).upper()
    multipliers = {"T": 1024, "G": 1, "M": 1/1024, "K": 1/1024**2, "": 1/1024**3}
    return num * multipliers.get(unit, 1)

def render_free_output(content: str) -> str:
    """将 free -h 输出渲染为纵向键值对卡片 + 顶部使用率进度条"""
    rows = ""
    mem_total_gb = 0.0
    mem_used_gb = 0.0
    swap_total_gb = 0.0
    swap_used_gb = 0.0

    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or re.match(r"^\s*total\b", line, re.I):
            continue
        m = re.match(r"^(Mem|Swap):\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(\S+))?(?:\s+(\S+))?(?:\s+(\S+))?", line)
        if not m:
            continue
        label = m.group(1)
        values = [g for g in m.groups()[1:] if g]
        if label == "Mem":
            keys = ["total", "used", "free", "shared", "buff/cache", "available"]
            mem_total_gb = parse_mem_value(values[0])
            mem_used_gb = parse_mem_value(values[1])
        else:
            keys = ["total", "used", "free"]
            swap_total_gb = parse_mem_value(values[0])
            swap_used_gb = parse_mem_value(values[1])

        for k, v in zip(keys, values):
            cls = ""
            if label == "Swap" and k == "used" and v not in ("0B", "0"):
                cls = "kv-warn"
            elif k == "used":
                cls = "kv-used"
            elif k == "available":
                cls = "kv-avail"
            elif k == "free" and label == "Mem":
                cls = "kv-dim"

            rows += f'''
            <div class="kv-row {cls}">
                <span class="kv-key">{label} {k}</span>
                <span class="kv-val">{escape_html(v)}</span>
            </div>'''

    # ── 使用率进度条 ──
    usage_html = ""
    if mem_total_gb > 0:
        mem_pct = mem_used_gb / mem_total_gb * 100
        swap_pct = swap_used_gb / swap_total_gb * 100 if swap_total_gb > 0 else 0

        def rate_status(pct: float, low: float, high: float):
            if pct >= high:
                return ("🔴", C["red"], "危险")
            elif pct >= low:
                return ("🟡", C["yellow"], "关注")
            return ("🟢", C["green"], "正常")

        mem_dot, mem_color, mem_label = rate_status(mem_pct, 80, 90)
        swap_dot, swap_color, swap_label = rate_status(swap_pct, 30, 60)

        usage_html = f'''
        <div class="mem-usage-bar">
            <div class="mem-usage-item">
                <div class="mem-usage-header">
                    <span>{mem_dot} 内存使用率 ({mem_pct:.1f}%)</span>
                    <span style="color:{mem_color};font-weight:600">{mem_label}</span>
                </div>
                <div class="bar-track">
                    <div class="bar-fill" style="width:{min(mem_pct, 100):.1f}%;background:{mem_color}"></div>
                </div>
            </div>
            <div class="mem-usage-item">
                <div class="mem-usage-header">
                    <span>{swap_dot} Swap 使用率 ({swap_pct:.1f}%)</span>
                    <span style="color:{swap_color};font-weight:600">{swap_label}</span>
                </div>
                <div class="bar-track">
                    <div class="bar-fill" style="width:{min(swap_pct, 100):.1f}%;background:{swap_color}"></div>
                </div>
            </div>
        </div>'''

    return usage_html + f'<div class="kv-card">{rows}</div>'

def render_metric_card(title: str, content: str, explanation: str, ctx: dict | None = None) -> str:
    """渲染单个指标卡片：标题 + 内容 + 通俗解释"""
    is_table = is_table_text(content)
    ctx = {} if ctx is None else ctx

    # ── 特殊：内存总览（free -h 输出）→ 纵向键值对卡片 + 使用率条 ──
    if "内存总览" in title and is_free_output(content):
        body, first_line = render_mem_overview_block(content)
    elif title == "Swap 状态":
        body, first_line = render_swap_block(content)
    elif title == "系统负载":
        body, first_line = render_load_block(content)
        load_data = parse_load_block(content)
        if load_data and load_data.get("cores"):
            ctx["cpu_cores"] = load_data["cores"]
    elif title == "CPU 使用率分布":
        body, first_line = render_cpu_usage_block(content)
    elif "mpstat" in title.lower() or "每核 CPU" in title:
        body, first_line = render_mpstat_block(content, ctx.get("cpu_cores", 0))
    elif title == "运行队列":
        body, first_line = render_vmstat_block(content, ctx.get("cpu_cores", 0))
    elif title == "CPU Top 5":
        body, first_line = render_cpu_top_block(content, ctx.get("cpu_cores", 0))
    elif title == "高内存进程 Top 5":
        body, first_line = render_mem_top_block(content)
    elif title == "磁盘使用率":
        body, first_line = render_disk_usage_block(content)
    elif title == "Inode 使用率":
        body, first_line = render_inode_block(content)
    elif title in ("高使用率挂载点", "根分区大目录 Top 5"):
        body, first_line = render_disk_alert_block(content)
    elif title == "进程统计":
        body, first_line = render_process_stats_block(content)
    elif title == "僵尸进程详情":
        body, first_line = render_zombie_block(content or "无僵尸进程")
    elif title == "内存 Top 5":
        body, first_line = render_mem_top_block(content)
    elif title == "网络接口 IP":
        body, first_line = render_network_iface_block(content)
    elif title == "监听端口":
        body, first_line = render_listen_ports_block(content)
    elif title == "连接统计":
        body, first_line = render_conn_stats_block(content)
    elif is_ps_output(content):
        body, first_line = render_ps_top_table(content)
    elif is_table:
        body = f'<div class="card-body">{text_to_table(content)}</div>'
        first_line = content.strip().split("\n")[0][:80]
    else:
        body = f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>'
        first_line = content.strip().split("\n")[0][:80]

    # 如果 explanation 包含 HTML 标签则直接渲染，否则转义
    if '<' in explanation and '>' in explanation:
        desc_html = explanation
    else:
        desc_html = escape_html(explanation)

    return f'''
    <div class="metric-card">
        <div class="metric-header">
            <span class="metric-title">{escape_html(title)}</span>
            <span class="metric-val">{escape_html(first_line)}</span>
        </div>
        {body}
        <div class="metric-desc">💡 {desc_html}</div>
    </div>
    '''


def render_module(key: str, blocks: list[dict]) -> str:
    """渲染单个检查模块的指标卡片内容"""
    kb = METRIC_KB.get(key, {})

    # 进程模块：固定顺序、异常汇总
    if key == "05_process":
        order_map = {t: i for i, t in enumerate(PROCESS_BLOCK_ORDER)}
        blocks = sorted(blocks, key=lambda b: order_map.get(b["title"], 99))

    # 网络模块：固定顺序、异常汇总
    if key == "06_network":
        order_map = {t: i for i, t in enumerate(NETWORK_BLOCK_ORDER)}
        blocks = sorted(blocks, key=lambda b: order_map.get(b["title"], 99))

    # 磁盘模块：固定顺序、异常汇总
    if key == "04_disk":
        order_map = {t: i for i, t in enumerate(DISK_BLOCK_ORDER)}
        blocks = sorted(blocks, key=lambda b: order_map.get(b["title"], 99))

    # 内存模块：合并「内存使用率」、固定顺序、异常汇总
    if key == "03_memory":
        for b in blocks:
            if b["title"] == "内存使用率":
                b["_skip"] = True
        order_map = {t: i for i, t in enumerate(MEMORY_BLOCK_ORDER)}
        blocks = sorted(blocks, key=lambda b: order_map.get(b["title"], 99))

    # CPU 模块：固定卡片展示顺序
    if key == "02_cpu":
        order_map = {t: i for i, t in enumerate(CPU_BLOCK_ORDER)}
        blocks = sorted(blocks, key=lambda b: order_map.get(b["title"], 99))

    cards = ""
    ctx: dict = {}

    # CPU / 内存模块：异常指标汇总
    anomaly_banner = ""
    if key == "02_cpu":
        anomaly_banner = render_cpu_anomaly_summary(collect_cpu_anomalies(blocks))
    elif key == "03_memory":
        anomaly_banner = render_memory_anomaly_summary(collect_memory_anomalies(blocks))
    elif key == "04_disk":
        anomaly_banner = render_disk_anomaly_summary(collect_disk_anomalies(blocks))
    elif key == "05_process":
        anomaly_banner = render_process_anomaly_summary(collect_process_anomalies(blocks))
    elif key == "06_network":
        anomaly_banner = render_network_anomaly_summary(collect_network_anomalies(blocks))

    for b in blocks:
        if b.get("_skip"):
            continue
        title = b["title"]
        content = b["content"]
        # 匹配知识库中的解释
        explanation = kb.get(title, "")
        if not explanation:
            # 模糊匹配
            for k, v in kb.items():
                if k in title or title in k:
                    explanation = v
                    break
        cards += render_metric_card(title, content, explanation, ctx)

    return f'''
    <div class="metrics-grid">{anomaly_banner}{cards}</div>
    '''


def guess_status(blocks: list[dict]) -> str:
    """根据内容推测模块状态"""
    full = " ".join(b["content"].lower() for b in blocks)
    if any(w in full for w in ["error", "failed", "defunct"]):
        return "red"
    for b in blocks:
        if b["title"] == "系统负载":
            load = parse_load_block(b["content"])
            if load and load["status"] == "red":
                return "red"
            if load and load["status"] == "yellow":
                return "yellow"
        if b["title"] == "CPU 使用率分布":
            cpu = parse_cpu_usage(b["content"])
            if cpu and cpu.get("id", 100) < 10:
                return "red"
            if cpu and cpu.get("id", 100) < 20:
                return "yellow"
        if b["title"] == "内存总览":
            data = parse_free_h(b["content"])
            if data:
                mem = data["mem"]
                st, _, _ = mem_rate_status(mem["used_pct"], mem["avail_pct"])
                if st == "red":
                    return "red"
                if st == "yellow":
                    return "yellow"
                if "swap" in data:
                    ss, _, _ = swap_rate_status(data["swap"]["used_pct"])
                    if ss == "red":
                        return "red"
                    if ss == "yellow":
                        return "yellow"
        if b["title"] == "磁盘使用率":
            for r in parse_df_lines(b["content"], False):
                st, _, _ = disk_pct_status(r["pct"])
                if st == "red":
                    return "red"
                if st == "yellow":
                    return "yellow"
        if b["title"] == "Inode 使用率":
            for r in parse_df_lines(b["content"], True):
                st, _, _ = disk_pct_status(r["pct"])
                if st == "red":
                    return "red"
                if st == "yellow":
                    return "yellow"
        if b["title"] == "进程统计":
            ps = parse_process_stats(b["content"])
            if ps:
                zst, _, _ = zombie_status(ps["zombie"])
                if zst == "red":
                    return "red"
                if zst == "yellow":
                    return "yellow"
        if b["title"] == "连接统计":
            conn = parse_conn_stats(b["content"])
            if conn:
                st, _, _ = conn_estab_status(conn["estab"])
                if st == "red":
                    return "red"
                if st == "yellow":
                    return "yellow"
    if any(w in full for w in ["warn", "warning", "high"]):
        return "yellow"
    return "green"


# ═══════════════════════════════════════════════════════════════
#  完整 HTML
# ═══════════════════════════════════════════════════════════════

CSS = '''<style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
        background: ''' + C["bg"] + ''';
        color: ''' + C["text"] + ''';
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        padding: 24px; max-width: 1100px; margin: 0 auto;
    }
    /* ── 头部 ── */
    .header {
        padding: 24px; border: 1px solid ''' + C["border"] + ''';
        border-radius: 10px; background: ''' + C["card"] + ''';
        margin-bottom: 24px;
        display: flex; justify-content: space-between; align-items: flex-start;
        flex-wrap: wrap; gap: 16px;
    }
    .header h1 { font-size: 22px; margin-bottom: 8px; }
    .header .info { color: ''' + C["dim"] + '''; font-size: 14px; line-height: 1.8; }
    .header .info b { color: ''' + C["text"] + '''; }
    .status-dot { font-size: 32px; }
    /* ── 模块 ── */
    .module {
        margin-bottom: 20px;
        border: 1px solid ''' + C["border"] + ''';
        border-radius: 10px; overflow: hidden;
    }
    .module-title {
        padding: 14px 18px; background: ''' + C["card"] + ''';
        font-size: 15px; font-weight: 600; border-bottom: 1px solid ''' + C["border"] + ''';
    }
    .metrics-grid {
        padding: 12px;
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(480px, 1fr));
        gap: 10px;
    }
    /* ── 指标卡片 ── */
    .metric-card {
        background: ''' + C["card"] + ''';
        border: 1px solid ''' + C["border"] + ''';
        border-radius: 8px; overflow: hidden;
    }
    .metric-header {
        padding: 10px 14px;
        background: ''' + C["pre_bg"] + ''';
        display: flex; justify-content: space-between; align-items: center;
        gap: 12px; border-bottom: 1px solid ''' + C["border"] + ''';
    }
    .metric-title {
        font-size: 13px; font-weight: 600; color: ''' + C["accent"] + ''';
        white-space: nowrap;
    }
    .metric-val {
        font-size: 12px; color: ''' + C["dim"] + ''';
        text-align: right; overflow: hidden; text-overflow: ellipsis;
        white-space: nowrap; max-width: 280px;
    }
    .card-body { padding: 8px 14px; }
    .metric-desc {
        padding: 8px 14px;
        font-size: 12px; color: ''' + C["dim"] + ''';
        line-height: 1.6; border-top: 1px solid ''' + C["border"] + ''';
        background: ''' + C["pre_bg"] + ''';
    }
    /* ── 知识库 ── */
    .kb-section { margin-bottom: 8px; }
    .kb-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 6px;
    }
    .kb-item {
        background: ''' + C["card"] + ''';
        border: 1px solid ''' + C["border"] + ''';
        border-radius: 6px; padding: 8px 10px;
        font-size: 11.5px; line-height: 1.6;
    }
    .kb-tag {
        display: inline-block; padding: 1px 6px; border-radius: 3px;
        font-size: 10.5px; font-weight: 600; margin-right: 4px;
    }
    .kb-tag.tag-good { background: #1a3a1a; color: ''' + C["green"] + '''; }
    .kb-tag.tag-warn { background: #3a2e1a; color: ''' + C["yellow"] + '''; }
    .kb-tag.tag-bad  { background: #3a1a1a; color: ''' + C["red"] + '''; }
    .kb-tag.tag-dim  { background: #21262d; color: ''' + C["dim"] + '''; }
    /* ── CPU 指标明细表格 ── */
    .cpu-tbl {
        width: 100%; border-collapse: collapse; font-size: 12px;
    }
    .cpu-tbl th {
        background: ''' + C["th_bg"] + ''';
        color: ''' + C["dim"] + ''';
        padding: 7px 10px; font-size: 11px; font-weight: 500;
        text-align: left; border-bottom: 2px solid ''' + C["border"] + ''';
    }
    .cpu-tbl td { padding: 8px 10px; border-bottom: 1px solid ''' + C["border"] + '''; }
    .cpu-row        { background: ''' + C["row"] + '''; }
    .cpu-row:hover  { background: ''' + C["th_bg"] + '''; }
    .cpu-row.cpu-green  { border-left: 3px solid ''' + C["green"] + '''; }
    .cpu-row.cpu-yellow { border-left: 3px solid ''' + C["yellow"] + '''; }
    .cpu-row.cpu-red    { border-left: 3px solid ''' + C["red"] + '''; }
    .cpu-col-name b { color: ''' + C["text"] + '''; font-size: 13px; display: block; }
    .cpu-col-key   { font-size: 10px; color: ''' + C["dim"] + '''; }
    .cpu-col-val   { font-size: 16px; font-weight: 700; color: ''' + C["text"] + '''; white-space: nowrap; }
    .cpu-col-pct   { font-size: 11px; color: ''' + C["dim"] + '''; font-weight: 400; }
    .cpu-col-light { font-size: 16px; text-align: center; }
    .cpu-col-desc  { color: ''' + C["dim"] + '''; font-size: 11.5px; }
    .cpu-col-thresh { font-size: 10.5px; white-space: nowrap; }
    .thresh-good   { color: ''' + C["green"] + '''; }
    .thresh-warn   { color: ''' + C["yellow"] + '''; }
    .thresh-danger { color: ''' + C["red"] + '''; }
    .cpu-col-fix   { color: ''' + C["dim"] + '''; font-size: 11px; line-height: 1.5; }
    /* 窄屏时 CPU 表格横向滚动 */
    .card-body { overflow-x: auto; }
    /* ── CPU 异常指标汇总 ── */
    .cpu-anomaly-banner {
        grid-column: 1 / -1;
        padding: 14px 18px;
        border: 1px solid ''' + C["border"] + ''';
        border-radius: 8px;
        background: ''' + C["card"] + ''';
        margin-bottom: 4px;
    }
    .cpu-anomaly-ok { border-left: 3px solid ''' + C["green"] + '''; }
    .cpu-anomaly-warn { border-left: 3px solid ''' + C["yellow"] + '''; }
    .cpu-anomaly-red { border-left: 3px solid ''' + C["red"] + '''; }
    .cpu-anomaly-title {
        font-size: 13px; font-weight: 600; color: ''' + C["accent"] + ''';
        margin-bottom: 8px;
    }
    .cpu-anomaly-none {
        font-size: 13px; color: ''' + C["green"] + ''';
    }
    .cpu-anomaly-list {
        list-style: none; padding: 0; margin: 0;
        font-size: 12.5px; line-height: 1.8;
    }
    .cpu-anomaly-list li { padding: 2px 0; }
    .cpu-anomaly-li-red { color: ''' + C["red"] + '''; }
    .cpu-anomaly-li-yellow { color: ''' + C["yellow"] + '''; }
    /* ── Load 说明与排查指引 ── */
    .load-guide {
        margin-bottom: 12px;
        padding: 12px 14px;
        border: 1px solid ''' + C["border"] + ''';
        border-radius: 8px;
        font-size: 12.5px;
        line-height: 1.7;
    }
    .load-guide-info {
        background: ''' + C["pre_bg"] + ''';
        border-left: 3px solid ''' + C["accent"] + ''';
    }
    .load-guide-warn {
        background: ''' + C["pre_bg"] + ''';
        border-left: 3px solid ''' + C["yellow"] + ''';
    }
    .load-guide-bad {
        background: ''' + C["pre_bg"] + ''';
        border-left: 3px solid ''' + C["red"] + ''';
    }
    .load-guide-title {
        font-size: 13px;
        font-weight: 600;
        color: ''' + C["accent"] + ''';
        margin-bottom: 8px;
    }
    .load-guide-collapsible {
        margin-top: 10px;
        margin-bottom: 0;
    }
    .load-guide-collapsible > summary.load-guide-title {
        cursor: pointer;
        list-style: none;
        margin-bottom: 0;
        user-select: none;
    }
    .load-guide-collapsible > summary.load-guide-title::-webkit-details-marker {
        display: none;
    }
    .load-guide-collapsible > summary.load-guide-title::before {
        content: "▸ ";
        display: inline-block;
        width: 1em;
        color: ''' + C["dim"] + ''';
    }
    .load-guide-collapsible[open] > summary.load-guide-title::before {
        content: "▾ ";
    }
    .load-guide-collapsible[open] > summary.load-guide-title {
        margin-bottom: 8px;
    }
    .load-guide-collapsible > .load-guide-body {
        padding-top: 2px;
    }
    .load-guide-body p { margin: 6px 0; color: ''' + C["text"] + '''; }
    .load-guide-body code {
        background: ''' + C["card"] + ''';
        padding: 1px 5px;
        border-radius: 3px;
        font-size: 11.5px;
        color: ''' + C["accent"] + ''';
    }
    .load-ref-tbl {
        width: 100%;
        border-collapse: collapse;
        margin: 8px 0;
        font-size: 12px;
    }
    .load-ref-tbl th, .load-ref-tbl td {
        padding: 6px 10px;
        border: 1px solid ''' + C["border"] + ''';
        text-align: left;
    }
    .load-ref-tbl th {
        background: ''' + C["th_bg"] + ''';
        color: ''' + C["dim"] + ''';
        font-weight: 500;
    }
    .load-thresh { margin-top: 8px; }
    .load-trend-hint {
        margin-top: 10px;
        padding: 8px 12px;
        background: ''' + C["pre_bg"] + ''';
        border-radius: 6px;
        font-size: 12px;
        color: ''' + C["dim"] + ''';
    }
    .load-guide-list {
        margin: 6px 0 0 18px;
        color: ''' + C["text"] + ''';
    }
    .load-guide-list li { margin: 8px 0; }
    .load-guide-list ul {
        margin: 4px 0 0 16px;
        list-style: disc;
    }
    .load-example {
        padding: 6px 10px;
        background: ''' + C["card"] + ''';
        border-radius: 4px;
        margin-bottom: 8px;
        color: ''' + C["dim"] + ''';
    }
    /* ── 表格 ── */
    .tbl {
        width: 100%; border-collapse: collapse; font-size: 12px;
    }
    .tbl th {
        background: ''' + C["th_bg"] + ''';
        color: ''' + C["dim"] + ''';
        padding: 6px 10px; text-align: left;
        border: 1px solid ''' + C["border"] + ''';
        font-weight: 500; font-size: 11px; text-transform: uppercase;
    }
    .tbl td {
        padding: 5px 10px; border: 1px solid ''' + C["border"] + ''';
        color: ''' + C["text"] + ''';
    }
    .tbl tr { background: ''' + C["row"] + '''; }
    .tbl tr.alt { background: ''' + C["row_alt"] + '''; }
    /* ── Pre ── */
    .pre {
        background: ''' + C["pre_bg"] + ''';
        color: ''' + C["text"] + ''';
        padding: 10px; border-radius: 6px;
        font-size: 13px; line-height: 1.5;
        white-space: pre-wrap; word-break: break-all;
        overflow-x: auto; max-height: 300px; overflow-y: auto;
    }
    /* ── 内存使用率进度条 ── */
    .mem-usage-bar {
        padding: 8px 14px; display: flex; gap: 16px;
        border-bottom: 1px solid ''' + C["border"] + ''';
        background: ''' + C["pre_bg"] + ''';
    }
    .mem-usage-item {
        flex: 1; min-width: 0;
    }
    .mem-usage-header {
        display: flex; justify-content: space-between; align-items: center;
        font-size: 12px; margin-bottom: 5px;
    }
    .bar-track {
        width: 100%; height: 8px; background: ''' + C["bg"] + ''';
        border-radius: 4px; overflow: hidden;
    }
    .bar-fill {
        height: 100%; border-radius: 4px; transition: width 0.4s ease;
    }
    /* ── 内存纵向键值对卡片 ── */
    .kv-card {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 4px 16px;
    }
    .kv-row {
        display: flex; justify-content: space-between; align-items: center;
        padding: 6px 0; border-bottom: 1px solid ''' + C["border"] + ''';
    }
    .kv-key {
        font-size: 12px; color: ''' + C["dim"] + ''';
    }
    .kv-val {
        font-size: 14px; font-weight: 600; color: ''' + C["text"] + ''';
        font-variant-numeric: tabular-nums;
    }
    .kv-used .kv-val { color: ''' + C["accent"] + '''; }
    .kv-avail .kv-val { color: ''' + C["green"] + '''; }
    .kv-warn .kv-val { color: ''' + C["yellow"] + '''; }
    .kv-dim  .kv-val { color: ''' + C["dim"] + '''; }
    /* ── 页脚 ── */
    .footer {
        text-align: center; color: ''' + C["dim"] + ''';
        font-size: 12px; margin-top: 32px; padding-top: 16px;
        border-top: 1px solid ''' + C["border"] + ''';
    }
    /* ── Tab 页 ── */
    .tab-container {
        border: 1px solid ''' + C["border"] + ''';
        border-radius: 10px;
        overflow: hidden;
        background: ''' + C["card"] + ''';
        margin-bottom: 20px;
    }
    .tab-nav {
        display: flex;
        flex-wrap: wrap;
        gap: 0;
        border-bottom: 1px solid ''' + C["border"] + ''';
        background: ''' + C["pre_bg"] + ''';
        overflow-x: auto;
    }
    .tab-btn {
        padding: 12px 18px;
        border: none;
        background: transparent;
        color: ''' + C["dim"] + ''';
        cursor: pointer;
        font-size: 14px;
        font-family: inherit;
        border-bottom: 2px solid transparent;
        white-space: nowrap;
        transition: color 0.15s, background 0.15s;
    }
    .tab-btn:hover {
        color: ''' + C["text"] + ''';
        background: ''' + C["card"] + ''';
    }
    .tab-btn.active {
        color: ''' + C["accent"] + ''';
        border-bottom-color: ''' + C["accent"] + ''';
        background: ''' + C["card"] + ''';
        font-weight: 600;
    }
    .tab-status {
        font-size: 10px;
        margin-left: 4px;
        vertical-align: middle;
    }
    .tab-panels { background: ''' + C["card"] + '''; }
    .tab-panel {
        display: none;
        padding: 12px;
        animation: tabFadeIn 0.2s ease;
    }
    .tab-panel.active { display: block; }
    @keyframes tabFadeIn {
        from { opacity: 0; }
        to   { opacity: 1; }
    }
</style>'''

TAB_JS = '''<script>
(function() {
    var btns = document.querySelectorAll(".tab-btn");
    var panels = document.querySelectorAll(".tab-panel");
    btns.forEach(function(btn) {
        btn.addEventListener("click", function() {
            var id = btn.getAttribute("data-tab");
            btns.forEach(function(b) { b.classList.remove("active"); });
            panels.forEach(function(p) { p.classList.remove("active"); });
            btn.classList.add("active");
            var panel = document.getElementById(id);
            if (panel) panel.classList.add("active");
        });
    });
})();
</script>'''


def module_tab_label(key: str, status: str) -> tuple[str, str]:
    """返回 (tab_id, 显示标签)"""
    icon, name = MODULE_NAMES.get(key, ("📋", key.replace("_", " ")))
    dot_color = {"green": C["green"], "yellow": C["yellow"], "red": C["red"]}.get(status, C["dim"])
    label = f'{icon} {name} <span class="tab-status" style="color:{dot_color}">●</span>'
    return f"tab-{key}", label


def render_tabs(modules: list[dict]) -> str:
    """将各检查模块渲染为 Tab 页"""
    if not modules:
        return ""

    if len(modules) == 1:
        m = modules[0]
        return f'<div class="tab-container tab-single">{render_module(m["key"], m["blocks"])}</div>'

    nav_btns = ""
    panels = ""
    for i, m in enumerate(modules):
        tab_id, label = module_tab_label(m["key"], m["status"])
        active = " active" if i == 0 else ""
        nav_btns += f'<button type="button" class="tab-btn{active}" data-tab="{tab_id}">{label}</button>'
        panels += f'<div class="tab-panel{active}" id="{tab_id}">{render_module(m["key"], m["blocks"])}</div>'

    return f'''
<div class="tab-container">
    <div class="tab-nav">{nav_btns}</div>
    <div class="tab-panels">{panels}</div>
</div>'''


def build_html(server_ip: str, hostname: str, check_time: str, modules: list[dict]) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 状态统计
    n_g = sum(1 for m in modules if m["status"] == "green")
    n_y = sum(1 for m in modules if m["status"] == "yellow")
    n_r = sum(1 for m in modules if m["status"] == "red")
    dot_color = C["red"] if n_r > 0 else (C["yellow"] if n_y > 0 else C["green"])

    modules_html = render_tabs(modules)
    tab_hint = "点击 Tab 切换各模块" if len(modules) > 1 else ""

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>服务器巡检报告 - {server_ip}</title>
{CSS}
</head>
<body>

<div class="header">
    <div>
        <h1>🖥️ 服务器巡检报告</h1>
        <div class="info">
            <div>📍 服务器：<b>{server_ip}</b></div>
            <div>🏷️ 主机名：{hostname}</div>
            <div>🕐 检查时间：{check_time}</div>
            <div>📝 报告生成：{now_str}</div>
        </div>
    </div>
    <div style="text-align:right;">
        <div class="status-dot" style="color:{dot_color};">●</div>
        <div style="font-size:12px;color:{C["dim"]};margin-top:4px;">
            正常 {n_g} / 警告 {n_y} / 异常 {n_r}
        </div>
    </div>
</div>

<div style="margin-bottom:16px;color:{C["dim"]};font-size:13px;">
    📊 共 {len(modules)} 个检查模块 · {tab_hint} · Tab 旁 ● 表示模块状态（绿/黄/红）
</div>

{modules_html}

<div class="footer">
    由 JumpServer Monitor Skill 生成 · {now_str}
</div>

{TAB_JS}
</body>
</html>'''


# ═══════════════════════════════════════════════════════════════
def main():
    if len(sys.argv) < 3:
        print("用法: python3 gen_html.py <input_dir> <output_html>")
        sys.exit(1)

    input_dir = sys.argv[1]
    output_html = sys.argv[2]

    # 元数据
    meta_path = os.path.join(input_dir, "metadata.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

    server_ip  = meta.get("server_ip", "未知")
    hostname   = meta.get("hostname", "未知")
    check_time = meta.get("check_time", "-")

    # 模块数据
    modules = []
    txt_files = sorted([f for f in os.listdir(input_dir)
                        if f.startswith("module_") and f.endswith(".txt")])

    for tf in txt_files:
        key = tf[len("module_"):-len(".txt")]
        with open(os.path.join(input_dir, tf), "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        text = strip_decorations(text)
        blocks = parse_blocks(text)
        status = guess_status(blocks)
        modules.append({"key": key, "status": status, "blocks": blocks})

    if not modules:
        modules.append({
            "key": "_empty", "status": "yellow",
            "blocks": [{"title": "", "content": "(未找到模块输出，请检查连接)"}],
        })

    html = build_html(server_ip, hostname, check_time, modules)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] HTML 报告已生成: {output_html}")


if __name__ == "__main__":
    main()
