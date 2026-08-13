"""Deterministic financing lease queries over the OAG ObjectRepository."""

from __future__ import annotations

from collections import Counter
from typing import Any

from oag.ontology.repository import ObjectRepository
from uom.graph import trace_object


def get_finance_overview(repository: ObjectRepository) -> dict[str, Any]:
    objects = repository.query("Object")
    relations = repository.query("Relation")
    amounts: dict[str, float] = {}
    for item in objects:
        value = (item.get("properties") or {}).get("amount")
        if isinstance(value, dict) and isinstance(value.get("amount"), (int, float)):
            amounts[item.get("type", "unknown")] = amounts.get(item.get("type", "unknown"), 0) + value["amount"]
    consistency = audit_finance_consistency(repository)
    return {
        "counts": {"objects": len(objects), "relations": len(relations)},
        "object_types": dict(Counter(item.get("type", "unknown") for item in objects)),
        "relation_types": dict(Counter(item.get("type", "unknown") for item in relations)),
        "amount_totals": amounts,
        "unallocated_payment_count": len(find_unallocated_payments(repository)),
        "consistency": consistency,
    }


def get_contract_trace(
    repository: ObjectRepository,
    contract_id: str,
    depth: int = 5,
) -> dict[str, Any]:
    contract = repository.query_by_id("Object", contract_id)
    if not contract or contract.get("type") != "contract":
        raise ValueError(f"未找到融资租赁合同: {contract_id}")
    graph = trace_object(repository, contract_id, depth)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in graph["objects"]:
        grouped.setdefault(str(item.get("type", "unknown")), []).append(item)
    return {"contract": contract, "facts_by_type": grouped, "relations": graph["relations"]}


def find_unallocated_payments(repository: ObjectRepository) -> list[dict[str, Any]]:
    objects = {item["id"]: item for item in repository.query("Object") if isinstance(item.get("id"), str)}
    allocated: set[str] = set()
    for relation in repository.query("Relation"):
        source = objects.get(relation.get("from"), {})
        target = objects.get(relation.get("to"), {})
        if relation.get("type") == "derives" and source.get("type") == "payment" and target.get("type") == "allocation":
            allocated.add(source["id"])
    return [
        item for item in objects.values()
        if item.get("type") == "payment" and item.get("id") not in allocated
    ]


def audit_finance_consistency(repository: ObjectRepository) -> dict[str, Any]:
    return audit_finance_records(
        repository.query("Object"),
        repository.query("Relation"),
    )


def audit_finance_records(
    object_records: list[dict[str, Any]],
    relations: list[dict[str, Any]],
) -> dict[str, Any]:
    objects = {
        item["id"]: item
        for item in object_records
        if isinstance(item.get("id"), str)
    }
    payment_by_allocation: dict[str, list[str]] = {}
    target_by_allocation: dict[str, list[str]] = {}
    voucher_lines: dict[str, list[str]] = {}
    credit_entries: dict[str, list[str]] = {}
    for relation in relations:
        source = objects.get(relation.get("from"), {})
        target = objects.get(relation.get("to"), {})
        if relation.get("type") == "derives" and source.get("type") == "payment" and target.get("type") == "allocation":
            payment_by_allocation.setdefault(target["id"], []).append(source["id"])
        if relation.get("type") == "references" and source.get("type") == "allocation" and target.get("type") in {"receivable", "penalty"}:
            target_by_allocation.setdefault(source["id"], []).append(target["id"])
        if relation.get("type") == "contains" and source.get("type") == "voucher" and target.get("type") == "voucher_line":
            voucher_lines.setdefault(source["id"], []).append(target["id"])
        if relation.get("type") == "contains" and source.get("type") == "credit" and target.get("type") == "credit_entry":
            credit_entries.setdefault(source["id"], []).append(target["id"])

    errors: list[str] = []
    allocated_by_payment: dict[str, float] = {}
    allocated_by_target: dict[str, float] = {}
    for allocation in (item for item in objects.values() if item.get("type") == "allocation"):
        allocation_id = allocation["id"]
        payments = payment_by_allocation.get(allocation_id, [])
        targets = target_by_allocation.get(allocation_id, [])
        if len(payments) != 1:
            errors.append(f"{allocation_id}: 必须来源于一笔收款")
        if len(targets) != 1:
            errors.append(f"{allocation_id}: 必须核销一笔应收或罚息")
        amount, currency = _money(allocation)
        if amount is None:
            errors.append(f"{allocation_id}: 核销金额无效")
            continue
        for owner_id, totals in ((payments[0], allocated_by_payment) if len(payments) == 1 else (None, {}), (targets[0], allocated_by_target) if len(targets) == 1 else (None, {})):
            if owner_id:
                owner_amount, owner_currency = _money(objects[owner_id])
                if owner_currency != currency:
                    errors.append(f"{allocation_id}: 与 {owner_id} 币种不一致")
                totals[owner_id] = totals.get(owner_id, 0) + amount
                if owner_amount is not None and totals[owner_id] > owner_amount + 1e-9:
                    errors.append(f"{owner_id}: 累计核销金额超过业务金额")

    for voucher_id, line_ids in voucher_lines.items():
        debit = credit = 0.0
        for line_id in line_ids:
            line = objects[line_id]
            amount, _ = _money(line)
            if amount is None:
                errors.append(f"{line_id}: 分录金额无效")
                continue
            direction = (line.get("properties") or {}).get("category")
            if direction == "debit":
                debit += amount
            elif direction == "credit":
                credit += amount
            else:
                errors.append(f"{line_id}: 借贷方向必须是 debit 或 credit")
        if abs(debit - credit) > 1e-9:
            errors.append(f"{voucher_id}: 借贷不平衡")

    credit_balances: dict[str, dict[str, float]] = {}
    for credit_id, entry_ids in credit_entries.items():
        reserved = used = 0.0
        currency: str | None = None
        for entry_id in entry_ids:
            entry = objects[entry_id]
            amount, entry_currency = _money(entry)
            if amount is None:
                errors.append(f"{entry_id}: 额度变动金额无效")
                continue
            currency = currency or entry_currency
            if entry_currency != currency:
                errors.append(f"{entry_id}: 额度流水币种不一致")
            category = (entry.get("properties") or {}).get("category")
            if category == "reserve":
                reserved += amount
            elif category == "release":
                reserved -= amount
            elif category == "occupy":
                used += amount
            elif category == "reverse_occupy":
                used -= amount
            elif category == "convert_reserve_to_used":
                reserved -= amount
                used += amount
            else:
                errors.append(f"{entry_id}: 未知额度变动类型 {category}")
        limit, limit_currency = _money(objects[credit_id])
        if currency and limit_currency != currency:
            errors.append(f"{credit_id}: 额度与流水币种不一致")
        if reserved < -1e-9 or used < -1e-9:
            errors.append(f"{credit_id}: 预占或已用余额不能为负")
        if limit is not None and reserved + used > limit + 1e-9:
            errors.append(f"{credit_id}: 预占与已用金额超过授信金额")
        credit_balances[credit_id] = {"reserved": reserved, "used": used}

    return {
        "valid": not errors,
        "errors": errors,
        "allocated_by_payment": allocated_by_payment,
        "allocated_by_target": allocated_by_target,
        "credit_balances": credit_balances,
    }


def _money(item: dict[str, Any]) -> tuple[float | None, str | None]:
    value = (item.get("properties") or {}).get("amount")
    if not isinstance(value, dict) or isinstance(value.get("amount"), bool) or not isinstance(value.get("amount"), (int, float)):
        return None, None
    return float(value["amount"]), value.get("currency")
