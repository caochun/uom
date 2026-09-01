"""Facility-operations UOM domain provider."""

from __future__ import annotations

from pathlib import Path

from oag.ontology.domain import DomainContext
from oag.ontology.schema import Ontology

from highway.domains.facility_operations.business import get_facility_overview
from uom.provider import UomDomainProvider


class FacilityOperationsDomainProvider:
    def __init__(self, domain_dir: str | Path):
        self.uom = UomDomainProvider(
            domain_dir,
            function_handlers={"get_facility_overview": get_facility_overview},
        )

    def load_ontology(self) -> Ontology:
        return self.uom.load_ontology()

    def register(self, context: DomainContext) -> None:
        self.uom.register(context)


def create_domain(domain_dir: str | Path) -> FacilityOperationsDomainProvider:
    return FacilityOperationsDomainProvider(domain_dir)
