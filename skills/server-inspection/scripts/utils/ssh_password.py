#!/usr/bin/env python3
"""SSH 密码登录执行远程命令（Paramiko，Windows 下比 SSH_ASKPASS 更可靠）"""
from __future__ import annotations

import os
import sys


def _read_password() -> str:
    pw = os.environ.get("SSH_TARGET_PASSWORD", "")
    if pw:
        return pw
    pw_file = os.environ.get("SSH_ASKPASS_FILE", "")
    if pw_file and os.path.isfile(pw_file):
        with open(pw_file, encoding="utf-8") as f:
            return f.read()
    return ""


def _parse_target(target: str) -> tuple[str, str]:
    user, host = target.split("@", 1)
    return user, host


def run_command(target: str, command: str, *, timeout: int = 30) -> int:
    import paramiko

    password = _read_password()
    if not password:
        print("[ERROR] 未找到 SSH 密码（SSH_TARGET_PASSWORD / SSH_ASKPASS_FILE）", file=sys.stderr)
        return 2

    user, host = _parse_target(target)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        username=user,
        password=password,
        timeout=timeout,
        allow_agent=False,
        look_for_keys=False,
        banner_timeout=timeout,
        auth_timeout=timeout,
    )
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read()
        err = stderr.read()
        if out:
            sys.stdout.buffer.write(out)
        if err:
            sys.stderr.buffer.write(err)
        return stdout.channel.recv_exit_status()
    finally:
        client.close()


def run_script(target: str, script: bytes | str, *, timeout: int = 120) -> int:
    import paramiko

    password = _read_password()
    if not password:
        print("[ERROR] 未找到 SSH 密码（SSH_TARGET_PASSWORD / SSH_ASKPASS_FILE）", file=sys.stderr)
        return 2

    script_bytes = script if isinstance(script, bytes) else script.encode("utf-8")

    user, host = _parse_target(target)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        username=user,
        password=password,
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        _stdin, stdout, stderr = client.exec_command("bash -s", timeout=timeout)
        assert _stdin is not None
        # 用 bytes 直写 channel，避免 Windows 文本层编码导致 UnicodeEncodeError
        _stdin.channel.sendall(script_bytes)
        _stdin.channel.shutdown_write()
        out = stdout.read()
        err = stderr.read()
        if out:
            sys.stdout.buffer.write(out)
        if err:
            sys.stderr.buffer.write(err)
        return stdout.channel.recv_exit_status()
    finally:
        client.close()


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: ssh_password.py <user@host> command|< script", file=sys.stderr)
        return 1
    target = sys.argv[1]
    if sys.argv[2] == "--script":
        script = sys.stdin.buffer.read()
        return run_script(target, script)
    command = sys.argv[2]
    return run_command(target, command)


if __name__ == "__main__":
    raise SystemExit(main())
