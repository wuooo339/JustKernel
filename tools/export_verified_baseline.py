"""Reconstruct the verified operator from an official template and solution overlays."""

import argparse
import hashlib
import json
import stat
from pathlib import Path

from aworker.lab.project import clean_project_path, source_identity

REPO = Path(__file__).resolve().parents[1]
SOLUTION = REPO / "examples/confusionmulgrad/verified"


# ---- export_baseline -------------------------------------------------------
def export_baseline(template: Path, destination: Path) -> dict:
    metadata = json.loads((SOLUTION / "baseline.json").read_text(encoding="utf-8"))
    if destination.exists():
        raise ValueError("Destination already exists; choose a new project directory.")
    if not template.is_dir():
        raise ValueError(
            "Import the official template first: uv run python tools/import_official_template.py"
        )
    files = {}
    for name, expected in metadata["template_files"].items():
        clean_project_path(name)
        original = template / name
        if original.is_symlink() or not original.resolve().is_relative_to(template.resolve()):
            raise ValueError("Template file escaped the project: " + name)
        data = original.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("Official template version/integrity mismatch: " + name)
        if name in metadata["overlays"]:
            overlay = SOLUTION / "source" / name
            data = overlay.read_bytes()
            if hashlib.sha256(data).hexdigest() != metadata["overlays"][name]:
                raise ValueError("Solution overlay integrity mismatch: " + name)
        files[name] = data.decode("utf-8")
    if source_identity(files) != metadata["source_sha256"]:
        raise ValueError("Reconstructed source does not match the official passing version.")
    destination.mkdir(parents=True)
    for name, text in files.items():
        out = destination / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(text.encode("utf-8"))
        if name.endswith(".sh"):
            out.chmod(out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return {
        "project": str(destination.resolve()),
        "source_sha256": metadata["source_sha256"],
        "official": metadata["official"]["submission_id"],
    }


# ---- main -----------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--template",
        type=Path,
        default=REPO / "src/aworker/lab/resources/confusion_mul_grad/project",
    )
    args = parser.parse_args()
    try:
        result = export_baseline(args.template, args.destination)
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
