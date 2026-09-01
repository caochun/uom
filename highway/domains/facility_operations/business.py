"""Deterministic facility and road-network views over the shared UOM graph."""

from __future__ import annotations

from collections import Counter
from typing import Any

from oag.ontology.repository import OntologyRepository


FACILITY_TYPES = (
    "toll_road",
    "section",
    "toll_interval",
    "toll_station",
    "toll_gantry",
    "toll_lane",
    "equipment",
)


def _type(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return "unknown"
    return str(record.get("_object_type") or record.get("type") or "unknown")


def _properties(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("properties")
    if isinstance(value, dict):
        return value
    base = {"id", "type", "_object_type", "name", "from", "to", "lifecycle"}
    return {key: item for key, item in record.items() if key not in base and not key.startswith("_")}


def _get(repository: OntologyRepository, record_id: Any) -> dict[str, Any] | None:
    if not record_id:
        return None
    return repository.get_object_any(record_id)


def _children(
    repository: OntologyRepository,
    object_id: str,
    relation_type: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    links = repository.query_relations(
        relation_type, from_id=object_id, direction="out"
    )
    records = [
        target
        for link in links
        if (target := _get(repository, link.get("to"))) is not None
    ]
    return records, links


def get_facility_overview(
    repository: OntologyRepository,
    facility_id: str = "",
) -> dict[str, Any]:
    """Summarize facility inventory, or return one facility's local network view."""
    if facility_id:
        root = _get(repository, facility_id)
        if root is None or _type(root) not in FACILITY_TYPES:
            raise ValueError(f"未找到收费设施: {facility_id}")
        objects = {str(root["id"]): root}
        relations: list[dict[str, Any]] = []
        frontier = [root]
        while frontier:
            current = frontier.pop(0)
            children, links = _children(repository, str(current["id"]), "contains")
            relations.extend(links)
            for child in children:
                if _type(child) not in FACILITY_TYPES:
                    continue
                if str(child["id"]) not in objects:
                    objects[str(child["id"])] = child
                    frontier.append(child)
            next_nodes, links = _children(repository, str(current["id"]), "route_next")
            relations.extend(links)
            for node in next_nodes:
                if _type(node) in FACILITY_TYPES and str(node["id"]) not in objects:
                    objects[str(node["id"])] = node
        return {
            "root": root,
            "objects": list(objects.values()),
            "relations": list({str(item["id"]): item for item in relations}.values()),
            "summary": {
                "object_count": len(objects),
                "object_types": dict(sorted(Counter(_type(item) for item in objects.values()).items())),
                "coordinate_count": sum(
                    1
                    for item in objects.values()
                    if _properties(item).get("longitude") is not None
                    and _properties(item).get("latitude") is not None
                ),
            },
        }

    records = {
        object_type: repository.query_objects(object_type)
        for object_type in FACILITY_TYPES
    }
    all_records = [item for values in records.values() for item in values]
    return {
        "summary": {
            "facility_count": len(all_records),
            "object_types": {key: len(records[key]) for key in FACILITY_TYPES},
            "coordinate_count": sum(
                1
                for item in all_records
                if _properties(item).get("longitude") is not None
                and _properties(item).get("latitude") is not None
            ),
        },
        "facilities": all_records,
    }
