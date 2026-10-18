"""Trusted remote evaluator: reproducible inputs, bounded host memory, live progress."""

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch


# ---- progress ---------------------------------------------------------------
def progress(stage, state, message):
    print(
        "JK_EVENT:" + json.dumps({"stage": stage, "state": state, "message": message}), flush=True
    )


# ---- golden -----------------------------------------------------------------
def golden(x, positions, theta):
    dim = x.shape[-1]
    inv = 1.0 / (theta ** (torch.arange(0, dim, 2).float() / dim))
    freqs = torch.from_numpy(positions).float().unsqueeze(-1) * inv
    angles = torch.cat([freqs, freqs], -1).unsqueeze(2)
    values = torch.from_numpy(x).float()
    rotate = torch.cat([-values[..., dim // 2 :], values[..., : dim // 2]], -1)
    return (values * angles.cos() + rotate * angles.sin()).numpy().astype(x.dtype)


# ---- generate_inputs --------------------------------------------------------
def generate_inputs(folder, case):
    b, s, h, d = case["shape"]
    rows = b * s
    chunk = max(1, 1_048_576 // (h * d))
    rng = np.random.default_rng(case["seed"])
    x = np.memmap(folder / "x.bin", mode="w+", dtype=case["dtype"], shape=(rows, h, d))
    # Consecutive chunks consume exactly the same RNG stream as one full uniform() call.
    for start in range(0, rows, chunk):
        stop = min(start + chunk, rows)
        x[start:stop] = rng.uniform(-10, 10, (stop - start, h, d)).astype(case["dtype"])
    x.flush()
    if case["positions"] == "sequential":
        p = np.broadcast_to(np.arange(s, dtype=np.int32), (b, s)).copy()
    else:
        p = rng.integers(0, case["position_upper"], (b, s), dtype=np.int32)
    p.tofile(folder / "positions.bin")
    return x, p.reshape(-1), chunk


# ---- verify_outputs ---------------------------------------------------------
def verify_outputs(folder, case, x, positions, chunk):
    shape, dtype = x.shape, np.dtype(case["dtype"])
    expected_bytes = math.prod(shape) * dtype.itemsize
    summaries, arrays = {}, {}
    for key in ("first", "last"):
        path = folder / (key + "_y.bin")
        if not path.exists() or path.stat().st_size != expected_bytes:
            summaries[key] = {"pass": False, "reason": "output size mismatch"}
        else:
            arrays[key] = np.memmap(path, mode="r", dtype=dtype, shape=shape)
            summaries[key] = {
                "pass": True,
                "mismatches": 0,
                "elements": math.prod(shape),
                "max_abs_error": 0.0,
            }
    tolerance = 1e-4 if dtype == np.dtype("float32") else 1e-3
    for start in range(0, shape[0], chunk):
        stop = min(start + chunk, shape[0])
        target = golden(np.array(x[start:stop])[None], positions[None, start:stop], case["theta"])[
            0
        ].astype(np.float64)
        for key, array in arrays.items():
            actual = np.asarray(array[start:stop], dtype=np.float64)
            errors = np.abs(actual - target)
            bad = ~np.isfinite(actual) | (errors > tolerance + tolerance * np.abs(target))
            summary = summaries[key]
            summary["mismatches"] += int(bad.sum())
            summary["max_abs_error"] = max(
                summary["max_abs_error"], float(np.nan_to_num(errors, nan=np.inf).max())
            )
            summary["pass"] = summary["mismatches"] == 0
    return summaries["first"], summaries["last"]


# ---- main -------------------------------------------------------------------
def main():
    torch.set_num_threads(4)
    root = Path.cwd()
    cases = json.loads((root / "cases.json").read_text())
    result = {
        "source": "npu-local",
        "official_score": False,
        "timing": "ACL events around repeated complete operator calls",
        "compliance": "not certified; source review and physical launch trace required",
        "cases": [],
    }
    for index, case in enumerate(cases, 1):
        progress("execute", "progress", f"Input {index}/{len(cases)}: {case['shape']}")
        folder = root / "data" / case["id"]
        folder.mkdir(parents=True, exist_ok=True)
        entry = {"input": case}
        try:
            x, positions, chunk = generate_inputs(folder, case)
            b, s, h, d = case["shape"]
            completed = subprocess.run(
                [
                    str(root / "build" / "rope_evaluate"),
                    sys.argv[1],
                    str(b),
                    str(s),
                    str(h),
                    str(d),
                    "0" if case["dtype"] == "float32" else "1",
                    str(case["theta"]),
                    "20",
                ],
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=45,
            )
            entry["returncode"] = completed.returncode
            if completed.returncode:
                entry.update({"pass": False, "stderr": completed.stderr[-3000:]})
            else:
                progress("verify", "progress", f"Checking input {index}/{len(cases)}")
                entry["first"], entry["repeated"] = verify_outputs(
                    folder, case, x, positions, chunk
                )
                entry["pass"] = entry["first"]["pass"] and entry["repeated"]["pass"]
                entry["measurement"] = json.loads(completed.stdout.strip().splitlines()[-1])
            del x
        except Exception as exc:
            entry.update({"pass": False, "error": str(exc)[:3000]})
        result["cases"].append(entry)
        progress(
            "verify",
            "progress",
            f"Input {index}/{len(cases)}: " + ("PASS" if entry["pass"] else "FAIL"),
        )
        (root / "result.partial.json").write_text(json.dumps(result, indent=2))
        # Inputs can be regenerated from their frozen specification; keep failed evidence files.
        if entry["pass"]:
            for name in ("x.bin", "positions.bin", "first_y.bin", "last_y.bin"):
                (folder / name).unlink(missing_ok=True)
    result["pass"] = all(c["pass"] for c in result["cases"])
    (root / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
