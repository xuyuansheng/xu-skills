---
name: jumpserver-monitor
description: |
  通过 JumpServer 堡垒机 ProxyJump 连接内网服务器，执行全面的资源监控检查。
  包含 5 个检查模块：CPU 使用率分布、内存、磁盘/Inode、进程分析、网络/端口。
  支持单台检查、快速检查（--quick）、指定模块检查（--module）、批量巡检（--all），并可生成 HTML 可视化报告（--html）。
  此技能应在用户需要查看堡垒机内服务器状态、查询进程资源占用、执行批量服务器巡检或生成巡检报告时触发。
  典型触发词：查看进程、资源占用、查服务器状态、登录堡垒机、top进程、内存占用、磁盘空间、批量巡检、生成报告、HTML报告。
agent_created: true
---

# JumpServer 堡垒机服务器监控

## Overview

通过 SSH ProxyJump 方式穿透 JumpServer 堡垒机，对目标服务器执行 5 大模块的全面健康检查，支持单台/批量/模块化执行。

## 目录结构

```
jumpserver-monitor/
├── SKILL.md
├── config/
│   ├── bastion.conf       # 堡垒机连接参数（修改此文件切换环境）
│   └── servers.txt       # 批量巡检的服务器列表
└── scripts/
    ├── check_server.sh    # 主入口（接受 user@ip 或 --all）
    ├── utils/
    │   ├── remote_exec.sh  # 核心：ProxyJump 连接函数
    │   └── gen_html.py    # HTML 报告生成器
    └── modules/
        ├── 02_cpu.sh         # CPU 与负载
        ├── 03_memory.sh      # 内存与 Swap
        ├── 04_disk.sh        # 磁盘、Inode、IO
        ├── 05_process.sh     # 进程分析
        └── 06_network.sh     # 网络与端口
```

## 配置文件

### `config/bastion.conf`

堡垒机连接参数，切换堡垒机只需改此文件：

```bash
BASTION_HOST="172.18.2.97"    # 堡垒机 IP
BASTION_PORT="60022"            # 堡垒机 SSH 端口
BASTION_USER="yuansheng.xu"    # 堡垒机登录用户
SSH_OPTS="..."                  # SSH 选项（一般不需修改）
```

### `config/servers.txt`

批量巡检时的服务器列表，格式 `user@ip`，`#` 开头为注释：

```
# 格式: user@ip
ops@172.18.0.245
root@172.16.202.92
```

## 使用方式

### 单台全量检查（全部 5 个模块）

```bash
bash scripts/check_server.sh root@172.16.202.92
```

### 单台快速检查（CPU/内存/磁盘，共 3 个模块）

```bash
bash scripts/check_server.sh root@172.16.202.92 --quick
```

### 单台指定模块检查

```bash
# 只查 CPU 和内存
bash scripts/check_server.sh root@172.16.202.92 --module 02_cpu --module 03_memory

# 查看模块编号对应关系: 02=cpu, 03=memory, 04=disk, 05=process, 06=network
```

### 单台生成 HTML 报告

```bash
# 自动生成报告文件名（含 IP 和时间）
bash scripts/check_server.sh root@172.16.202.92 --html

# 指定输出文件名
bash scripts/check_server.sh root@172.16.202.92 --html report.html

# 快速检查 + HTML 报告
bash scripts/check_server.sh root@172.16.202.92 --quick --html
```

### 批量生成 HTML 报告

每台服务器生成一个独立的 HTML 报告，保存在指定目录：

```bash
# 报告保存到 ./reports/ 目录
bash scripts/check_server.sh --all --html reports/

# 快速模式 + HTML
bash scripts/check_server.sh --all --quick --html reports/
```

> HTML 报告特性：
> - 📑 **Tab 页布局**：每个检查模块独立 Tab，点击切换，Tab 旁 ● 显示模块状态
> - 📊 深色主题，指标卡片式布局
> - 💡 每个指标附有通俗解释，非专业人士也能看懂
> - 📋 表格精简，只展示关键列（PID/进程名/CPU%/MEM%）
> - 🟢🟡🔴 状态指示灯（正常/警告/异常）
> - 📋 报告头部显示服务器 IP、主机名、检查时间

### 列出所有可用模块

```bash
bash scripts/check_server.sh --list-modules
```

### 批量巡检（读取 `config/servers.txt`）

```bash
bash scripts/check_server.sh --all
bash scripts/check_server.sh --all --quick          # 批量+快速模式
bash scripts/check_server.sh --all --module 02_cpu  # 批量+指定模块
```

## 5 大检查模块说明

| 模块 | 文件 | 关键指标 |
|------|------|----------|
| 02 CPU/负载 | `02_cpu.sh` | CPU 使用率分布(us/sy/ni/id/wa/hi/si/st)，含阈值/含义/排查建议 |
| 03 内存 | `03_memory.sh` | 内存总览(free)、使用率百分比、Swap状态、高内存进程Top5 |
| 04 磁盘 | `04_disk.sh` | 磁盘使用率(df -hP)、Inode(df -iP)、高使用率挂载点(df 筛选，无 du) |
| 05 进程 | `05_process.sh` | 进程统计、僵尸详情、CPU/内存 Top5 |
| 06 网络 | `06_network.sh` | 网络接口(ip)、监听端口(ss)、连接统计 |

每个指标在 HTML 报告中均附有 💡 详细解释，说明指标含义、正常范围和异常处理建议。

## 为什么用 ProxyJump 而非 GateShell TUI

JumpServer 的 GateShell 交互界面在管道/脚本中不可靠：

- `echo ":ssh ops@172.18.0.245" | ssh ...` 会把 `:s` 截获为 GateShell 的排序快捷键
- 导致实际连接到错误的服务器
- 本 skill 使用 SSH `ProxyCommand` 方式，绕开 GateShell TUI，直接穿透到目标服务器

## 手动在目标服务器执行自定义命令

如果需要在目标服务器上执行脚本未覆盖的命令，直接用 `ssh` + ProxyJump：

```bash
ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    -o ProxyCommand="ssh -p 60022 yuansheng.xu@172.18.2.97 -W %h:%p" \
    root@172.16.202.92 "your_command_here"
```

## 首次使用前置条件

1. 确认 `~/.ssh/id_rsa` 私钥已配置，且已添加到 JumpServer 堡垒机
2. 编辑 `config/bastion.conf`，确认堡垒机参数正确
3. （可选）编辑 `config/servers.txt`，填入需要巡检的服务器列表
