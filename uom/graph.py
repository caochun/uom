"""Domain-independent graph queries over UOM Object and Relation records."""

from __future__ import annotations

from typing import Any

from oag.ontology.repository import ObjectRepository


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
