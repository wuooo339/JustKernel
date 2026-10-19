"""Portable execution evidence; no login files or device lease tokens."""

import hashlib
import json

from aworker.lab.project import project_manifest, source_display, source_files, source_identity


# ---- execution_record -------------------------------------------------------
def execution_record(service) -> dict:
    snapshot = service.store.snapshot()
    snapshot["teams"] = [t for t in snapshot["teams"] if t["runtime"] == "deepagents"]
    teams = {t["id"] for t in snapshot["teams"]}
    for job in snapshot["jobs"]:
        job.pop("token", None)
    snapshot["experiences"] = service.store.experiences()
    snapshot["public"] = service.public(include_source=True)
    snapshot["continuous"] = service.swarm.status()
    snapshot["iterations"] = service.iterations.snapshot()
    snapshot["simulation"] = {
        "required": service.simulator.required,
        "target_soc": "Ascend910B4",
        "concurrency": service.simulator.status()["concurrency"],
        "profiling_concurrency": service.simulator.status()["profiling_concurrency"],
    }
    sources = {}
    for team in snapshot["teams"]:
        if project_manifest(service.root).get("project_files"):
            folder = service.root / "teams" / team["id"]
            if folder.is_dir():
                files = source_files(service.root, folder)
                sources[team["id"]] = {
                    "files": files,
                    "source": source_display(
                        files, project_manifest(service.root)["editable_paths"]
                    ),
                    "sha256": source_identity(files),
                }
            continue
        source = service.root / "teams" / team["id"] / "kernel.asc"
        if source.is_file():
            data = source.read_bytes()
            sources[team["id"]] = {
                "source": data.decode("utf-8"),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    entries, cursor, legacy = [], 0, 0
    while batch := service.store.events(cursor):
        current = [e for e in batch if e["team"] in teams or e["team"] in {"controller", "judger"}]
        entries.extend(current)
        legacy += len(batch) - len(current)
        cursor = batch[-1]["seq"]
    folder = service.root / "challenge"
    return {
        "schema": "justkernel.events.v2",
        "source": "real-execution",
        "harness": "deepagents",
        "operator": service.operator,
        "execution_mode": service.execution_mode,
        "events": entries,
        "snapshot": snapshot,
        "models": service.registry.catalog(),
        "sources": sources,
        "legacy_events_retained_locally": legacy,
        "challenge": {
            "cases": json.loads((folder / "cases.json").read_text(encoding="utf-8")),
            "manifest": json.loads((folder / "manifest.json").read_text(encoding="utf-8")),
        },
    }
