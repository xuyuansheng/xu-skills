"""HTML 指标卡片与完整报告渲染。"""
from __future__ import annotations

import os
import re
from datetime import datetime

from .parsers import (
    collect_cpu_anomalies,
    collect_disk_anomalies,
    collect_memory_anomalies,
    collect_network_anomalies,
    collect_process_anomalies,
    consolidate_listen_ports,
    is_collection_failed,
    is_df_output,
    is_free_output,
    is_ps_output,
    is_table_text,
    parse_conn_stats,
    parse_cpu_usage,
    parse_df_lines,
    parse_dstate_lines,
    parse_free_h,
    parse_ip_interfaces,
    parse_listen_ports,
    parse_load_block,
    parse_mem_value,
    parse_mpstat,
    parse_process_stats,
    parse_ps_lines,
    parse_ss_summary,
    parse_swapon,
    parse_vmstat,
    parse_zombie_lines,
    shorten_service_cmd,
)
from .templates import load_css, load_tab_js
from .thresholds import (
    C,
    CPU_BLOCK_ORDER,
    CPU_METRICS,
    DISK_BLOCK_ORDER,
    MEMORY_BLOCK_ORDER,
    METRIC_KB,
    MODULE_NAMES,
    MPSTAT_COLUMNS,
    NETWORK_BLOCK_ORDER,
    PROCESS_BLOCK_ORDER,
    RISKY_PORTS,
    conn_estab_status,
    cpu_status_light,
    disk_pct_status,
    load_trend_hint,
    mem_rate_status,
    swap_rate_status,
    vmstat_b_status,
    vmstat_cs_status,
    vmstat_r_status,
    zombie_status,
)

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

def render_cpu_top_interpret_hint(rows: list[dict], cores: int = 0, service_cmd: bool = False) -> str:
    """根据 CPU Top 5 给出解读提示"""
    if not rows:
        return ""
    top = rows[0]
    hints: list[str] = []
    try:
        cpu_val = float(top["cpu"])
    except ValueError:
        return "➡️ 查看排行第一进程是否为本机预期业务"

    comm = shorten_service_cmd(top["comm"]) if service_cmd else top["comm"]
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

def render_cpu_top_block(content: str, cores: int = 0, service_cmd: bool = False) -> tuple[str, str]:
    """渲染 CPU Top 5 卡片（含详细说明）"""
    columns, rows = parse_ps_lines(content)
    if not rows:
        return render_ps_top_table(content)

    if service_cmd and columns:
        columns = list(columns)
        for i, c in enumerate(columns):
            if c in ("COMMAND", "服务/命令"):
                columns[i] = "服务/命令"

    thead = "".join(f"<th>{escape_html(c)}</th>" for c in columns)
    tbody = ""
    for idx, r in enumerate(rows):
        cls = "alt" if idx % 2 == 0 else ""
        cmd_raw = r["comm"]
        cmd_show = shorten_service_cmd(cmd_raw) if service_cmd else cmd_raw
        tip = f' title="{escape_html(cmd_raw)}"' if service_cmd and cmd_raw != cmd_show else ""
        if "rss" in r:
            cells = [r["pid"], r["user"], r["cpu"], r["mem"], r["rss"]]
            tds = "".join(f"<td>{escape_html(c)}</td>" for c in cells)
            tds += f'<td{tip} style="max-width:420px;word-break:break-all;">{escape_html(cmd_show)}</td>'
        else:
            cells = [r["pid"], r["user"], r["cpu"], r["mem"]]
            tds = "".join(f"<td>{escape_html(c)}</td>" for c in cells)
            tds += f'<td{tip} style="max-width:420px;word-break:break-all;">{escape_html(cmd_show)}</td>'
        tbody += f'<tr class="{cls}">{tds}</tr>'

    top = rows[0]
    top_label = shorten_service_cmd(top["comm"]) if service_cmd else top["comm"]
    summary = f'{top_label} (PID {top["pid"]}) CPU {top["cpu"]}% MEM {top["mem"]}%'
    hint = render_cpu_top_interpret_hint(rows, cores, service_cmd)
    guide = render_process_cpu_top_guide(cores) if service_cmd else render_cpu_top_stat_guide(cores)
    body = f'''
    <div class="card-body">
        <table class="tbl"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>
        {guide}
        <div class="load-trend-hint">{hint}</div>
        {render_cpu_top_high_guide(rows, cores)}
    </div>'''
    return body, summary

