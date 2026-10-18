"""Multi-file operator identity and immutable judge/build inputs."""

import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath


# ---- clean_project_path -----------------------------------------------------
def clean_project_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or any(p in {"", ".", ".."} for p in value.split("/"))
        or any(c in value for c in "\\:\n\r\0")
    ):
        raise ValueError("project paths must be relative POSIX paths without traversal")
    return path.as_posix()


# ---- project_manifest -------------------------------------------------------
def project_manifest(root: Path) -> dict:
    return json.loads((root / "challenge/manifest.json").read_text(encoding="utf-8"))


# ---- source_files -----------------------------------------------------------
def source_files(root: Path, folder: Path) -> dict[str, str]:
    manifest = project_manifest(root)
    if not manifest.get("project_files"):
        return {"kernel.asc": (folder / "kernel.asc").read_bytes().decode("utf-8")}
    editable = set(manifest["editable_paths"])
    actual = {
        p.relative_to(folder / "project").as_posix()
        for p in (folder / "project").rglob("*")
        if p.is_file()
    }
    if actual != set(manifest["project_files"]):
        raise ValueError("project file list changed; use only the official editable paths")
    files = {}
    for name, expected in manifest["project_files"].items():
        clean_project_path(name)
        path = folder / "project" / name
        if path.is_symlink() or not path.resolve().is_relative_to((folder / "project").resolve()):
            raise ValueError("project file escaped its workspace")
        data = path.read_bytes()
        if name not in editable and hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("protected official project file changed: " + name)
        files[name] = data.decode("utf-8")
    return files


# ---- source_identity --------------------------------------------------------
def source_identity(files: dict[str, str]) -> str:
    data = (
        files["kernel.asc"].encode("utf-8")
        if set(files) == {"kernel.asc"}
        else json.dumps(files, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    return hashlib.sha256(data).hexdigest()


# ---- source_display ---------------------------------------------------------
def source_display(files: dict[str, str], editable: list[str] | None = None) -> str:
    if set(files) == {"kernel.asc"}:
        return files["kernel.asc"]
    return "\n\n".join("// FILE: " + name + "\n" + files[name] for name in (editable or files))


# ---- prepare_official_challenge ---------------------------------------------
def prepare_official_challenge(root: Path) -> dict:
    resource = Path(__file__).parent / "resources/confusion_mul_grad"
    if not (resource / "project/op_kernel/confusion_mul_grad.cpp").is_file():
        raise ValueError(
            "Import the official empty project first: "
            "uv run python tools/import_official_template.py (see README.md)"
        )
    challenge = root / "challenge"
    challenge.mkdir(parents=True, exist_ok=False)
    shutil.copytree(resource / "project", challenge / "project")
    for name in ("statement.md", "cases.json", "input-source.json"):
        shutil.copyfile(resource / name, challenge / name)
    constraints = (Path(__file__).parent / "resources/default_constraints.md").read_text(
        encoding="utf-8"
    )
    constraints += (
        "\n\n## ConfusionMulGrad\n\n"
        "output0=input0*input1；output1=ReduceSum(input1*input2, axis, keep_dims)。\n"
        "三输入同 shape、同 dtype；乘法及归约以 FLOAT32 完成，最终 cast 回输入 dtype。\n"
        "input1 在片上复用；完整调用只启动一个 Kernel。以 statement.md 的官方定义为准。\n"
        "只修改 project-manifest.json 列出的 editable_paths；构建、测试和评测文件受保护。\n"
        "官方空工程仍有 TODO，不是通过的基准。官方模板 UT 只含单个示例，不能代表 15 点。\n"
    )
    (challenge / "CONSTRAINTS.md").write_text(constraints, encoding="utf-8")
    source = json.loads((resource / "input-source.json").read_text(encoding="utf-8"))
    files = {
        p.relative_to(challenge / "project").as_posix(): p.read_bytes().decode("utf-8")
        for p in sorted((challenge / "project").rglob("*"))
        if p.is_file()
    }
    manifest = {
        "operator": "ConfusionMulGrad",
        "name": "ConfusionMulGrad",
        "harness": "deepagents",
        "adapter_ready": False,
        "code_layout": "official-project",
        "entrypoint": "confusion_mul_grad",
        "baseline_sha256": source_identity(files),
        "project_files": {
            name: hashlib.sha256((challenge / "project" / name).read_bytes()).hexdigest()
            for name in files
        },
        "editable_paths": source["editable_paths"],
        "input_source": source,
        "not_official_hidden_cases": True,
        "input_definition": "Provisional local cases; official hidden inputs are not known",
    }
    (challenge / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (challenge / "project-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
