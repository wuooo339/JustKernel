"""Serialize synchronous read/modify/write operations from concurrent agent tools."""

import time
from functools import wraps


# ---- replace_file -----------------------------------------------------------
def replace_file(temporary, destination):
    """Retry short Windows sharing locks; persistent denial still propagates."""
    for attempt in range(6):
        try:
            temporary.replace(destination)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 5:
                raise
            time.sleep(0.02 * 2**attempt)


# ---- serialized -------------------------------------------------------------
def serialized(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        owner = getattr(self, "monitor", self)
        with owner.data_lock:
            return method(self, *args, **kwargs)

    return invoke
