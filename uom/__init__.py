"""Reusable runtime for Unified Ontology Modeling domains."""

__all__ = [
    "ChangeValidationError",
    "ModelActionService",
    "UomChangeSource",
    "UomChangeStore",
    "UomSqliteGraphSource",
    "UomWorkspaceService",
    "trace_object",
]


def __getattr__(name: str):
    if name == "ModelActionService":
        from .actions import ModelActionService

        return ModelActionService
    if name in {"UomChangeSource", "UomChangeStore"}:
        from .change_store import UomChangeSource, UomChangeStore

        return {
            "UomChangeSource": UomChangeSource,
            "UomChangeStore": UomChangeStore,
        }[name]
    if name == "trace_object":
        from .graph import trace_object

        return trace_object
    if name == "UomSqliteGraphSource":
        from .sqlite_adapter import UomSqliteGraphSource

        return UomSqliteGraphSource
    if name in {"ChangeValidationError", "UomWorkspaceService"}:
        from .workspace import ChangeValidationError, UomWorkspaceService

        return {
            "ChangeValidationError": ChangeValidationError,
            "UomWorkspaceService": UomWorkspaceService,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
