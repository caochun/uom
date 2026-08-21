"""Highway domain provider built on the reusable UOM runtime."""

from __future__ import annotations

from pathlib import Path

from oag.ontology.domain import DomainContext
from oag.ontology.schema import Ontology

from highway.business import (
    find_incomplete_passages,
    get_business_overview,
    get_passage_trace,
)
from highway.spatial import SpatialViewService
from uom.provider import UomDomainProvider


class HighwayDomainProvider:
    def __init__(self, domain_dir: str | Path):
        self.uom = UomDomainProvider(domain_dir, function_handlers={
            "get_business_overview": get_business_overview,
            "get_passage_trace": get_passage_trace,
            "find_incomplete_passages": find_incomplete_passages,
        })

    def load_ontology(self) -> Ontology:
        return self.uom.load_ontology()

    def register(self, context: DomainContext) -> None:
        self.uom.register(context)
        context.registry.register_service(
            "spatial_view",
            SpatialViewService(context.registry.get_service("uom_graph")),
        )


def create_domain(domain_dir: str | Path) -> HighwayDomainProvider:
    return HighwayDomainProvider(domain_dir)
