"""Shared test helpers."""
import sys


def reset_app_modules() -> None:
    """Forget all app.* modules AND SQLModel's global table registry so a test
    can re-import the app against fresh env vars without 'table already
    defined' collisions."""
    from sqlmodel import SQLModel
    for mod in list(sys.modules):
        if mod.startswith("app."):
            del sys.modules[mod]
    SQLModel.metadata.clear()
    try:
        from sqlmodel.main import default_registry
        default_registry.dispose()
    except Exception:
        pass
