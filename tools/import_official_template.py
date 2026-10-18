"""Import the original contest template locally; do not redistribute it in this repository."""

import argparse
import hashlib
import io
import json
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = ROOT / "src/aworker/lab/resources/confusion_mul_grad"


# ---- validated_files --------------------------------------------------------
def validated_files(data: bytes, expected: dict[str, str]) -> dict[str, bytes]:
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 200:
            raise ValueError("Unexpected archive member count")
        for item in archive.infolist():
            original = item.orig_filename
            path = PurePosixPath(original)
            if path.is_absolute() or ".." in path.parts or "\\" in original or "\0" in original:
                raise ValueError("Unsafe archive path")
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("Archive symlinks are not supported")
            if item.is_dir():
                continue
            if not item.filename.startswith("code/") or item.file_size > 2_000_000:
                raise ValueError("Unexpected archive member")
            name = item.filename.removeprefix("code/")
            if name not in expected or name in result:
                raise ValueError("Unexpected or duplicate project file: " + name)
            content = archive.read(item)
            if hashlib.sha256(content).hexdigest() != expected[name]:
                raise ValueError("Official template changed; review before importing: " + name)
            result[name] = content
    if set(result) != set(expected):
        raise ValueError("Incomplete official template")
    return result


# ---- import_template --------------------------------------------------------
def import_template(data: bytes, resource: Path = RESOURCE) -> Path:
    expected = json.loads((resource / "template-files.json").read_text(encoding="utf-8"))
    files = validated_files(data, expected)
    target = resource / "project"
    if target.exists():
        existing = {
            p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in target.rglob("*")
            if p.is_file()
        }
        if existing != expected:
            raise ValueError(
                "Existing project differs; preserving it. Use a fresh clone to import."
            )
        return target
    with tempfile.TemporaryDirectory(prefix=".template-", dir=resource) as temporary:
        staging = Path(temporary) / "project"
        for name, content in files.items():
            output = staging / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
        shutil.move(str(staging), str(target))
    return target


# ---- main -------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--zip", type=Path, help="Already downloaded official ZIP; no network needed"
    )
    args = parser.parse_args()
    if args.zip:
        data = args.zip.read_bytes()
    else:
        source = json.loads((RESOURCE / "input-source.json").read_text(encoding="utf-8"))
        request = urllib.request.Request(
            source["template_url"], headers={"User-Agent": "JustKernel"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(8_000_001)
    if len(data) > 8_000_000:
        raise ValueError("Template archive is unexpectedly large")
    destination = import_template(data)
    print("Verified 34 official files; imported locally: " + str(destination))
    print("Contest template remains subject to its original terms; it is excluded from releases.")


if __name__ == "__main__":
    main()
