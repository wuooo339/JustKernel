"""Replaceable SSH profiles, local credential vault, probes and real SSH transport."""

import asyncio
import hashlib
import json
import shlex
import subprocess
from pathlib import Path
from typing import Literal

import asyncssh
from cryptography.fernet import Fernet
from pydantic import BaseModel, Field, SecretStr, field_validator

from aworker.config import Settings


# ---- ServerProfile ----------------------------------------------------------
class ServerProfile(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
    name: str = Field(min_length=1, max_length=120)
    host: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,252}$")
    user: str = Field(default="", pattern=r"^[A-Za-z0-9_.-]*$")
    port: int | None = Field(default=None, ge=1, le=65535)
    auth: Literal["openssh", "password", "key"] = "openssh"
    identity_file: str = Field(default="", max_length=1000)
    config_file: str = Field(default="", max_length=1000)
    devices: list[int] = Field(default_factory=lambda: [0], min_length=1, max_length=8)
    remote_root: str = "/mnt/workspace/justkernel-lab"
    cann_env: str = "/usr/local/Ascend/ascend-toolkit/set_env.sh"
    trusted_key: str = Field(default="", max_length=4000)

    # ---- path and resource boundaries --------------------------------------
    @field_validator("remote_root", "cann_env")
    @classmethod
    def absolute_remote_path(cls, value):
        if (
            not value.startswith("/")
            or ".." in value.split("/")
            or any(c in value for c in "\n\r\0")
        ):
            raise ValueError("remote path must be absolute and contain no traversal or newlines")
        return value

    @field_validator("devices")
    @classmethod
    def distinct_devices(cls, values):
        if len(set(values)) != len(values) or any(i < 0 or i > 127 for i in values):
            raise ValueError("require distinct physical device indices")
        return values


# ---- ServerSave -------------------------------------------------------------
class ServerSave(BaseModel):
    profile: ServerProfile
    password: SecretStr | None = None
    key_passphrase: SecretStr | None = None
    ssh_config: str | None = Field(default=None, max_length=32000)


# ---- parse_ssh_text ---------------------------------------------------------
def parse_ssh_text(text: str) -> dict:
    """Parse connection metadata locally. Do not send pasted SSH data to a model."""
    if len(text) > 16000 or "\0" in text:
        raise ValueError("SSH connection text is too long")
    fields = {}
    if any(line.strip().lower().startswith("host ") for line in text.splitlines()):
        mapping = {
            "hostname": "host",
            "host": "alias",
            "user": "user",
            "port": "port",
            "identityfile": "identity_file",
        }
        for line in text.splitlines():
            parts = shlex.split(line, comments=True)
            if len(parts) >= 2 and parts[0].lower() in mapping:
                fields[mapping[parts[0].lower()]] = parts[1]
        fields.setdefault("host", fields.get("alias", ""))
        # Complex Match/ProxyCommand/ProxyJump stay in the user's OpenSSH configuration.
        if "proxycommand" in text.lower() or "proxyjump" in text.lower():
            fields["host"] = fields.get("alias", fields["host"])
            fields["note"] = (
                "Host alias selected. Paste the complete Host block to save proxy configuration."
            )
    else:
        parts = shlex.split(text.strip())
        if parts and parts[0] in {"ssh", "ssh.exe"}:
            parts.pop(0)
        while parts:
            item = parts.pop(0)
            if item in {"-p", "-l", "-i", "-F"} and parts:
                fields[
                    {"-p": "port", "-l": "user", "-i": "identity_file", "-F": "config_file"}[item]
                ] = parts.pop(0)
            elif item.startswith("-"):
                raise ValueError(
                    "paste a Host block or ssh [-p port] [-l user] [-i key] [-F config] host"
                )
            elif "host" not in fields:
                user, marker, host = item.rpartition("@")
                fields["host"] = host if marker else item
                if marker:
                    fields["user"] = user
            else:
                raise ValueError("remote commands are not part of a connection profile")
    if "port" in fields:
        fields["port"] = int(fields["port"])
    if not fields.get("host"):
        raise ValueError("no SSH host found")
    return fields


# ---- PinnedClient -----------------------------------------------------------
class PinnedClient(asyncssh.SSHClient):
    def __init__(self, key: str):
        self.fingerprint = asyncssh.import_public_key(key).get_fingerprint()

    # ---- identity verification ---------------------------------------------
    def validate_host_public_key(self, host, addr, port, key):
        return key.get_fingerprint() == self.fingerprint


