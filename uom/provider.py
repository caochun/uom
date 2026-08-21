"""OAG DomainProvider implementation for Unified Ontology Modeling."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Callable

from oag.ontology.domain import DomainContext
from oag.ontology.schema import Ontology

from uom.actions import ModelActionService
from uom.model import (
    load_action_plans,
    load_public_ontology,
    validate_action_plans,
)
from uom.sqlite_adapter import UomGraphAccess, UomSqliteGraphSource
from uom.workspace import UomWorkspaceService


class UomDomainProvider:
    """Load a UOM domain ontology and bind the reusable UOM runtime."""

    def __init__(
        self,
        domain_dir: str | Path,
        function_handlers: dict[str, Callable[..., Any]] | None = None,
    ):
        self.domain_dir = Path(domain_dir).resolve()
        self.function_handlers = dict(function_handlers or {})

    def load_ontology(self) -> Ontology:
        public_model, ontology = load_public_ontology(self.domain_dir)
        validate_action_plans(public_model, load_action_plans(self.domain_dir))
        return ontology

    def register(self, context: DomainContext) -> None:
        context.registry.register_source_adapter(
            "uom_sqlite_graph",
            UomSqliteGraphSource.factory(context.domain_dir),
        )
        source = context.ontology.data_sources["uom_graph"]
        graph = UomGraphAccess(
            context.domain_dir,
            source.config.get("database") or source.config.get("path"),
        )
        workspace = UomWorkspaceService(
            context.domain_dir,
            graph,
        )
        actions = ModelActionService(workspace)
        context.registry.register_service("uom_workspace", workspace)
        context.registry.register_service("uom_graph", graph)
        context.registry.register_action_runtime(actions)

        for name, handler in self.function_handlers.items():
            definition = context.ontology.functions.get(name)
            if definition is None:
                raise ValueError(f"function handler references unknown model function: {name}")
            context.registry.register(
                name,
                partial(handler, context.repository),
                definition,
            )


def create_domain(domain_dir: str | Path) -> UomDomainProvider:
    return UomDomainProvider(domain_dir)
