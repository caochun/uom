"""FoxOMS domain provider built on the reusable UOM runtime."""

from __future__ import annotations

from pathlib import Path

from oag.ontology.domain import DomainContext
from oag.ontology.schema import Ontology

from foxoms.actions import FoxOmsActionService
from uom.provider import UomDomainProvider


class FoxOmsDomainProvider:
    def __init__(self, domain_dir: str | Path):
        self.uom = UomDomainProvider(domain_dir)

    def load_ontology(self) -> Ontology:
        return self.uom.load_ontology()

    def register(self, context: DomainContext) -> None:
        self.uom.register(context)
        workspace = context.registry.get_service("uom_workspace")
        actions = FoxOmsActionService(workspace)
        context.registry.register_action_runtime(actions)


def create_domain(domain_dir: str | Path) -> FoxOmsDomainProvider:
    return FoxOmsDomainProvider(domain_dir)
