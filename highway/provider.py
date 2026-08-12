"""Highway domain provider built on the reusable UOM runtime."""

from __future__ import annotations

from pathlib import Path

from oag.ontology.domain import DomainContext
from oag.ontology.schema import Ontology

from highway.spatial import SpatialViewService
from uom.provider import UomDomainProvider


class HighwayDomainProvider:
    def __init__(self, domain_dir: str | Path):
        self.uom = UomDomainProvider(domain_dir)

    def load_ontology(self) -> Ontology:
        return self.uom.load_ontology()

    def register(self, context: DomainContext) -> None:
        self.uom.register(context)
        context.registry.register_resolver(
            "spatial_view",
            SpatialViewService(context.repository),
        )


def create_domain(domain_dir: str | Path) -> HighwayDomainProvider:
    return HighwayDomainProvider(domain_dir)
