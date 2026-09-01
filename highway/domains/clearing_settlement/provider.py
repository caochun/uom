"""Clearing and settlement UOM domain provider."""

from __future__ import annotations

from pathlib import Path

from oag.ontology.domain import DomainContext
from oag.ontology.schema import Ontology

from highway.domains.clearing_settlement.business import get_settlement_trace
from uom.provider import UomDomainProvider


class ClearingSettlementDomainProvider:
    def __init__(self, domain_dir: str | Path):
        self.uom = UomDomainProvider(
            domain_dir,
            function_handlers={"get_settlement_trace": get_settlement_trace},
        )

    def load_ontology(self) -> Ontology:
        return self.uom.load_ontology()

    def register(self, context: DomainContext) -> None:
        self.uom.register(context)


def create_domain(domain_dir: str | Path) -> ClearingSettlementDomainProvider:
    return ClearingSettlementDomainProvider(domain_dir)
