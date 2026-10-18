"""Extract input metadata only; never distribute the source table's history."""

import hashlib
import json
import re
import shutil
from pathlib import Path


# ---- read_input_geometry ----------------------------------------------------
def read_input_geometry(path: Path) -> list[dict]:
    rows = [
        line.split("|")[1:-1]
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.startswith("|")
    ]
    header = next((r for r in rows if any("[B,S,H,D]" in c for c in r)), None)
    if header is None:
        raise ValueError("input geometry table header is missing")
    xi = next(i for i, c in enumerate(header) if "[B,S,H,D]" in c)
    ti = next(i for i, c in enumerate(header) if c.strip() == "theta")
    result = []
    for row in rows:
        if len(row) <= max(xi, ti) or not re.fullmatch(r"\s*(?:[1-9]|1[0-5])\s*", row[0]):
            continue
        point = int(row[0])
        shape = []
        for field in ("B", "S", "H", "D"):
            match = re.search(rf"(?:^|；)\s*{field}=(\d+)", row[xi])
            if match is None:
                raise ValueError(f"point {point}: {field} is unknown")
            shape.append(int(match[1]))
        dtype = re.search(r"\bFP(16|32)\b", row[xi])
        theta = re.match(r"\s*(\d+(?:\.\d+)?)(?:f)?", row[ti])
        if dtype is None or theta is None:
            raise ValueError(f"point {point}: dtype/theta is unknown")
        result.append(
            {
                "id": f"geometry-{point:02d}",
                "contest_point": point,
                "shape": shape,
                "dtype": "float" + dtype[1],
                "theta": float(theta[1]),
                "positions": "random",
                "position_upper": 8192,
                "seed": 2026101700 + point,
                "source": "INPUTS.md geometry (timing-inferred); tensor values self-defined",
                "official_tensor_values_known": False,
            }
        )
    if sorted(c["contest_point"] for c in result) != list(range(1, 16)):
        raise ValueError("require exactly one complete metadata row for each point 1–15")
    return sorted(result, key=lambda c: c["contest_point"])


# ---- import_input_cases -----------------------------------------------------
def import_input_cases(root: Path, path: Path) -> dict:
    cases = read_input_geometry(path)
    challenge = root / "challenge"
    manifest_path = challenge / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = json.dumps(cases, ensure_ascii=False, indent=2).encode("utf-8")
    provenance = {
        "file": path.name,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "section": "唯一逐点表",
        "extracted_fields": ["point", "B", "S", "H", "D", "dtype", "theta"],
        "geometry_basis": "timing-coded inference recorded in INPUTS.md; not official raw inputs",
        "official_tensor_values_known": False,
        "generated_data": "NumPy default_rng(seed); x uniform[-10,10), C contiguous; "
        "positions int32 random[0,8192); seeds and geometry in cases.json",
        "case_pack_sha256": hashlib.sha256(payload).hexdigest(),
        "count": len(cases),
    }
    (challenge / "cases.json").write_bytes(payload)
    (challenge / "input-source.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest.update(input_source=provenance, input_definition=provenance["generated_data"])
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    for folder in (root / "teams").glob("*"):
        if folder.is_dir() and (folder / "team.json").is_file():
            for name in ("cases.json", "input-source.json"):
                shutil.copyfile(challenge / name, folder / name)
    return provenance
