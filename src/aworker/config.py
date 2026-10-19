"""Runtime configuration for the Aworker server.

Configuration is read once at startup from environment variables (prefixed with
``AWORKER_``) and an optional ``.env`` file, then passed around as a validated
object. Business logic must not read environment variables directly.
"""

import os
import sys
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---- private_data_root ------------------------------------------------------
def private_data_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return base / "JustKernel/workbench"


# ---- default_judge_browser_channel ------------------------------------------
def default_judge_browser_channel() -> str | None:
    if sys.platform != "win32":
        return None
    bases = [
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")),
        Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")),
    ]
    for channel, relative in [
        ("chrome", "Google/Chrome/Application/chrome.exe"),
        ("msedge", "Microsoft/Edge/Application/msedge.exe"),
    ]:
        if any((base / relative).is_file() for base in bases):
            return channel
    return None


# ---- Settings ---------------------------------------------------------------
class Settings(BaseSettings):
    """Validated server settings loaded from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="AWORKER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    public_url: str | None = None

    agent_name: str = "JustKernel"
    agent_description: str = (
        "A worker swarm that solves a task using a dynamically sized team of agents."
    )
    version: str = "0.2.0"

    model: str = "openai:gpt-4o-mini"
    max_members: int = 16
    require_llm_credential: bool = True

    lab_root: Path = Path(".justkernel")
    lab_default_operator: str = "ConfusionMulGrad"
    lab_execution_mode: str = "judge-only"
    lab_private_root: Path = Field(default_factory=private_data_root)
    lab_host: str = "127.0.0.1"
    lab_port: int = 4173
    lab_ssh_host: str | None = None
    lab_ssh_options: tuple[str, ...] = ()
    lab_remote_root: str = "/mnt/workspace/justkernel-lab"
    lab_cann_env: str = "/home/developer/Ascend/cann-9.0.0/set_env.sh"
    lab_device: int = Field(default=0, ge=0)
    lab_max_active: int = Field(default=8, ge=1, le=8)
    lab_compile_timeout: int = Field(default=300, ge=1, le=600)
    lab_job_timeout: int = Field(default=600, ge=1, le=3600)
    lab_proxy_url: str | None = None
    lab_models_file: Path = Path("models.toml")
    lab_provider_keys: dict[str, SecretStr] = Field(default_factory=dict)
    lab_agent_timeout: int = Field(default=3600, ge=10, le=7200)
    lab_max_steps: int = Field(default=400, ge=4, le=1000)
    lab_baseline_idle_seconds: int = Field(default=300, ge=30, le=3600)
    lab_baseline_idle_calls: int = Field(default=12, ge=2, le=100)
    lab_max_teams: int = Field(default=100, ge=1, le=100)
    lab_team_concurrency: int = Field(default=4, ge=1, le=100)
    lab_simulator_concurrency: int = Field(default=1, ge=1, le=32)
    lab_simulation_wait_seconds: float = Field(default=2, ge=0.01, le=60)
    lab_simulation_timeout_seconds: int = Field(default=3600, ge=30, le=3600)
    lab_simulation_case_timeout_seconds: int = Field(default=1800, ge=30, le=3600)
    lab_require_simulation: bool = False
    lab_judge_browser_channel: str | None = Field(default_factory=default_judge_browser_channel)
    lab_judge_browser_disable_gpu: bool = False
    lab_judge_bridge: Path | None = None
    lab_judge_submit_interval: int = Field(default=60, ge=15, le=3600)
    lab_selector_timeout: int = Field(default=240, ge=10, le=1800)
    lab_max_evaluations: int = Field(default=2, ge=1, le=100)
    lab_langsmith_enabled: bool = False
    lab_langsmith_api_key: SecretStr | None = None
    lab_langsmith_project: str = "JustKernel"
    lab_langsmith_endpoint: str = "https://api.smith.langchain.com"

    # ---- child analysis process environment --------------------------------
    def analysis_environment(self) -> dict[str, str]:
        allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "LANG"}
        return {key: value for key, value in os.environ.items() if key.upper() in allowed}

    # ---- isolated official-site browser worker environment ------------------
    def judge_browser_environment(self, temporary: Path) -> dict[str, str]:
        temporary = temporary.resolve()
        if not temporary.is_relative_to(self.lab_private_root.resolve()):
            raise ValueError("browser temporary directory must remain inside the private root")
        allowed = {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "LANG",
            "LC_ALL",
            "HOME",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
            "PROGRAMFILES",
            "PROGRAMFILES(X86)",
            "PROGRAMW6432",
            "SYSTEMDRIVE",
            "USERNAME",
            "USERDOMAIN",
            "HOMEDRIVE",
            "HOMEPATH",
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "XAUTHORITY",
            "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS",
        }
        env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        env.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
        if sys.platform == "win32":
            # Launch the base executable directly while retaining this venv.
            env["__PYVENV_LAUNCHER__"] = sys.executable
        env["DEBUG"] = "pw:browser"
        return env

    # ---- child server retains its intended credential environment -----------
    def service_environment(self) -> dict[str, str]:
        env = dict(os.environ)
        if sys.platform == "win32":
            env["__PYVENV_LAUNCHER__"] = sys.executable
        return env

    @property
    def base_url(self) -> str:
        """Public base URL advertised in the agent card."""
        if self.public_url:
            return self.public_url.rstrip("/")
        return f"http://{self.host}:{self.port}"
