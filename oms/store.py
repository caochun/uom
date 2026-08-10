"""SQLite-backed OMS store shared by the UI and OAG Agent tools."""

from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

import yaml

from oms.scripts.validate_model import ModelValidator


TYPE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_WRITE_LOCK = threading.RLock()
_DATABASE_SCHEMA_VERSION = "1"


class ChangeValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class OmsStore:
    def __init__(self, oms_root: str | Path, database_path: str | Path | None = None):
        self.root = Path(oms_root).resolve()
        self.ontology_path = self.root / "ontology.yaml"
        self.model_path = self.root / "model.yaml"
        self.database_path = (
            Path(database_path).resolve()
            if database_path is not None
            else self.root / "data" / "oms.db"
        )
        self._previews: dict[str, str] = {}
        self._ensure_database()

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
        if not isinstance(value, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
        return value

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_database(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS objects (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    payload TEXT NOT NULL CHECK (json_valid(payload))
                );

                CREATE TABLE IF NOT EXISTS relations (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    payload TEXT NOT NULL CHECK (json_valid(payload)),
                    FOREIGN KEY (source_id) REFERENCES objects(id) ON DELETE RESTRICT,
                    FOREIGN KEY (target_id) REFERENCES objects(id) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_objects_type ON objects(type);
                CREATE INDEX IF NOT EXISTS idx_objects_name ON objects(name);
                CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(type);
                CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
                CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
                """
            )
            connection.execute("BEGIN IMMEDIATE")

            schema_version = self._metadata(connection, "schema_version")
            if schema_version and schema_version != _DATABASE_SCHEMA_VERSION:
                raise ValueError(
                    f"unsupported OMS database schema {schema_version}; "
                    f"expected {_DATABASE_SCHEMA_VERSION}"
                )
            self._set_metadata(connection, "schema_version", _DATABASE_SCHEMA_VERSION)
            if self._metadata(connection, "data_revision") is None:
                self._set_metadata(connection, "data_revision", "0")
            connection.commit()

    @staticmethod
    def _metadata(connection: sqlite3.Connection, key: str) -> str | None:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = ?",
            (key,),
        ).fetchone()
        return str(row["value"]) if row else None

    @staticmethod
    def _set_metadata(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def _increment_revision(self, connection: sqlite3.Connection) -> None:
        current = int(self._metadata(connection, "data_revision") or "0")
        self._set_metadata(connection, "data_revision", str(current + 1))

    @staticmethod
    def _table_name(table: str) -> str:
        if table not in {"objects", "relations"}:
            raise ValueError(f"unknown OMS data table: {table}")
        return table

    @staticmethod
    def _read_records(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
        table_name = OmsStore._table_name(table)
        rows = connection.execute(
            f"SELECT payload FROM {table_name} ORDER BY rowid"
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    @staticmethod
    def _replace_records(
        connection: sqlite3.Connection,
        table: str,
        records: list[dict[str, Any]],
    ) -> None:
        table_name = OmsStore._table_name(table)
        connection.execute(f"DELETE FROM {table_name}")
        if table == "objects":
            connection.executemany(
                "INSERT INTO objects(id, type, name, payload) VALUES (?, ?, ?, ?)",
                [
                    (
                        record["id"],
                        record["type"],
                        record["name"],
                        OmsStore._encode_record(record),
                    )
                    for record in records
                ],
            )
            return
        connection.executemany(
            "INSERT INTO relations(id, type, source_id, target_id, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    record["id"],
                    record["type"],
                    record["from"],
                    record["to"],
                    OmsStore._encode_record(record),
                )
                for record in records
            ],
        )

    @staticmethod
    def _encode_record(record: dict[str, Any]) -> str:
        return json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            return self._snapshot(connection)

    def _snapshot(self, connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        return {
            "ontology": self._load(self.ontology_path),
            "model": self._load(self.model_path),
            "objects": {
                "schema": "oms.data.objects.v2",
                "objects": self._read_records(connection, "objects"),
            },
            "relations": {
                "schema": "oms.data.relations.v2",
                "relations": self._read_records(connection, "relations"),
            },
        }

    def bootstrap(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        objects = snapshot["objects"].get("objects", [])
        relations = snapshot["relations"].get("relations", [])
        model = snapshot["model"]
        return {
            "ontology": snapshot["ontology"],
            "model": model,
            "objects": objects,
            "relations": relations,
            "stats": self._stats(objects, relations),
            "model_usage": self._model_usage(model, objects, relations),
        }

    def preview_changes(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        with _WRITE_LOCK:
            snapshot = self.snapshot()
            changed_sections, summaries = self._apply_operations(snapshot, operations)
            errors = self._validate_snapshot(snapshot)
            if not errors:
                self._previews[self._digest(operations)] = self._snapshot_digest(self.snapshot())
            return {
                "valid": not errors,
                "errors": errors,
                "changes": summaries,
                "changed_files": self._changed_targets(changed_sections),
            }

    def apply_changes(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        with _WRITE_LOCK:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("PRAGMA defer_foreign_keys = ON")
                snapshot = self._snapshot(connection)
                operation_digest = self._digest(operations)
                preview_snapshot = self._previews.get(operation_digest)
                if preview_snapshot != self._snapshot_digest(snapshot):
                    connection.rollback()
                    raise ChangeValidationError(["changes: 必须基于当前数据先完成相同 ChangeSet 的预览"])

                original_model = deepcopy(snapshot["model"])
                changed_sections, summaries = self._apply_operations(snapshot, operations)
                errors = self._validate_snapshot(snapshot)
                if errors:
                    connection.rollback()
                    raise ChangeValidationError(errors)

                model_written = False
                try:
                    if "objects" in changed_sections:
                        self._replace_records(
                            connection,
                            "objects",
                            snapshot["objects"].get("objects", []),
                        )
                    if "relations" in changed_sections:
                        self._replace_records(
                            connection,
                            "relations",
                            snapshot["relations"].get("relations", []),
                        )
                    if changed_sections & {"objects", "relations"}:
                        self._increment_revision(connection)
                    if "model" in changed_sections:
                        self._write_atomic(self.model_path, snapshot["model"])
                        model_written = True
                    connection.commit()
                except Exception:
                    connection.rollback()
                    if model_written:
                        self._write_atomic(self.model_path, original_model)
                    raise

                self._previews.pop(operation_digest, None)
                return {
                    "applied": True,
                    "changes": summaries,
                    "changed_files": self._changed_targets(changed_sections),
                }

    def list_objects(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return self._read_records(connection, "objects")

    def list_relations(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return self._read_records(connection, "relations")

    def get_model_vocabulary(self, kind: str = "all", type_id: str = "") -> dict[str, Any]:
        model = self.snapshot()["model"]
        sections = {
            "property": model.get("property_definitions", {}),
            "object": model.get("object_types", {}),
            "relation": model.get("relation_types", {}),
        }
        if kind in sections:
            values = sections[kind]
            return {type_id: values[type_id]} if type_id and type_id in values else values
        return sections

    def business_overview(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        objects = snapshot["objects"].get("objects", [])
        relations = snapshot["relations"].get("relations", [])
        totals: dict[str, dict[str, float]] = {
            "revenue": {}, "cost": {}, "cash_receipt": {}, "cash_payment": {},
        }
        for item in objects:
            object_type = item.get("type")
            if object_type not in totals:
                continue
            money = item.get("properties", {}).get("amount", {})
            amount, currency = money.get("amount"), money.get("currency")
            if isinstance(amount, (int, float)) and isinstance(currency, str):
                totals[object_type][currency] = totals[object_type].get(currency, 0) + amount
        pending = self.find_unattributed_costs()
        return {
            "counts": {"objects": len(objects), "relations": len(relations)},
            "totals": totals,
            "unattributed_costs": pending,
        }

    def revenue_contribution(self, revenue_id: str) -> dict[str, Any]:
        snapshot = self.snapshot()
        objects = {item.get("id"): item for item in snapshot["objects"].get("objects", [])}
        revenue = objects.get(revenue_id)
        if not revenue or revenue.get("type") != "revenue":
            raise ValueError(f"未找到收入对象: {revenue_id}")
        money = revenue.get("properties", {}).get("amount", {})
        currency = money.get("currency")
        revenue_amount = money.get("amount")
        if not isinstance(revenue_amount, (int, float)) or not isinstance(currency, str):
            raise ValueError("收入对象缺少有效金额")
        attributions = []
        attributed = 0.0
        for relation in snapshot["relations"].get("relations", []):
            props = relation.get("properties", {})
            rel_money = props.get("amount", {})
            if (
                relation.get("type") == "cost_attribution"
                and relation.get("to") == revenue_id
                and props.get("status") == "confirmed"
                and rel_money.get("currency") == currency
                and isinstance(rel_money.get("amount"), (int, float))
            ):
                amount = float(rel_money["amount"])
                attributed += amount
                attributions.append({
                    "relation_id": relation.get("id"),
                    "cost_id": relation.get("from"),
                    "amount": amount,
                    "basis": props.get("basis"),
                })
        return {
            "revenue_id": revenue_id,
            "revenue_amount": revenue_amount,
            "currency": currency,
            "attributed_cost": attributed,
            "contribution": float(revenue_amount) - attributed,
            "attributions": attributions,
        }

    def find_unattributed_costs(self) -> list[dict[str, Any]]:
        snapshot = self.snapshot()
        relations = snapshot["relations"].get("relations", [])
        disposition: dict[tuple[str, str], float] = {}
        for relation in relations:
            if relation.get("type") not in {"cost_attribution", "enterprise_absorption"}:
                continue
            props = relation.get("properties", {})
            if props.get("status") != "confirmed":
                continue
            money = props.get("amount", {})
            amount, currency = money.get("amount"), money.get("currency")
            if isinstance(amount, (int, float)) and isinstance(currency, str):
                key = (str(relation.get("from")), currency)
                disposition[key] = disposition.get(key, 0) + float(amount)
        result = []
        for item in snapshot["objects"].get("objects", []):
            if item.get("type") != "cost":
                continue
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

    def trace_object(self, object_id: str, depth: int = 2) -> dict[str, Any]:
        snapshot = self.snapshot()
        object_index = {
            item.get("id"): item for item in snapshot["objects"].get("objects", [])
        }
        if object_id not in object_index:
            raise ValueError(f"未知对象: {object_id}")
        relations = snapshot["relations"].get("relations", [])
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
            "root": object_index[object_id],
            "objects": [object_index[item_id] for item_id in seen if item_id in object_index],
            "relations": matched_relations,
        }

    def _apply_operations(
        self,
        snapshot: dict[str, dict[str, Any]],
        operations: list[dict[str, Any]],
    ) -> tuple[set[str], list[str]]:
        if not isinstance(operations, list) or not operations:
            raise ChangeValidationError(["changes: 至少需要一个操作"])
        changed_files: set[str] = set()
        summaries: list[str] = []
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                raise ChangeValidationError([f"changes[{index}]: 必须是对象"])
            action = operation.get("action")
            if action == "create_object":
                record = deepcopy(operation.get("record"))
                snapshot["objects"].setdefault("objects", []).append(record)
                changed_files.add("objects")
                summaries.append(f"新增对象 {self._record_label(record)}")
            elif action == "update_object":
                record = self._find_record(snapshot["objects"].get("objects", []), operation.get("id"))
                self._merge_record(record, operation.get("changes"))
                changed_files.add("objects")
                summaries.append(f"更新对象 {self._record_label(record)}")
            elif action == "delete_object":
                object_id = operation.get("id")
                if any(
                    rel.get("from") == object_id or rel.get("to") == object_id
                    for rel in snapshot["relations"].get("relations", [])
                ):
                    raise ChangeValidationError([f"对象 {object_id} 仍有关联关系，不能删除"])
                self._delete_record(snapshot["objects"].get("objects", []), object_id)
                changed_files.add("objects")
                summaries.append(f"删除对象 {object_id}")
            elif action == "create_relation":
                record = deepcopy(operation.get("record"))
                snapshot["relations"].setdefault("relations", []).append(record)
                changed_files.add("relations")
                summaries.append(f"新增关系 {self._record_label(record)}")
            elif action == "update_relation":
                record = self._find_record(snapshot["relations"].get("relations", []), operation.get("id"))
                self._merge_record(record, operation.get("changes"))
                changed_files.add("relations")
                summaries.append(f"更新关系 {self._record_label(record)}")
            elif action == "delete_relation":
                relation_id = operation.get("id")
                self._delete_record(snapshot["relations"].get("relations", []), relation_id)
                changed_files.add("relations")
                summaries.append(f"删除关系 {relation_id}")
            elif action == "upsert_property_definition":
                property_id = operation.get("property_id")
                definition = deepcopy(operation.get("definition"))
                if not isinstance(property_id, str) or not isinstance(definition, dict):
                    raise ChangeValidationError([f"changes[{index}]: 属性定义不完整"])
                snapshot["model"].setdefault("property_definitions", {})[property_id] = definition
                changed_files.add("model")
                summaries.append(f"定义业务属性 {property_id}")
            elif action in {"upsert_object_type", "upsert_relation_type"}:
                kind = "object" if action == "upsert_object_type" else "relation"
                section = f"{kind}_types"
                type_id = operation.get("type_id")
                definition = deepcopy(operation.get("definition"))
                if not isinstance(type_id, str) or not isinstance(definition, dict):
                    raise ChangeValidationError([f"changes[{index}]: 类型定义不完整"])
                snapshot["model"].setdefault(section, {})[type_id] = definition
                changed_files.add("model")
                summaries.append(f"定义{self._kind_label(kind)}类型 {type_id}")
            else:
                raise ChangeValidationError([f"changes[{index}]: 未知操作 {action}"])
        if "model" in changed_files:
            self._bump_model_version(snapshot["model"])
        return changed_files, summaries

    def _validate_snapshot(self, snapshot: dict[str, dict[str, Any]]) -> list[str]:
        result = ModelValidator(
            snapshot["ontology"],
            snapshot["objects"],
            snapshot["relations"],
            snapshot["model"],
        ).validate()
        return result.errors

    @staticmethod
    def _stats(objects: list[dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, Any]:
        object_types: dict[str, int] = {}
        relation_types: dict[str, int] = {}
        for item in objects:
            type_id = str(item.get("type", "unknown"))
            object_types[type_id] = object_types.get(type_id, 0) + 1
        for item in relations:
            type_id = str(item.get("type", "unknown"))
            relation_types[type_id] = relation_types.get(type_id, 0) + 1
        return {
            "object_count": len(objects),
            "relation_count": len(relations),
            "object_types": object_types,
            "relation_types": relation_types,
        }

    @staticmethod
    def _model_usage(
        model: dict[str, Any],
        objects: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        object_counts: dict[str, int] = {}
        relation_counts: dict[str, int] = {}
        for item in objects:
            object_counts[item.get("type")] = object_counts.get(item.get("type"), 0) + 1
        for item in relations:
            relation_counts[item.get("type")] = relation_counts.get(item.get("type"), 0) + 1
        return {
            "object": {
                type_id: {
                    "count": count,
                    "defined": type_id in model.get("object_types", {}),
                }
                for type_id, count in sorted(object_counts.items())
            },
            "relation": {
                type_id: {
                    "count": count,
                    "defined": type_id in model.get("relation_types", {}),
                }
                for type_id, count in sorted(relation_counts.items())
            },
        }

    @staticmethod
    def _record_label(record: Any) -> str:
        if not isinstance(record, dict):
            return "<invalid>"
        return f"{record.get('id', '<missing>')} ({record.get('type', '<missing>')})"

    @staticmethod
    def _find_record(records: list[dict[str, Any]], record_id: Any) -> dict[str, Any]:
        for record in records:
            if record.get("id") == record_id:
                return record
        raise ChangeValidationError([f"未找到记录 {record_id}"])

    @staticmethod
    def _delete_record(records: list[dict[str, Any]], record_id: Any) -> None:
        for index, record in enumerate(records):
            if record.get("id") == record_id:
                records.pop(index)
                return
        raise ChangeValidationError([f"未找到记录 {record_id}"])

    @staticmethod
    def _merge_record(record: dict[str, Any], changes: Any) -> None:
        if not isinstance(changes, dict):
            raise ChangeValidationError(["changes: 更新内容必须是对象"])
        for key, value in changes.items():
            if key == "id":
                raise ChangeValidationError(["changes.id: 不允许修改稳定 ID"])
            if key == "properties" and isinstance(value, dict):
                record.setdefault("properties", {}).update(deepcopy(value))
            else:
                record[key] = deepcopy(value)

    @staticmethod
    def _kind_label(kind: str) -> str:
        return "对象" if kind == "object" else "关系"

    @staticmethod
    def _bump_model_version(model: dict[str, Any]) -> None:
        metadata = model.setdefault("model", {})
        parts = str(metadata.get("version", "0.0.0")).split(".")
        if len(parts) == 3 and all(part.isdigit() for part in parts):
            parts[-1] = str(int(parts[-1]) + 1)
            metadata["version"] = ".".join(parts)

    @staticmethod
    def _changed_targets(changed_sections: set[str]) -> list[str]:
        targets = []
        if changed_sections & {"objects", "relations"}:
            targets.append("data/oms.db")
        if "model" in changed_sections:
            targets.append("model.yaml")
        return targets

    @staticmethod
    def _digest(value: Any) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _snapshot_digest(self, snapshot: dict[str, dict[str, Any]]) -> str:
        return self._digest({key: snapshot[key] for key in ("model", "objects", "relations")})

    @staticmethod
    def _write_atomic(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                yaml.safe_dump(value, stream, allow_unicode=True, sort_keys=False, width=100)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


class OmsResolver:
    """Expose SQLite-backed Object or Relation records through the OAG contract."""

    def __init__(self, store: OmsStore, kind: str):
        self.store = store
        self.kind = kind

    def _rows(self) -> list[dict[str, Any]]:
        return self.store.list_objects() if self.kind == "object" else self.store.list_relations()

    def query(
        self,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        order_by: str | None = None,
        offset: int | None = None,
        **_: Any,
    ) -> list[dict[str, Any]]:
        rows = [deepcopy(row) for row in self._rows()]
        for field, expected in (filters or {}).items():
            name, operator = field.rsplit("__", 1) if "__" in field else (field, "eq")
            rows = [
                row
                for row in rows
                if self._matches(row.get(name), expected, operator)
            ]
        if order_by:
            reverse = order_by.startswith("-")
            key = order_by.lstrip("-")
            rows.sort(key=lambda row: str(row.get(key, "")), reverse=reverse)
        if offset:
            rows = rows[offset:]
        return rows[:limit] if limit else rows

    def count(self, filters: dict[str, Any] | None = None, **_: Any) -> int:
        return len(self.query(filters=filters))

    def query_by_id(self, id_value: Any, **_: Any) -> dict[str, Any] | None:
        return next((row for row in self._rows() if row.get("id") == id_value), None)

    def search_text(
        self,
        keyword: str,
        limit: int = 20,
        object_type: str = "",
        **_: Any,
    ) -> list[dict[str, Any]]:
        needle = keyword.lower()
        results = []
        for row in self._rows():
            matched_fields = [
                field
                for field, value in row.items()
                if needle in json.dumps(value, ensure_ascii=False).lower()
            ]
            if not matched_fields:
                continue
            result = deepcopy(row)
            result["_object_type"] = object_type or self._oag_object_type()
            result["_matched_field"] = ", ".join(matched_fields)
            results.append(result)
            if len(results) >= limit:
                break
        return results

    def insert_record(self, data: dict[str, Any], **_: Any) -> dict[str, Any]:
        action = "create_object" if self.kind == "object" else "create_relation"
        return self._apply([{"action": action, "record": data}])

    def update_record(self, id_value: Any, data: dict[str, Any], **_: Any) -> dict[str, Any]:
        action = "update_object" if self.kind == "object" else "update_relation"
        return self._apply([{"action": action, "id": id_value, "changes": data}])

    def delete_record(self, id_value: Any, **_: Any) -> dict[str, Any]:
        action = "delete_object" if self.kind == "object" else "delete_relation"
        return self._apply([{"action": action, "id": id_value}])

    def table_count(self, **_: Any) -> int:
        return len(self._rows())

    def _apply(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        preview = self.store.preview_changes(operations)
        if not preview["valid"]:
            raise ChangeValidationError(preview["errors"])
        return self.store.apply_changes(operations)

    def _oag_object_type(self) -> str:
        return "Object" if self.kind == "object" else "Relation"

    @staticmethod
    def _matches(actual: Any, expected: Any, operator: str) -> bool:
        if operator == "like":
            return str(expected).lower() in str(actual or "").lower()
        if operator == "ne":
            return actual != expected
        if operator == "gt":
            return OmsResolver._compare(actual, expected, lambda left, right: left > right)
        if operator == "gte":
            return OmsResolver._compare(actual, expected, lambda left, right: left >= right)
        if operator == "lt":
            return OmsResolver._compare(actual, expected, lambda left, right: left < right)
        if operator == "lte":
            return OmsResolver._compare(actual, expected, lambda left, right: left <= right)
        return actual == expected

    @staticmethod
    def _compare(actual: Any, expected: Any, comparator) -> bool:
        try:
            return bool(comparator(actual, expected))
        except TypeError:
            return False
