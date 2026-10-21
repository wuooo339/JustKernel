"""Check built wheel/sdist for package, dependency and legacy hygiene."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
ALLOWED_DEPS = {"fastapi", "pyyaml"}
FORBIDDEN = ("awork" + "er", ".codegraph", "opencode.jsonc", "AGENTS.md", ".env", "3q")


def _forbidden(name: str) -> bool:
    return any(token in name for token in FORBIDDEN)


def check_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata = archive.read("justkernel-0.1.0.dist-info/METADATA").decode("utf-8")
        entry = archive.read("justkernel-0.1.0.dist-info/entry_points.txt").decode("utf-8")
    assert names, "wheel is empty"
    assert all(
        name.startswith(("justkernel/", "justkernel-0.1.0.dist-info/")) for name in names
    ), "wheel contains files outside justkernel"
    assert not any(_forbidden(name) for name in names), "wheel contains forbidden files"
    required = {
        "justkernel/resources/skills/base/supervisor/SKILL.md",
        "justkernel/resources/skills/builtin/tester-cann-simulation/SKILL.md",
        "justkernel/web/state/reducer.js",
        "justkernel/platform/http/app.py",
    }
    assert required <= set(names), "wheel is missing runtime resources"
    for line in metadata.splitlines():
        if line.startswith("Requires-Dist:"):
            name = line.split(":", 1)[1].strip().split()[0].split(">")[0].lower()
            assert name in ALLOWED_DEPS, f"unexpected wheel dependency: {name}"
    assert "justkernel = justkernel.bootstrap.cli:main" in entry


def check_sdist(path: Path) -> None:
    with tarfile.open(path) as archive:
        names = archive.getnames()
    assert names, "sdist is empty"
    prefix = "justkernel-0.1.0/"
    assert all(name == prefix[:-1] or name.startswith(prefix) for name in names), (
        "sdist contains a foreign top-level path"
    )
    assert not any(_forbidden(name) for name in names), "sdist contains forbidden files"
    relative = {name[len(prefix):] for name in names if name.startswith(prefix)}
    assert "src/justkernel/bootstrap/cli.py" in relative
    assert "tests/architecture/test_no_legacy.py" in relative
    assert "SPEC/01-product-vision.md" not in relative
    assert "src/justkernel/web/demo/fixture.json" in relative


def main() -> int:
    wheels = sorted(DIST.glob("*.whl"))
    sdists = sorted(DIST.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print("expected exactly one wheel and one sdist", file=sys.stderr)
        return 1
    check_wheel(wheels[0])
    check_sdist(sdists[0])
    print(f"checked {wheels[0].name} and {sdists[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
