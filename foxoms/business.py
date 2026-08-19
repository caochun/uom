"""Deterministic consistency checks for the FoxOMS business graph."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Any


def audit_foxoms_records(
    object_records: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Audit cross-record rules that cannot be expressed by the UOM schema."""
    objects = {
        item["id"]: item
        for item in object_records
        if isinstance(item.get("id"), str)
    }
    errors: list[str] = []

    incoming_contains: dict[str, list[str]] = defaultdict(list)
    incoming_derives: dict[str, list[str]] = defaultdict(list)
    participants: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    settlements_by_receipt: dict[str, float] = defaultdict(float)
    settlements_by_invoice: dict[str, float] = defaultdict(float)
    ip_links: Counter[str] = Counter()
    downstream_by_bid: Counter[str] = Counter()
    participant_keys: set[tuple[str, str, str]] = set()

    for relation in relations:
        relation_type = relation.get("type")
        source_id = relation.get("from")
        target_id = relation.get("to")
        if relation_type == "contains":
            incoming_contains[target_id].append(source_id)
        elif relation_type == "derives":
            incoming_derives[target_id].append(source_id)
            downstream_by_bid[source_id] += 1
        elif relation_type == "participates_in":
            role = (relation.get("properties") or {}).get("participation_role")
            key = (str(source_id), str(target_id), str(role))
            if key in participant_keys:
                errors.append(f"{relation.get('id')}: 同一主体不能以相同角色重复参与业务")
            participant_keys.add(key)
            participants[target_id][str(role)].append(source_id)
        elif relation_type == "involves_ip":
            ip_links[target_id] += 1
        elif relation_type == "allocated_to":
            _audit_allocation(relation, errors)
        elif relation_type == "settles":
            _audit_settlement(
                relation,
                objects,
                settlements_by_receipt,
                settlements_by_invoice,
                errors,
            )

    for record in objects.values():
        object_id = record["id"]
        object_type = record.get("type")
        if object_type == "opportunity":
            operating_parties = participants[object_id]["operating_party"]
            potential_customers = participants[object_id]["potential_customer"]
            if len(operating_parties) != 1:
                errors.append(f"{object_id}: 商机必须有一个经营方")
            elif not (objects.get(operating_parties[0], {}).get("properties") or {}).get(
                "is_managed"
            ):
                errors.append(f"{object_id}: 商机经营方必须是受管业务主体")
            if not potential_customers:
                errors.append(f"{object_id}: 商机必须有潜在客户")
        elif object_type == "tender":
            _require_parent_type(
                object_id, "招标事项", "opportunity", incoming_contains, objects, errors
            )
            if len(participants[object_id]["tenderer"]) != 1:
                errors.append(f"{object_id}: 招标事项必须有一个招标方")
        elif object_type == "bid":
            _require_parent_type(
                object_id, "投标记录", "tender", incoming_contains, objects, errors
            )
            if not participants[object_id]["lead_bidder"]:
                errors.append(f"{object_id}: 投标记录必须有牵头投标方")
            result = (record.get("properties") or {}).get("bid_result")
            if result is not None and result not in {"awarded", "not_awarded"}:
                errors.append(f"{object_id}: 投标结果无效")
        elif object_type in {"framework_agreement", "contract"}:
            parent_ids = incoming_derives[object_id]
            if len(parent_ids) != 1 or objects.get(parent_ids[0], {}).get("type") != "bid":
                errors.append(f"{object_id}: 协议或合同必须由一个投标记录形成")
            elif (objects[parent_ids[0]].get("properties") or {}).get(
                "bid_result"
            ) != "awarded":
                errors.append(f"{object_id}: 只能由中标记录形成协议或合同")
            _require_transaction_parties(object_id, participants, objects, errors)
        elif object_type == "order":
            _require_parent_type(
                object_id,
                "订单",
                "framework_agreement",
                incoming_contains,
                objects,
                errors,
            )
        elif object_type == "work_item":
            _require_parent_type(
                object_id, "项目/任务", "contract", incoming_contains, objects, errors
            )
        elif object_type == "invoice":
            parents = incoming_contains[object_id]
            if len(parents) != 1 or objects.get(parents[0], {}).get("type") not in {
                "contract",
                "order",
            }:
                errors.append(f"{object_id}: 发票必须属于一个项目合同或订单")
            _audit_positive_money(record, "发票", errors)
        elif object_type == "receipt":
            _audit_positive_money(record, "回款", errors)
            if settlements_by_receipt[object_id] <= 0:
                errors.append(f"{object_id}: 回款必须至少核销一张发票")
        elif object_type == "intellectual_asset" and ip_links[object_id] != 1:
            errors.append(f"{object_id}: 知识资产必须且只能关联一个履约对象")

    for relation in relations:
        if relation.get("type") != "involves_ip":
            continue
        role = (relation.get("properties") or {}).get("ip_role")
        if role not in {"required", "produced"}:
            errors.append(f"{relation.get('id')}: 知识资产角色无效")

    for bid_id, count in downstream_by_bid.items():
        if count > 1:
            errors.append(f"{bid_id}: 一个中标记录只能形成一条后续商务路径")

    for receipt_id, total in settlements_by_receipt.items():
        amount, _ = _money(objects.get(receipt_id))
        if amount is not None and total > amount + 1e-9:
            errors.append(f"{receipt_id}: 累计核销金额超过回款金额")
    for invoice_id, total in settlements_by_invoice.items():
        amount, _ = _money(objects.get(invoice_id))
        if amount is not None and total > amount + 1e-9:
            errors.append(f"{invoice_id}: 累计核销金额超过发票金额")

    for receipt_id in settlements_by_receipt:
        pairs = {
            pair
            for invoice_id in _settled_invoice_ids(receipt_id, relations)
            if (pair := _invoice_party_pair(
                invoice_id, incoming_contains, participants, objects
            ))
        }
        if len(pairs) > 1:
            errors.append(f"{receipt_id}: 一笔回款只能核销同一交易双方的发票")

    return {
        "valid": not errors,
        "errors": errors,
        "settled_by_receipt": dict(settlements_by_receipt),
        "settled_by_invoice": dict(settlements_by_invoice),
    }


