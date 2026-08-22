"""Financing lease domain provider built on the reusable UOM runtime."""

from __future__ import annotations

from pathlib import Path

from oag.ontology.domain import DomainContext
from oag.ontology.schema import Ontology

from leasing.actions import LeasingActionService
from leasing.business import (
    audit_finance_consistency,
    find_unallocated_payments,
    get_contract_trace,
    get_finance_overview,
)
from uom.provider import UomDomainProvider


class LeasingDomainProvider:
    def __init__(self, domain_dir: str | Path):
        self.uom = UomDomainProvider(
            domain_dir,
            function_handlers={
                "get_finance_overview": get_finance_overview,
                "get_contract_trace": get_contract_trace,
                "find_unallocated_payments": find_unallocated_payments,
                "audit_finance_consistency": audit_finance_consistency,
            },
            action_runtime_factory=LeasingActionService,
        )

    def load_ontology(self) -> Ontology:
        return self.uom.load_ontology()

    def register(self, context: DomainContext) -> None:
        self.uom.register(context)


def create_domain(domain_dir: str | Path) -> LeasingDomainProvider:
    return LeasingDomainProvider(domain_dir)
