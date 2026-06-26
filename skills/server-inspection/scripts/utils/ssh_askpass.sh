#!/bin/sh
# SSH_ASKPASS 辅助：从 SSH_ASKPASS_FILE 或 SSH_TARGET_PASSWORD 输出密码
if [ -n "${SSH_ASKPASS_FILE:-}" ] && [ -f "$SSH_ASKPASS_FILE" ]; then
    cat "$SSH_ASKPASS_FILE"
elif [ -n "${SSH_TARGET_PASSWORD:-}" ]; then
    printf '%s' "$SSH_TARGET_PASSWORD"
fi
