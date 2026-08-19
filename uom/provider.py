"""OAG DomainProvider implementation for Unified Ontology Modeling."""

from __future__ import annotations

import importlib
from functools import partial
from pathlib import Path
from typing import Any

import yaml

from oag.ontology.domain import DomainContext
from oag.ontology.schema import Ontology

from uom.actions import ModelActionService
from uom.composition import (
    compose_ontology_payload,
    domain_function_implementations,
)
from uom.graph import trace_object
from uom.sqlite_adapter import UomSqliteAdapter
from uom.workspace import UomWorkspaceService


CORE_ONTOLOGY_PATH = Path(__file__).with_name("ontology.yaml")


class UomDomainProvider:
    """Load a UOM domain ontology and bind the reusable UOM runtime."""

    def __init__(self, domain_dir: str | Path):
        self.domain_dir = Path(domain_dir).resolve()
        self.model = self._load(self.domain_dir / "model.yaml")
        self.effective_payload: dict[str, Any] = {}

    def load_ontology(self) -> Ontology:
        core_payload = self._load(CORE_ONTOLOGY_PATH)
        self.effective_payload = compose_ontology_payload(core_payload, self.model)
        return Ontology.model_validate(self.effective_payload)

    def register(self, context: DomainContext) -> None:
        context.registry.register_adapter(
            "uom_sqlite",
            UomSqliteAdapter.factory(context.domain_dir),
        )
        workspace = UomWorkspaceService(
            context.domain_dir,
            context.repository,
            core_ontology_path=CORE_ONTOLOGY_PATH,
            runtime_ontology=self.effective_payload,
        )
        actions = ModelActionService(workspace)
        context.registry.register_resolver("uom_workspace", workspace)
        context.registry.register_resolver("uom_actions", actions)

        handlers = {
            "trace_object": partial(trace_object, context.repository),
            "get_model_vocabulary": workspace.get_model_vocabulary,
            "get_record_history": workspace.get_record_history,
            "preview_changes": workspace.preview_changes,
            "apply_changes": workspace.apply_changes,
            "get_available_actions": actions.get_available_actions,
            "preview_action": actions.preview_action,
            "apply_action": actions.apply_action,
        }
        for name, reference in domain_function_implementations(self.model).items():
            handlers[name] = partial(
                self._resolve_implementation(reference),
                context.repository,
            )

        missing = set(context.ontology.functions) - set(handlers)
        if missing:
            raise ValueError(
                "UOM function implementations are missing: "
                + ", ".join(sorted(missing))
            )
        for name, definition in context.ontology.functions.items():
            context.registry.register(name, handlers[name], definition)

    @staticmethod
    def _resolve_implementation(reference: str):
        if ":" not in reference:
            raise ValueError(f"Invalid UOM function implementation: {reference}")
        module_name, attribute = reference.split(":", 1)
        implementation = getattr(importlib.import_module(module_name), attribute, None)
        if not callable(implementation):
            raise ValueError(f"UOM function implementation not found: {reference}")
        return implementation

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
        if not isinstance(value, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
        return value


def create_domain(domain_dir: str | Path) -> UomDomainProvider:
    return UomDomainProvider(domain_dir)
