"""Deterministic pricing and control views over the shared Highway graph."""

from __future__ import annotations

from collections import Counter
from typing import Any

from oag.ontology.repository import OntologyRepository


def _type(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return "unknown"
    return str(record.get("_object_type") or record.get("type") or "unknown")


def _outgoing(repository: OntologyRepository, source_id: str, target_type: str):
    records = []
    for relation in repository.query_relations(
        "references", from_id=source_id, direction="out"
    ):
        target = repository.get_object_any(relation.get("to"))
        if target is not None and _type(target) == target_type:
            records.append(target)
    return records


def get_pricing_control_overview(
    repository: OntologyRepository,
    object_id: str = "",
) -> dict[str, Any]:
    types = ("rate_version", "rate_rule", "control_record")
    records = [item for object_type in types for item in repository.query_objects(object_type)]
    result: dict[str, Any] = {
        "summary": dict(sorted(Counter(_type(item) for item in records).items())),
        "records": records,
    }
    if object_id:
        selected = repository.get_object_any(object_id)
        if selected is None:
            raise ValueError(f"未找到费率或控制对象: {object_id}")
        outgoing = repository.query_relations(
            "references", from_id=object_id, direction="out"
        )
        incoming = repository.query_relations(
            "references", from_id=object_id, direction="in"
        )
        relations = list({item["id"]: item for item in [*outgoing, *incoming]}.values())
        result.update({
            "selected": selected,
            "relations": relations,
            "related": [
                item
                for relation in relations
                if (item := repository.get_object_any(
                    relation["to"] if relation.get("from") == object_id else relation["from"]
                )) is not None
            ],
        })
    return result


def get_passage_fare_basis(
    repository: OntologyRepository,
    passage_id: str,
) -> dict[str, Any]:
    passage = repository.get_object("passage", passage_id)
    if not passage:
        raise ValueError(f"未找到通行过程: {passage_id}")
    charges = []
    for relation in repository.query_relations(
        "derives", from_id=passage_id, direction="out"
    ):
        target = repository.get_object_any(relation.get("to"))
        if target is not None and _type(target) == "charge":
            charges.append(target)
    details = []
    for charge in charges:
        versions = _outgoing(repository, str(charge["id"]), "rate_version")
        rules = _outgoing(repository, str(charge["id"]), "rate_rule")
        seen = {str(item["id"]) for item in rules}
        for version in versions:
            for rule in _outgoing(repository, str(version["id"]), "rate_rule"):
                if str(rule["id"]) not in seen:
                    rules.append(rule)
                    seen.add(str(rule["id"]))
        details.append({"charge": charge, "rate_versions": versions, "rate_rules": rules})
    return {
        "passage": passage,
        "charges": details,
        "summary": [{
            "charge_id": item["charge"].get("id"),
            "rate_version_ids": [record.get("id") for record in item["rate_versions"]],
            "rate_rule_ids": [record.get("id") for record in item["rate_rules"]],
        } for item in details],
    }
