"""Immutable candidate snapshots submitted through one physical-device queue."""

import hashlib
import json
import re
import shlex
import shutil
import subprocess
import tarfile
import threading
import time
from pathlib import Path, PurePosixPath

from aworker.config import Settings
from aworker.lab.domain import Stage, StageUpdate
from aworker.lab.store import LabStore, identifier


# ---- RemoteRunner -----------------------------------------------------------
class RemoteRunner:
    def __init__(
        self,
        settings: Settings,
        store: LabStore,
        transport=None,
        evaluator: Path | None = None,
        register_device: bool = True,
    ):
        self.settings = settings
        self.store = store
        self.root = settings.lab_root.resolve()
        self.evaluator = evaluator or Path(__file__).resolve().parent / "resources" / "evaluator"
        self.transport = transport
        self.remote = PurePosixPath(settings.lab_remote_root)
        if not self.remote.is_absolute() or ".." in self.remote.parts:
            raise ValueError("remote root must be an absolute clean path")
        if not settings.lab_ssh_host or (
            transport is None and not re.fullmatch(r"[\w.-]+", settings.lab_ssh_host)
        ):
            raise ValueError("configure an SSH Host alias")
        self.host = settings.lab_ssh_host
        if register_device:
            store.register_device("npu-0", self.host, settings.lab_device)

    # ---- remote commands ----------------------------------------------------
    def ssh(self, script: str, timeout: int = 30) -> subprocess.CompletedProcess:
        if self.transport:
            return self.transport.run(script, timeout)
        result = subprocess.run(
            [
                "ssh",
                *self.settings.lab_ssh_options,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=12",
                self.host,
                "bash -s",
            ],
            input=script.replace("\r\n", "\n").encode("utf-8"),
            capture_output=True,
            timeout=timeout,
        )
        return subprocess.CompletedProcess(
            result.args,
            result.returncode,
            result.stdout.decode("utf-8", "replace"),
            result.stderr.decode("utf-8", "replace"),
        )

    def check(self) -> str:
        result = self.ssh(self.environment() + "\nnpu-smi info\n")
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        return result.stdout

    def environment(self) -> str:
        return (
            "set -euo pipefail\nsource " + shlex.quote(self.settings.lab_cann_env) + "\n"
            "export LD_LIBRARY_PATH=/usr/local/Ascend/driver/lib64/common:"
            "/usr/local/Ascend/driver/lib64/driver:${LD_LIBRARY_PATH:-}\n"
        )

    # ---- evaluation ---------------------------------------------------------
    def evaluate(self, team: str, source: str, run_id: str | None = None) -> dict:
        identifier(team)
        if not source or len(source.encode()) > 2_000_000:
            raise ValueError("candidate must be 1 byte to 2 MB")
        digest = hashlib.sha256(source.encode()).hexdigest()
        job = self.store.enqueue(team)
        self.store.stage(
            team,
            StageUpdate(
                stage=Stage.QUEUE,
                state="started",
                message="Waiting for an exclusive physical NPU lease",
                run_id=run_id,
                evidence=job,
            ),
        )
        folder = self.root / "jobs" / job
        folder.mkdir(parents=True)
        (folder / "kernel.asc").write_text(source, encoding="utf-8", newline="\n")
        for name in ("CMakeLists.txt", "main.asc", "evaluate.py"):
            shutil.copyfile(self.evaluator / name, folder / name)
        if (self.evaluator / "reference.py").exists():
            shutil.copyfile(self.evaluator / "reference.py", folder / "reference.py")
        shutil.copyfile(self.root / "challenge" / "cases.json", folder / "cases.json")
        case_digest = hashlib.sha256((folder / "cases.json").read_bytes()).hexdigest()
        input_source = self.root / "challenge" / "input-source.json"
        if input_source.exists():
            shutil.copyfile(input_source, folder / "input-source.json")
        self.store.event(team, "candidate.created", job_id=job, sha256=digest)
        deadline = time.monotonic() + self.settings.lab_job_timeout
        lease = None
        finished = False
        try:
            while lease is None:
                if time.monotonic() > deadline:
                    raise TimeoutError("device queue timeout")
                lease = self.store.claim(job, self.settings.lab_max_active)
                if lease is None:
                    time.sleep(0.3)
            self.store.event(
                team,
                "device.acquired",
                job_id=job,
                logical_npu=team,
                physical_npu=lease["id"],
                source_sha256=digest,
                run_id=run_id,
            )
            self.store.stage(
                team,
                StageUpdate(
                    stage=Stage.QUEUE,
                    state="completed",
                    message="Physical NPU lease acquired",
                    run_id=run_id,
                    evidence=job,
                ),
            )
            result = self._execute(job, folder, lease["device"], team, run_id)
            result.update({"job_id": job, "team": team, "source_sha256": digest})
            result["case_pack_sha256"] = case_digest
            (folder / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            self.store.finish(job, lease["token"], None if result["pass"] else "validation failed")
            finished = True
            self.store.event(team, "evaluation.completed", run_id=run_id, **result)
            self.store.stage(
                team,
                StageUpdate(
                    stage=Stage.EXECUTE,
                    state="completed",
                    message="Device evaluation finished; result saved",
                    run_id=run_id,
                    evidence=job,
                ),
            )
            self.store.stage(
                team,
                StageUpdate(
                    stage=Stage.VERIFY,
                    state="completed" if result["pass"] else "failed",
                    message=(
                        f"{sum(c['pass'] for c in result['cases'])}/"
                        f"{len(result['cases'])} local cases passed"
                    ),
                    run_id=run_id,
                    evidence=job,
                ),
            )
            return result
        except BaseException as exc:
            if lease and not finished:
                self.store.finish(job, lease["token"], str(exc))
            else:
                self.store.cancel_queued(job)
            self.store.event(team, "evaluation.failed", job_id=job, message=str(exc))
            self.store.stage(
                team,
                StageUpdate(
                    stage=Stage.EXECUTE,
                    state="failed",
                    message=str(exc)[:1000],
                    run_id=run_id,
                    evidence=job,
                ),
            )
            raise
        finally:
            if lease:
                self.store.event(team, "device.released", job_id=job)

    def _execute(self, job: str, folder: Path, device: int, team: str, run_id: str | None) -> dict:
        remote = str(self.remote / "jobs" / job)
        quote = shlex.quote
        archive = folder / "payload.tar.gz"
        names = ["kernel.asc", "CMakeLists.txt", "main.asc", "evaluate.py", "cases.json"]
        if (folder / "reference.py").exists():
            names.append("reference.py")
        with tarfile.open(archive, "w:gz") as tar:
            for name in names:
                tar.add(folder / name, arcname=name)
        created = self.ssh("set -eu\nmkdir -p " + quote(remote) + "\n")
        if created.returncode:
            raise RuntimeError(created.stderr[-2000:])
        if self.transport:
            self.transport.upload(archive, remote + "/payload.tar.gz")
            copied = subprocess.CompletedProcess([], 0, "", "")
        else:
            copied = subprocess.run(
                [
                    "scp",
                    "-q",
                    *self.settings.lab_ssh_options,
                    "-o",
                    "BatchMode=yes",
                    str(archive),
                    f"{self.host}:{remote}/payload.tar.gz",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        if copied.returncode:
            raise RuntimeError(copied.stderr[-2000:])
        inner = (
            self.environment() + "cd " + quote(remote) + "\n"
            "tar -xzf payload.tar.gz\n"
            "npu-smi info > device-before.txt\n"
            "for attempt in $(seq 1 15); do\n"
            "  npu-smi info > device-before.txt\n"
            "  if python3 -c "
            + quote(
                "import re,sys; from pathlib import Path; "
                "s=Path('device-before.txt').read_text(); "
                "p=s.split('Process id',1)[-1]; "
                "busy=any(int(m[1])==int(sys.argv[1]) for m in "
                "re.finditer(r'\\|\\s*(\\d+)\\s+\\d+\\s+\\d+\\s+',p)); "
                "sys.exit(1 if busy or 'Process id' not in s else 0)"
            )
            + " "
            + str(device)
            + "; then break; fi\n"
            '  if [ "$attempt" = 15 ]; then '
            "echo 'NPU busy outside JustKernel' >&2; exit 75; fi\n"
            '  echo \'JK_EVENT:{"stage":"queue","state":"progress",'
            '"message":"Waiting for NPU work outside JustKernel to finish"}\'\n'
            "  sleep 3\ndone\n"
            'echo \'JK_EVENT:{"stage":"queue","state":"completed",'
            '"message":"Physical NPU is available"}\'\n'
            'echo \'JK_EVENT:{"stage":"execute","state":"started",'
            '"message":"Compiling trusted CANN evaluator and candidate"}\'\n'
            "timeout -k 10 "
            + str(self.settings.lab_compile_timeout)
            + " bash -c 'cmake -S . -B build && cmake --build build -j2' > compile.log 2>&1\n"
            'echo \'JK_EVENT:{"stage":"execute","state":"progress",'
            '"message":"Compilation completed; evaluating frozen inputs"}\'\n'
            "timeout -k 10 225 python3 -u evaluate.py " + str(device) + " | tee evaluation.log\n"
        )
        # flock also protects this device across separately started local schedulers.
        lock = "/tmp/justkernel-npu-" + str(device) + ".lock"
        command = "flock -w 30 " + quote(lock) + " bash -c " + quote(inner) + "\n"
        completed = self.ssh_progress(command, team, run_id, folder)
        logs = self.ssh(
            "cd " + quote(remote) + "\n"
            "for f in compile.log evaluation.log device-before.txt; do "
            'echo "FILE:$f"; tail -c 16000 "$f" 2>/dev/null || true; done\n'
        )
        (folder / "remote.log").write_text(logs.stdout + completed.stderr, encoding="utf-8")
        fetched = self.ssh("cat " + quote(remote + "/result.json") + "\n")
        if fetched.returncode:
            raise RuntimeError(
                f"remote execution failed ({completed.returncode}); see {folder / 'remote.log'}"
            )
        result = json.loads(fetched.stdout)
        result["remote_path"] = remote
        result["environment"] = {
            "host_alias": self.host,
            "device": device,
            "cann_env": self.settings.lab_cann_env,
        }
        if self.transport:
            result["environment"].update(
                server_profile=self.transport.profile.id, ssh_port=self.transport.profile.port
            )
        return result

    # ---- trusted progress stream -------------------------------------------
    def ssh_progress(self, script: str, team: str, run_id: str | None, folder: Path):
        if self.transport:

            def progress(line):
                if line.startswith("JK_EVENT:"):
                    try:
                        update = json.loads(line[len("JK_EVENT:") :])
                        update["run_id"] = run_id
                        self.store.stage(team, StageUpdate.model_validate(update))
                    except (ValueError, TypeError):
                        pass

            result = self.transport.run(script, self.settings.lab_job_timeout, progress)
            (folder / "transport.log").write_text(result.stdout, encoding="utf-8")
            return result
        arguments = [
            "ssh",
            *self.settings.lab_ssh_options,
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=12",
            self.host,
            "bash -s",
        ]
        process = subprocess.Popen(
            arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        timer = threading.Timer(self.settings.lab_job_timeout, process.terminate)
        timer.start()
        tail = bytearray()
        try:
            process.stdin.write(script.replace("\r\n", "\n").encode("utf-8"))
            process.stdin.close()
            for line in process.stdout:
                tail.extend(line)
                if len(tail) > 64000:
                    del tail[:-64000]
                if line.startswith(b"JK_EVENT:"):
                    try:
                        update = json.loads(line[len(b"JK_EVENT:") :])
                        update["run_id"] = run_id
                        self.store.stage(team, StageUpdate.model_validate(update))
                    except (ValueError, TypeError):
                        pass
            process.wait()
        finally:
            timer.cancel()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        output = tail.decode("utf-8", "replace")
        (folder / "transport.log").write_text(output, encoding="utf-8")
        return subprocess.CompletedProcess(arguments, process.returncode, output, "")
