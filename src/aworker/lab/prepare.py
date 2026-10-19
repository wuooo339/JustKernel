"""Prepare the single operator challenge and independent team workspaces."""

import hashlib
import json
import shutil
from pathlib import Path

from aworker.lab.persistence import replace_file
from aworker.lab.project import project_manifest
from aworker.lab.store import identifier

TEAM_INSTRUCTIONS = """# JustKernel team workspace

Every team and specialist uses Deep Agents. Start with statement.md, CONSTRAINTS.md,
cases.json and input-source.json. These files define this operator's input package;
locally generated tensor values are not official hidden tensor values.
Maintain candidate source files and your own analysis scripts and notes. In single-coder
mode, implement directly; the independent Judger reviews immutable candidate snapshots.
Register record_experiment_plan when a repair work item exists, then edit and test.
Optional specialists in parallel mode receive only a narrow question, not the whole task.
Skills are in /skills/. Read their instructions when relevant.
Use inspect_policy for source checks, simulate_kernel for the CPU CANN lane, and
evaluate_kernel only when a physical NPU is actually configured.
Use run_python for workspace analysis scripts. Do not SSH or access the physical NPU.
Do not modify inputs, constraints, tools, judge, timers or accuracy thresholds.
Never read external contest history, private team files or credentials.
Use list_public_results/read_public_code and team messages to cooperate. Record the
parent artifact when reusing a published method. publish_result requires an exact
source/input-pack match with a real passed evaluation. record_experience additionally
requires a real evidence job and explicit conditions and limitations.
Local correctness, device timing, policy review and official scores are distinct.
"""


# ---- refresh generated guidance without changing any operator or custom skill --
def refresh_team_guidance(root: Path, team: str) -> None:
    folder = root / "teams" / identifier(team)
    manifest = project_manifest(root)
    instructions = TEAM_INSTRUCTIONS
    if manifest.get("project_files"):
        instructions += (
            "\nThis is a complete official CANN Judge project. Read /project-manifest.json.\n"
            "Edit only /project/ files listed in editable_paths, NOT kernel.asc.\n"
            "Use simulation tools before requesting scarce physical NPU work.\n"
            "Never claim a guessed INPUT is an official hidden test.\n"
        )
    skill = Path(__file__).parent / "resources/skills/kernel-engineering/SKILL.md"
    for relative, content in {
        "TEAM.md": instructions,
        "skills/kernel-engineering/SKILL.md": skill.read_text(encoding="utf-8"),
    }.items():
        destination = folder / relative
        if destination.is_file():
            original = destination.read_bytes()
            if original.decode("utf-8") == content:
                continue
            archive = (
                root
                / "guidance-history"
                / team
                / hashlib.sha256(original).hexdigest()[:16]
                / relative
            )
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(original)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        replace_file(temporary, destination)


# ---- prepare_challenge ------------------------------------------------------
def prepare_challenge(
    root: Path, baseline: Path | None = None, statement: Path | None = None
) -> dict:
    challenge = root / "challenge"
    if challenge.exists():
        raise ValueError("challenge already exists; baseline is immutable")
    template = Path(__file__).parent / "resources" / "rotary_pos_emb"
    shutil.copytree(template, challenge)
    if not (challenge / "kernel.asc").exists():
        # Legacy journals remain readable; the private optimized baseline is not distributed.
        (challenge / "kernel.asc").write_text(
            "#include <stdexcept>\n"
            'extern "C" void run_kernel(GM_ADDR, const TensorGroupInfo&, GM_ADDR, '
            "const TensorGroupInfo&, GM_ADDR, const TensorGroupInfo&, "
            "int64_t, aclrtStream, float) {\n"
            '  throw std::runtime_error("Legacy baseline not distributed; use ConfusionMulGrad");\n'
            "}\n",
            encoding="utf-8",
        )
    if baseline:
        shutil.copyfile(baseline, challenge / "kernel.asc")
    if statement:
        shutil.copyfile(statement, challenge / "statement.md")
    manifest = {
        "operator": "RotaryPosEmb",
        "harness": "deepagents",
        "baseline_sha256": hashlib.sha256((challenge / "kernel.asc").read_bytes()).hexdigest(),
        "not_official_hidden_cases": True,
        "input_definition": "Fixed NumPy generators in cases.json; local measurements only",
        "input_source": json.loads((challenge / "input-source.json").read_text(encoding="utf-8")),
    }
    (challenge / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# ---- prepare_team -----------------------------------------------------------
def prepare_team(root: Path, team: str) -> Path:
    folder = root / "teams" / identifier(team)
    if folder.exists():
        refresh_team_guidance(root, team)
        return folder
    folder.mkdir(parents=True)
    names = ["statement.md", "CONSTRAINTS.md", "cases.json", "input-source.json"]
    manifest = project_manifest(root)
    if manifest.get("project_files"):
        shutil.copytree(root / "challenge/project", folder / "project")
        names.append("project-manifest.json")
    else:
        names.append("kernel.asc")
    for name in names:
        shutil.copyfile(root / "challenge" / name, folder / name)
    (folder / "TEAM.md").write_text(TEAM_INSTRUCTIONS, encoding="utf-8")
    if manifest.get("project_files"):
        with (folder / "TEAM.md").open("a", encoding="utf-8") as instructions:
            instructions.write(
                "\nThis is a complete official CANN Judge project. Read /project-manifest.json.\n"
                "Edit only /project/ files listed in editable_paths, NOT kernel.asc.\n"
                "Use simulation tools before requesting scarce physical NPU work.\n"
                "Never claim a guessed INPUT is an official hidden test.\n"
            )
    shutil.copytree(Path(__file__).parent / "resources" / "skills", folder / "skills")
    return folder
