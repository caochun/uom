"""Deterministic clearing and settlement views over the shared UOM graph."""

from __future__ import annotations

from typing import Any

from oag.ontology.repository import OntologyRepository


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


def _incoming(
    repository: OntologyRepository,
    relation_type: str,
    target_id: str,
    source_type: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    relations = repository.query_relations(
        relation_type, to_id=target_id, direction="in"
    )
    records = []
    for relation in relations:
        source = _get(repository, relation.get("from"))
        if source is not None and _type(source) == source_type:
            records.append(source)
    return records, relations


def get_settlement_trace(
    repository: OntologyRepository,
    settlement_id: str,
) -> dict[str, Any]:
    """Trace one settlement to its split, charge, payment and passage facts."""
    settlement = repository.get_object("settlement", settlement_id)
    if not settlement:
        raise ValueError(f"未找到清分结算: {settlement_id}")

    relations: list[dict[str, Any]] = []
    splits, links = _incoming(repository, "derives", settlement_id, "split_result")
    relations.extend(links)
    charges: list[dict[str, Any]] = []
    passages: list[dict[str, Any]] = []
    payments: list[dict[str, Any]] = []
    for split in splits:
        records, links = _incoming(repository, "derives", str(split["id"]), "charge")
        relations.extend(links)
        charges.extend(records)
    for charge in charges:
        records, links = _incoming(repository, "derives", str(charge["id"]), "passage")
        relations.extend(links)
        passages.extend(records)
        records, links = _incoming(repository, "references", str(charge["id"]), "payment")
        relations.extend(links)
        payments.extend(records)

    # Keep role-bearing references to the settlement's owner and its toll unit.
    owners: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    for split in splits:
        links = repository.query_relations(
            "references", from_id=split["id"], direction="out"
        )
        relations.extend(links)
        for link in links:
            target = _get(repository, link.get("to"))
            if target is None:
                continue
            role = (_properties(link).get("role") or "").lower()
            if _type(target) == "party" or role == "owner":
                owners.append(target)
            if _type(target) == "toll_interval" or role == "toll_interval":
                intervals.append(target)

    def unique(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return list({str(item["id"]): item for item in records}.values())

    splits, charges, passages, payments, owners, intervals = map(
        unique, (splits, charges, passages, payments, owners, intervals)
    )
    return {
        "settlement": settlement,
        "split_results": splits,
        "charges": charges,
        "passages": passages,
        "payments": payments,
        "owners": owners,
        "toll_intervals": intervals,
        "relations": unique(relations),
        "summary": {
            "split_count": len(splits),
            "charge_count": len(charges),
            "passage_count": len(passages),
            "payment_count": len(payments),
            "owner_count": len(owners),
            "settled_amount": _properties(settlement).get("allocated_amount")
            or _properties(settlement).get("amount"),
        },
    }
