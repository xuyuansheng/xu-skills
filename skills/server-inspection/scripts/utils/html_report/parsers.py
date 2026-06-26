"""模块输出文本解析与异常汇总。"""
from __future__ import annotations

import os
import re

from .thresholds import (
    CPU_METRICS,
    RISKY_PORTS,
    conn_estab_status,
    cpu_status_light,
    disk_pct_status,
    mem_rate_status,
    swap_rate_status,
    vmstat_b_status,
    vmstat_cs_status,
    vmstat_r_status,
    zombie_status,
)

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

def shorten_service_cmd(cmd: str, max_len: int = 80) -> str:
    """将完整命令行压缩为可识别的服务名"""
    cmd = (cmd or "").strip()
    if not cmd:
        return "—"
    lower = cmd.lower()
    if "java" in lower:
        if "jarlauncher" in lower or "springframework.boot" in lower:
            app = "/app"
            m = re.search(r"-cp\s+(\S+)", cmd)
            if m:
                app = m.group(1)
            return f"java → Spring Boot ({app})"
        m = re.search(r"-jar\s+(\S+\.jar)", cmd, re.I)
        if m:
            return f"java → {os.path.basename(m.group(1))}"
        m = re.search(r"(\S+\.jar)", cmd)
        if m:
            return f"java → {os.path.basename(m.group(1))}"
        m = re.search(r"([\w.$]+\.[A-Z]\w[\w.$]*)", cmd)
        if m and m.group(1) != "java":
            cls = m.group(1)
            if len(cls) > 40:
                cls = "…" + cls[-38:]
            return f"java → {cls}"
    base = os.path.basename(cmd.split()[0]) if cmd.split() else cmd
    known = {
        "kubelet": "K8s kubelet", "dockerd": "Docker", "containerd": "containerd",
        "nginx": "Nginx", "redis-server": "Redis", "mysqld": "MySQL",
        "postgres": "PostgreSQL", "sshd": "SSH", "systemd": "systemd",
        "lua-runner": "lua-runner", "calico": "Calico", "etcd": "etcd",
    }
    for k, label in known.items():
        if k in lower:
            return label
    if len(cmd) <= max_len:
        return cmd
    return cmd[: max_len - 3] + "..."

