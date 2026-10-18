"""Real localhost SSH protocol, with explicit fake shell output and fixture credentials."""

import asyncio

import asyncssh
import pytest
from pydantic import SecretStr
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from aworker.config import Settings
from aworker.lab.api import create_lab_app
from aworker.lab.servers import ServerProfile, ServerRegistry, ServerSave
from aworker.lab.service import LabService


# ---- FixtureSSHServer -------------------------------------------------------
class FixtureSSHServer(asyncssh.SSHServer):
    # ---- password authentication -------------------------------------------
    def begin_auth(self, username):
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        return username == "fixture-user" and password == "fixture-password"


# ---- transport and interactive channel -------------------------------------
def test_password_transport_sftp_and_pty_verify_the_host_key(tmp_path):
    async def process(channel):
        if channel.command == "bash -s":
            source = await channel.stdin.read()
            channel.stdout.write("fixture executed: " + source.strip() + "\n")
        else:
            channel.stdout.write("fixture terminal ready\n")
            while True:
                try:
                    text = await channel.stdin.readline()
                    break
                except asyncssh.TerminalSizeChanged:
                    continue
            channel.stdout.write("fixture received: " + text)
        channel.exit(0)

    async def scenario():
        key = asyncssh.generate_private_key("ssh-ed25519")
        upload_root = tmp_path / "remote"
        upload_root.mkdir()
        server = await asyncssh.listen(
            "127.0.0.1",
            0,
            server_factory=FixtureSSHServer,
            server_host_keys=[key],
            process_factory=process,
            sftp_factory=lambda chan: asyncssh.SFTPServer(chan, chroot=str(upload_root)),
        )
        registry = ServerRegistry(
            Settings(
                lab_root=tmp_path / "lab",
                lab_private_root=tmp_path / "vault",
                lab_ssh_host=None,
                _env_file=None,
            ),
            tmp_path / "lab",
        )
        profile = ServerProfile(
            id="fixture",
            name="Local fixture",
            host="127.0.0.1",
            user="fixture-user",
            port=server.get_port(),
            auth="password",
            trusted_key=key.export_public_key().decode(),
        )
        registry.save(ServerSave(profile=profile, password=SecretStr("fixture-password")))
        try:
            result = await asyncio.to_thread(
                registry.transport("fixture").run, "fixture command", 10
            )
            assert result.returncode == 0
            assert "fixture executed: fixture command" in result.stdout
            local = tmp_path / "payload.txt"
            local.write_text("fixture payload", encoding="utf-8")
            await asyncio.to_thread(registry.transport("fixture").upload, local, "/uploaded.txt")
            assert (upload_root / "uploaded.txt").read_text() == "fixture payload"
            async with (
                asyncssh.connect(profile.host, **registry.async_options("fixture")) as conn,
                conn.create_process(term_type="xterm-256color", term_size=(100, 28)) as shell,
            ):
                assert "fixture terminal ready" in await asyncio.wait_for(
                    shell.stdout.readline(), 5
                )
                shell.change_terminal_size(120, 32)
                shell.stdin.write("hello\n")
                lines = []
                async with asyncio.timeout(5):
                    async for line in shell.stdout:
                        lines.append(line)
                        if "fixture received: hello" in line:
                            break
                assert any("fixture received: hello" in line for line in lines)

            def browser_bridge():
                service = LabService(registry.settings)
                with TestClient(create_lab_app(service)) as client:
                    route = "/api/lab/workspace/terminal/fixture"
                    with (
                        pytest.raises(WebSocketDisconnect),
                        client.websocket_connect(route, headers={"origin": "https://other"}),
                    ):
                        pytest.fail("cross-origin terminal access must be rejected")
                    with client.websocket_connect(
                        route, headers={"origin": "http://testserver"}
                    ) as channel:
                        assert channel.receive_json()["type"] == "connected"
                        assert "fixture terminal ready" in channel.receive_json()["data"]
                        channel.send_json({"type": "resize", "cols": 120, "rows": 32})
                        channel.send_json({"type": "input", "data": "websocket hello\n"})
                        output = ""
                        for _ in range(10):
                            output += channel.receive_json().get("data", "")
                            if "fixture received: websocket hello" in output:
                                break
                        assert "fixture received: websocket hello" in output

            await asyncio.wait_for(asyncio.to_thread(browser_bridge), 15)
            wrong = asyncssh.generate_private_key("ssh-ed25519")
            registry.save(
                ServerSave(
                    profile=profile.model_copy(
                        update={"trusted_key": wrong.export_public_key().decode()}
                    )
                )
            )
            with pytest.raises(asyncssh.HostKeyNotVerifiable):
                async with asyncssh.connect(profile.host, **registry.async_options("fixture")):
                    pytest.fail("a mismatched host key must never be accepted")
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(scenario())