def render_process_cpu_top_guide(cores: int = 0) -> str:
    cores_note = (
        f"本机 <b>{cores} 核</b>，单进程 %CPU 理论最大约 <b>{cores * 100}%</b>。"
        if cores else "多核机器上 %CPU 为多核累计值。"
    )
    return f'''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 CPU Top 5 说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>ps args</code> 完整命令行，<strong>服务/命令</strong>列展示可识别服务名
            （Java 会提取 jar/主类；鼠标悬停可看完整命令）。{cores_note}</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>含义</th></tr>
                <tr><td><b>PID</b></td><td>进程 ID</td></tr>
                <tr><td><b>USER</b></td><td>运行用户</td></tr>
                <tr><td><b>%CPU / %MEM</b></td><td>瞬时 CPU / 内存占用</td></tr>
                <tr><td><b>服务/命令</b></td><td>完整启动命令的缩写；<code>java</code> 会显示 jar 包或主类名</td></tr>
            </table>
            <p><b>识别技巧</b>：Java 看 <code>-jar xxx.jar</code>；K8s 看 <code>kubelet</code>；脚本看 lua/python 路径。</p>
            <p>🔧 <code>ps -fp &lt;pid&gt;</code> · <code>cat /proc/&lt;pid&gt;/cmdline</code> · Java <code>jcmd &lt;pid&gt; VM.command_line</code></p>
        </div>
    </details>'''

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

def render_mem_top_interpret_hint(rows: list[dict], service_cmd: bool = False) -> str:
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
    comm = shorten_service_cmd(top["comm"]) if service_cmd else top["comm"]
    hints.append(f'Top1 {comm}(PID {top["pid"]}) %MEM {mem_val}% · RSS {rss_gb:.2f}G')

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

def render_mem_top_block(content: str, service_cmd: bool = False) -> tuple[str, str]:
    columns, rows = parse_ps_lines(content)
    if not rows:
        return render_ps_top_table(content)

    if service_cmd:
        columns = [("服务/命令" if c in ("COMMAND", "服务/命令") else c) for c in columns]

    thead = "".join(f"<th>{escape_html(c)}</th>" for c in columns)
    tbody = ""
    for idx, r in enumerate(rows):
        cls = "alt" if idx % 2 == 0 else ""
        cmd_raw = r["comm"]
        cmd_show = shorten_service_cmd(cmd_raw) if service_cmd else cmd_raw
        tip = f' title="{escape_html(cmd_raw)}"' if service_cmd and cmd_raw != cmd_show else ""
        if "rss" in r:
            cells = [r["pid"], r["user"], r["cpu"], r["mem"], r["rss"]]
            tds = "".join(f"<td>{escape_html(c)}</td>" for c in cells)
            tds += f'<td{tip} style="max-width:420px;word-break:break-all;">{escape_html(cmd_show)}</td>'
        else:
            cells = [r["pid"], r["user"], r["cpu"], r["mem"]]
            tds = "".join(f"<td>{escape_html(c)}</td>" for c in cells)
            tds += f'<td{tip} style="max-width:420px;word-break:break-all;">{escape_html(cmd_show)}</td>'
        tbody += f'<tr class="{cls}">{tds}</tr>'

    top = rows[0]
    top_label = shorten_service_cmd(top["comm"]) if service_cmd else top["comm"]
    summary = f'{top_label} (PID {top["pid"]}) CPU {top["cpu"]}% MEM {top["mem"]}%'
    hint = render_mem_top_interpret_hint(rows, service_cmd)
    guide = render_process_mem_top_guide() if service_cmd else render_mem_top_stat_guide()
    body = f'''
    <div class="card-body">
        <table class="tbl"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>
        {guide}
        <div class="load-trend-hint">{hint}</div>
        {render_mem_top_high_guide(rows)}
    </div>'''
    return body, summary

