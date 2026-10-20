"""Explicit process-exit fixtures; no native crash is induced in the real service."""

import json
import signal

from aworker.config import Settings
from aworker.lab import supervisor


# ---- native crash recovery versus intentional shutdown ----------------------
def test_native_exit_codes_do_not_treat_normal_shutdown_as_crash():
    for code in [0, 1, 130, 0xC000013A]:
        assert not supervisor.native_crash(code)
    for code in [0xC0000409, -1073740791, 0xC0000005, 0xC0000374, -1073740940, -signal.SIGSEGV]:
        assert supervisor.native_crash(code)


def test_native_crash_respawns_with_same_root_and_planned_exit_stays_stopped(tmp_path, monkeypatch):
    settings = Settings(lab_root=tmp_path, _env_file=None)
    (tmp_path / "judge-attempts.json").write_text('[{"id":"already-counted"}]')
    codes = iter([0xC0000374, 0])
    calls = []

    class Child:
        pid = 123

        def wait(self):
            return next(codes)

    def spawn(command, **kwargs):
        calls.append(command)
        return Child()

    monkeypatch.setattr(supervisor.time, "sleep", lambda _: None)
    assert supervisor.supervise(settings, spawn=spawn) == 0
    assert len(calls) == 2
    assert all(str(tmp_path) in c and "faulthandler" in c for c in calls)
    assert json.loads((tmp_path / "supervisor.json").read_text())["restarts"] == 1
    assert json.loads((tmp_path / "judge-attempts.json").read_text()) == [{"id": "already-counted"}]


def test_live_attachment_waits_without_interrupting_existing_work(tmp_path):
    settings = Settings(lab_root=tmp_path, _env_file=None)
    calls = []

    def wait(pid, root):
        calls.append((pid, root))
        return 1  # Explicit planned Stop-Process, not a native failure.

    def spawn(*args, **kwargs):
        raise AssertionError("must not replace an attached live service")

    assert supervisor.supervise(settings, attach=456, spawn=spawn, wait=wait) == 1
    assert calls == [(456, tmp_path)]
