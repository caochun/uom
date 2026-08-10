"""Bind OMS storage and deterministic functions to the OAG domain."""

from __future__ import annotations

from pathlib import Path

from oms.store import OmsResolver, OmsStore


def register(registry, repository, ontology) -> None:
    """Register the handlers declared by the OAG-native ontology.yaml."""
    oms_root = Path(__file__).resolve().parents[1]
    store = OmsStore(oms_root)

    registry.register_resolver("oms_objects", OmsResolver(store, "object"))
    registry.register_resolver("oms_relations", OmsResolver(store, "relation"))

    handlers = {
        "get_business_overview": store.business_overview,
        "calculate_revenue_contribution": store.revenue_contribution,
        "find_unattributed_costs": store.find_unattributed_costs,
        "trace_object": store.trace_object,
        "get_model_vocabulary": store.get_model_vocabulary,
        "preview_changes": store.preview_changes,
        "apply_changes": store.apply_changes,
    }
    for name, handler in handlers.items():
        registry.register(name, handler, ontology.functions[name])
