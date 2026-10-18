"""Pipeline independent jobs; serialize profiling on one logical simulator Device.

The measurement adapter remains worker.py. This scheduler has a separate recorded identity.
CANN compilation/preparation may overlap; msopprof collection never overlaps on this Device.
"""

import argparse
import fcntl
import hashlib
import json
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from worker import SimulationJob, SimulatorWorker, atomic_json


# ---- PipelineJob ------------------------------------------------------------
class PipelineJob(SimulationJob):
    # ---- tolerate short Windows reader handles on the shared spool -----------
    def save(self):
        for attempt in range(8):
            try:
                super().save()
                return
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))

    # ---- one performance collector per logical Device -----------------------
    def run(self, args, phase, custom=None, timeout=600):
        if not phase.startswith("simulate:"):
            return super().run(args, phase, custom, timeout)
        self.record.update(phase="waiting-profiler:" + phase.split(":", 1)[1])
        self.save()
        wait_started = time.monotonic()
        with (self.worker.root / "profile-device-0.lock").open("a") as device_lock:
            fcntl.flock(device_lock, fcntl.LOCK_EX)
            # Waiting for the resource is not execution time or a kernel measurement.
            self.deadline += time.monotonic() - wait_started
            return super().run(args, phase, custom, timeout)


# ---- SimulatorPool ----------------------------------------------------------
class SimulatorPool(SimulatorWorker):
    def __init__(self, args):
        super().__init__(args)
        self.capacity = args.concurrency
        self.scheduler_identity = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        self.stop = threading.Event()

    # ---- actual capacity and active phases ----------------------------------
    def heartbeat(self, state="ready", job_id=None):
        with self.jobs_lock:
            active = [
                {"id": j.key, "team": j.request["team"], "phase": j.record.get("phase")}
                for j in self.jobs.values()
            ]
        atomic_json(
            self.spool / "heartbeat.json",
            {
                "schema": "justkernel.simulator.worker.v1",
                "state": state,
                "job_id": job_id or (active[0]["id"] if active else None),
                "worker_id": self.worker_id,
                "worker_sha256": self.identity,
                "scheduler": "pipeline-v1",
                "scheduler_sha256": self.scheduler_identity,
                "target_soc": "Ascend910B4",
                "cann_version": "9.0.0",
                "at": time.time(),
                "pid": __import__("os").getpid(),
                "concurrency": self.capacity,
                "profiling_concurrency": 1,
                "active_jobs": active,
                "physical_npu_required": False,
            },
        )

    # ---- preserve partial failures and immutable experiment identity ---------
    def execute_job(self, job):
        job.record.update(scheduler="pipeline-v1", scheduler_sha256=self.scheduler_identity)
        try:
            job.save()
            job.execute()
        except Exception as error:
            job.record.update(state="failed", error=str(error)[:2000])
        finally:
            job.record["finished_at"] = time.time()
            job.save()

    # ---- bounded parallel build, exclusive collector, cooperative draining ---
    def serve(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.spool.mkdir(parents=True, exist_ok=True)
        with (self.spool / "worker.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: self.stop.set())
            futures = {}
            with ThreadPoolExecutor(max_workers=8, thread_name_prefix="simulation") as executor:
                while not self.stop.is_set() or futures:
                    for key, future in list(futures.items()):
                        if future.done():
                            try:
                                future.result()
                            finally:
                                del futures[key]
                                with self.jobs_lock:
                                    self.jobs.pop(key, None)
                    control = self.spool / "pool-control.json"
                    if control.is_file():
                        value = json.loads(control.read_text(encoding="utf-8"))
                        desired = value.get("concurrency", self.capacity)
                        if type(desired) is int and 1 <= desired <= 8:
                            self.capacity = desired
                    if not self.stop.is_set():
                        requests = sorted(
                            self.spool.glob("jobs/*/request.json"), key=lambda p: p.stat().st_mtime
                        )
                        for path in requests:
                            if len(futures) >= self.capacity:
                                break
                            if (
                                path.parent.name in futures
                                or (path.parent / "result.json").exists()
                            ):
                                continue
                            job = PipelineJob(self, path)
                            with self.jobs_lock:
                                self.jobs[job.key] = job
                            futures[job.key] = executor.submit(self.execute_job, job)
                    self.heartbeat("busy" if futures else "ready")
                    time.sleep(1)
            self.heartbeat("stopped")


# ---- main -------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--spool", type=Path, required=True)
    parser.add_argument("--cann", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=1)
    SimulatorPool(parser.parse_args()).serve()


if __name__ == "__main__":
    main()
