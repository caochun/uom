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

    adapter_for = getattr(repository, "adapter_for", None)
    relation_adapter = adapter_for("Relation") if callable(adapter_for) else None
    object_adapter = adapter_for("Object") if callable(adapter_for) else None
    seen = {object_id}
    frontier = {object_id}
    matched_relations: list[dict[str, Any]] = []
    seen_relations: set[str] = set()
    for _ in range(max(0, min(depth, 5))):
        next_frontier: set[str] = set()
        query_adjacent = getattr(relation_adapter, "query_adjacent", None)
        relations = (
            query_adjacent(frontier)
            if callable(query_adjacent)
            else repository.query("Relation")
        )
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
    query_by_ids = getattr(object_adapter, "query_by_ids", None)
    object_rows = (
        query_by_ids(seen)
        if callable(query_by_ids)
        else repository.query("Object")
    )
    object_index = {
        item["id"]: item
        for item in object_rows
        if isinstance(item.get("id"), str)
    }
    return {
        "root": root,
        "objects": [object_index[item_id] for item_id in seen if item_id in object_index],
        "relations": matched_relations,
    }
