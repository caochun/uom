"""Deterministic highway-domain queries over the OAG ObjectRepository."""

from __future__ import annotations

from collections import Counter
from typing import Any

from oag.ontology.repository import ObjectRepository


def get_business_overview(repository: ObjectRepository) -> dict[str, Any]:
    objects = repository.query("Object")
    relations = repository.query("Relation")
    object_counts = Counter(str(item.get("type", "unknown")) for item in objects)
    relation_counts = Counter(str(item.get("type", "unknown")) for item in relations)
    amount_totals: dict[str, dict[str, float]] = {}
    for item in objects:
        properties = item.get("properties", {})
        for property_name in ("amount", "paid_amount"):
            money = properties.get(property_name, {})
            if not isinstance(money, dict):
                continue
            amount, currency = money.get("amount"), money.get("currency")
            if isinstance(amount, (int, float)) and isinstance(currency, str):
                object_type = str(item.get("type", "unknown"))
                totals = amount_totals.setdefault(object_type, {})
                totals[currency] = totals.get(currency, 0.0) + float(amount)

    incomplete = find_incomplete_passages(repository)
    return {
        "counts": {
            "objects": len(objects),
            "relations": len(relations),
        },
        "object_types": dict(sorted(object_counts.items())),
        "relation_types": dict(sorted(relation_counts.items())),
        "amount_totals": amount_totals,
        "incomplete_passage_count": len(incomplete),
    }


def get_passage_trace(
    repository: ObjectRepository,
    passage_id: str,
    depth: int = 4,
) -> dict[str, Any]:
    passage = repository.query_by_id("Object", passage_id)
    if not passage or passage.get("type") != "passage":
        raise ValueError(f"未找到通行记录: {passage_id}")

    graph = trace_object(repository, passage_id, depth)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in graph["objects"]:
        grouped.setdefault(str(item.get("type", "unknown")), []).append(item)
    return {
        "passage": passage,
        "facts_by_type": grouped,
        "relations": graph["relations"],
    }


def find_incomplete_passages(repository: ObjectRepository) -> list[dict[str, Any]]:
    object_index = {
        str(item.get("id")): item
        for item in repository.query("Object")
        if isinstance(item.get("id"), str)
    }
    relations = repository.query("Relation")
    result = []
    for passage in repository.query("Object", filters={"type": "passage"}):
        passage_id = str(passage.get("id"))
        stages: set[str] = set()
        has_split = False
        for relation in relations:
            if relation.get("from") != passage_id:
                continue
            target = object_index.get(str(relation.get("to")), {})
            if relation.get("type") == "references" and target.get("type") == "toll_transaction":
                stage = target.get("properties", {}).get("stage")
                if isinstance(stage, str):
                    stages.add(stage)
            if relation.get("type") == "derives" and target.get("type") == "split_record":
                has_split = True

        missing = []
        for stage in ("entry", "exit"):
            if stage not in stages:
                missing.append(f"{stage}_transaction")
        if not has_split:
            missing.append("split_record")
        if missing:
            result.append({
                "id": passage.get("id"),
                "name": passage.get("name"),
                "status": passage.get("properties", {}).get("status"),
                "transaction_stages": sorted(stages),
                "missing": missing,
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
