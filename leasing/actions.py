"""Financing lease Action service with domain consistency checks."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from leasing.business import audit_finance_records
from uom.actions import ModelActionService


class LeasingActionService(ModelActionService):
    def _compile_action_effects(
        self,
        action_id: str,
        effects: list[dict[str, Any]],
        inputs: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        operations = super()._compile_action_effects(action_id, effects, inputs, context)
        if action_id == "record_approval_decision" and context:
            self._enrich_approval_decision(operations, context, inputs)
        return operations

    def _enrich_approval_decision(
        self,
        operations: list[dict[str, Any]],
        context: dict[str, Any],
        inputs: dict[str, Any],
    ) -> None:
        approval = self.workspace.repository.query_by_id("Object", context.get("id"))
        if not approval:
            return
        properties = deepcopy(approval.get("properties") or {})
        details = deepcopy(properties.get("details") or {})
        history = details.setdefault("history", [])
        history.append({
            "sequence": inputs.get("sequence"),
            "decision": inputs.get("decision"),
            "occurred_on": inputs.get("occurred_on"),
            "opinion": inputs.get("opinion", ""),
        })
        if inputs.get("is_final", False):
            details["result"] = {
                "decision": inputs.get("decision"),
                "occurred_on": inputs.get("occurred_on"),
                "summary": inputs.get("opinion", "") or inputs.get("reason", ""),
            }
        else:
            details.setdefault("result", {"decision": "pending"})
            inputs = {**inputs, "decision": "pending"}
        for operation in operations:
            if operation.get("action") == "update_object" and operation.get("id") == context.get("id"):
                operation.setdefault("changes", {}).setdefault("properties", {})["status"] = inputs.get("decision")
                operation.setdefault("changes", {}).setdefault("properties", {})["details"] = details
                break

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
            elif operation["action"] == "update_object":
                target = next((item for item in objects if item.get("id") == operation.get("id")), None)
                if target is not None:
                    changes = operation.get("changes") or {}
                    for key, value in changes.items():
                        if key == "properties" and isinstance(value, dict):
                            target.setdefault("properties", {}).update(deepcopy(value))
                        else:
                            target[key] = deepcopy(value)
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
