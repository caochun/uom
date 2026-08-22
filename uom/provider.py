"""OAG DomainProvider implementation for Unified Ontology Modeling."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Callable

from oag.ontology.domain import DomainContext
from oag.ontology.schema import Ontology

from uom.actions import ModelActionService
from uom.change_store import UomChangeSource, UomChangeStore
from uom.model import (
    load_action_plans,
    load_domain_model,
    load_public_ontology,
    validate_action_plans,
)
from uom.sqlite_adapter import UomSqliteGraphSource
from uom.workspace import UomWorkspaceService


class UomDomainProvider:
    """Load a UOM domain ontology and bind the reusable UOM runtime."""

    def __init__(
        self,
        domain_dir: str | Path,
        function_handlers: dict[str, Callable[..., Any]] | None = None,
        action_runtime_factory: Callable[[UomWorkspaceService], Any] | None = None,
    ):
        self.domain_dir = Path(domain_dir).resolve()
        self.function_handlers = dict(function_handlers or {})
        self.action_runtime_factory = action_runtime_factory
        self.workspace: UomWorkspaceService | None = None
        self.change_store: UomChangeStore | None = None
        self.actions: Any = None

    def load_ontology(self) -> Ontology:
        public_model, ontology = load_public_ontology(self.domain_dir)
        validate_action_plans(public_model, load_action_plans(self.domain_dir))
        return ontology

    def register(self, context: DomainContext) -> None:
        context.sources.register(
            "uom_sqlite_graph",
            UomSqliteGraphSource.factory(self.domain_dir),
        )
        _, source_model = load_domain_model(self.domain_dir)
        source_name = source_model.default_repository
        source = context.sources.require(source_name, UomChangeSource)
        change_store = UomChangeStore(
            source,
            writable=context.ontology.data_sources[source_name].mode == "writable",
        )
        workspace = UomWorkspaceService(
            self.domain_dir,
            change_store,
        )
        actions = (
            self.action_runtime_factory(workspace)
            if self.action_runtime_factory is not None
            else ModelActionService(workspace)
        )
        self.workspace = workspace
        self.change_store = change_store
        self.actions = actions
        context.bindings.register_action_runtime(actions)

        for name, handler in self.function_handlers.items():
            definition = context.ontology.functions.get(name)
            if definition is None:
                raise ValueError(f"function handler references unknown model function: {name}")
            context.bindings.register(
                name,
                partial(handler, context.repository),
                definition,
            )


def create_domain(domain_dir: str | Path) -> UomDomainProvider:
    return UomDomainProvider(domain_dir)
