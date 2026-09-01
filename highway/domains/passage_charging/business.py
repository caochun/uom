"""Deterministic passage-charging queries over the UOM graph repository."""

from __future__ import annotations

from collections import Counter
from typing import Any

from oag.ontology.repository import OntologyRepository


def _type(record: dict[str, Any]) -> str:
    return str(record.get("_object_type") or record.get("type") or "unknown")


def _properties(record: dict[str, Any]) -> dict[str, Any]:
    properties = record.get("properties")
    if isinstance(properties, dict):
        return properties
    base = {"id", "type", "_object_type", "name", "from", "to", "lifecycle"}
    return {key: value for key, value in record.items() if key not in base}


def _money(value: Any) -> tuple[float, str | None]:
    if not isinstance(value, dict):
        return 0.0, None
    amount, currency = value.get("amount"), value.get("currency")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return 0.0, None
    return float(amount), str(currency) if currency else None


def _sum_money(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    total = 0.0
    currencies: Counter[str] = Counter()
    for record in records:
        amount, currency = _money(_properties(record).get(field))
        total += amount
        if currency:
            currencies[currency] += 1
    currency = currencies.most_common(1)[0][0] if currencies else "CNY"
    return {"amount": round(total, 2), "currency": currency}


def _graph(repository: OntologyRepository) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    objects = repository.query_all_objects()
    return (
        {str(item["id"]): item for item in objects if isinstance(item.get("id"), str)},
        repository.query_all_relations(),
    )


def _outgoing(
    object_id: str,
    relation_type: str,
    relations: list[dict[str, Any]],
    index: dict[str, dict[str, Any]],
    target_type: str | None = None,
) -> list[dict[str, Any]]:
    result = []
    for relation in relations:
        if relation.get("from") != object_id or _type(relation) != relation_type:
            continue
        target = index.get(str(relation.get("to")))
        if target is not None and (target_type is None or _type(target) == target_type):
            result.append(target)
    return result


def get_business_overview(repository: OntologyRepository) -> dict[str, Any]:
    """Summarize the operational graph without asking the LLM to calculate it."""
    objects = repository.query_all_objects()
    relations = repository.query_all_relations()
    by_type = {
        object_type: [item for item in objects if _type(item) == object_type]
        for object_type in {
            "passage", "passage_event", "charge", "payment"
        }
    }
    incomplete = find_incomplete_passages(repository)
    return {
        "counts": {"objects": len(objects), "relations": len(relations)},
        "object_types": dict(sorted(Counter(_type(item) for item in objects).items())),
        "relation_types": dict(sorted(Counter(_type(item) for item in relations).items())),
        "business": {
            "passages": len(by_type["passage"]),
            "events": len(by_type["passage_event"]),
            "charges": len(by_type["charge"]),
            "payments": len(by_type["payment"]),
        },
        "amounts": {
            "receivable": _sum_money(by_type["charge"], "receivable_amount"),
            "discount": _sum_money(by_type["charge"], "discount_amount"),
            "charged": _sum_money(by_type["charge"], "paid_amount"),
            "paid": _sum_money(by_type["payment"], "amount"),
        },
        # Kept as a compact compatibility shape for existing dashboard clients.
        "amount_totals": {
            "charge": _sum_money(by_type["charge"], "paid_amount"),
            "payment": _sum_money(by_type["payment"], "amount"),
        },
        "incomplete_passage_count": len(incomplete),
    }


def get_passage_trace(
    repository: OntologyRepository,
    passage_id: str,
    depth: int = 5,
) -> dict[str, Any]:
    passage = repository.get_object("passage", passage_id)
    if not passage:
        raise ValueError(f"未找到通行过程: {passage_id}")
    graph = _scoped_trace(repository, passage_id, depth)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in graph["objects"]:
        grouped.setdefault(_type(item), []).append(item)
    return {
        "passage": passage,
        "facts_by_type": grouped,
        "relations": graph["relations"],
        "trace_order": [
            "passage", "vehicle", "toll_medium", "passage_event",
            "charge", "rate_version", "rate_rule", "payment",
        ],
    }


def _scoped_trace(
    repository: OntologyRepository,
    passage_id: str,
    depth: int,
) -> dict[str, Any]:
    """Follow only relations that form a passage's business trace.

    A generic graph traversal would jump from one passage to another through a
    shared operator, road or account. This traversal keeps the financial and
    observed-fact chain explicit while still including useful endpoint objects.
    """
    index, relations = _graph(repository)
    seen = {passage_id}
    seen_order = [passage_id]
    frontier = [(passage_id, 0)]
    matched: list[dict[str, Any]] = []
    matched_ids: set[str] = set()
    outgoing_rules = {
        "passage": {"associates", "references", "contains", "derives"},
        "vehicle": {"associates"},
        "passage_event": {"references"},
        "charge": {"references"},
        "payment": {"associates"},
    }
    max_depth = max(1, min(int(depth), 8))
    while frontier:
        current_id, current_depth = frontier.pop(0)
        current = index.get(current_id)
        if current is None or current_depth >= max_depth:
            continue
        current_type = _type(current)
        for relation in relations:
            relation_id = str(relation.get("id"))
            relation_type = _type(relation)
            source = str(relation.get("from"))
            target = str(relation.get("to"))
            next_id: str | None = None
            if source == current_id and relation_type in outgoing_rules.get(current_type, set()):
                next_id = target
            elif (
                target == current_id
                and current_type == "charge"
                and relation_type == "references"
                and _type(index.get(source, {})) == "payment"
            ):
                next_id = source
            if next_id is None or next_id not in index:
                continue
            if relation_id not in matched_ids:
                matched.append(relation)
                matched_ids.add(relation_id)
            if next_id not in seen:
                seen.add(next_id)
                seen_order.append(next_id)
                frontier.append((next_id, current_depth + 1))
    return {
        "root": index[passage_id],
        "objects": [index[item_id] for item_id in seen_order if item_id in index],
        "relations": matched,
    }


def find_incomplete_passages(repository: OntologyRepository) -> list[dict[str, Any]]:
    index, relations = _graph(repository)
    result = []
    for passage in repository.query_objects("passage"):
        passage_id = str(passage.get("id"))
        events = _outgoing(passage_id, "contains", relations, index, "passage_event")
        stages = {
            str(_properties(event).get("stage"))
            for event in events
            if _properties(event).get("stage")
        }
        charges = _outgoing(passage_id, "derives", relations, index, "charge")
        missing = []
        if "entry" not in stages:
            missing.append("entry_event")
        if "exit" not in stages:
            missing.append("exit_event")
        if not charges:
            missing.append("charge")
        if missing:
            result.append({
                "id": passage.get("id"),
                "name": passage.get("name") or passage.get("id"),
                "status": _properties(passage).get("status"),
                "event_stages": sorted(stages),
                "missing": missing,
            })
    return result


def get_passage_economics(
    repository: OntologyRepository,
    passage_id: str,
) -> dict[str, Any]:
    """Return the deterministic financial chain rooted at one passage."""
    passage = repository.get_object("passage", passage_id)
    if not passage:
        raise ValueError(f"未找到通行过程: {passage_id}")
    index, relations = _graph(repository)
    charges = _outgoing(passage_id, "derives", relations, index, "charge")
    charge_ids = {str(item["id"]) for item in charges}
    payments = [
        item for item in index.values()
        if _type(item) == "payment"
        and any(
            relation.get("from") == item.get("id")
            and relation.get("to") in charge_ids
            and _type(relation) == "references"
            for relation in relations
        )
    ]
    return {
        "passage": passage,
        "charges": charges,
        "payments": payments,
        "totals": {
            "receivable": _sum_money(charges, "receivable_amount"),
            "discount": _sum_money(charges, "discount_amount"),
            "charged": _sum_money(charges, "paid_amount"),
            "paid": _sum_money(payments, "amount"),
        },
        "linked_ids": {
            "charge": sorted(charge_ids),
        },
    }
