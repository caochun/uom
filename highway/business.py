"""Deterministic highway-domain queries over the OAG ontology repository."""

from __future__ import annotations

from collections import Counter
from typing import Any

from oag.ontology.repository import OntologyRepository
from uom.graph import trace_object


def get_business_overview(repository: OntologyRepository) -> dict[str, Any]:
    objects = repository.query_all_objects()
    relations = repository.query_all_relations()
    object_counts = Counter(str(item.get("_object_type", "unknown")) for item in objects)
    relation_counts = Counter(str(item.get("_object_type", "unknown")) for item in relations)
    amount_totals: dict[str, dict[str, float]] = {}
    for item in objects:
        for property_name in ("amount", "paid_amount"):
            money = item.get(property_name, {})
            if not isinstance(money, dict):
                continue
            amount, currency = money.get("amount"), money.get("currency")
            if isinstance(amount, (int, float)) and isinstance(currency, str):
                object_type = str(item.get("_object_type", "unknown"))
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
    repository: OntologyRepository,
    passage_id: str,
    depth: int = 4,
) -> dict[str, Any]:
    passage = repository.get_object("passage", passage_id)
    if not passage:
        raise ValueError(f"未找到通行记录: {passage_id}")

    graph = trace_object(repository, passage_id, depth)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in graph["objects"]:
        grouped.setdefault(str(item.get("_object_type", "unknown")), []).append(item)
    return {
        "passage": passage,
        "facts_by_type": grouped,
        "relations": graph["relations"],
    }


def find_incomplete_passages(repository: OntologyRepository) -> list[dict[str, Any]]:
    object_index = {
        str(item.get("id")): item
        for item in repository.query_all_objects()
        if isinstance(item.get("id"), str)
    }
    relations = repository.query_all_relations()
    result = []
    for passage in repository.query_objects("passage"):
        passage_id = str(passage.get("id"))
        stages: set[str] = set()
        has_split = False
        for relation in relations:
            if relation.get("from") != passage_id:
                continue
            target = object_index.get(str(relation.get("to")), {})
            if relation.get("_object_type") == "references" and target.get("_object_type") == "toll_transaction":
                stage = target.get("stage")
                if isinstance(stage, str):
                    stages.add(stage)
            if relation.get("_object_type") == "derives" and target.get("_object_type") == "split_record":
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
                "status": passage.get("status"),
                "transaction_stages": sorted(stages),
                "missing": missing,
            })
    return result
