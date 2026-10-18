"""Real thread/file-lock pipeline scheduling, using synthetic execution only."""

import importlib.util
import json
import signal
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


# ---- atomic_fixture ---------------------------------------------------------
def atomic_fixture(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---- PipelineTests ----------------------------------------------------------
@unittest.skipIf(sys.platform == "win32", "Linux Worker file-lock semantics")
class PipelineTests(unittest.TestCase):
    # ---- bounded compile overlap and exclusive profiler ---------------------
    def test_two_builds_overlap_but_collectors_never_overlap(self):
        stats = {"build": 0, "profile": 0, "max_build": 0, "max_profile": 0, "finished": 0}
        stats_lock, first_builds = threading.Lock(), threading.Barrier(2)

        class BaseWorker:
            def __init__(self, args):
                self.root, self.spool, self.cann = args.root, args.spool, args.cann
                self.worker_id, self.identity = "fixture-worker", "fixture-adapter"

        class BaseJob:
            def __init__(self, worker, path):
                self.worker, self.spool, self.key = worker, path.parent, path.parent.name
                self.request = json.loads(path.read_text())
                self.record = {"state": "running", "phase": "prepare"}
                self.deadline = time.monotonic() + 60

            def save(self):
                atomic_fixture(self.spool / "result.json", self.record)

            def run(self, args, phase, custom=None, timeout=600):
                key = "profile" if phase.startswith("simulate:") else "build"
                with stats_lock:
                    stats[key] += 1
                    stats["max_" + key] = max(stats["max_" + key], stats[key])
                if key == "build" and self.request["team"] in {"fixture-1", "fixture-2"}:
                    first_builds.wait(timeout=5)
                time.sleep(0.04)
                with stats_lock:
                    stats[key] -= 1

            def execute(self):
                self.run([], "compile")
                self.run([], "simulate:fixture-case")
                self.record.update(state="completed", phase="completed")
                with stats_lock:
                    stats["finished"] += 1
                    if stats["finished"] == 3:
                        self.worker.stop.set()

        fake = types.SimpleNamespace(
            SimulationJob=BaseJob, SimulatorWorker=BaseWorker, atomic_json=atomic_fixture
        )
        path = Path(__file__).resolve().parents[1] / "src/aworker/lab/resources/simulator/pool.py"
        spec = importlib.util.spec_from_file_location("fixture_pool", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"worker": fake}):
            spec.loader.exec_module(module)
        with TemporaryDirectory(
            dir=Path(__file__).resolve().parents[1] / ".justkernel-test-tmp"
        ) as tmp:
            root = Path(tmp)
            spool = root / "spool"
            for i in range(1, 4):
                atomic_fixture(spool / "jobs" / str(i) / "request.json", {"team": f"fixture-{i}"})
            args = types.SimpleNamespace(root=root, spool=spool, cann=root, concurrency=2)
            pool = module.SimulatorPool(args)
            original_handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
            watchdog = threading.Timer(10, pool.stop.set)
            watchdog.start()
            try:
                pool.serve()
            finally:
                watchdog.cancel()
                for sig, handler in original_handlers.items():
                    signal.signal(sig, handler)
            records = [json.loads(p.read_text()) for p in spool.glob("jobs/*/result.json")]
            self.assertEqual(len(records), 3)
            self.assertTrue(all(r["state"] == "completed" for r in records))
            self.assertEqual(stats["max_build"], 2)
            self.assertEqual(stats["max_profile"], 1)
            heartbeat = json.loads((spool / "heartbeat.json").read_text())
            self.assertEqual(heartbeat["concurrency"], 2)
            self.assertEqual(heartbeat["profiling_concurrency"], 1)
            self.assertEqual(heartbeat["state"], "stopped")


if __name__ == "__main__":
    unittest.main()