def render_process_mem_top_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 内存 Top 5 说明</summary>
        <div class="load-guide-body">
            <p><strong>服务/命令</strong>列从完整启动参数提取服务名；Java 进程显示 jar/主类，悬停可看完整命令。</p>
            <p>RSS 为物理内存占用（KB），%MEM 为占总内存比例。</p>
        </div>
    </details>'''

def render_memory_anomaly_summary(anomalies: list[tuple[str, str]]) -> str:
    return render_cpu_anomaly_summary(anomalies)

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

def render_disk_anomaly_summary(anomalies: list[tuple[str, str]]) -> str:
    return render_cpu_anomaly_summary(anomalies)

def render_collection_failed_block(title: str, content: str) -> tuple[str, str]:
    msg = content.strip() if content.strip() else f"{title} 无数据"
    body = f'''
    <div class="card-body">
        <div class="load-guide load-guide-warn">
            <div class="load-guide-title">⚠️ 数据采集异常</div>
            <div class="load-guide-body">
                <p>{escape_html(msg)}</p>
                <p>可能原因：命令不在 PATH、权限不足、或目标系统缺少 ip/ss/netstat 工具。</p>
            </div>
        </div>
    </div>'''
    return body, "采集失败"

def render_process_stats_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 进程统计说明</summary>
        <div class="load-guide-body">
            <p>数据来自远程 <code>ps</code> 的<strong>瞬时快照</strong>，按进程状态（STAT 首字母）分类统计。</p>
            <table class="load-ref-tbl">
                <tr><th>指标</th><th>含义</th><th>正常范围</th></tr>
                <tr><td><b>总数</b></td><td><code>ps -e</code> 条目数（含内核线程、用户进程、容器进程）</td><td>视业务；K8s 节点数百~上千常见</td></tr>
                <tr><td><b>运行中 (R)</b></td><td>正在 CPU 上运行或就绪等待 CPU</td><td>通常个位数~数十；持续接近核数×2需关注</td></tr>
                <tr><td><b>睡眠 (S)</b></td><td>可中断睡眠，等待事件/IO/定时器</td><td>占绝大多数，正常</td></tr>
                <tr><td><b>D 状态</b></td><td>不可中断睡眠，多卡在等磁盘/NFS IO</td><td><b>应为 0</b>；&gt;0 需排查存储</td></tr>
                <tr><td><b>僵尸 (Z)</b></td><td>子进程已退出，父进程未回收</td><td><b>应为 0</b>；持续增长必须查父进程</td></tr>
            </table>
            <p class="load-thresh">
                <span class="kb-tag tag-good">🟢 僵尸=0 且 D=0</span> 正常 &nbsp;
                <span class="kb-tag tag-warn">🟡 僵尸 1~9 或 D&gt;0</span> 需关注 &nbsp;
                <span class="kb-tag tag-bad">🔴 僵尸≥10</span> 父进程异常
            </p>
            <p><b>状态对照</b>：R=运行 · S=睡眠 · D=等IO · Z=僵尸 · T=停止</p>
            <p>🔧 查 D 状态：<code>ps -eo pid,stat,cmd | awk '$2~/D/'</code>
            · 查僵尸：<code>ps -eo pid,ppid,stat,cmd | awk '$3~/Z/'</code>
            · 查父进程：<code>ps -fp &lt;ppid&gt;</code></p>
        </div>
    </details>'''

