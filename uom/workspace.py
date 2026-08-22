"""UOM workspace service for model editing and validated ChangeSets."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import yaml
from pydantic import ValidationError

from uom.model import (
    load_action_plans,
    load_domain_model,
    public_ontology,
    storage_contract_payload,
    update_source_vocabulary,
    workspace_model,
)
from uom.validation import ModelValidator

if TYPE_CHECKING:
    from uom.change_store import UomChangeStore


TYPE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_CHANGE_LOCK = threading.RLock()


class ChangeValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class UomWorkspaceService:
    """Manage user vocabulary and atomic, validated graph ChangeSets."""

    def __init__(
        self,
        domain_root: str | Path,
        repository: UomChangeStore,
    ):
        self.root = Path(domain_root).resolve()
        self.model_path = self.root / "model.yaml"
        self.repository = repository
        self._previews: dict[str, dict[str, Any]] = {}

    @property
    def database_path(self) -> Path:
        path = self.repository.database_path
        if not isinstance(path, Path):
            raise TypeError("Object 的命名数据源没有本地数据库路径")
        return path

    def snapshot(self) -> dict[str, dict[str, Any]]:
        source_model, public_model, editor_model = self._model_snapshot()
        return {
            "ontology": storage_contract_payload(),
            "source_model": source_model,
            "public_model": public_model,
            "model": editor_model,
            "objects": {
                "schema": "uom.data.objects.v1",
                "objects": self.repository.query_objects(),
            },
            "relations": {
                "schema": "uom.data.relations.v1",
                "relations": self.repository.query_relations(),
            },
        }

    def load_model(self) -> dict[str, Any]:
        """Return the private Action/editor projection of the public OAG model."""
        _, _, editor_model = self._model_snapshot()
        return editor_model

    def _model_snapshot(
        self,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        source_model, parsed_source_model = load_domain_model(self.root)
        public_model, _ = public_ontology(parsed_source_model)
        action_plans = load_action_plans(self.root)
        return source_model, public_model, workspace_model(
            public_model,
            action_plans,
            source_model,
        )

    def changeset_snapshot(
        self,
        operations: list[dict[str, Any]],
        read_object_ids: set[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Load the smallest graph slice needed to preview a data ChangeSet."""
        if not isinstance(operations, list) or not operations:
            raise ChangeValidationError(["changes: 至少需要一个操作"])
        if any(not isinstance(operation, dict) for operation in operations):
            raise ChangeValidationError(["changes: 每个操作都必须是对象"])
        model_actions = {
            "upsert_property_definition", "upsert_object_type", "upsert_relation_type",
        }
        if any(operation.get("action") in model_actions for operation in operations):
            return self.snapshot()

        source_model, public_model, model = self._model_snapshot()
        supplemental_object_ids = set(read_object_ids or set())
        object_ids: set[str] = set(supplemental_object_ids)
        relation_ids: set[str] = set()
        delete_object_ids: set[str] = set()
        acyclic_types: set[str] = set()
        created_object_ids = {
            str(record["id"])
            for operation in operations
            if operation.get("action") == "create_object"
            and isinstance((record := operation.get("record")), dict)
            and isinstance(record.get("id"), str)
        }

        for operation in operations:
            action = str(operation.get("action") or "")
            record = operation.get("record")
            if action in {"update_object", "delete_object"}:
                if isinstance(operation.get("id"), str):
                    object_ids.add(operation["id"])
                    if action == "delete_object":
                        delete_object_ids.add(operation["id"])
            elif action == "create_relation" and isinstance(record, dict):
                for endpoint in (record.get("from"), record.get("to")):
                    if isinstance(endpoint, str) and endpoint not in created_object_ids:
                        object_ids.add(endpoint)
                relation_type = record.get("type")
                definition = model.get("relation_types", {}).get(relation_type, {})
                if isinstance(definition, dict) and definition.get("acyclic") is True:
                    acyclic_types.add(str(relation_type))
            elif action in {"update_relation", "delete_relation"}:
                if isinstance(operation.get("id"), str):
                    relation_ids.add(operation["id"])

        objects = self.repository.query_by_ids("object", object_ids)
        relations = self.repository.query_by_ids("relation", relation_ids)

        for relation in relations:
            for endpoint in (relation.get("from"), relation.get("to")):
                if isinstance(endpoint, str) and endpoint not in created_object_ids:
                    object_ids.add(endpoint)
        adjacent_object_ids = delete_object_ids | supplemental_object_ids
        if adjacent_object_ids:
            adjacent = self.repository.query_adjacent(adjacent_object_ids)
            relations.extend(adjacent)
        for relation_type in acyclic_types:
            relations.extend(self.repository.query_relations(
                filters={"type": relation_type},
            ))

        loaded_object_ids = {item.get("id") for item in objects}
        missing_object_ids = object_ids - loaded_object_ids - created_object_ids
        if missing_object_ids:
            additional = self.repository.query_by_ids("object", missing_object_ids)
            objects.extend(additional)

        return {
            "ontology": storage_contract_payload(),
            "source_model": source_model,
            "public_model": public_model,
            "model": model,
            "objects": {
                "schema": "uom.data.objects.v1",
                "objects": self._unique_records(objects),
            },
            "relations": {
                "schema": "uom.data.relations.v1",
                "relations": self._unique_records(relations),
            },
        }

    @staticmethod
    def _unique_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        unique: dict[str, dict[str, Any]] = {}
        for record in records:
            if isinstance(record, dict) and isinstance(record.get("id"), str):
                unique[record["id"]] = record
        return list(unique.values())

    def bootstrap(self, include_graph: bool = True) -> dict[str, Any]:
        _, public_model, model = self._model_snapshot()
        client_model = self._client_model(model)
        object_type_counts = self.repository.type_counts("object")
        relation_type_counts = self.repository.type_counts("relation")
        stats = {
            "object_count": sum(object_type_counts.values()),
            "relation_count": sum(relation_type_counts.values()),
            "object_types": object_type_counts,
            "relation_types": relation_type_counts,
        }
        result = {
            "ontology": public_model,
            "model": client_model,
            "stats": stats,
            "model_usage": self._model_usage_from_counts(
                client_model, object_type_counts, relation_type_counts,
            ),
            "recent_actions": self.repository.list_action_log(limit=50),
            "graph_loaded": bool(include_graph),
        }
        if include_graph:
            result["objects"] = self.repository.query_objects()
            result["relations"] = self.repository.query_relations()
        return result

    @staticmethod
    def _client_model(model: dict[str, Any]) -> dict[str, Any]:
        """Hide private ChangeSet templates from the browser-facing catalog."""
        result = deepcopy(model)
        for definition in result.get("actions", {}).values():
            if isinstance(definition, dict):
                definition.pop("handler", None)
                definition.pop("effects", None)
        return result

    def query_records(
        self,
        kind: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 200,
        offset: int = 0,
        order_by: str | None = None,
    ) -> dict[str, Any]:
        if kind not in {"object", "relation"}:
            raise ValueError("kind 必须是 object 或 relation")
        safe_limit = max(1, min(int(limit), 500))
        safe_offset = max(0, int(offset))
        query = (
            self.repository.query_objects
            if kind == "object"
            else self.repository.query_relations
        )
        count = (
            self.repository.count_objects
            if kind == "object"
            else self.repository.count_relations
        )
        records = query(
            filters=filters or None, limit=safe_limit,
            order_by=order_by, offset=safe_offset,
        )
        total = count(filters=filters or None)
        return {
            "kind": kind,
            "records": records,
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
            "has_more": safe_offset + len(records) < total,
        }

    def preview_changes(
        self,
        operations: list[dict[str, Any]],
        read_object_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        with _CHANGE_LOCK:
            try:
                snapshot = self.changeset_snapshot(operations, read_object_ids)
            except ChangeValidationError as exc:
                return {
                    "valid": False,
                    "errors": exc.errors,
                    "changes": [],
                    "changed_files": [],
                }
            base_model_digest = self._digest(snapshot["source_model"])
            base_snapshot = deepcopy(snapshot)
            try:
                changed_sections, summaries = self._apply_operations(snapshot, operations)
            except ChangeValidationError as exc:
                return {
                    "valid": False,
                    "errors": exc.errors,
                    "changes": [],
                    "changed_files": [],
                }
            errors = self._validate_changed_snapshot(
                snapshot, operations, changed_sections,
            )
            if not errors:
                self._previews[self._digest(operations)] = {
                    "model_digest": base_model_digest,
                    "read_set": self._collect_read_set(
                        base_snapshot, operations, read_object_ids,
                    ),
                }
            return {
                "valid": not errors,
                "errors": errors,
                "changes": summaries,
                "changed_files": self._changed_targets(changed_sections),
            }

    def apply_changes(
        self,
        operations: list[dict[str, Any]],
        audit: dict[str, Any] | None = None,
        reason: str = "",
        actor: str = "agent",
        channel: str = "agent",
    ) -> dict[str, Any]:
        with _CHANGE_LOCK:
            snapshot = self.changeset_snapshot(operations)
            operation_digest = self._digest(operations)
            preview = self._previews.get(operation_digest)
            if not isinstance(preview, dict):
                raise ChangeValidationError([
                    "changes: 必须基于当前数据先完成相同 ChangeSet 的预览"
                ])
            if preview.get("model_digest") != self._digest(snapshot["source_model"]):
                raise ChangeValidationError([
                    "changes: 模型或数据前提已变化，请重新预览"
                ])
            if not self._read_set_matches(preview.get("read_set", {})):
                raise ChangeValidationError([
                    "changes: 相关记录已被其他操作修改，请刷新后重试"
                ])

            before_snapshot = deepcopy(snapshot)
            original_model = deepcopy(snapshot["source_model"])
            changed_sections, summaries = self._apply_operations(snapshot, operations)
            errors = self._validate_changed_snapshot(
                snapshot, operations, changed_sections,
            )
            if errors:
                raise ChangeValidationError(errors)

            data_changed = bool(changed_sections & {"objects", "relations"})
            model_changed = "model" in changed_sections
            model_written = False
            audit_entry = deepcopy(audit) if audit else None
            if data_changed and audit_entry is None:
                audit_entry = {
                    "id": f"changeset:{uuid4()}",
                    "action_id": "apply_changes",
                    "actor": str(actor or "unknown"),
                    "channel": str(channel or "unknown"),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "action_name": "高级数据变更",
                        "reason": str(reason or ""),
                        "operations": deepcopy(operations),
                    },
                }
            if audit_entry is not None:
                if not data_changed:
                    raise ChangeValidationError(["action: 业务操作必须产生图数据变更"])
                payload = audit_entry.setdefault("payload", {})
                if not isinstance(payload, dict):
                    raise ChangeValidationError(["action.audit.payload: 必须是对象"])
                payload["changes"] = self._audit_changes(
                    before_snapshot,
                    snapshot,
                    operations,
                )

            def write_model() -> None:
                nonlocal model_written
                updated = update_source_vocabulary(
                    snapshot["source_model"], snapshot["model"]
                )
                self._write_atomic(self.model_path, updated)
                model_written = True

            try:
                if data_changed:
                    self.repository.apply_changeset(
                        operations,
                        expected_revisions=preview.get("read_set", {}),
                        acyclic_relation_types={
                            type_id
                            for type_id, definition in snapshot["model"].get("relation_types", {}).items()
                            if isinstance(definition, dict) and definition.get("acyclic") is True
                        },
                        before_commit=write_model if model_changed else None,
                        audit_entry=audit_entry,
                    )
                elif model_changed:
                    write_model()
            except Exception:
                if model_written:
                    self._write_atomic(self.model_path, original_model)
                raise

            self._previews.pop(operation_digest, None)
            return {
                "applied": True,
                "changes": summaries,
                "changed_files": self._changed_targets(changed_sections),
            }

    @staticmethod
    def _audit_changes(
        before: dict[str, dict[str, Any]],
        after: dict[str, dict[str, Any]],
        operations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        indexes: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        for kind, section, records_key in (
            ("object", "objects", "objects"),
            ("relation", "relations", "relations"),
        ):
            indexes[kind] = (
                {
                    item["id"]: item
                    for item in before[section].get(records_key, [])
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                },
                {
                    item["id"]: item
                    for item in after[section].get(records_key, [])
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                },
            )
        changes = []
        for operation in operations:
            action = str(operation.get("action") or "")
            if not action.endswith(("_object", "_relation")):
                continue
            kind = "object" if action.endswith("_object") else "relation"
            record_id = (
                operation.get("record", {}).get("id")
                if action.startswith("create_")
                else operation.get("id")
            )
            before_index, after_index = indexes[kind]
            changes.append({
                "operation": action,
                "kind": kind,
                "id": record_id,
                "before": deepcopy(before_index.get(record_id)),
                "after": deepcopy(after_index.get(record_id)),
            })
        return changes

    def list_objects(self) -> list[dict[str, Any]]:
        return self.repository.query_objects()

    def list_relations(self) -> list[dict[str, Any]]:
        return self.repository.query_relations()

    def get_model_vocabulary(self, kind: str = "all", type_id: str = "") -> dict[str, Any]:
        model = self.load_model()
        sections = {
            "property": model.get("property_definitions", {}),
            "object": model.get("object_types", {}),
            "relation": model.get("relation_types", {}),
        }
        if kind in sections:
            values = sections[kind]
            return {type_id: values[type_id]} if type_id and type_id in values else values
        return sections

    def get_record_history(
        self,
        kind: str,
        record_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "kind": kind,
            "record_id": record_id,
            "history": self.repository.list_record_history(
                kind, record_id, limit=limit,
            ),
        }

    def _apply_operations(
        self,
        snapshot: dict[str, dict[str, Any]],
        operations: list[dict[str, Any]],
    ) -> tuple[set[str], list[str]]:
        if not isinstance(operations, list) or not operations:
            raise ChangeValidationError(["changes: 至少需要一个操作"])
        changed_sections: set[str] = set()
        summaries: list[str] = []
        for index, operation in enumerate(operations):
            if not isinstance(operation, dict):
                raise ChangeValidationError([f"changes[{index}]: 必须是对象"])
            action = operation.get("action")
            if action == "create_object":
                record = deepcopy(operation.get("record"))
                self._validate_new_record(record, "object")
                snapshot["objects"].setdefault("objects", []).append(record)
                changed_sections.add("objects")
                summaries.append(f"新增对象 {self._record_label(record)}")
            elif action == "update_object":
                record = self._find_record(
                    snapshot["objects"].get("objects", []),
                    operation.get("id"),
                )
                self._merge_record(record, operation.get("changes"), "object")
                changed_sections.add("objects")
                summaries.append(f"更新对象 {self._record_label(record)}")
            elif action == "delete_object":
                object_id = operation.get("id")
                if any(
                    relation.get("from") == object_id or relation.get("to") == object_id
                    for relation in snapshot["relations"].get("relations", [])
                    if self._is_active(relation)
                ):
                    raise ChangeValidationError([f"对象 {object_id} 仍有有效关系，不能退役"])
                record = self._find_record(
                    snapshot["objects"].get("objects", []),
                    object_id,
                )
                self._retire_record(record)
                changed_sections.add("objects")
                summaries.append(f"退役对象 {object_id}")
            elif action == "create_relation":
                record = deepcopy(operation.get("record"))
                self._validate_new_record(record, "relation")
                snapshot["relations"].setdefault("relations", []).append(record)
                changed_sections.add("relations")
                summaries.append(f"新增关系 {self._record_label(record)}")
            elif action == "update_relation":
                record = self._find_record(
                    snapshot["relations"].get("relations", []),
                    operation.get("id"),
                )
                self._merge_record(record, operation.get("changes"), "relation")
                changed_sections.add("relations")
                summaries.append(f"更新关系 {self._record_label(record)}")
            elif action == "delete_relation":
                relation_id = operation.get("id")
                record = self._find_record(
                    snapshot["relations"].get("relations", []),
                    relation_id,
                )
                self._retire_record(record)
                changed_sections.add("relations")
                summaries.append(f"退役关系 {relation_id}")
            elif action == "upsert_property_definition":
                property_id = operation.get("property_id")
                definition = deepcopy(operation.get("definition"))
                if not isinstance(property_id, str) or not isinstance(definition, dict):
                    raise ChangeValidationError([f"changes[{index}]: 属性定义不完整"])
                current = snapshot["model"].get("property_definitions", {}).get(property_id)
                if (
                    isinstance(current, dict)
                    and current.get("type") != definition.get("type")
                    and self._property_is_used(snapshot, property_id)
                ):
                    raise ChangeValidationError([
                        f"属性 {property_id} 已被数据使用，不能原地修改值类型；"
                        "请新建属性并执行显式数据迁移"
                    ])
                snapshot["model"].setdefault("property_definitions", {})[property_id] = definition
                changed_sections.add("model")
                summaries.append(f"定义业务属性 {property_id}")
            elif action in {"upsert_object_type", "upsert_relation_type"}:
                kind = "object" if action == "upsert_object_type" else "relation"
                section = f"{kind}_types"
                type_id = operation.get("type_id")
                definition = deepcopy(operation.get("definition"))
                if not isinstance(type_id, str) or not isinstance(definition, dict):
                    raise ChangeValidationError([f"changes[{index}]: 类型定义不完整"])
                snapshot["model"].setdefault(section, {})[type_id] = definition
                changed_sections.add("model")
                summaries.append(f"定义{self._kind_label(kind)}类型 {type_id}")
            else:
                raise ChangeValidationError([f"changes[{index}]: 未知操作 {action}"])
        if "model" in changed_sections:
            self._bump_model_version(snapshot["model"])
        return changed_sections, summaries

    @staticmethod
    def _property_is_used(
        snapshot: dict[str, dict[str, Any]],
        property_id: str,
    ) -> bool:
        for section, records_key in (("objects", "objects"), ("relations", "relations")):
            for record in snapshot[section].get(records_key, []):
                if property_id in (record.get("properties") or {}):
                    return True
        return False

    @staticmethod
    def _model_usage_from_counts(
        model: dict[str, Any],
        object_counts: dict[str, int],
        relation_counts: dict[str, int],
    ) -> dict[str, Any]:
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

    def _validate_snapshot(self, snapshot: dict[str, dict[str, Any]]) -> list[str]:
        errors = ModelValidator(
            snapshot["ontology"],
            snapshot["objects"],
            snapshot["relations"],
            snapshot["model"],
        ).validate().errors
        try:
            update_source_vocabulary(snapshot["source_model"], snapshot["model"])
        except (TypeError, ValueError, ValidationError) as exc:
            errors.append(f"model: {exc}")
        return errors

    def _validate_changed_snapshot(
        self,
        snapshot: dict[str, dict[str, Any]],
        operations: list[dict[str, Any]],
        changed_sections: set[str],
    ) -> list[str]:
        if "model" in changed_sections:
            return self._validate_snapshot(snapshot)
        object_ids: set[str] = set()
        relation_ids: set[str] = set()
        acyclic_types: set[str] = set()
        for operation in operations:
            action = str(operation.get("action") or "")
            record = operation.get("record")
            record_id = (
                record.get("id") if isinstance(record, dict) and action.startswith("create_")
                else operation.get("id")
            )
            if action.endswith("_object") and isinstance(record_id, str):
                object_ids.add(record_id)
            elif action.endswith("_relation") and isinstance(record_id, str):
                relation_ids.add(record_id)
                if action == "create_relation" and isinstance(record, dict):
                    relation_type = record.get("type")
                    if isinstance(relation_type, str):
                        acyclic_types.add(relation_type)
        return ModelValidator(
            snapshot["ontology"],
            snapshot["objects"],
            snapshot["relations"],
            snapshot["model"],
        ).validate_changes(
            object_ids,
            relation_ids,
            check_acyclic_types=acyclic_types,
        ).errors

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
    def _merge_record(record: dict[str, Any], changes: Any, kind: str) -> None:
        if not isinstance(changes, dict):
            raise ChangeValidationError(["changes: 更新内容必须是对象"])
        immutable = {"id", "type", "lifecycle"}
        if kind == "relation":
            immutable.update({"from", "to"})
        for key, value in changes.items():
            if key in immutable:
                raise ChangeValidationError([f"changes.{key}: 不允许修改稳定身份字段"])
            if key == "properties" and isinstance(value, dict):
                record.setdefault("properties", {}).update(deepcopy(value))
            else:
                record[key] = deepcopy(value)

    @staticmethod
    def _retire_record(record: dict[str, Any]) -> None:
        lifecycle = record.get("lifecycle")
        if not isinstance(lifecycle, dict):
            raise ChangeValidationError([f"记录 {record.get('id')} 缺少 UOM 生命周期信息"])
        if lifecycle.get("retired_at"):
            raise ChangeValidationError([f"记录 {record.get('id')} 已经退役"])
        lifecycle["retired_at"] = datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _is_active(record: dict[str, Any]) -> bool:
        lifecycle = record.get("lifecycle")
        return not isinstance(lifecycle, dict) or not lifecycle.get("retired_at")

    def _validate_new_record(
        self,
        record: Any,
        kind: str,
    ) -> None:
        if not isinstance(record, dict):
            return
        if "lifecycle" in record:
            raise ChangeValidationError(["lifecycle: 由 UOM 存储层维护，不能由业务输入"])
        if self.repository.record_exists(kind, str(record.get("id") or "")):
            raise ChangeValidationError([
                f"稳定 ID {record.get('id')} 已存在或曾经使用，不能重复创建"
            ])

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
            targets.append("data/graph.db")
        if "model" in changed_sections:
            targets.append("model.yaml")
        return targets

    @staticmethod
    def _digest(value: Any) -> str:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _collect_read_set(
        self,
        snapshot: dict[str, dict[str, Any]],
        operations: list[dict[str, Any]],
        supplemental_object_ids: set[str] | None = None,
    ) -> dict[str, int]:
        objects = {
            item.get("id"): item
            for item in snapshot["objects"].get("objects", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        relations = {
            item.get("id"): item
            for item in snapshot["relations"].get("relations", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        read_set: dict[str, int] = {}

        def add(kind: str, record: dict[str, Any] | None) -> None:
            if not isinstance(record, dict):
                return
            lifecycle = record.get("lifecycle")
            revision = lifecycle.get("revision") if isinstance(lifecycle, dict) else None
            record_id = record.get("id")
            if isinstance(record_id, str) and isinstance(revision, int):
                read_set[f"{kind}:{record_id}"] = revision

        for operation in operations:
            action = str(operation.get("action") or "")
            if action in {"update_object", "delete_object"}:
                target = objects.get(operation.get("id"))
                add("object", target)
                if action == "delete_object" and target:
                    for relation in relations.values():
                        if relation.get("from") == target.get("id") or relation.get("to") == target.get("id"):
                            if self._is_active(relation):
                                add("relation", relation)
            elif action == "update_relation" or action == "delete_relation":
                target = relations.get(operation.get("id"))
                add("relation", target)
                if target:
                    add("object", objects.get(target.get("from")))
                    add("object", objects.get(target.get("to")))
            elif action == "create_relation":
                record = operation.get("record")
                if isinstance(record, dict):
                    add("object", objects.get(record.get("from")))
                    add("object", objects.get(record.get("to")))
        for object_id in supplemental_object_ids or set():
            add("object", objects.get(object_id))
            for relation in relations.values():
                if relation.get("from") == object_id or relation.get("to") == object_id:
                    add("relation", relation)
        return read_set

    def _read_set_matches(self, read_set: Any) -> bool:
        if not isinstance(read_set, dict):
            return False
        for key, expected in read_set.items():
            try:
                kind, record_id = str(key).split(":", 1)
            except ValueError:
                return False
            state = self.repository.get_record_version(kind, record_id)
            if not state or int(state.get("revision", -1)) != int(expected):
                return False
        return True

    @staticmethod
    def _write_atomic(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
            text=True,
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                yaml.safe_dump(
                    value,
                    stream,
                    allow_unicode=True,
                    sort_keys=False,
                    width=100,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
