"""Deterministic OMS calculations over the OAG ObjectRepository."""

from __future__ import annotations

from typing import Any

from oag.ontology.repository import ObjectRepository


def get_business_overview(repository: ObjectRepository) -> dict[str, Any]:
    objects = repository.query("Object")
    totals: dict[str, dict[str, float]] = {
        "revenue": {},
        "cost": {},
        "cash_receipt": {},
        "cash_payment": {},
    }
    for item in objects:
        object_type = item.get("type")
        if object_type not in totals:
            continue
        money = item.get("properties", {}).get("amount", {})
        amount, currency = money.get("amount"), money.get("currency")
        if isinstance(amount, (int, float)) and isinstance(currency, str):
            totals[object_type][currency] = totals[object_type].get(currency, 0) + amount
    return {
        "counts": {
            "objects": len(objects),
            "relations": repository.count("Relation"),
        },
        "totals": totals,
        "unattributed_costs": find_unattributed_costs(repository),
    }


def calculate_revenue_contribution(
    repository: ObjectRepository,
    revenue_id: str,
) -> dict[str, Any]:
    revenue = repository.query_by_id("Object", revenue_id)
    if not revenue or revenue.get("type") != "revenue":
        raise ValueError(f"未找到收入对象: {revenue_id}")
    money = revenue.get("properties", {}).get("amount", {})
    currency = money.get("currency")
    revenue_amount = money.get("amount")
    if not isinstance(revenue_amount, (int, float)) or not isinstance(currency, str):
        raise ValueError("收入对象缺少有效金额")

    attributions = []
    attributed = 0.0
    for relation in repository.query(
        "Relation",
        filters={"type": "allocated_to", "to": revenue_id},
    ):
        source = repository.query_by_id("Object", str(relation.get("from")))
        if not source or source.get("type") != "cost":
            continue
        properties = relation.get("properties", {})
        relation_money = properties.get("amount", {})
        if (
            properties.get("status") == "confirmed"
            and relation_money.get("currency") == currency
            and isinstance(relation_money.get("amount"), (int, float))
        ):
            amount = float(relation_money["amount"])
            attributed += amount
            attributions.append({
                "relation_id": relation.get("id"),
                "cost_id": relation.get("from"),
                "amount": amount,
                "basis": properties.get("basis"),
            })
    return {
        "revenue_id": revenue_id,
        "revenue_amount": revenue_amount,
        "currency": currency,
        "attributed_cost": attributed,
        "contribution": float(revenue_amount) - attributed,
        "attributions": attributions,
    }


def find_unattributed_costs(repository: ObjectRepository) -> list[dict[str, Any]]:
    disposition: dict[tuple[str, str], float] = {}
    cost_ids = {
        str(item.get("id"))
        for item in repository.query("Object", filters={"type": "cost"})
    }
    for relation in repository.query("Relation", filters={"type": "allocated_to"}):
        if str(relation.get("from")) not in cost_ids:
            continue
        properties = relation.get("properties", {})
        if properties.get("status") != "confirmed":
            continue
        money = properties.get("amount", {})
        amount, currency = money.get("amount"), money.get("currency")
        if isinstance(amount, (int, float)) and isinstance(currency, str):
            key = (str(relation.get("from")), currency)
            disposition[key] = disposition.get(key, 0) + float(amount)

    result = []
    for item in repository.query("Object", filters={"type": "cost"}):
        money = item.get("properties", {}).get("amount", {})
        amount, currency = money.get("amount"), money.get("currency")
        if not isinstance(amount, (int, float)) or not isinstance(currency, str):
            continue
        remaining = float(amount) - disposition.get((str(item.get("id")), currency), 0)
        if remaining > 1e-9:
            result.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "amount": amount,
                "currency": currency,
                "unattributed_amount": remaining,
                "period": item.get("properties", {}).get("period"),
            })
    return result


def trace_object(
    repository: ObjectRepository,
    object_id: str,
    depth: int = 2,
) -> dict[str, Any]:
    root = repository.query_by_id("Object", object_id)
    if not root:
        raise ValueError(f"未知对象: {object_id}")

    object_index = {
        item["id"]: item
        for item in repository.query("Object")
        if isinstance(item.get("id"), str)
    }
    relations = repository.query("Relation")
    seen = {object_id}
    frontier = {object_id}
    matched_relations: list[dict[str, Any]] = []
    seen_relations: set[str] = set()
    for _ in range(max(0, min(depth, 5))):
        next_frontier: set[str] = set()
        for relation in relations:
            source, target = relation.get("from"), relation.get("to")
            if source not in frontier and target not in frontier:
                continue
            relation_id = str(relation.get("id"))
            if relation_id not in seen_relations:
                matched_relations.append(relation)
                seen_relations.add(relation_id)
            for endpoint in (source, target):
                if isinstance(endpoint, str) and endpoint not in seen:
                    seen.add(endpoint)
                    next_frontier.add(endpoint)
        frontier = next_frontier
        if not frontier:
            break
    return {
        "root": root,
        "objects": [object_index[item_id] for item_id in seen if item_id in object_index],
        "relations": matched_relations,
    }
