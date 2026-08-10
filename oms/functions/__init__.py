"""Bind the OMS adapter and deterministic functions to the OAG domain."""

from __future__ import annotations

from pathlib import Path

from oms.actions import OmsActionService
from oms.business import (
    calculate_revenue_contribution,
    find_unattributed_costs,
    get_business_overview,
    trace_object,
)
from oms.sqlite_adapter import OmsSqliteAdapter
from oms.store import OmsWorkspaceService


def register(registry, repository, ontology) -> None:
    """Register the handlers declared by the OAG-native ontology.yaml."""
    oms_root = Path(__file__).resolve().parents[1]
    registry.register_adapter("oms_sqlite", OmsSqliteAdapter.factory(oms_root))
    workspace = OmsWorkspaceService(oms_root, repository)
    actions = OmsActionService(workspace)
    registry.register_resolver("oms_actions", actions)

    handlers = {
        "get_business_overview": lambda: get_business_overview(repository),
        "calculate_revenue_contribution": (
            lambda revenue_id: calculate_revenue_contribution(repository, revenue_id)
        ),
        "find_unattributed_costs": lambda: find_unattributed_costs(repository),
        "trace_object": (
            lambda object_id, depth=2: trace_object(repository, object_id, depth)
        ),
        "get_model_vocabulary": workspace.get_model_vocabulary,
        "preview_changes": workspace.preview_changes,
        "apply_changes": workspace.apply_changes,
        "get_available_actions": actions.get_available_actions,
        "preview_action": actions.preview_action,
        "apply_action": actions.apply_action,
    }
    for name, handler in handlers.items():
        registry.register(name, handler, ontology.functions[name])
