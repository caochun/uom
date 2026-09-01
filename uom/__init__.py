"""Reusable runtime for Unified Ontology Modeling domains."""

__all__ = [
    "ChangeValidationError",
    "ModelActionService",
    "UomChangeSource",
    "UomChangeStore",
    "UomSqliteGraphSource",
    "UomWorkspaceService",
    "trace_object",
    "compose_domain_models",
    "load_composed_domain",
    "DomainDescriptor",
    "DomainRegistry",
    "DomainMatch",
    "DomainRouter",
    "DomainSelection",
    "UomRuntimeManager",
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
    if name == "compose_domain_models":
        from .composition import compose_domain_models

        return compose_domain_models
    if name == "load_composed_domain":
        from .loader import load_composed_domain

        return load_composed_domain
    if name in {"DomainDescriptor", "DomainMatch", "DomainRegistry"}:
        from .registry import DomainDescriptor, DomainMatch, DomainRegistry

        return {
            "DomainDescriptor": DomainDescriptor,
            "DomainMatch": DomainMatch,
            "DomainRegistry": DomainRegistry,
        }[name]
    if name in {"DomainRouter", "DomainSelection"}:
        from .routing import DomainRouter, DomainSelection

        return {"DomainRouter": DomainRouter, "DomainSelection": DomainSelection}[name]
    if name == "UomRuntimeManager":
        from .loader import UomRuntimeManager

        return UomRuntimeManager
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