def render_process_stats_interpret_hint(data: dict) -> str:
    hints: list[str] = []
    zst, _, _ = zombie_status(data["zombie"])
    hints.append(f"进程总数 {data['total']}，运行中 {data['running']}")
    if data.get("sleep") is not None:
        hints.append(f"睡眠 {data['sleep']}")
    dstate = data.get("dstate", 0)
    if dstate > 0:
        hints.append(f"D 状态 {dstate} 个，优先排查 IO/存储")
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
    dstate = data.get("dstate", 0)
    if zst == "green" and data["total"] <= 5000 and dstate == 0:
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
    dst_dot = "🟢" if data.get("dstate", 0) == 0 else "🟡"
    sleep_row = ""
    if data.get("sleep") is not None:
        sleep_row = f'<div class="kv-row"><span class="kv-key">睡眠 (S)</span><span class="kv-val">{data["sleep"]}</span></div>'
    body = f'''
    <div class="card-body">
        <div class="kv-card">
            <div class="kv-row"><span class="kv-key">进程总数</span><span class="kv-val">{data["total"]}</span></div>
            <div class="kv-row"><span class="kv-key">运行中 (R)</span><span class="kv-val">{data["running"]}</span></div>
            {sleep_row}
            <div class="kv-row"><span class="kv-key">D 状态 (IO)</span><span class="kv-val">{data.get("dstate", 0)} {dst_dot}</span></div>
            <div class="kv-row"><span class="kv-key">僵尸 (Z)</span><span class="kv-val">{data["zombie"]} {zdot}</span></div>
        </div>
        {render_process_stats_guide()}
        <div class="load-trend-hint">{render_process_stats_interpret_hint(data)}</div>
        {render_process_stats_high_guide(data)}
    </div>'''
    summary = f'总数: {data["total"]} | 运行中: {data["running"]} | 僵尸: {data["zombie"]}'
    return body, summary

def render_dstate_block(content: str) -> tuple[str, str]:
    if is_collection_failed(content):
        return render_collection_failed_block("D 状态进程", content)
    rows = parse_dstate_lines(content)
    if not rows:
        hint = "🟢 无 D 状态进程，IO 阻塞正常"
        body = f'''
    <div class="card-body">
        <p style="padding:12px;color:{C["green"]};">{hint}</p>
        <div class="load-trend-hint">{hint}</div>
    </div>'''
        return body, "无 D 状态进程"
    tbody = ""
    for r in rows:
        tbody += f'''<tr class="cpu-row cpu-yellow">
            <td>{escape_html(r["pid"])}</td><td>{escape_html(r["ppid"])}</td>
            <td>{escape_html(r["stat"])}</td>
            <td>{escape_html(r["cmd"][:80])}</td></tr>'''
    body = f'''
    <div class="card-body">
        <table class="cpu-tbl">
            <thead><tr><th>PID</th><th>PPID</th><th>STAT</th><th>COMMAND</th></tr></thead>
            <tbody>{tbody}</tbody>
        </table>
        <div class="load-guide load-guide-warn">
            <div class="load-guide-title">🔍 D 状态进程 · 排查指引</div>
            <div class="load-guide-body">
                <ol class="load-guide-list">
                    <li>查挂载/NFS：<code>mount | grep nfs</code>、<code>dmesg | tail</code></li>
                    <li>查 IO：<code>iostat -x 1 3</code>、<code>vmstat 1 5</code> 看 wa/b</li>
                    <li>持续 D 状态 → 存储 hang 或驱动问题，考虑重启相关服务</li>
                </ol>
            </div>
        </div>
        <div class="load-trend-hint">🟡 发现 {len(rows)} 个 D 状态进程，优先排查磁盘/存储 IO</div>
    </div>'''
    return body, f"{len(rows)} 个 D 状态进程"

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
            <td>{escape_html(r["pid"])}</td><td>{escape_html(r.get("ppid", ""))}</td>
            <td>{escape_html(r.get("user", ""))}</td><td>{escape_html(r["stat"])}</td>
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