def _require_parent_type(
    object_id: str,
    label: str,
    parent_type: str,
    incoming: dict[str, list[str]],
    objects: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    parent_ids = incoming[object_id]
    if len(parent_ids) != 1 or objects.get(parent_ids[0], {}).get("type") != parent_type:
        errors.append(f"{object_id}: {label}必须有一个 {parent_type} 上级")


def _require_transaction_parties(
    object_id: str,
    participants: dict[str, dict[str, list[str]]],
    objects: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    providers = participants[object_id]["service_provider"]
    customers = participants[object_id]["customer"]
    if len(providers) != 1 or len(customers) != 1:
        errors.append(f"{object_id}: 协议或合同必须有一个服务提供方和一个客户")
        return
    provider = objects.get(providers[0], {})
    if not (provider.get("properties") or {}).get("is_managed"):
        errors.append(f"{object_id}: 服务提供方必须是受管业务主体")
    if providers[0] == customers[0]:
        errors.append(f"{object_id}: 服务提供方和客户不能是同一主体")


def _audit_allocation(relation: dict[str, Any], errors: list[str]) -> None:
    properties = relation.get("properties") or {}
    quantity = properties.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or quantity <= 0:
        errors.append(f"{relation.get('id')}: 资源投入数量必须大于零")
    start = properties.get("start_date")
    end = properties.get("end_date")
    if start and end:
        try:
            if date.fromisoformat(end) < date.fromisoformat(start):
                errors.append(f"{relation.get('id')}: 资源投入结束日期不能早于开始日期")
        except (TypeError, ValueError):
            errors.append(f"{relation.get('id')}: 资源投入日期无效")


def _audit_positive_money(
    record: dict[str, Any], label: str, errors: list[str]
) -> None:
    amount, _ = _money(record)
    if amount is None or amount <= 0:
        errors.append(f"{record['id']}: {label}金额必须大于零")


def _audit_settlement(
    relation: dict[str, Any],
    objects: dict[str, dict[str, Any]],
    by_receipt: dict[str, float],
    by_invoice: dict[str, float],
    errors: list[str],
) -> None:
    value = (relation.get("properties") or {}).get("settled_amount")
    amount, currency = _money_value(value)
    if amount is None or amount <= 0:
        errors.append(f"{relation.get('id')}: 核销金额必须大于零")
        return
    receipt_id = relation.get("from")
    invoice_id = relation.get("to")
    receipt_amount, receipt_currency = _money(objects.get(receipt_id))
    invoice_amount, invoice_currency = _money(objects.get(invoice_id))
    if receipt_amount is None or invoice_amount is None:
        errors.append(f"{relation.get('id')}: 核销两端缺少有效业务金额")
        return
    if currency != receipt_currency or currency != invoice_currency:
        errors.append(f"{relation.get('id')}: 核销、回款和发票币种必须一致")
    by_receipt[receipt_id] += amount
    by_invoice[invoice_id] += amount


def _settled_invoice_ids(
    receipt_id: str, relations: list[dict[str, Any]]
) -> list[str]:
    return [
        relation["to"]
        for relation in relations
        if relation.get("type") == "settles" and relation.get("from") == receipt_id
    ]


def _invoice_party_pair(
    invoice_id: str,
    incoming_contains: dict[str, list[str]],
    participants: dict[str, dict[str, list[str]]],
    objects: dict[str, dict[str, Any]],
) -> tuple[str, str] | None:
    parent_ids = incoming_contains[invoice_id]
    if len(parent_ids) != 1:
        return None
    business_id = parent_ids[0]
    if objects.get(business_id, {}).get("type") == "order":
        framework_ids = incoming_contains[business_id]
        if len(framework_ids) != 1:
            return None
        business_id = framework_ids[0]
    providers = participants[business_id]["service_provider"]
    customers = participants[business_id]["customer"]
    if len(providers) == len(customers) == 1:
        return providers[0], customers[0]
    return None


def _money(record: dict[str, Any] | None) -> tuple[float | None, str | None]:
    return _money_value((record or {}).get("properties", {}).get("amount"))


def _money_value(value: Any) -> tuple[float | None, str | None]:
    if not isinstance(value, dict):
        return None, None
    amount = value.get("amount")
    currency = value.get("currency")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return None, None
    if not isinstance(currency, str):
        return None, None
    return float(amount), currency
