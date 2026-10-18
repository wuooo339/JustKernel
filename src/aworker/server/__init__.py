"""A2A server package: exposes the swarm as a single agent.

The public entry points are imported lazily so that importing a server submodule
(for example ``aworker.server.credentials``) does not eagerly build the app and
create an import cycle with the swarm.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aworker.server.app import create_app, run_server

__all__ = ["create_app", "run_server"]


# ---- __getattr__ ------------------------------------------------------------
def __getattr__(name: str) -> Any:
    if name in __all__:
        from aworker.server import app

        return getattr(app, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