def render_process_anomaly_summary(anomalies: list[tuple[str, str]]) -> str:
    return render_cpu_anomaly_summary(anomalies)

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
    if is_collection_failed(content):
        return render_collection_failed_block("网络接口 IP", content)
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
            <p>数据来自 <code>ss -tlnp</code>（无权限时降级 <code>ss -tln</code>）的<strong>瞬时快照</strong>。</p>
            <table class="load-ref-tbl">
                <tr><th>字段</th><th>含义</th></tr>
                <tr><td><b>端口</b></td><td>TCP 端口号</td></tr>
                <tr><td><b>绑定范围</b></td><td><code>*</code>=所有 IPv4 网卡 · <code>[::]</code>=IPv6 · <code>127.0.0.1</code>=仅本机</td></tr>
                <tr><td><b>套接字数</b></td><td>同一端口+绑定范围的 LISTEN 条目数；Nginx/K8s Ingress 多 worker 时 &gt;1 属正常</td></tr>
                <tr><td><b>Process / PID</b></td><td>需 <strong>root</strong> 或 <code>CAP_NET_ADMIN</code>；dev 等普通账号通常为空</td></tr>
            </table>
            <p><b>为何同一端口多行？</b> 原始 <code>ss</code> 输出中，每个 worker 进程各占用一个监听套接字
            （如 16 个 Nginx worker → 16 条 <code>*:80</code>）。报告已按「端口+绑定范围」<strong>合并</strong>，套接字数列显示实际数量。</p>
            <p><b>安全核对</b>：3306/6379 等是否绑定 <code>*</code> 对全网暴露。</p>
            <p>🔧 root 下：<code>ss -tlnp</code> · <code>lsof -iTCP -sTCP:LISTEN -P -n</code></p>
        </div>
    </details>'''

def render_listen_ports_nonroot_notice(raw_rows: list[dict], consolidated: list[dict], content: str = "") -> str:
    has_privilege = "[note:privilege]" in content
    has_process = any(r.get("process") not in ("—", "-", "") for r in raw_rows)
    if has_privilege and has_process:
        total_sockets = sum(r["count"] for r in consolidated)
        return f'''
    <div class="load-guide load-guide-info" style="margin-bottom:12px;border-color:{C["green"]};">
        <div class="load-guide-title">✅ 已通过 sudo 提权采集进程信息</div>
        <div class="load-guide-body">
            <p>非 root 账号通过 <code>sudo -i</code> 临时提权，已获取监听端口的 Process/PID。
            共 <b>{len(consolidated)}</b> 组监听、<b>{total_sockets}</b> 个套接字。</p>
        </div>
    </div>'''
    if has_process:
        return ""
    total_sockets = sum(r["count"] for r in consolidated)
    return f'''
    <div class="load-guide load-guide-info" style="margin-bottom:12px;">
        <div class="load-guide-title">ℹ️ Process/PID 为空的原因</div>
        <div class="load-guide-body">
            <p>当前使用 <strong>非 root</strong> 账号巡检，且 <code>sudo -i</code> 不可用或未授权，
            内核不允许查看其他用户的监听进程信息。
            表格已合并重复端口：共 <b>{len(consolidated)}</b> 组监听、
            <b>{total_sockets}</b> 个套接字。如需进程名，请配置免密 sudo 或改用 <code>root@</code> 巡检。</p>
        </div>
    </div>'''

def render_listen_ports_interpret_hint(raw_rows: list[dict], consolidated: list[dict]) -> str:
    if not consolidated:
        return "➡️ 未检测到 TCP 监听端口"
    total_sockets = sum(r["count"] for r in consolidated)
    hints: list[str] = [
        f"{len(consolidated)} 组监听 / {total_sockets} 个套接字",
    ]
    multi = [r for r in consolidated if r["count"] > 1]
    if multi:
        hints.append(f"{len(multi)} 组有多 worker（套接字&gt;1）")
    wildcards = [r for r in consolidated if "全网卡" in r["bind"]]
    if wildcards:
        hints.append(f"{len(wildcards)} 组绑定全网卡")
    risky = [RISKY_PORTS[r["port"]] for r in consolidated
             if r["port"] in RISKY_PORTS and "全网卡" in r["bind"]]
    if risky:
        hints.append("⚠️ 高危端口对外暴露: " + "/".join(sorted(set(risky))))
    well_known = {"22": "SSH", "80": "HTTP", "443": "HTTPS", "3306": "MySQL", "6379": "Redis"}
    ports = {r["port"] for r in consolidated}
    found = [well_known[p] for p in ports if p in well_known]
    if found:
        hints.append("含 " + "/".join(sorted(set(found))))
    if raw_rows and all(r.get("process") in ("—", "-", "") for r in raw_rows):
        hints.append("非 root 无法显示进程名")
    return " · ".join(hints)

def render_listen_ports_block(content: str) -> tuple[str, str]:
    if is_collection_failed(content):
        return render_collection_failed_block("监听端口", content)
    # 过滤 note 行
    clean = "\n".join(
        l for l in content.split("\n")
        if not l.strip().startswith("[note:")
    )
    raw_rows = parse_listen_ports(clean)
    if not raw_rows:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content[:2000])}</pre></div>',
            content.strip().split("\n")[0][:80] if content.strip() else "无监听",
        )
    consolidated = consolidate_listen_ports(raw_rows)
    tbody = ""
    for r in consolidated:
        count_tip = f' title="{r["count"]} 个 LISTEN 套接字"' if r["count"] > 1 else ""
        tbody += f'''<tr class="cpu-row cpu-green">
            <td>{escape_html(r["port"])}</td>
            <td>{escape_html(r["bind"])}</td>
            <td{count_tip}>{r["count"]}</td>
            <td>{escape_html(r["process"])}</td>
            <td>{escape_html(r["pid"])}</td></tr>'''
    total_sockets = sum(r["count"] for r in consolidated)
    summary = f"{len(consolidated)} 组监听 / {total_sockets} 套接字"
    body = f'''
    <div class="card-body" style="max-height:480px;overflow-y:auto;">
        {render_listen_ports_nonroot_notice(raw_rows, consolidated, content)}
        <table class="cpu-tbl">
            <thead><tr><th>端口</th><th>绑定范围</th><th>套接字数</th><th>Process</th><th>PID</th></tr></thead>
            <tbody>{tbody}</tbody>
        </table>
        {render_listen_ports_guide()}
        <div class="load-trend-hint">{render_listen_ports_interpret_hint(raw_rows, consolidated)}</div>
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
    if data.get("timewait") is not None:
        tw = data["timewait"]
        tw_hint = "正常" if tw < 5000 else ("关注" if tw < 20000 else "偏高")
        hints.append(f"TIME_WAIT {tw} ({tw_hint})")
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
    if is_collection_failed(content):
        return render_collection_failed_block("连接统计", content)
    data = parse_conn_stats(content)
    if not data:
        return (
            f'<div class="card-body"><pre class="pre">{escape_html(content)}</pre></div>',
            content.strip()[:80],
        )
    est_st, est_dot, est_label = conn_estab_status(data["estab"])
    tw_row = ""
    if data.get("timewait") is not None:
        tw = data["timewait"]
        tw_dot = "🟢" if tw < 5000 else ("🟡" if tw < 20000 else "🔴")
        tw_row = f'''<div class="kv-row"><span class="kv-key">TIME_WAIT</span>
                <span class="kv-val">{tw} {tw_dot}</span></div>'''
    body = f'''
    <div class="card-body">
        <div class="kv-card">
            <div class="kv-row"><span class="kv-key">已建立 (ESTAB)</span>
                <span class="kv-val">{data["estab"]} {est_dot}</span></div>
            <div class="kv-row"><span class="kv-key">监听中 (LISTEN)</span>
                <span class="kv-val">{data["listen"]}</span></div>
            {tw_row}
            <div class="kv-row"><span class="kv-key">总连接</span>
                <span class="kv-val">{data["total"]}</span></div>
        </div>
        {render_conn_stats_guide()}
        <div class="load-trend-hint">{render_conn_stats_interpret_hint(data)}</div>
        {render_conn_stats_high_guide(data)}
    </div>'''
    summary = f'已建立: {data["estab"]} | 监听中: {data["listen"]} | 总连接: {data["total"]}'
    return body, summary

