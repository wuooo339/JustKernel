#!/usr/bin/env bash
set -eu
if [ "$#" -lt 4 ] || [ "$#" -gt 5 ]; then
    echo "Usage: bash tools/start_simulator_worker.sh LINUX_ROOT CANN_ROOT PYTHON SHARED_SPOOL [JOBS=1]" >&2
    exit 64
fi
sim_root=$1
sim_cann=$2
sim_python=$3
sim_spool=$4
sim_jobs=${5:-1}
case "$sim_jobs" in [1-8]) ;; *) echo "JOBS must be 1..8" >&2; exit 64 ;; esac
sim_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sim_worker="$sim_script_dir/../src/aworker/lab/resources/simulator/pool.py"
mkdir -p -- "$sim_root" "$sim_spool" "$sim_root/tmp"
# Keep one worker per shared queue, including simultaneous launch attempts.
exec 9>"$sim_spool/launcher.lock"
if ! flock -n 9; then
    echo "仿真 Worker 正在启动，请在面板查看状态，无需重复启动。"
    exit 0
fi
if ! flock -n "$sim_spool/worker.lock" true; then
    "$sim_python" -c 'import json,pathlib,sys; p=pathlib.Path(sys.argv[1]); t=p.with_suffix(".tmp"); t.write_text(json.dumps({"concurrency":int(sys.argv[2])})); t.replace(p)' "$sim_spool/pool-control.json" "$sim_jobs"
    echo "仿真 Worker 已在运行，保留当前实验和日志，无需重复启动。"
    exit 0
fi
nohup env TMPDIR="$sim_root/tmp" "$sim_python" -X "pycache_prefix=$sim_root/pycache" "$sim_worker" \
    --root "$sim_root" --cann "$sim_cann" --spool "$sim_spool" --concurrency "$sim_jobs" \
    >> "$sim_root/worker.log" 2>&1 < /dev/null 9>&- &
sim_pid=$!
sleep 1
if ! kill -0 "$sim_pid" 2>/dev/null; then
    tail -n 30 "$sim_root/worker.log" >&2
    exit 1
fi
echo "CANN pipeline started: $sim_pid ($sim_jobs concurrent jobs; 1 exclusive profiler Device)"
