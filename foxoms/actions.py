"""FoxOMS Action service with domain-level consistency checks."""

from __future__ import annotations

from datetime import date
from typing import Any

from foxoms.business import audit_foxoms_records
from uom.actions import ModelActionService
from uom.workspace import ChangeValidationError


class FoxOmsActionService(ModelActionService):
    _ALLOCATION_ACTIONS = {
        "allocate_personnel",
        "allocate_software",
        "allocate_hardware",
    }
    _SIGNING_ACTIONS = {"sign_framework_agreement", "sign_project_contract"}
    _RESERVED_PARTICIPATION_ROLES = {
        "operating_party",
        "tenderer",
        "lead_bidder",
        "service_provider",
        "customer",
    }

    def _compile_action_effects(
        self,
        action_id: str,
        effects: list[dict[str, Any]],
        inputs: dict[str, Any],
        context: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        self._validate_business_action(action_id, inputs)
        return super()._compile_action_effects(action_id, effects, inputs, context)

    def execute_action(
        self,
        preview_token: str,
        reason: str = "",
        actor: str = "agent",
        channel: str = "agent",
    ) -> dict[str, Any]:
        with self._lock:
            preview = self._previews.get(preview_token)
            if preview is not None:
                self._validate_business_action(
                    preview["action_id"], preview["inputs"]
                )
            return super().execute_action(preview_token, reason, actor, channel)

    def list_actions(self, context_id: str = "") -> dict[str, Any]:
        result = super().list_actions(context_id)
        context = result.get("context")
        if not context:
            return result
        for action in result["actions"]:
            reason = self._availability_reason(action["id"], context)
            if reason:
                action["executable"] = False
                action.setdefault("blocked_reasons", []).append(reason)
        return result

    def _validate_business_action(
        self, action_id: str, inputs: dict[str, Any]
    ) -> None:
        if action_id == "create_opportunity":
            self._validate_opportunity(inputs)
        elif action_id == "add_business_participant":
            self._validate_participant(inputs)
        elif action_id == "record_bid_result":
            self._validate_bid_result(inputs)
        elif action_id in self._SIGNING_ACTIONS:
            self._validate_signing(inputs)
        elif action_id in self._ALLOCATION_ACTIONS:
            self._validate_allocation(inputs)
        elif action_id == "register_intellectual_asset":
            if inputs["ip_role"] not in {"required", "produced"}:
                raise ChangeValidationError([
                    "action.inputs.ip_role: 只能是 required 或 produced"
                ])
        elif action_id == "issue_invoice":
            self._require_positive_money(inputs["amount"], "发票金额")
        elif action_id == "record_receipt":
            self._validate_new_receipt(inputs)
        elif action_id == "settle_receipt":
            self._validate_settlement(inputs)

    def _validate_opportunity(self, inputs: dict[str, Any]) -> None:
        operating_party = self._object(inputs["operating_party_id"])
        if not (operating_party.get("properties") or {}).get("is_managed"):
            raise ChangeValidationError([
                "action.inputs.operating_party_id: 经营方必须是受管业务主体"
            ])
        if inputs["operating_party_id"] == inputs["potential_customer_id"]:
            raise ChangeValidationError([
                "action.inputs.potential_customer_id: 潜在客户不能与经营方相同"
            ])

    def _validate_participant(self, inputs: dict[str, Any]) -> None:
        if inputs["participation_role"] in self._RESERVED_PARTICIPATION_ROLES:
            raise ChangeValidationError([
                "action.inputs.participation_role: 核心角色应由对应业务操作建立"
            ])
        for relation in self.workspace.repository.query_relations():
            if (
                relation.get("type") == "participates_in"
                and relation.get("from") == inputs["party_id"]
                and relation.get("to") == inputs["business_object_id"]
                and (relation.get("properties") or {}).get("participation_role")
                == inputs["participation_role"]
            ):
                raise ChangeValidationError(["action: 该主体已以相同角色参与此业务"])

    def _validate_bid_result(self, inputs: dict[str, Any]) -> None:
        bid = self._object(inputs["bid_id"])
        if (bid.get("properties") or {}).get("bid_result"):
            raise ChangeValidationError(["action: 该投标已经记录结果"])
        if inputs["bid_result"] not in {"awarded", "not_awarded"}:
            raise ChangeValidationError([
                "action.inputs.bid_result: 只能是 awarded 或 not_awarded"
            ])

    def _validate_signing(self, inputs: dict[str, Any]) -> None:
        bid = self._object(inputs["bid_id"])
        if (bid.get("properties") or {}).get("bid_result") != "awarded":
            raise ChangeValidationError(["action: 只有中标记录才能形成协议或合同"])
        if self._downstream_count(bid["id"]):
            raise ChangeValidationError(["action: 该中标记录已经形成后续商务路径"])
        provider = self._object(inputs["service_provider_id"])
        if not (provider.get("properties") or {}).get("is_managed"):
            raise ChangeValidationError([
                "action.inputs.service_provider_id: 服务提供方必须是受管业务主体"
            ])
        if inputs["service_provider_id"] == inputs["customer_id"]:
            raise ChangeValidationError([
                "action.inputs.customer_id: 客户不能与服务提供方相同"
            ])

    @staticmethod
    def _validate_allocation(inputs: dict[str, Any]) -> None:
        quantity = inputs["quantity"]
        if quantity <= 0:
            raise ChangeValidationError(["action.inputs.quantity: 必须大于零"])
        start = inputs.get("start_date")
        end = inputs.get("end_date")
        if start and end and date.fromisoformat(end) < date.fromisoformat(start):
            raise ChangeValidationError([
                "action.inputs.end_date: 不能早于开始日期"
            ])

    def _validate_new_receipt(self, inputs: dict[str, Any]) -> None:
        receipt_amount, receipt_currency = self._require_positive_money(
            inputs["amount"], "回款金额"
        )
        settled_amount, settled_currency = self._require_positive_money(
            inputs["settled_amount"], "核销金额"
        )
        invoice = self._object(inputs["invoice_id"])
        invoice_amount, invoice_currency = self._record_money(invoice, "发票")
        already_settled = self._audit()["settled_by_invoice"].get(invoice["id"], 0)
        if len({receipt_currency, settled_currency, invoice_currency}) != 1:
            raise ChangeValidationError(["action: 回款、核销和发票币种必须一致"])
        if settled_amount > receipt_amount + 1e-9:
            raise ChangeValidationError(["action.inputs.settled_amount: 不能超过回款金额"])
        if already_settled + settled_amount > invoice_amount + 1e-9:
            raise ChangeValidationError(["action.inputs.settled_amount: 发票将被超额核销"])

    def _validate_settlement(self, inputs: dict[str, Any]) -> None:
        receipt = self._object(inputs["receipt_id"])
        invoice = self._object(inputs["invoice_id"])
        amount, currency = self._require_positive_money(
            inputs["settled_amount"], "核销金额"
        )
        receipt_amount, receipt_currency = self._record_money(receipt, "回款")
        invoice_amount, invoice_currency = self._record_money(invoice, "发票")
        audit = self._audit()
        if len({currency, receipt_currency, invoice_currency}) != 1:
            raise ChangeValidationError(["action: 回款、核销和发票币种必须一致"])
        if audit["settled_by_receipt"].get(receipt["id"], 0) + amount > receipt_amount + 1e-9:
            raise ChangeValidationError(["action.inputs.settled_amount: 回款将被超额核销"])
        if audit["settled_by_invoice"].get(invoice["id"], 0) + amount > invoice_amount + 1e-9:
            raise ChangeValidationError(["action.inputs.settled_amount: 发票将被超额核销"])
        current_invoice_ids = {
            relation.get("to")
            for relation in self.workspace.repository.query_relations()
            if relation.get("type") == "settles"
            and relation.get("from") == receipt["id"]
        }
        if current_invoice_ids and not self._same_transaction_chain(
            next(iter(current_invoice_ids)), invoice["id"]
        ):
            raise ChangeValidationError(["action.inputs.invoice_id: 必须属于同一交易双方"])

    def _availability_reason(
        self, action_id: str, context: dict[str, Any]
    ) -> str:
        if context.get("type") == "bid":
            result = (context.get("properties") or {}).get("bid_result")
            if action_id == "record_bid_result" and result:
                return "该投标已经记录结果"
            if action_id in self._SIGNING_ACTIONS:
                if result != "awarded":
                    return "只有中标记录才能签约"
                if self._downstream_count(context["id"]):
                    return "该中标记录已经形成后续商务路径"
        if context.get("type") == "receipt" and action_id == "settle_receipt":
            amount, _ = self._record_money(context, "回款")
            if self._audit()["settled_by_receipt"].get(context["id"], 0) >= amount - 1e-9:
                return "该回款已经全部核销"
        if context.get("type") == "invoice" and action_id == "record_receipt":
            amount, _ = self._record_money(context, "发票")
            if self._audit()["settled_by_invoice"].get(context["id"], 0) >= amount - 1e-9:
                return "该发票已经全部核销"
        return ""

    def _audit(self) -> dict[str, Any]:
        audit = audit_foxoms_records(
            self.workspace.repository.query_objects(),
            self.workspace.repository.query_relations(),
        )
        if not audit["valid"]:
            raise ChangeValidationError([
                f"foxoms: {error}" for error in audit["errors"]
            ])
        return audit

    def _same_transaction_chain(self, first_invoice: str, second_invoice: str) -> bool:
        return self._transaction_parties(first_invoice) == self._transaction_parties(
            second_invoice
        )

    def _transaction_parties(self, invoice_id: str) -> tuple[str, str] | None:
        relations = self.workspace.repository.query_relations()
        parent_ids = [
            relation.get("from")
            for relation in relations
            if relation.get("type") == "contains"
            and relation.get("to") == invoice_id
        ]
        if len(parent_ids) != 1:
            return None
        business_id = parent_ids[0]
        business = self._object(business_id)
        if business.get("type") == "order":
            framework_ids = [
                relation.get("from")
                for relation in relations
                if relation.get("type") == "contains"
                and relation.get("to") == business_id
            ]
            if len(framework_ids) != 1:
                return None
            business_id = framework_ids[0]
        by_role: dict[str, list[str]] = {"service_provider": [], "customer": []}
        for relation in relations:
            if relation.get("type") != "participates_in" or relation.get("to") != business_id:
                continue
            role = (relation.get("properties") or {}).get("participation_role")
            if role in by_role:
                by_role[role].append(relation.get("from"))
        if len(by_role["service_provider"]) == len(by_role["customer"]) == 1:
            return by_role["service_provider"][0], by_role["customer"][0]
        return None

    def _downstream_count(self, bid_id: str) -> int:
        return sum(
            relation.get("type") == "derives" and relation.get("from") == bid_id
            for relation in self.workspace.repository.query_relations()
        )

    def _object(self, object_id: str) -> dict[str, Any]:
        record = self.workspace.repository.get_object(object_id)
        if not record:
            raise ChangeValidationError([f"action: 未找到对象 {object_id}"])
        return record

    @staticmethod
    def _require_positive_money(value: Any, label: str) -> tuple[float, str]:
        amount = value.get("amount") if isinstance(value, dict) else None
        currency = value.get("currency") if isinstance(value, dict) else None
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
            raise ChangeValidationError([f"action: {label}必须大于零"])
        return float(amount), str(currency)

    @classmethod
    def _record_money(
        cls, record: dict[str, Any], label: str
    ) -> tuple[float, str]:
        return cls._require_positive_money(
            (record.get("properties") or {}).get("amount"), label
        )