def render_conn_summary_guide() -> str:
    return '''
    <details class="load-guide load-guide-info load-guide-collapsible">
        <summary class="load-guide-title">📖 连接状态摘要说明</summary>
        <div class="load-guide-body">
            <p>数据来自 <code>ss -s</code>，内核维护的 socket 统计快照。</p>
            <table class="load-ref-tbl">
                <tr><th>指标</th><th>含义</th><th>关注阈值</th></tr>
                <tr><td><b>Total</b></td><td>系统 socket 总数（含所有协议）</td><td>—</td></tr>
                <tr><td><b>estab</b></td><td>TCP 已建立连接数</td><td>&gt;5000 关注，&gt;10000 异常</td></tr>
                <tr><td><b>closed</b></td><td>已关闭但未完全释放的 TCP 套接字</td><td>持续偏高查泄漏</td></tr>
                <tr><td><b>orphaned</b></td><td>孤儿连接（进程已退出但未关闭）</td><td>&gt;0 需排查</td></tr>
                <tr><td><b>synrecv</b></td><td>半连接（SYN 收到），SYN 洪水指标</td><td>&gt;100 警惕攻击</td></tr>
                <tr><td><b>timewait</b></td><td>TIME_WAIT 状态连接数</td><td>&gt;5000 关注，&gt;20000 偏高</td></tr>
                <tr><td><b>ports</b></td><td>本地 TCP 端口使用数</td><td>接近 65535 会端口耗尽</td></tr>
            </table>
            <p><b>Transport 表</b>：各协议（TCP/UDP/RAW）的 socket 计数，分 IPv4/IPv6。</p>
            <p>🔧 <code>ss -s</code> · <code>ss -tan state time-wait | wc -l</code> · <code>sysctl net.ipv4.tcp_tw_reuse</code></p>
        </div>
    </details>'''

