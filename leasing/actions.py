"""Financing lease Action service with domain consistency checks."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from leasing.business import audit_finance_records
from uom.actions import ModelActionService
from uom.workspace import ChangeValidationError


class LeasingActionService(ModelActionService):
    def _compile_action_effects(
        self,
        action_id: str,
        effects: list[dict[str, Any]],
        inputs: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        operations = super()._compile_action_effects(action_id, effects, inputs, context)
        if action_id == "start_approval":
            self._enrich_approval_start(operations, inputs)
        elif action_id == "record_approval_decision" and context:
            self._enrich_approval_decision(operations, context, inputs)
        elif action_id == "sign_contract":
            self._validate_contract_signing(inputs)
        elif action_id == "create_schedule_version":
            self._validate_schedule_replacement(inputs)
        elif action_id == "allocate_payment":
            self._enrich_payment_allocation(operations, inputs)
        elif action_id == "settle_contract":
            self._enrich_contract_settlement(operations, inputs)
        return operations

    def _enrich_approval_start(
        self,
        operations: list[dict[str, Any]],
        inputs: dict[str, Any],
    ) -> None:
        reviewed_id = inputs.get("reviewed_object")
        reviewed = self.workspace.repository.get_object(reviewed_id)
        if not reviewed or reviewed.get("type") != "lease_plan":
            return
        for relation in self.workspace.repository.query_relations():
            if (
                relation.get("type") == "references"
                and relation.get("to") == reviewed_id
                and (relation.get("properties") or {}).get("role") == "reviewed_object"
            ):
                approval = self.workspace.repository.get_object(
                    "Object", relation.get("from")
                )
                if approval and (approval.get("properties") or {}).get("status") == "pending":
                    raise ChangeValidationError(["action: 该项目方案已有进行中的审批"])
        self._merge_object_properties(operations, reviewed_id, {"status": "pending_approval"})

    def _enrich_approval_decision(
        self,
        operations: list[dict[str, Any]],
        context: dict[str, Any],
        inputs: dict[str, Any],
    ) -> None:
        approval = self.workspace.repository.get_object(context.get("id"))
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
            if inputs.get("decision") not in {"approved", "rejected"}:
                raise ChangeValidationError([
                    "action.inputs.decision: 最终审批决定必须是 approved 或 rejected"
                ])
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
        if inputs.get("is_final", False):
            self._apply_reviewed_object_decision(operations, approval, inputs)

    def _apply_reviewed_object_decision(
        self,
        operations: list[dict[str, Any]],
        approval: dict[str, Any],
        inputs: dict[str, Any],
    ) -> None:
        reviewed_ids = [
            relation.get("to")
            for relation in self.workspace.repository.query_relations()
            if relation.get("type") == "references"
            and relation.get("from") == approval.get("id")
            and (relation.get("properties") or {}).get("role") == "reviewed_object"
        ]
        if len(reviewed_ids) != 1:
            raise ChangeValidationError(["action: 审批必须且只能指向一个被审批对象"])
        reviewed = self.workspace.repository.get_object(reviewed_ids[0])
        if not reviewed or reviewed.get("type") != "lease_plan":
            return
        decision = inputs["decision"]
        self._merge_object_properties(
            operations,
            reviewed["id"],
            {"status": decision},
        )
        if decision == "rejected":
            self._append_credit_release_for_plan(
                operations,
                reviewed,
                inputs["occurred_on"],
            )

    def _append_credit_release_for_plan(
        self,
        operations: list[dict[str, Any]],
        plan: dict[str, Any],
        occurred_on: str,
    ) -> None:
        credit_ids = {
            relation.get("to")
            for relation in self.workspace.repository.query_relations()
            if relation.get("type") == "references"
            and relation.get("from") == plan.get("id")
            and (relation.get("properties") or {}).get("role") == "reserved_credit"
        }
        if len(credit_ids) != 1:
            raise ChangeValidationError(["action: 被拒方案必须关联唯一的预占授信"])
        amount = deepcopy((plan.get("properties") or {}).get("amount"))
        self._require_positive_money(amount, "项目方案金额")
        release_id = f"credit_entry:{uuid4()}"
        operations.extend([
            {
                "action": "create_object",
                "record": {
                    "id": release_id,
                    "type": "credit_entry",
                    "name": f"{plan.get('name')}审批拒绝释放额度",
                    "properties": {
                        "category": "release",
                        "amount": amount,
                        "occurred_on": occurred_on,
                        "status": "posted",
                        "reason": "方案审批未通过",
                    },
                },
            },
            self._relation_operation(
                "contains", next(iter(credit_ids)), release_id, "credit_entry"
            ),
            self._relation_operation(
                "references", release_id, plan["id"], "source_plan"
            ),
        ])

    def _validate_contract_signing(self, inputs: dict[str, Any]) -> None:
        plan = self.workspace.repository.get_object(inputs["lease_plan_id"])
        plan_money = (plan.get("properties") or {}).get("amount") if plan else None
        contract_money = inputs.get("amount")
        self._require_positive_money(contract_money, "合同金额")
        if plan_money != contract_money:
            raise ChangeValidationError(["action.inputs.amount: 合同金额必须与项目方案金额一致"])

    def _validate_schedule_replacement(self, inputs: dict[str, Any]) -> None:
        contract_id = inputs["contract_id"]
        schedule_ids = self._contract_schedule_ids(contract_id)
        schedules = {
            schedule_id: self.workspace.repository.get_object(schedule_id)
            for schedule_id in schedule_ids
        }
        if any(
            (item.get("properties") or {}).get("version") == inputs["version"]
            for item in schedules.values()
            if item
        ):
            raise ChangeValidationError(["action.inputs.version: 该合同已存在相同租金计划版本"])
        active_ids = {
            schedule_id
            for schedule_id, item in schedules.items()
            if item and (item.get("properties") or {}).get("status") == "active"
        }
        supersedes_id = inputs.get("supersedes_id")
        if active_ids and supersedes_id not in active_ids:
            raise ChangeValidationError([
                "action.inputs.supersedes_id: 已有生效租金计划时必须选择被替代的当前版本"
            ])
        if supersedes_id and supersedes_id not in active_ids:
            raise ChangeValidationError([
                "action.inputs.supersedes_id: 被替代版本必须属于当前合同且处于 active"
            ])
        if len(active_ids) > 1:
            raise ChangeValidationError(["action: 当前合同存在多个生效租金计划，请先修复数据"])

    def _enrich_payment_allocation(
        self,
        operations: list[dict[str, Any]],
        inputs: dict[str, Any],
    ) -> None:
        payment = self.workspace.repository.get_object(inputs["payment_id"])
        target = self.workspace.repository.get_object(inputs["target_id"])
        allocation_money = inputs.get("amount")
        allocation_amount, _ = self._require_positive_money(
            allocation_money,
            "核销金额",
        )
        payment_amount, _ = self._record_money(payment, "收款")
        target_amount, _ = self._record_money(target, "核销目标")
        audit = audit_finance_records(
            self.workspace.repository.query_objects(),
            self.workspace.repository.query_relations(),
        )
        if not audit["valid"]:
            raise ChangeValidationError([f"finance: {error}" for error in audit["errors"]])
        payment_total = audit["allocated_by_payment"].get(payment["id"], 0.0) + allocation_amount
        target_total = audit["allocated_by_target"].get(target["id"], 0.0) + allocation_amount
        payment_status = "allocated" if payment_total >= payment_amount - 1e-9 else "partial"
        target_status = "settled" if target_total >= target_amount - 1e-9 else "partial"
        self._merge_object_properties(operations, payment["id"], {"status": payment_status})
        self._merge_object_properties(operations, target["id"], {"status": target_status})

    def _enrich_contract_settlement(
        self,
        operations: list[dict[str, Any]],
        inputs: dict[str, Any],
    ) -> None:
        self._require_positive_money(inputs.get("amount"), "结清金额")
        contract_id = inputs["contract_id"]
        open_obligations = []
        for object_id in self._contract_obligation_ids(contract_id):
            record = self.workspace.repository.get_object(object_id)
            if record and (record.get("properties") or {}).get("status") != "settled":
                open_obligations.append(record.get("name") or object_id)
        if open_obligations:
            raise ChangeValidationError([
                "action: 合同仍有未结清应收或罚息：" + "、".join(open_obligations)
            ])

        settlement_id = next(
            operation["record"]["id"]
            for operation in operations
            if operation.get("action") == "create_object"
            and operation.get("record", {}).get("type") == "settlement"
        )
        credit_id, outstanding, currency = self._contract_credit_position(contract_id)
        if outstanding > 1e-9:
            release_id = f"credit_entry:{uuid4()}"
            operations.extend([
                {
                    "action": "create_object",
                    "record": {
                        "id": release_id,
                        "type": "credit_entry",
                        "name": f"{inputs['reference_no']}释放合同占用额度",
                        "properties": {
                            "category": "reverse_occupy",
                            "amount": {"amount": outstanding, "currency": currency},
                            "occurred_on": inputs["occurred_on"],
                            "status": "posted",
                            "reason": "合同结清",
                        },
                    },
                },
                self._relation_operation("contains", credit_id, release_id, "credit_entry"),
                self._relation_operation("references", release_id, contract_id, "source_contract"),
                self._relation_operation("references", release_id, settlement_id, "source_settlement"),
            ])

        for relation in self.workspace.repository.query_relations():
            if relation.get("type") != "contains" or relation.get("from") != contract_id:
                continue
            participant = self.workspace.repository.get_object(relation.get("to"))
            if participant and participant.get("type") == "contract_participation":
                self._merge_object_properties(
                    operations,
                    participant["id"],
                    {"status": "inactive", "valid_to": inputs["occurred_on"]},
                )
        for schedule_id in self._contract_schedule_ids(contract_id):
            schedule = self.workspace.repository.get_object(schedule_id)
            if schedule and (schedule.get("properties") or {}).get("status") == "active":
                self._merge_object_properties(
                    operations,
                    schedule_id,
                    {"status": "inactive", "valid_to": inputs["occurred_on"]},
                )

    def _contract_credit_position(self, contract_id: str) -> tuple[str, float, str]:
        objects = {
            item["id"]: item
            for item in self.workspace.repository.query_objects()
            if isinstance(item.get("id"), str)
        }
        relations = self.workspace.repository.query_relations()
        entry_ids = {
            relation.get("from")
            for relation in relations
            if relation.get("type") == "references"
            and relation.get("to") == contract_id
            and (relation.get("properties") or {}).get("role") == "source_contract"
            and objects.get(relation.get("from"), {}).get("type") == "credit_entry"
        }
        credit_ids = {
            relation.get("from")
            for relation in relations
            if relation.get("type") == "contains"
            and relation.get("to") in entry_ids
            and objects.get(relation.get("from"), {}).get("type") == "credit"
        }
        if len(credit_ids) != 1:
            raise ChangeValidationError(["action: 合同必须关联唯一的已占用授信"])
        outstanding = 0.0
        currency = ""
        for entry_id in entry_ids:
            entry = objects[entry_id]
            amount, entry_currency = self._record_money(entry, "额度流水")
            currency = currency or entry_currency
            if entry_currency != currency:
                raise ChangeValidationError(["action: 合同额度流水币种不一致"])
            category = (entry.get("properties") or {}).get("category")
            if category in {"occupy", "convert_reserve_to_used"}:
                outstanding += amount
            elif category == "reverse_occupy":
                outstanding -= amount
        if outstanding < -1e-9:
            raise ChangeValidationError(["action: 合同已释放额度超过原占用额度"])
        return next(iter(credit_ids)), outstanding, currency

    def _contract_schedule_ids(self, contract_id: str) -> set[str]:
        objects = {
            item["id"]: item
            for item in self.workspace.repository.query_objects()
            if isinstance(item.get("id"), str)
        }
        relations = self.workspace.repository.query_relations()
        change_ids = {
            relation.get("from")
            for relation in relations
            if relation.get("type") == "references"
            and relation.get("to") == contract_id
            and objects.get(relation.get("from"), {}).get("type") == "change_order"
        }
        sources = {contract_id, *change_ids}
        return {
            relation.get("to")
            for relation in relations
            if relation.get("type") == "derives"
            and relation.get("from") in sources
            and objects.get(relation.get("to"), {}).get("type") == "schedule_version"
        }

    def _contract_obligation_ids(self, contract_id: str) -> set[str]:
        objects = {
            item["id"]: item
            for item in self.workspace.repository.query_objects()
            if isinstance(item.get("id"), str)
        }
        relations = self.workspace.repository.query_relations()
        loan_ids = {
            relation.get("to")
            for relation in relations
            if relation.get("type") == "derives"
            and relation.get("from") == contract_id
            and objects.get(relation.get("to"), {}).get("type") == "loan"
        }
        receivable_sources = {
            contract_id,
            *loan_ids,
            *self._contract_schedule_ids(contract_id),
        }
        receivable_ids = {
            relation.get("to")
            for relation in relations
            if relation.get("type") == "derives"
            and relation.get("from") in receivable_sources
            and objects.get(relation.get("to"), {}).get("type") == "receivable"
        }
        penalty_ids = {
            relation.get("to")
            for relation in relations
            if relation.get("type") == "derives"
            and relation.get("from") in receivable_ids
            and objects.get(relation.get("to"), {}).get("type") == "penalty"
        }
        return receivable_ids | penalty_ids

    @staticmethod
    def _merge_object_properties(
        operations: list[dict[str, Any]],
        object_id: str,
        properties: dict[str, Any],
    ) -> None:
        for operation in operations:
            if operation.get("action") == "update_object" and operation.get("id") == object_id:
                operation.setdefault("changes", {}).setdefault("properties", {}).update(
                    deepcopy(properties)
                )
                return
        operations.append({
            "action": "update_object",
            "id": object_id,
            "changes": {"properties": deepcopy(properties)},
        })

    @staticmethod
    def _relation_operation(
        relation_type: str,
        source: str,
        target: str,
        role: str,
    ) -> dict[str, Any]:
        return {
            "action": "create_relation",
            "record": {
                "id": f"rel:{relation_type}:{uuid4()}",
                "type": relation_type,
                "from": source,
                "to": target,
                "properties": {"role": role},
            },
        }

    @staticmethod
    def _require_positive_money(value: Any, label: str) -> tuple[float, str]:
        if not isinstance(value, dict):
            raise ChangeValidationError([f"action: {label}无效"])
        amount = value.get("amount")
        currency = value.get("currency")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
            raise ChangeValidationError([f"action: {label}必须大于 0"])
        if not isinstance(currency, str):
            raise ChangeValidationError([f"action: {label}币种无效"])
        return float(amount), currency

    def _record_money(
        self,
        record: dict[str, Any] | None,
        label: str,
    ) -> tuple[float, str]:
        if not record:
            raise ChangeValidationError([f"action: 未找到{label}"])
        return self._require_positive_money(
            (record.get("properties") or {}).get("amount"),
            label,
        )

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
