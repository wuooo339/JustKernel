"""Standalone Python 3.10+ CANN worker; no model credentials or physical NPU lease.

The local controller commits immutable requests to a private workbench spool.
One worker serializes CANN simulation; each job builds and runs in its own Linux directory.
This is a developer execution environment for trusted team code, not an OS sandbox.
"""

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import torch

if torch.__version__ != "2.14.1+cpu":
    raise RuntimeError(
        "Simulator reference requires torch==2.14.1+cpu; install CPU Worker dependencies"
    )
torch.set_num_threads(1)


# ---- reference_outputs ------------------------------------------------------
def reference_outputs(inputs, axes, keep_dims):
    """Execute the statement's FP32 PyTorch reference, with a fixed CPU reduction.

    NumPy FP32 sum uses a different reduction order and can disagree beyond the
    absolute tolerance on large reductions. Neither local reference reproduces
    hidden official inputs or guarantees their runtime's reduction ordering.
    """
    a, b, c = (torch.from_numpy(value).float() for value in inputs)
    dtype = torch.float16 if inputs[0].dtype == np.float16 else torch.float32
    with torch.inference_mode():
        return [
            (a * b).to(dtype).numpy(),
            (b * c).sum(dim=axes, keepdim=keep_dims).to(dtype).numpy(),
        ]


# ---- atomic_json ------------------------------------------------------------
def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix("." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(10):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05 * (attempt + 1))


