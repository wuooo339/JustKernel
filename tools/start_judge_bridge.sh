#!/usr/bin/env bash
set -eu
if [ "$#" -ne 4 ]; then
    echo "Usage: bash tools/start_judge_bridge.sh LINUX_ROOT PYTHON SHARED_SPOOL OFFICIAL_URL" >&2
    exit 64
fi
judge_root=$1
judge_python=$2
judge_spool=$3
judge_url=$4
judge_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p -- "$judge_root" "$judge_spool"
# Serialize launch attempts separately from the worker's lifetime lock.
exec 9>"$judge_spool/launcher.lock"
if ! flock -n 9; then
    echo "官测浏览器服务正在启动，请在面板查看状态，无需重复启动。"
    exit 0
fi
if ! flock -n "$judge_spool/worker.lock" true; then
    echo "官测浏览器服务已在运行，保留现有窗口和登录，无需再次启动。"
    echo "请在面板 Judger 查看登录状态；窗口关闭时点击连接重新打开。"
    exit 0
fi
nohup env PYTHONPATH="$judge_script_dir/../src" PYTHONPYCACHEPREFIX="$judge_root/pycache" \
    dbus-run-session -- "$judge_python" -m aworker.lab.judge_bridge --root "$judge_root" --spool "$judge_spool" \
    --open "$judge_url" >> "$judge_root/bridge.log" 2>&1 < /dev/null 9>&- &
judge_pid=$!
sleep 3
if ! kill -0 "$judge_pid" 2>/dev/null; then
    tail -n 30 "$judge_root/bridge.log" >&2
    exit 1
fi
echo "官测浏览器服务进程已启动：$judge_pid；窗口和登录是否就绪，请以面板状态为准。"
