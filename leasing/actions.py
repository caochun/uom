"""Financing lease Action service with domain consistency checks."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from leasing.business import audit_finance_records
from uom.actions import ModelActionService


class LeasingActionService(ModelActionService):
    def preview_action(
        self,
        action_id: str,
        inputs: dict[str, Any] | None = None,
        context_id: str = "",
    ) -> dict[str, Any]:
        result = super().preview_action(action_id, inputs, context_id)
        if not result["valid"]:
            return result

        snapshot = self.workspace.snapshot()
        objects = deepcopy(snapshot["objects"]["objects"])
        relations = deepcopy(snapshot["relations"]["relations"])
        for operation in result["operations"]:
            if operation["action"] == "create_object":
                objects.append(deepcopy(operation["record"]))
            elif operation["action"] == "create_relation":
                relations.append(deepcopy(operation["record"]))

        consistency = audit_finance_records(objects, relations)
        result["finance_consistency"] = consistency
        if consistency["valid"]:
            return result

        token = result.pop("preview_token", None)
        if token:
            self._previews.pop(token, None)
        result["valid"] = False
        result["errors"] = [
            *result["errors"],
            *(f"finance: {error}" for error in consistency["errors"]),
        ]
        return result