# ---- source_identity --------------------------------------------------------
def source_identity(files):
    return hashlib.sha256(
        json.dumps(files, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


# ---- safe_path --------------------------------------------------------------
def safe_path(root, name):
    if not name or "\\" in name or any(x in {"", ".", ".."} for x in name.split("/")):
        raise ValueError("invalid relative file path")
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("file escaped job directory")
    return path


# ---- SimulationJob ----------------------------------------------------------
class SimulationJob:
    def __init__(self, worker, request_file):
        self.worker = worker
        self.spool = request_file.parent
        raw = request_file.read_bytes()
        self.request = json.loads(raw)
        self.key = self.spool.name
        if not re.fullmatch(r"[a-f0-9]{32}", self.key):
            raise ValueError("invalid simulation job identity")
        self.folder = worker.root / "jobs" / self.key
        self.record = {
            "schema": "justkernel.simulation.v1",
            "id": self.key,
            "team": self.request["team"],
            "operator": self.request["operator"],
            "workspace_id": self.request["workspace_id"],
            "request_sha256": hashlib.sha256(raw).hexdigest(),
            "source_sha256": self.request["source_sha256"],
            "case_pack_sha256": self.request["case_pack_sha256"],
            "target_soc": "Ascend910B4",
            "cann_version": "9.0.0",
            "worker_sha256": worker.identity,
            "source": "cann-simulator",
            "state": "running",
            "phase": "prepare",
            "started_at": time.time(),
            "cases": [],
            "functional_pass": False,
            "official_score": None,
            "npu_latency_us": None,
            "reference": {
                "engine": "pytorch-cpu-fp32-v1",
                "version": torch.__version__,
                "threads": 1,
            },
        }
        self.deadline = time.monotonic() + min(int(self.request.get("timeout_seconds", 1800)), 3600)

    # ---- real child execution and bounded diagnostics -----------------------
    def save(self):
        atomic_json(self.spool / "result.json", self.record)

    def run(self, args, phase, custom=None, timeout=600):
        self.record.update(phase=phase, command=args)
        self.save()
        prefix = "source " + shlex.quote(str(self.worker.cann / "set_env.sh")) + "\n"
        prefix += "export PATH=" + shlex.quote(str(Path(sys.executable).parent)) + ':"$PATH"\n'
        prefix += (
            "export PYTHONPYCACHEPREFIX=" + shlex.quote(str(self.worker.root / "pycache")) + "\n"
        )
        simulator = self.worker.cann / "x86_64-linux/simulator/Ascend910B4/lib"
        prefix += (
            "export LD_LIBRARY_PATH=" + shlex.quote(str(simulator)) + ':"${LD_LIBRARY_PATH:-}"\n'
        )
        if custom:
            prefix += "export ASCEND_CUSTOM_OPP_PATH=" + shlex.quote(str(custom)) + "\n"
            prefix += "export LD_LIBRARY_PATH=" + shlex.quote(str(custom / "op_api/lib"))
            prefix += ':"${LD_LIBRARY_PATH:-}"\n'
        command = ["bash", "--noprofile", "--norc", "-c", "set -e\n" + prefix + shlex.join(args)]
        with (self.spool / "execution.log").open("ab") as log:
            log.write(("\nPHASE " + phase + "\n" + shlex.join(args) + "\n").encode())
            log.flush()
            process = subprocess.Popen(
                command,
                cwd=self.folder,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            self.record["child_pid"] = process.pid
            self.save()
            remaining = max(1, min(timeout, self.deadline - time.monotonic()))
            try:
                code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise ValueError(phase + " timed out") from None
            finally:
                self.record.pop("child_pid", None)
            if code:
                raise ValueError(phase + " failed (exit " + str(code) + "); inspect execution.log")

    # ---- immutable input and source preparation -----------------------------
    def execute(self):
        req = self.request
        if req.get("schema") != "justkernel.simulation.request.v1":
            raise ValueError("unsupported simulation request")
        if req["operator"] != "ConfusionMulGrad" or req.get("target_soc") != "Ascend910B4":
            raise ValueError("this trusted adapter supports ConfusionMulGrad on Ascend910B4")
        if req.get("worker_sha256") != self.worker.identity:
            raise ValueError("worker/adapter changed; request a fresh experiment")
        if source_identity(req["files"]) != req["source_sha256"]:
            raise ValueError("source hash mismatch")
        if hashlib.sha256(req["cases_json"].encode()).hexdigest() != req["case_pack_sha256"]:
            raise ValueError("input pack hash mismatch")
        self.folder.mkdir(parents=True, exist_ok=False)
        source = self.folder / "source"
        source.mkdir()
        for name, text in req["files"].items():
            path = safe_path(source, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
        available = json.loads(req["cases_json"])
        selected = set(req["case_ids"])
        cases = [c for c in available if c["id"] in selected]
        if not selected or len(selected) != len(cases):
            raise ValueError("select distinct known local cases")
        self.record["case_ids"] = [c["id"] for c in cases]
        self.run(
            [
                "cmake",
                "-S",
                str(self.worker.adapter),
                "-B",
                "build",
                "-DASCEND_CANN_PACKAGE_PATH=" + str(self.worker.cann),
                "-DCANDIDATE_ROOT=" + str(source),
                "-DASCEND_COMPUTE_UNIT=ascend910b",
                "-Dvendor_name=justkernel",
            ],
            "configure",
        )
        self.run(["cmake", "--build", "build", "--target", "binary", "-j2"], "compile")
        binaries = list((self.folder / "build").rglob("kernel_meta/*.o"))
        if not binaries:
            binaries = list((self.folder / "build").rglob("kernel/*/*.o"))
        self.record["compiled_binaries"] = [
            {
                "path": str(p.relative_to(self.folder)),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
            for p in binaries
        ]
        self.run(["cmake", "--build", "build", "--target", "package", "-j2"], "package")
        packages = list((self.folder / "build").glob("*.run"))
        if len(packages) != 1:
            raise ValueError("expected one compiled private operator package")
        self.run(
            ["bash", str(packages[0]), "--quiet", "--install-path=" + str(self.folder / "install")],
            "deploy",
        )
        vendors = [p.parent for p in (self.folder / "install").rglob("op_api") if p.is_dir()]
        if len(vendors) != 1:
            raise ValueError("private operator package layout not recognized")
        custom = vendors[0]
        header = next((self.folder / "build").rglob("aclnn_confusion_mul_grad.h"))
        self.run(
            [
                "g++",
                "-std=c++17",
                "-D_GLIBCXX_USE_CXX11_ABI=0",
                str(self.worker.adapter / "runner.cpp"),
                "-o",
                "runner",
                "-I" + str(header.parent),
                "-I" + str(self.worker.cann / "include"),
                "-L" + str(custom / "op_api/lib"),
                "-L" + str(self.worker.cann / "lib64"),
                "-lcust_opapi",
                "-lascendcl",
                "-lnnopbase",
            ],
            "build-driver",
            custom,
        )
        mode = req.get("evaluation_mode", "full-profile")
        self.record["evaluation_mode"] = mode
        if mode == "functional-then-profile":
            for case in cases:
                self.evaluate_case(case, custom, profile=False)
            self.record["functional_pass"] = True
            self.record["functional_finished_at"] = time.time()
            self.save()
            wanted = req.get("profile_case_ids", [])
            if not set(wanted) <= {c["id"] for c in cases}:
                raise ValueError("invalid representative profiling cases")
            for case in cases:
                if case["id"] in wanted:
                    self.evaluate_case(case, custom, profile=True, append=False)
        elif mode == "full-profile":
            for case in cases:
                self.evaluate_case(case, custom)
        else:
            raise ValueError("unsupported evaluation mode")
        actual = {name: safe_path(source, name).read_bytes().decode() for name in req["files"]}
        if source_identity(actual) != req["source_sha256"]:
            raise ValueError("source changed during build/evaluation")
        self.record.update(state="completed", phase="completed", functional_pass=True)

    # ---- local correctness and real official-tool output --------------------
    def evaluate_case(self, case, custom, profile=True, append=True):
        shape = tuple(case["shape"])
        if len(shape) != 2 or any(not isinstance(n, int) or n < 1 for n in shape):
            raise ValueError("invalid local shape")
        dtype = np.dtype(case["dtype"])
        if dtype not in {np.dtype("float16"), np.dtype("float32")}:
            raise ValueError("invalid local dtype")
        axes = tuple(sorted({int(a) % 2 for a in case["axis"]}))
        if not axes or any(int(a) not in {-2, -1, 0, 1} for a in case["axis"]):
            raise ValueError("invalid reduction axes")
        folder = self.folder / "cases" / case["id"]
        folder.mkdir(parents=True, exist_ok=not append)
        rng = np.random.default_rng(case["seed"])
        dist = case["distribution"]
        if dist["kind"] != "uniform":
            raise ValueError("unsupported input generator")
        inputs = [
            rng.uniform(dist["low"], dist["high"], size=shape).astype(dtype) for _ in range(3)
        ]
        for i, data in enumerate(inputs):
            data.tofile(folder / ("input" + str(i) + ".bin"))
        golden = reference_outputs(inputs, axes, case["keep_dims"])
        args = [str(n) for n in shape] + [
            case["dtype"],
            str(sum(1 << a for a in axes)),
            str(int(case["keep_dims"])),
            str(folder),
            str(folder),
        ]
        output = folder / "profile"
        if profile:
            self.run(
                [
                    "msopprof",
                    "simulator",
                    "--soc-version=Ascend910B4",
                    "--output=" + str(output),
                    str(self.folder / "runner"),
                    *args,
                ],
                "simulate:" + case["id"],
                custom,
            )
        else:
            defaults = self.worker.cann / "x86_64-linux/simulator/Ascend910B4/lib"
            config = folder / "functional-config"
            config.mkdir(exist_ok=True)
            for path in defaults.glob("*.json"):
                data = json.loads(path.read_text(encoding="utf-8"))
                if path.name == "config.json":
                    # Functional validation needs tensor outputs, not instruction dumps.
                    # The separate msopprof phase retains its full tracing configuration.
                    data["LOG"]["core_enable_mask"] = ["0x0"]
                (config / path.name).write_text(json.dumps(data), encoding="utf-8")
            log = folder / "functional-pvmodel"
            log.mkdir(exist_ok=True)
            self.run(
                [
                    "env",
                    "LD_PRELOAD=libruntime_cmodel.so",
                    "CAMODEL_SOC_VERSION=Ascend910B4",
                    "CAMODEL_CONFIG_PATH=" + str(config),
                    "CAMODEL_LOG_PATH=" + str(log),
                    str(self.folder / "runner"),
                    *args,
                ],
                "functional:" + case["id"],
                custom,
            )
        checks = []
        tolerance = 1e-3 if dtype == np.dtype("float16") else 1e-4
        for i, expected in enumerate(golden):
            actual = np.fromfile(folder / ("output" + str(i) + ".bin"), dtype=dtype)
            if actual.size != expected.size:
                raise ValueError("output size mismatch: " + case["id"])
            a, b = actual.astype(np.float64), expected.reshape(-1).astype(np.float64)
            absolute = np.abs(a - b)
            relative = absolute / np.maximum(np.abs(b), 1e-6)
            # Explicit strict local gate from statement, not a claim of official equivalence.
            passed = bool(
                np.all(np.isfinite(a))
                and np.all(absolute < tolerance)
                and np.all(relative < tolerance)
            )
            checks.append(
                {
                    "output": i,
                    "pass": passed,
                    "max_abs": float(absolute.max()),
                    "max_rel": float(relative.max()),
                    "tolerance": tolerance,
                }
            )
        raw = []
        for path in sorted(output.rglob("*")):
            if not path.is_file() or path.suffix not in {".csv", ".json", ".bin"}:
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(output.resolve()):
                raise ValueError("profiling output escaped its directory")
            item = {"path": path.relative_to(self.folder).as_posix(), "size": path.stat().st_size}
            if path.suffix == ".csv":
                with path.open(encoding="utf-8-sig", errors="replace") as stream:
                    reader = csv.reader(stream)
                    item["preview"] = [row for _, row in zip(range(12), reader, strict=False)]
            raw.append(item)
        if profile and not any(
            p["size"] > 0 and (p["path"].endswith("trace.json") or p["path"].endswith(".csv"))
            for p in raw
        ):
            raise ValueError("simulator produced no trace or profiling CSV")
        item = {
            "id": case["id"],
            "shape": list(shape),
            "dtype": case["dtype"],
            "official_case_id": None,
            "pass": all(c["pass"] for c in checks),
            "correctness": checks,
            "profiling_files": raw[:40],
            "cycles": None,
            "note": "Raw simulator metrics; no conversion to hardware time or official score",
            "validation_kind": "profiled-camodel" if profile else "functional-pvmodel",
        }
        if append:
            self.record["cases"].append(item)
        else:
            previous = next(c for c in self.record["cases"] if c["id"] == case["id"])
            previous.update(
                profiling_files=item["profiling_files"],
                profile_pass=item["pass"],
                profile_correctness=item["correctness"],
            )
        self.save()
        if not item["pass"]:
            raise ValueError("local numerical validation failed: " + case["id"])


# ---- SimulatorWorker --------------------------------------------------------
class SimulatorWorker:
    def __init__(self, args):
        self.root, self.spool = args.root.resolve(), args.spool.resolve()
        self.cann = args.cann.resolve()
        self.adapter = Path(__file__).resolve().parent
        self.identity = hashlib.sha256(
            b"".join(
                (self.adapter / name).read_bytes()
                for name in ["worker.py", "runner.cpp", "CMakeLists.txt"]
            )
        ).hexdigest()
        self.worker_id = uuid4().hex

    # ---- one CPU worker, independent immutable team jobs ---------------------
    def heartbeat(self, state="ready", job_id=None):
        atomic_json(
            self.spool / "heartbeat.json",
            {
                "schema": "justkernel.simulator.worker.v1",
                "state": state,
                "job_id": job_id,
                "worker_id": self.worker_id,
                "worker_sha256": self.identity,
                "target_soc": "Ascend910B4",
                "cann_version": "9.0.0",
                "at": time.time(),
                "pid": os.getpid(),
                "concurrency": 1,
                "physical_npu_required": False,
            },
        )

    def serve(self):
        import threading

        self.root.mkdir(parents=True, exist_ok=True)
        self.spool.mkdir(parents=True, exist_ok=True)
        with (self.spool / "worker.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            current = {"job": None}
            stop = threading.Event()

            def pulse():
                while not stop.wait(3):
                    self.heartbeat("busy" if current["job"] else "ready", current["job"])

            self.heartbeat()
            pulse_thread = threading.Thread(target=pulse, daemon=True)
            pulse_thread.start()
            try:
                while True:
                    requests = sorted(
                        self.spool.glob("jobs/*/request.json"), key=lambda p: p.stat().st_mtime
                    )
                    for path in requests:
                        if (path.parent / "result.json").exists():
                            continue
                        current["job"] = path.parent.name
                        job = SimulationJob(self, path)
                        job.save()
                        try:
                            job.execute()
                        except Exception as error:
                            job.record.update(state="failed", error=str(error)[:2000])
                        finally:
                            job.record["finished_at"] = time.time()
                            job.save()
                            current["job"] = None
                    time.sleep(1)
            finally:
                stop.set()
                self.heartbeat("stopped")


# ---- main ------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--spool", type=Path, required=True)
    parser.add_argument("--cann", type=Path, required=True)
    args = parser.parse_args()
    SimulatorWorker(args).serve()


if __name__ == "__main__":
    main()
