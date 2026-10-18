"""Recover native interpreter crashes without resetting model evidence or judge budgets."""

import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from aworker.config import Settings
from aworker.lab.lifecycle import service_lock
from aworker.lab.persistence import replace_file


# ---- native_crash -----------------------------------------------------------
def native_crash(code):
    # Intentional exits (including Windows Stop-Process / Ctrl+C) stay stopped.
    return code in {-signal.SIGSEGV, -signal.SIGABRT} or code & 0xFFFFFFFF in {
        0xC0000005,
        0xC0000409,
        0xC00000FD,
    }


# ---- wait_existing ----------------------------------------------------------
def wait_existing(pid, root):
    """Read-only attachment to this workspace's existing Windows service."""
    if sys.platform != "win32":
        raise ValueError("attaching an existing service is only supported on Windows")
    if (root / "service.pid").read_text(encoding="utf-8").strip() != str(pid):
        raise ValueError("service PID does not match this workspace")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel.GetExitCodeProcess.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        while kernel.WaitForSingleObject(handle, 1000) == 0x102:
            pass
        code = ctypes.c_uint32()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value
    finally:
        kernel.CloseHandle(handle)


# ---- supervise --------------------------------------------------------------
def supervise(
    settings, attach=None, open_browser=False, spawn=subprocess.Popen, wait=wait_existing
):
    root = settings.lab_root.resolve()
    child = None
    restarts = 0
    recent = []
    path = root / "supervisor.json"

    def record(state, pid, code=None):
        value = {
            "state": state,
            "supervisor_pid": os.getpid(),
            "service_pid": pid,
            "root": str(root),
            "restarts": restarts,
            "last_exit": code,
            "updated_at": time.time(),
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value), encoding="utf-8")
        replace_file(temporary, path)

    with service_lock(root / "supervision"):
        try:
            while True:
                started = time.monotonic()
                if attach is not None:
                    pid = attach
                    record("watching", pid)
                    code = wait(pid, root)
                    attach = None
                else:
                    command = [
                        sys._base_executable if sys.platform == "win32" else sys.executable,
                        "-X",
                        "faulthandler",
                        "-u",
                        "-m",
                        "aworker.lab.cli",
                        "--root",
                        str(root),
                        "serve",
                        "--host",
                        settings.lab_host,
                        "--port",
                        str(settings.lab_port),
                    ]
                    if open_browser:
                        command.append("--open")
                        open_browser = False
                    child = spawn(command, env=settings.service_environment())
                    pid = child.pid
                    record("watching", pid)
                    code = child.wait()
                    child = None
                record("exited", pid, code)
                if not native_crash(code):
                    return code
                recent = [t for t in recent if time.monotonic() - t < 60]
                recent.append(time.monotonic())
                if len(recent) >= 5:
                    record("crash-loop", pid, code)
                    print(
                        "JustKernel: repeated native crashes; preserving work and stopping.",
                        flush=True,
                    )
                    return code
                restarts += 1
                delay = 2 if time.monotonic() - started > 60 else min(60, 2 ** len(recent))
                record("recovering", pid, code)
                print(f"JustKernel: native exit {code}; restoring service in {delay}s.", flush=True)
                time.sleep(delay)
        except KeyboardInterrupt:
            if child and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
            record("stopped", None)
            return 0


# ---- main -------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="JustKernel native-crash recovery")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--attach", type=int, default=None)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args()
    overrides = {
        "lab_" + k: v
        for k, v in vars(args).items()
        if k not in {"attach", "open_browser"} and v is not None
    }
    raise SystemExit(
        supervise(Settings(**overrides), attach=args.attach, open_browser=args.open_browser)
    )


if __name__ == "__main__":
    main()