# ---- ServerRegistry ---------------------------------------------------------
class ServerRegistry:
    def __init__(self, settings: Settings, root: Path):
        self.settings = settings
        identity = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
        self.folder = settings.lab_private_root.expanduser() / identity
        self.path = self.folder / "servers.json"

    # ---- persistence and encrypted fields ----------------------------------
    def data(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"active": "configured" if self.settings.lab_ssh_host else None, "profiles": {}}

    def profiles(self) -> dict[str, ServerProfile]:
        result = {}
        if self.settings.lab_ssh_host:
            result["configured"] = ServerProfile(
                id="configured",
                name="Existing SSH / VS Code connection",
                host=self.settings.lab_ssh_host,
                devices=[self.settings.lab_device],
                remote_root=self.settings.lab_remote_root,
                cann_env=self.settings.lab_cann_env,
            )
        result.update(
            {
                key: ServerProfile.model_validate(row["profile"])
                for key, row in self.data()["profiles"].items()
            }
        )
        return result

    def get(self, key: str) -> ServerProfile:
        if key not in self.profiles():
            raise ValueError("server profile does not exist")
        return self.profiles()[key]

    def catalog(self) -> dict:
        data = self.data()
        return {
            "active": data["active"],
            "profiles": [
                {
                    **p.model_dump(),
                    "has_password": bool(data["profiles"].get(p.id, {}).get("password")),
                    "has_key_passphrase": bool(data["profiles"].get(p.id, {}).get("passphrase")),
                }
                for p in self.profiles().values()
            ],
        }

    def _cipher(self) -> Fernet:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.folder.chmod(0o700)
        key = self.folder / "vault.key"
        if not key.exists():
            with key.open("xb") as stream:
                stream.write(Fernet.generate_key())
            key.chmod(0o600)
        return Fernet(key.read_bytes())

    def _write(self, data: dict) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.folder.chmod(0o700)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.chmod(0o600)
        temp.replace(self.path)

    def save(self, request: ServerSave) -> dict:
        data = self.data()
        if request.ssh_config:
            self.folder.mkdir(parents=True, exist_ok=True)
            config = self.folder / (request.profile.id + ".ssh_config")
            config.write_text(request.ssh_config, encoding="utf-8")
            config.chmod(0o600)
            request.profile.config_file = str(config)
        row = data["profiles"].get(request.profile.id, {})
        row["profile"] = request.profile.model_dump()
        for key, value in [("password", request.password), ("passphrase", request.key_passphrase)]:
            if value and value.get_secret_value():
                row[key] = self._cipher().encrypt(value.get_secret_value().encode()).decode()
        data["profiles"][request.profile.id] = row
        self._write(data)
        return {"id": request.profile.id, "saved": True}

    def secret(self, key: str, kind: str) -> str | None:
        text = self.data()["profiles"].get(key, {}).get(kind)
        return self._cipher().decrypt(text.encode()).decode() if text else None

    def select(self, key: str) -> None:
        self.get(key)
        data = self.data()
        data["active"] = key
        self._write(data)

    # ---- SSH options -------------------------------------------------------
    def async_options(self, key: str) -> dict:
        p = self.get(key)
        options = {"connect_timeout": 15, "login_timeout": 20, "encoding": "utf-8"}
        config = Path(p.config_file).expanduser() if p.config_file else Path.home() / ".ssh/config"
        if key == "configured" and not p.config_file:
            legacy = self.settings.lab_ssh_options
            if "-F" in legacy and legacy.index("-F") + 1 < len(legacy):
                config = Path(legacy[legacy.index("-F") + 1]).expanduser()
        if config.is_file():
            options["config"] = [str(config)]
        if p.port:
            options["port"] = p.port
        if p.user:
            options["username"] = p.user
        if p.identity_file:
            options["client_keys"] = [str(Path(p.identity_file).expanduser())]
        if p.auth == "password":
            password = self.secret(key, "password")
            if not password:
                raise ValueError("save the server password locally first")
            options.update(password=password, client_keys=None, agent_path=None)
        if secret := self.secret(key, "passphrase"):
            options["passphrase"] = secret
        if p.trusted_key:
            options.update(known_hosts=[], client_factory=lambda: PinnedClient(p.trusted_key))
        return options

    def native_options(self, key: str, scp: bool = False) -> list[str]:
        p = self.get(key)
        args = list(self.settings.lab_ssh_options) if key == "configured" else []
        args += [
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=12",
        ]
        if p.config_file:
            args += ["-F", str(Path(p.config_file).expanduser())]
        if p.port:
            args += ["-P" if scp else "-p", str(p.port)]
        if p.user:
            args += ["-o", "User=" + p.user]
        if p.identity_file:
            args += ["-i", str(Path(p.identity_file).expanduser())]
        if p.trusted_key:
            self.folder.mkdir(parents=True, exist_ok=True)
            known = self.folder / (key + ".known_hosts")
            known.write_text(key + " " + p.trusted_key.strip() + "\n", encoding="utf-8")
            args += ["-o", "HostKeyAlias=" + key, "-o", "UserKnownHostsFile=" + str(known)]
        return args

    async def host_key(self, key: str) -> dict:
        p = self.get(key)
        config = Path(p.config_file).expanduser() if p.config_file else Path.home() / ".ssh/config"
        if key == "configured" and not p.config_file:
            legacy = self.settings.lab_ssh_options
            if "-F" in legacy and legacy.index("-F") + 1 < len(legacy):
                config = Path(legacy[legacy.index("-F") + 1]).expanduser()
        options = {"config": [str(config)]} if config.is_file() else {}
        if p.port:
            options["port"] = p.port
        host_key = await asyncio.wait_for(asyncssh.get_server_host_key(p.host, **options), 20)
        if host_key is None:
            raise ValueError("server did not provide a host key")
        return {
            "fingerprint": host_key.get_fingerprint(),
            "public_key": host_key.export_public_key().decode().strip(),
        }

    def transport(self, key: str):
        return SSHTransport(self, key)

    def aliases(self) -> list[str]:
        path = Path.home() / ".ssh/config"
        if not path.is_file():
            return []
        values = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if parts and parts[0].lower() == "host":
                values.extend(p for p in parts[1:] if not any(c in p for c in "*?!"))
        return list(dict.fromkeys(values))


