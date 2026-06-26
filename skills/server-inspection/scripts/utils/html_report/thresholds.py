"""阈值、配色、指标知识库与状态判定。"""

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
            "来自 <code>ps</code> 的<strong>瞬时快照</strong>，统计进程总数、运行(R)、睡眠(S)、D 状态、僵尸(Z)数量。"
            "详细状态说明与排查步骤见上方卡片内指引。"
        ),
        "D 状态进程": (
            "列出当前 <strong>D 状态（不可中断睡眠）</strong>进程，通常卡在等磁盘/存储 IO。"
            "详细含义与排查见上方卡片内指引。"
        ),
        "僵尸进程详情": (
            "列出当前所有 <strong>Z 状态（僵尸）</strong>进程；无则显示正常。"
            "详细含义与父进程排查见上方卡片内指引。"
        ),
        "CPU Top 5": (
            "来自 <code>ps --sort=-%cpu</code> 的<strong>瞬时排行</strong>（进程模块视角）。"
            "sshd 偏高可能为本次 SSH 巡检所致；详细排查见上方卡片内指引。"
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
            "来自 <code>ss -tlnp</code> / <code>netstat -tlnp</code> 的<strong>瞬时快照</strong>。"
            "缺 Process/PID 时才会尝试 <code>sudo -i</code> 提权；已有进程信息则不会提权。"
        ),
        "连接统计": (
            "来自 <code>ss</code> 的<strong>瞬时统计</strong>：ESTAB、LISTEN、TIME_WAIT、总连接数。"
            "详细含义与异常排查见上方卡片内指引。"
        ),
        "连接状态摘要": (
            "来自 <code>ss -s</code> 的内核级 socket 统计摘要，含 TCP 各状态分布与传输层计数。"
            "详细指标说明见上方表格内指引。"
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
    "D 状态进程",
    "僵尸进程详情",
    "CPU Top 5",
    "内存 Top 5",
]

NETWORK_BLOCK_ORDER = [
    "网络接口 IP",
    "连接统计",
    "连接状态摘要",
    "监听端口",
]

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

def disk_pct_status(pct: float) -> tuple[str, str, str]:
    if pct >= 90:
        return "red", "🔴", "危险"
    if pct >= 80:
        return "yellow", "🟡", "关注"
    return "green", "🟢", "正常"

def zombie_status(count: int) -> tuple[str, str, str]:
    if count >= 10:
        return "red", "🔴", "异常"
    if count > 0:
        return "yellow", "🟡", "关注"
    return "green", "🟢", "正常"

RISKY_PORTS = {"3306": "MySQL", "6379": "Redis", "9200": "Elasticsearch",
               "27017": "MongoDB", "5432": "PostgreSQL", "11211": "Memcached"}

def conn_estab_status(estab: int) -> tuple[str, str, str]:
    if estab >= 10000:
        return "red", "🔴", "异常"
    if estab >= 5000:
        return "yellow", "🟡", "关注"
    return "green", "🟢", "正常"

