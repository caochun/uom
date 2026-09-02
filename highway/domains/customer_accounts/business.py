"""Deterministic customer-account views over the shared UOM graph."""

from __future__ import annotations

from collections import defaultdict
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


def _money(value: Any) -> tuple[float, str | None]:
    if not isinstance(value, dict):
        return 0.0, None
    amount = value.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return 0.0, None
    currency = value.get("currency")
    return float(amount), str(currency) if currency else None


def _sum_money(records: list[dict[str, Any]], field: str) -> dict[str, Any]:
    amounts = [_money(_properties(record).get(field)) for record in records]
    currency = next((currency for _, currency in amounts if currency), "CNY")
    return {
        "amount": round(sum(amount for amount, _ in amounts), 2),
        "currency": currency,
    }


def _get(repository: OntologyRepository, record_id: Any) -> dict[str, Any] | None:
    if not record_id:
        return None
    return repository.get_object_any(record_id)


def _linked_by_relation(
    repository: OntologyRepository,
    relation_type: str,
    *,
    object_id: str,
    direction: str,
    target_type: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    links = repository.query_relations(
        relation_type,
        **({"from_id": object_id} if direction == "out" else {"to_id": object_id}),
        direction=direction,
    )
    records = []
    for link in links:
        target_id = link.get("to") if direction == "out" else link.get("from")
        record = _get(repository, target_id)
        if record is not None and _type(record) == target_type:
            records.append(record)
    return records, links


def get_account_ledger(
    repository: OntologyRepository,
    account_id: str,
    limit: int = 100,
) -> dict[str, Any]:
    """Return one account's entries and the cross-domain facts they reference."""
    account = repository.get_object("account", account_id)
    if not account:
        raise ValueError(f"未找到客户账户: {account_id}")

    entry_links = repository.query_relations(
        "contains", from_id=account_id, direction="out", limit=max(1, min(int(limit), 500))
    )
    entry_ids = {
        str(link.get("to"))
        for link in entry_links
        if _type(_get(repository, link.get("to"))) == "account_entry"
    }
    entries = [
        item
        for item in (
            _get(repository, entry_id)
            for entry_id in entry_ids
        )
        if item is not None and _type(item) == "account_entry"
    ]
    entries.sort(
        key=lambda item: str(_properties(item).get("occurred_at") or ""),
        reverse=True,
    )

    wallets = [
        item
        for item in (_get(repository, link.get("to")) for link in entry_links)
        if item is not None and _type(item) == "wallet"
    ]

    relations = list(entry_links)
    linked: dict[str, list[dict[str, Any]]] = defaultdict(list)
    linked_ids: set[str] = set()

    account_links = [
        *repository.query_relations(
            "associates", from_id=account_id, direction="out"
        ),
        *repository.query_relations(
            "references", from_id=account_id, direction="out"
        ),
    ]
    relations.extend(account_links)
    account_structure: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for link in account_links:
        target = _get(repository, link.get("to"))
        if target is not None:
            account_structure[_type(target)].append(target)

    transactions, transaction_links = _linked_by_relation(
        repository,
        "associates",
        object_id=account_id,
        direction="in",
        target_type="fund_transaction",
    )
    relations.extend(transaction_links)
    for transaction in transactions:
        linked["fund_transaction"].append(transaction)
        linked_ids.add(str(transaction["id"]))

    bills, bill_links = _linked_by_relation(
        repository,
        "associates",
        object_id=account_id,
        direction="in",
        target_type="bill",
    )
    relations.extend(bill_links)
    for bill in bills:
        linked["bill"].append(bill)
        linked_ids.add(str(bill["id"]))

    operations, operation_links = _linked_by_relation(
        repository,
        "associates",
        object_id=account_id,
        direction="in",
        target_type="service_operation",
    )
    relations.extend(operation_links)
    for operation in operations:
        linked["service_operation"].append(operation)
        linked_ids.add(str(operation["id"]))
    for entry in entries:
        references = repository.query_relations(
            "references", from_id=entry["id"], direction="out"
        )
        relations.extend(references)
        for relation in references:
            target = _get(repository, relation.get("to"))
            if target is None:
                continue
            target_type = _type(target)
            linked[target_type].append(target)
            linked_ids.add(str(target["id"]))

    # A payment referenced by an entry normally points to its charge. Include
    # that second hop so the account view explains what was actually paid.
    for payment in list(linked.get("payment", [])):
        references = repository.query_relations(
            "references", from_id=payment["id"], direction="out"
        )
        relations.extend(references)
        for relation in references:
            target = _get(repository, relation.get("to"))
            if target is not None and str(target["id"]) not in linked_ids:
                linked[_type(target)].append(target)
                linked_ids.add(str(target["id"]))

    bill_settlements: list[dict[str, Any]] = []
    for bill in bills:
        settlements, links = _linked_by_relation(
            repository,
            "derives",
            object_id=str(bill["id"]),
            direction="out",
            target_type="bill_settlement",
        )
        relations.extend(links)
        bill_settlements.extend(settlements)
    linked["bill_settlement"].extend(bill_settlements)

    by_entry_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        kind = str(_properties(entry).get("entry_kind") or "unspecified")
        by_entry_kind[kind].append(entry)
    latest = entries[0] if entries else None
    latest_balance = (
        _properties(latest).get("balance_after") if latest is not None else None
    )
    return {
        "account": account,
        "wallets": sorted(wallets, key=lambda item: str(item.get("id"))),
        "related_accounts": sorted(
            account_structure.get("account", []), key=lambda item: str(item.get("id"))
        ),
        "related_media": sorted(
            account_structure.get("toll_medium", []), key=lambda item: str(item.get("id"))
        ),
        "account_parties": sorted(
            account_structure.get("party", []), key=lambda item: str(item.get("id"))
        ),
        "entries": entries,
        "transactions": sorted(transactions, key=lambda item: str(item.get("id"))),
        "bills": sorted(bills, key=lambda item: str(item.get("id"))),
        "bill_settlements": sorted(
            {str(item["id"]): item for item in bill_settlements}.values(),
            key=lambda item: str(item.get("id")),
        ),
        "service_operations": sorted(
            operations, key=lambda item: str(item.get("id"))
        ),
        "entries_by_kind": dict(sorted(by_entry_kind.items())),
        "linked_facts": {
            kind: sorted(records, key=lambda item: str(item.get("id")))
            for kind, records in sorted(linked.items())
        },
        "relations": relations,
        "summary": {
            "entry_count": len(entries),
            "wallet_count": len(wallets),
            "transaction_count": len(transactions),
            "bill_count": len(bills),
            "bill_settlement_count": len({str(item["id"]) for item in bill_settlements}),
            "latest_balance": latest_balance,
            "credits": _sum_money(
                [item for item in entries if _properties(item).get("entry_kind") in {"credit", "top_up", "refund"}],
                "amount",
            ),
            "debits": _sum_money(
                [item for item in entries if _properties(item).get("entry_kind") in {"debit", "charge", "deduction"}],
                "amount",
            ),
            "all_entries": _sum_money(entries, "amount"),
        },
    }