# ---- SSHTransport -----------------------------------------------------------
class SSHTransport:
    def __init__(self, registry: ServerRegistry, key: str):
        self.registry, self.key = registry, key
        self.profile = registry.get(key)

    # ---- synchronous runner bridge -----------------------------------------
    def run(self, script: str, timeout: int = 30, on_line=None) -> subprocess.CompletedProcess:
        if self.profile.auth != "password" and not self.registry.secret(self.key, "passphrase"):
            args = ["ssh", *self.registry.native_options(self.key), self.profile.host, "bash -s"]
            if on_line is None:
                result = subprocess.run(
                    args,
                    input=script.replace("\r\n", "\n"),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
                return result
            return self._native_stream(args, script, timeout, on_line)
        return asyncio.run(self._async_run(script, timeout, on_line))

    def _native_stream(self, args, script, timeout, on_line):
        import threading

        process = subprocess.Popen(
            args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        timer = threading.Timer(timeout, process.kill)
        timer.start()
        tail = ""
        try:
            process.stdin.write(script.replace("\r\n", "\n").encode())
            process.stdin.close()
            for line in process.stdout:
                text = line.decode("utf-8", "replace")
                tail = (tail + text)[-64000:]
                on_line(text)
            process.wait()
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
                process.wait()
        return subprocess.CompletedProcess(args, process.returncode, tail, "")

    async def _async_run(self, script, timeout, on_line):
        async with asyncssh.connect(
            self.profile.host, **self.registry.async_options(self.key)
        ) as conn:
            if on_line is None:
                result = await conn.run(
                    "bash -s", input=script.replace("\r\n", "\n"), timeout=timeout
                )
                return subprocess.CompletedProcess(
                    [], result.exit_status, result.stdout, result.stderr
                )
            async with conn.create_process("bash -s", stderr=asyncssh.STDOUT) as process:
                process.stdin.write(script.replace("\r\n", "\n"))
                process.stdin.write_eof()
                tail = ""
                async with asyncio.timeout(timeout):
                    async for line in process.stdout:
                        tail = (tail + line)[-64000:]
                        on_line(line)
                    await process.wait_closed()
                return subprocess.CompletedProcess([], process.exit_status, tail, "")

    def upload(self, source: Path, target: str) -> None:
        if self.profile.auth != "password" and not self.registry.secret(self.key, "passphrase"):
            result = subprocess.run(
                [
                    "scp",
                    "-q",
                    *self.registry.native_options(self.key, True),
                    str(source),
                    f"{self.profile.host}:{target}",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if result.returncode:
                raise ValueError(result.stderr[-3000:])
            return

        async def transfer():
            async with (
                asyncssh.connect(
                    self.profile.host, **self.registry.async_options(self.key)
                ) as conn,
                conn.start_sftp_client() as sftp,
            ):
                await sftp.put(str(source), target)

        asyncio.run(asyncio.wait_for(transfer(), 60))


# ---- probe_server -----------------------------------------------------------
def probe_server(registry: ServerRegistry, key: str) -> dict:
    script = r"""python3 - <<'JK_PROBE'
import glob,json,os,platform,shutil,subprocess,importlib.util,re
def run(args):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=15)
        return (p.stdout+p.stderr)[-16000:]
    except Exception as e: return str(e)
paths=glob.glob(os.path.expanduser('~/Ascend/*/set_env.sh'))+glob.glob('/usr/local/Ascend/*/set_env.sh')
npu=run(['npu-smi','info'])
indices=sorted({int(m[1]) for m in re.finditer(r'^\|\s*(\d+)\s+\d{3}[A-Za-z]\w*',npu,re.M)})
print(json.dumps({'hostname':platform.node(),'system':platform.platform(),'python':platform.python_version(),
'home':os.path.expanduser('~'),'cmake':shutil.which('cmake'),'npu_smi':shutil.which('npu-smi'),
'numpy':importlib.util.find_spec('numpy') is not None,
'torch':importlib.util.find_spec('torch') is not None,
'cann_env_candidates':paths,'devices':npu,'device_indices':indices}))
JK_PROBE
"""
    result = registry.transport(key).run(script, 40)
    if result.returncode:
        raise ValueError(result.stderr[-2000:] or result.stdout[-2000:] or "SSH probe failed")
    try:
        return {
            "server": key,
            "connected": True,
            **json.loads(result.stdout.strip().splitlines()[-1]),
        }
    except (ValueError, IndexError) as exc:
        raise ValueError(
            "server probe did not return valid metadata: " + result.stdout[-1000:]
        ) from exc
