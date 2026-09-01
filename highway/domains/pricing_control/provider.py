"""Provider for the Highway pricing and business-control domain."""

from __future__ import annotations

from pathlib import Path

from oag.ontology.domain import DomainContext
from oag.ontology.schema import Ontology

from highway.domains.pricing_control.business import (
    get_passage_fare_basis,
    get_pricing_control_overview,
)
from uom.provider import UomDomainProvider


class PricingControlDomainProvider:
    def __init__(self, domain_dir: str | Path):
        self.uom = UomDomainProvider(
            domain_dir,
            function_handlers={
                "get_pricing_control_overview": get_pricing_control_overview,
                "get_passage_fare_basis": get_passage_fare_basis,
            },
        )

    def load_ontology(self) -> Ontology:
        return self.uom.load_ontology()

    def register(self, context: DomainContext) -> None:
        self.uom.register(context)


def create_domain(domain_dir: str | Path) -> PricingControlDomainProvider:
    return PricingControlDomainProvider(domain_dir)