def render_conn_summary_block(content: str) -> tuple[str, str]:
    if is_collection_failed(content):
        return render_collection_failed_block("连接状态摘要", content)

    data = parse_ss_summary(content)
    tcp = data.get("tcp", {})
    if not tcp and data.get("total_sockets") is None and not data.get("transport"):
        lines = [l for l in content.strip().split("\n") if l.strip()]
        body = f'<div class="card-body"><pre class="pre">{escape_html(chr(10).join(lines))}</pre></div>'
        return body, lines[0][:60] if lines else "无摘要"

    rows_tcp = ""
    if tcp:
        tcp_items = [
            ("TCP 总数", tcp.get("total"), "内核 TCP socket 计数"),
            ("estab 已建立", tcp.get("estab"), "活跃数据传输连接"),
            ("closed 已关闭", tcp.get("closed"), "等待回收的关闭连接"),
            ("orphaned 孤儿", tcp.get("orphaned"), "进程退出未关闭的连接"),
            ("synrecv 半连接", tcp.get("synrecv"), "SYN 收到，防 SYN 洪水"),
            ("timewait", tcp.get("timewait"), "等待 2MSL 的连接"),
            ("ports 端口数", tcp.get("ports"), "已占用本地 TCP 端口"),
        ]
        for i, (name, val, desc) in enumerate(tcp_items):
            bg = C["row_alt"] if i % 2 else C["row"]
            dot = ""
            if name.startswith("estab") and val is not None:
                st, dot, _ = conn_estab_status(int(val))
            elif name.startswith("timewait") and val is not None:
                dot = "🟢" if int(val) < 5000 else ("🟡" if int(val) < 20000 else "🔴")
            elif name.startswith("orphaned") and val and int(val) > 0:
                dot = "🟡"
            elif name.startswith("synrecv") and val and int(val) > 100:
                dot = "🔴"
            rows_tcp += f'''<tr style="background:{bg};">
                <td><b>{escape_html(name)}</b></td>
                <td>{val if val is not None else "—"} {dot}</td>
                <td style="color:{C["dim"]};">{escape_html(desc)}</td></tr>'''

    rows_trans = ""
    for i, t in enumerate(data.get("transport", [])):
        bg = C["row_alt"] if i % 2 else C["row"]
        rows_trans += f'''<tr style="background:{bg};">
            <td><b>{escape_html(t["proto"])}</b></td>
            <td>{escape_html(t["total"])}</td>
            <td>{escape_html(t["ip"])}</td>
            <td>{escape_html(t["ipv6"])}</td></tr>'''

    total_row = ""
    if data.get("total_sockets") is not None:
        total_row = f'''
        <div class="kv-card" style="margin-bottom:16px;">
            <div class="kv-row"><span class="kv-key">Socket 总数</span>
                <span class="kv-val">{data["total_sockets"]}</span></div>
            <div class="kv-row"><span class="kv-key">Kernel 计数</span>
                <span class="kv-val">{data.get("kernel") if data.get("kernel") is not None else "—"}</span></div>
        </div>'''

    tcp_table = ""
    if rows_tcp:
        tcp_table = f'''
        <h4 style="color:{C["text"]};margin:12px 0 8px;">TCP 状态分布</h4>
        <table class="cpu-tbl">
            <thead><tr><th>指标</th><th>数值</th><th>说明</th></tr></thead>
            <tbody>{rows_tcp}</tbody>
        </table>'''

    trans_table = ""
    if rows_trans:
        trans_table = f'''
        <h4 style="color:{C["text"]};margin:16px 0 8px;">传输层统计</h4>
        <table class="cpu-tbl">
            <thead><tr><th>协议</th><th>Total</th><th>IPv4</th><th>IPv6</th></tr></thead>
            <tbody>{rows_trans}</tbody>
        </table>'''

    hint_parts = []
    if tcp.get("estab") is not None:
        hint_parts.append(f'estab {tcp["estab"]}')
    if tcp.get("timewait") is not None:
        hint_parts.append(f'timewait {tcp["timewait"]}')
    hint = " · ".join(hint_parts) if hint_parts else "内核 socket 统计"

    body = f'''
    <div class="card-body">
        {total_row}
        {tcp_table}
        {trans_table}
        {render_conn_summary_guide()}
        <div class="load-trend-hint">{hint}</div>
    </div>'''
    summary = f'TCP estab {tcp.get("estab", "—")}, timewait {tcp.get("timewait", "—")}'
    return body, summary

