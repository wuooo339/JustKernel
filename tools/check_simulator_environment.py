"""Read-only Linux/WSL preflight; never installs CANN or claims a simulation ran."""

import argparse
import json
import subprocess
from pathlib import Path

LINUX_PROBE = r"""
import glob
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return {"exit_code": p.returncode, "text": (p.stdout + p.stderr).strip()[:3000]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"exit_code": None, "text": str(e)}

def version(name):
    path = shutil.which(name)
    return {"path": path, "version": command([path, "--version"]) if path else None}

os_release = {}
for line in Path("/etc/os-release").read_text().splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        os_release[key] = value.strip('"')
memory = {}
for line in Path("/proc/meminfo").read_text().splitlines():
    key, value = line.split(":", 1)
    if key in {"MemTotal", "MemAvailable", "SwapTotal"}:
        memory[key] = int(value.split()[0]) * 1024
packages = {}
for name in ["build-essential", "cmake", "ninja-build", "python3-pip", "python3-dev",
             "libffi-dev", "libssl-dev", "libsqlite3-dev", "libbz2-dev", "liblzma-dev",
             "zlib1g-dev", "libnuma1", "unzip"]:
    p = command(["dpkg-query", "-W", "-f=${db:Status-Status} ${Version}", name])
    packages[name] = {"installed": p["exit_code"] == 0 and p["text"].startswith("installed "),
                      "detail": p["text"] if p["exit_code"] == 0 else "not installed"}
roots = [Path("/usr/local/Ascend"), Path("/opt/Ascend"), Path.home() / "Ascend"]
env_scripts = []
libraries = []
for root in roots:
    for pattern in ["set_env.sh", "*/set_env.sh", "*/*/set_env.sh"]:
        env_scripts.extend(str(p) for p in root.glob(pattern) if p.is_file())
    for pattern in ["tools/simulator/Ascend910B4*/lib", "*/tools/simulator/Ascend910B4*/lib",
                    "*/*/tools/simulator/Ascend910B4*/lib"]:
        libraries.extend(str(p) for p in root.glob(pattern) if p.is_dir())
module_probe = (
    "import importlib.util,json; "
    "print(json.dumps({n:importlib.util.find_spec(n) is not None "
    "for n in ['pip','numpy','sympy','psutil']}))"
)
pip = command(["python3", "-c", module_probe])
data = {
    "scope": "environment-preflight-only", "simulation_executed": False,
    "os": os_release, "kernel": platform.release(), "architecture": platform.machine(),
    "cpu_threads": os.cpu_count(), "memory_bytes": memory,
    "disk_bytes": dict(zip(["total", "used", "free"], shutil.disk_usage(str(Path.home())))),
    "commands": {n: version(n) for n in [
        "python3", "gcc", "g++", "cmake", "make", "ninja", "git", "curl", "wget",
        "docker", "msopprof", "msprof"]},
    "packages": packages, "python_modules": pip,
    "cann_env_scripts": sorted(set(env_scripts)),
    "target_simulator_libraries": sorted(set(libraries)),
    "sudo_noninteractive": command(["sudo", "-n", "true"])["exit_code"] == 0,
    "physical_npu_devices": sorted(glob.glob("/dev/davinci[0-9]*")),
    "target_soc": "Ascend910B4",
    "wsl_support": "requires an actual CANN compile and simulation smoke test; not certified",
}
print(json.dumps(data, ensure_ascii=False))
"""


# ---- process_text -----------------------------------------------------------
def process_text(data: bytes) -> str:
    if b"\0" in data:
        return data.decode("utf-16-le", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gb18030", "replace")


# ---- main ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wsl", help="Windows WSL distribution, e.g. Ubuntu-22.04")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    command = ["wsl", "-d", args.wsl, "--", "python3", "-"] if args.wsl else ["python3", "-"]
    completed = subprocess.run(
        command, input=LINUX_PROBE.encode("utf-8"), capture_output=True, timeout=90
    )
    stdout = process_text(completed.stdout)
    stderr = process_text(completed.stderr)
    if completed.returncode:
        raise SystemExit(stderr or stdout)
    report = json.loads(stdout)
    report["distribution"] = args.wsl
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