def parse_ps_lines(content: str) -> tuple[list[str], list[dict]]:
    """解析 ps -eo 输出 → (列名, 行数据)"""
    lines = [l for l in content.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return [], []

    header = lines[0].upper()
    has_rss = "RSS" in header
    has_service_col = "服务" in lines[0] or "ARGS" in header
    if has_rss:
        columns = ["PID", "USER", "%CPU", "%MEM", "RSS", "服务/命令"]
        pat = re.compile(r"^\s*(\d+)\s+(\S+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(.*)$")
    else:
        columns = ["PID", "USER", "%CPU", "%MEM", "服务/命令"] if has_service_col else ["PID", "USER", "%CPU", "%MEM", "COMMAND"]
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

def is_collection_failed(content: str) -> bool:
    s = (content or "").strip()
    if not s:
        return True
    if "[采集失败]" in s:
        return True
    if "Traceback (most recent call last)" in s:
        return True
    if "UnicodeEncodeError" in s:
        return True
    return False

def parse_process_stats(content: str) -> dict | None:
    m = re.search(
        r"总数:\s*(\d+)\s*\|\s*运行中:\s*(\d+)\s*(?:\|\s*睡眠:\s*(\d+)\s*)?"
        r"(?:\|\s*D状态:\s*(\d+)\s*)?\|\s*僵尸:\s*(\d+)",
        content,
    )
    if not m:
        m = re.search(r"总数:\s*(\d+)\s*\|\s*运行中:\s*(\d+)\s*\|\s*僵尸:\s*(\d+)", content)
        if not m:
            return None
        return {"total": int(m.group(1)), "running": int(m.group(2)),
                "sleep": None, "dstate": 0, "zombie": int(m.group(3))}
    return {
        "total": int(m.group(1)), "running": int(m.group(2)),
        "sleep": int(m.group(3)) if m.group(3) else None,
        "dstate": int(m.group(4)) if m.group(4) else 0,
        "zombie": int(m.group(5)),
    }

def parse_zombie_lines(content: str) -> list[dict]:
    if "无僵尸进程" in content:
        return []
    rows = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line.upper().startswith("PID"):
            continue
        parts = line.split(None, 4)
        if len(parts) >= 5 and "Z" in parts[3]:
            rows.append({
                "pid": parts[0], "ppid": parts[1], "user": parts[2],
                "stat": parts[3], "cmd": parts[4],
            })
            continue
        parts = line.split(None, 10)
        if len(parts) >= 11 and "Z" in parts[7]:
            rows.append({
                "user": parts[0], "pid": parts[1], "ppid": parts[2],
                "stat": parts[7], "cmd": parts[10],
            })
    return rows

def parse_dstate_lines(content: str) -> list[dict]:
    if "无 D 状态进程" in content:
        return []
    rows = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line.upper().startswith("PID"):
            continue
        parts = line.split(None, 3)
        if len(parts) >= 4 and "D" in parts[2]:
            rows.append({
                "pid": parts[0], "ppid": parts[1],
                "stat": parts[2], "cmd": parts[3],
            })
    return rows

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
                if data.get("dstate", 0) > 0:
                    anomalies.append(("yellow", f'D 状态进程 {data["dstate"]} 个'))
        elif title == "D 状态进程":
            rows = parse_dstate_lines(content)
            if rows:
                anomalies.append(("yellow", f"存在 {len(rows)} 个 D 状态进程"))
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

def parse_netstat_listen(content: str) -> list[dict]:
    rows: list[dict] = []
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("[") or "Active Internet" in line or line.upper().startswith("PROTO"):
            continue
        if "LISTEN" not in line:
            continue
        parts = line.split()
        if len(parts) < 6:
            continue
        local = parts[3]
        port = local.rsplit(":", 1)[-1] if ":" in local else local
        proc = parts[6] if len(parts) > 6 and parts[6] != "-" else "—"
        rows.append({"local": local, "port": port, "process": proc, "pid": ""})
    return rows

def classify_bind_address(local: str) -> str:
    """将 Local Address 归类为可读绑定范围"""
    if local.startswith("[::]"):
        return "IPv6 全网卡 [::]"
    if local.startswith("*:") or local.startswith("0.0.0.0:"):
        return "IPv4 全网卡 *"
    if local.startswith("127.0.0.1:"):
        return "本机 127.0.0.1"
    if local.startswith("[::1]:"):
        return "本机 [::1]"
    return local

def consolidate_listen_ports(rows: list[dict]) -> list[dict]:
    """按 端口+绑定范围 合并重复监听套接字（K8s/Nginx 多 worker 场景）"""
    groups: dict[tuple[str, str], dict] = {}
    for r in rows:
        port = r["port"]
        bind = classify_bind_address(r["local"])
        key = (port, bind)
        if key not in groups:
            groups[key] = {
                "port": port, "bind": bind, "count": 0,
                "processes": set(), "pids": set(),
            }
        g = groups[key]
        g["count"] += 1
        proc = r.get("process", "")
        if proc and proc not in ("—", "-", ""):
            g["processes"].add(proc)
        pid = r.get("pid", "")
        if pid:
            g["pids"].add(pid)

    result = []
    for (_, _), g in sorted(
        groups.items(),
        key=lambda x: (int(x[1]["port"]) if x[1]["port"].isdigit() else 99999, x[1]["bind"]),
    ):
        result.append({
            "port": g["port"],
            "bind": g["bind"],
            "count": g["count"],
            "process": ", ".join(sorted(g["processes"])) if g["processes"] else "—",
            "pid": ", ".join(sorted(g["pids"])) if g["pids"] else "—",
            "local": g["bind"],  # compat for anomaly checks
        })
    return result

def parse_listen_ports(content: str) -> list[dict]:
    """解析原始监听列表（未合并）"""
    if "[source:netstat]" in content:
        return parse_netstat_listen(content)
    rows = parse_ss_listen(content)
    if rows:
        return rows
    return parse_netstat_listen(content)

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
        r"已建立:\s*(\d+)\s*\|\s*监听中:\s*(\d+)\s*\|\s*TIME_WAIT:\s*(\d+)\s*\|\s*总连接:\s*(\d+)",
        content,
    )
    if m:
        return {
            "estab": int(m.group(1)), "listen": int(m.group(2)),
            "timewait": int(m.group(3)), "total": int(m.group(4)),
        }
    m = re.search(
        r"已建立:\s*(\d+)\s*\|\s*监听中:\s*(\d+)\s*\|\s*总连接:\s*(\d+)",
        content,
    )
    if not m:
        return None
    return {"estab": int(m.group(1)), "listen": int(m.group(2)),
            "timewait": None, "total": int(m.group(3))}

