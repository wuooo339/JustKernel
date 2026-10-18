"""Create a source-only ZIP; local credentials/state are never candidates."""

import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "AGENTS.md",
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "uv.lock",
    "models.toml",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    ".python-version",
    "start.ps1",
    "restart.ps1",
    "start.sh",
    "start.command",
    "重启面板.cmd",
    "启动演示.cmd",
]
DIRECTORIES = ["src", "tests", "docs", "examples", "tools", ".github"]
EXCLUDE = {"__pycache__", ".pytest_cache", ".ruff_cache"}
PRIVATE = (
    "src/aworker/lab/resources/confusion_mul_grad/project/",
    "src/aworker/lab/resources/rotary_pos_emb/kernel.asc",
    "docs/images/execution-record.png",
    "docs/images/simulation.png",
)
SENSITIVE = re.compile(
    rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|eyJ[A-Za-z0-9_-]{20,}\."
    rb"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{15,}|-----BEGIN "
    rb"(?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----)"
    rb"|(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"
)


# ---- main -------------------------------------------------------------------
def main():
    paths = [ROOT / name for name in FILES]
    for directory in DIRECTORIES:
        paths.extend(
            p
            for p in (ROOT / directory).rglob("*")
            if p.is_file()
            and not EXCLUDE.intersection(p.relative_to(ROOT).parts)
            and p.suffix not in {".pyc", ".pyo"}
        )
    manifest = {}
    for path in sorted(set(paths)):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(PRIVATE):
            continue
        data = path.read_bytes()
        if SENSITIVE.search(data):
            raise ValueError("possible credential material in " + relative)
        manifest[relative] = hashlib.sha256(data).hexdigest()
    destination = ROOT / "source-packages" / "justkernel-0.2.0-source.zip"
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in manifest:
            info = zipfile.ZipInfo.from_file(ROOT / relative, "JustKernel/" + relative)
            if relative in {"start.sh", "start.command"}:
                info.create_system = 3
                info.external_attr = 0o100755 << 16
            archive.writestr(info, (ROOT / relative).read_bytes(), zipfile.ZIP_DEFLATED)
        archive.writestr("JustKernel/SOURCE-MANIFEST.json", json.dumps(manifest, indent=2))
    print(
        json.dumps(
            {
                "archive": str(destination),
                "files": len(manifest),
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    main()
