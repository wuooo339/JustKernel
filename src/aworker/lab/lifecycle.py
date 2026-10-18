"""An OS-held service lock and explicit recovery of interrupted model work."""

from contextlib import contextmanager


# ---- service_lock -----------------------------------------------------------
@contextmanager
def service_lock(root):
    path = root / "service.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            import msvcrt
        except ImportError:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("another service owns this workspace") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        else:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("another service owns this workspace") from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


# ---- recover_model_work -----------------------------------------------------
def recover_model_work(service):
    """Call only while holding service_lock. Never release physical device leases."""
    snapshot = service.store.snapshot()
    service.judger.recover_submissions()
    message = "Service stopped before task completion; code and checkpoints retained."
    for row in snapshot["operations"]:
        if row["state"] == "running" and row["kind"] == "run":
            service.store.operation_finished(row["id"], "failed", message)
            service.store.event(
                row["team"], "control.failed", operation_id=row["id"], message=message
            )
    for row in snapshot["runs"]:
        if row["state"] == "running":
            service.store.run_finished(row["id"], "failed", message)
            service.store.event(row["team"], "team.turn.failed", run_id=row["id"], message=message)