def render_network_anomaly_summary(anomalies: list[tuple[str, str]]) -> str:
    return render_cpu_anomaly_summary(anomalies)

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
    ctx = {} if ctx is None else ctx

    if is_collection_failed(content) and (
        not title or "Traceback (most recent call last)" in content
    ):
        body, first_line = render_collection_failed_block(title or "数据采集", content)
        desc_html = escape_html(explanation) if explanation else ""
        return f'''
    <div class="metric-card">
        <div class="metric-header">
            <span class="metric-title">{escape_html(title or "采集异常")}</span>
            <span class="metric-val">{escape_html(first_line)}</span>
        </div>
        {body}
        <div class="metric-desc">💡 {desc_html}</div>
    </div>
    '''

    is_table = is_table_text(content)

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
        svc = ctx.get("module_key") == "05_process"
        body, first_line = render_cpu_top_block(content, ctx.get("cpu_cores", 0), service_cmd=svc)
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
    elif title == "D 状态进程":
        body, first_line = render_dstate_block(content or "无 D 状态进程")
    elif title == "僵尸进程详情":
        body, first_line = render_zombie_block(content or "无僵尸进程")
    elif title == "内存 Top 5":
        svc = ctx.get("module_key") == "05_process"
        body, first_line = render_mem_top_block(content, service_cmd=svc)
    elif title == "网络接口 IP":
        body, first_line = render_network_iface_block(content)
    elif title == "监听端口":
        body, first_line = render_listen_ports_block(content)
    elif title == "连接统计":
        body, first_line = render_conn_stats_block(content)
    elif title == "连接状态摘要":
        body, first_line = render_conn_summary_block(content)
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
    ctx: dict = {"module_key": key}

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
{load_css(C)}
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

{load_tab_js()}
</body>
</html>'''