def collect_network_anomalies(blocks: list[dict]) -> list[tuple[str, str]]:
    anomalies: list[tuple[str, str]] = []
    for b in blocks:
        if b.get("_skip"):
            continue
        title, content = b["title"], b["content"]
        if is_collection_failed(content):
            anomalies.append(("red", f"{title} 采集失败"))
            continue
        if title == "连接统计":
            data = parse_conn_stats(content)
            if data:
                st, _, _ = conn_estab_status(data["estab"])
                if st == "red":
                    anomalies.append(("red", f'已建立连接 {data["estab"]} 过高'))
                elif st == "yellow":
                    anomalies.append(("yellow", f'已建立连接 {data["estab"]} 偏高'))
                tw = data.get("timewait")
                if tw is not None and tw >= 20000:
                    anomalies.append(("yellow", f"TIME_WAIT {tw} 偏高"))
        elif title == "监听端口":
            raw = parse_listen_ports(
                "\n".join(l for l in content.split("\n") if not l.strip().startswith("[note:"))
            )
            rows = consolidate_listen_ports(raw)
            for r in rows:
                if r["port"] in RISKY_PORTS and "全网卡" in r.get("bind", r.get("local", "")):
                    anomalies.append(("yellow",
                        f'{RISKY_PORTS[r["port"]]} 端口 {r["port"]} 绑定全网卡'))
        elif title == "网络接口 IP":
            ifaces = parse_ip_interfaces(content)
            if not ifaces:
                anomalies.append(("red", "未解析到网络接口"))
    return anomalies

def parse_ss_summary(content: str) -> dict:
    """解析 ss -s 输出（兼容完整版与精简版内核输出）"""
    result: dict = {"total_sockets": None, "kernel": None, "tcp": {}, "transport": []}
    transport_protos = ("RAW", "UDP", "TCP", "ICMP", "INET")
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"Total:\s*(\d+)(?:\s*\(kernel\s+(\d+)\))?", line)
        if m:
            result["total_sockets"] = int(m.group(1))
            if m.group(2):
                result["kernel"] = int(m.group(2))
            continue
        m = re.match(
            r"TCP:\s*(\d+)\s*\(estab\s+(\d+),\s*closed\s+(\d+),\s*orphaned\s+(\d+),\s*"
            r"synrecv\s+(\d+),\s*timewait\s+(\d+)/(\d+)\),\s*ports\s+(\d+)",
            line,
        )
        if m:
            result["tcp"] = {
                "total": int(m.group(1)), "estab": int(m.group(2)),
                "closed": int(m.group(3)), "orphaned": int(m.group(4)),
                "synrecv": int(m.group(5)), "timewait": int(m.group(6)),
                "timewait_active": int(m.group(7)), "ports": int(m.group(8)),
            }
            continue
        m = re.match(
            r"TCP:\s*(\d+)\s*\(estab\s+(\d+),\s*closed\s+(\d+),\s*orphaned\s+(\d+),\s*"
            r"timewait\s+(\d+)/(\d+)\)",
            line,
        )
        if m:
            result["tcp"] = {
                "total": int(m.group(1)), "estab": int(m.group(2)),
                "closed": int(m.group(3)), "orphaned": int(m.group(4)),
                "timewait": int(m.group(5)), "timewait_active": int(m.group(6)),
            }
            continue
        m = re.match(
            r"TCP:\s*(\d+)\s*\(estab\s+(\d+),\s*closed\s+(\d+),\s*orphaned\s+(\d+),\s*timewait\s+(\d+)\)",
            line,
        )
        if m:
            result["tcp"] = {
                "total": int(m.group(1)), "estab": int(m.group(2)),
                "closed": int(m.group(3)), "orphaned": int(m.group(4)),
                "timewait": int(m.group(5)),
            }
            continue
        if line.startswith("Transport") or line.startswith("*"):
            continue
        parts = re.split(r"\s+", line)
        if len(parts) >= 4 and parts[0] in transport_protos:
            result["transport"].append({
                "proto": parts[0], "total": parts[1],
                "ip": parts[2], "ipv6": parts[3],
            })
    return result

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

def guess_status(blocks: list[dict]) -> str:
    """根据内容推测模块状态"""
    full = " ".join(b["content"].lower() for b in blocks)
    if any(w in full for w in ["traceback", "unicodeencodeerror"]):
        return "red"
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

