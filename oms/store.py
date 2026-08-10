"""OMS workspace service for model editing and validated ChangeSets."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from oms.scripts.validate_model import ModelValidator

if TYPE_CHECKING:
    from oag.ontology.repository import ObjectRepository


TYPE_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_CHANGE_LOCK = threading.RLock()


class ChangeValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class OmsWorkspaceService:
    """Manage user vocabulary and atomic, validated graph ChangeSets."""

    def __init__(self, oms_root: str | Path, repository: ObjectRepository):
        self.root = Path(oms_root).resolve()
        self.ontology_path = self.root / "ontology.yaml"
        self.model_path = self.root / "model.yaml"
        self.repository = repository
        self._previews: dict[str, str] = {}

    @property
    def database_path(self) -> Path:
        adapter = self.repository.adapter_for("Object")
        path = getattr(adapter, "database_path", None)
        if not isinstance(path, Path):
            raise TypeError("Object 的数据源不是 OMS SQLite adapter")
        return path

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as stream:
            value = yaml.safe_load(stream)
        if not isinstance(value, dict):
            raise ValueError(f"{path} must contain a YAML mapping")
        return value

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            "ontology": self._load(self.ontology_path),
            "model": self._load(self.model_path),
            "objects": {
                "schema": "oms.data.objects.v2",
                "objects": self.repository.query("Object"),
            },
            "relations": {
                "schema": "oms.data.relations.v2",
                "relations": self.repository.query("Relation"),
            },
        }

    def bootstrap(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        objects = snapshot["objects"].get("objects", [])
        relations = snapshot["relations"].get("relations", [])
        model = snapshot["model"]
        adapter = self.repository.adapter_for("Object")
        list_action_log = getattr(adapter, "list_action_log", None)
        return {
            "ontology": snapshot["ontology"],
            "model": model,
            "objects": objects,
            "relations": relations,
            "stats": self._stats(objects, relations),
            "model_usage": self._model_usage(model, objects, relations),
            "recent_actions": list_action_log(limit=50) if callable(list_action_log) else [],
        }

    def preview_changes(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        with _CHANGE_LOCK:
            snapshot = self.snapshot()
            base_digest = self._snapshot_digest(snapshot)
            changed_sections, summaries = self._apply_operations(snapshot, operations)
            errors = self._validate_snapshot(snapshot)
            if not errors:
                self._previews[self._digest(operations)] = base_digest
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
    ) -> dict[str, Any]:
        with _CHANGE_LOCK:
            snapshot = self.snapshot()
            operation_digest = self._digest(operations)
            if self._previews.get(operation_digest) != self._snapshot_digest(snapshot):
                raise ChangeValidationError([
                    "changes: 必须基于当前数据先完成相同 ChangeSet 的预览"
                ])

            before_snapshot = deepcopy(snapshot)
            original_model = deepcopy(snapshot["model"])
            changed_sections, summaries = self._apply_operations(snapshot, operations)
            errors = self._validate_snapshot(snapshot)
            if errors:
                raise ChangeValidationError(errors)

            data_changed = bool(changed_sections & {"objects", "relations"})
            model_changed = "model" in changed_sections
            model_written = False
            audit_entry = deepcopy(audit) if audit else None
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
                self._write_atomic(self.model_path, snapshot["model"])
                model_written = True

            try:
                if data_changed:
                    adapter = self.repository.adapter_for("Object")
                    replace_graph = getattr(adapter, "replace_graph", None)
                    if not callable(replace_graph):
                        raise TypeError("Object 数据源不支持 OMS 图事务")
                    replace_graph(
                        snapshot["objects"].get("objects", []),
                        snapshot["relations"].get("relations", []),
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
        return self.repository.query("Object")

    def list_relations(self) -> list[dict[str, Any]]:
        return self.repository.query("Relation")

    def get_model_vocabulary(self, kind: str = "all", type_id: str = "") -> dict[str, Any]:
        model = self._load(self.model_path)
        sections = {
            "property": model.get("property_definitions", {}),
            "object": model.get("object_types", {}),
            "relation": model.get("relation_types", {}),
        }
        if kind in sections:
            values = sections[kind]
            return {type_id: values[type_id]} if type_id and type_id in values else values
        return sections

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
                snapshot["objects"].setdefault("objects", []).append(record)
                changed_sections.add("objects")
                summaries.append(f"新增对象 {self._record_label(record)}")
            elif action == "update_object":
                record = self._find_record(
                    snapshot["objects"].get("objects", []),
                    operation.get("id"),
                )
                self._merge_record(record, operation.get("changes"))
                changed_sections.add("objects")
                summaries.append(f"更新对象 {self._record_label(record)}")
            elif action == "delete_object":
                object_id = operation.get("id")
                if any(
                    relation.get("from") == object_id or relation.get("to") == object_id
                    for relation in snapshot["relations"].get("relations", [])
                ):
                    raise ChangeValidationError([f"对象 {object_id} 仍有关联关系，不能删除"])
                self._delete_record(snapshot["objects"].get("objects", []), object_id)
                changed_sections.add("objects")
                summaries.append(f"删除对象 {object_id}")
            elif action == "create_relation":
                record = deepcopy(operation.get("record"))
                snapshot["relations"].setdefault("relations", []).append(record)
                changed_sections.add("relations")
                summaries.append(f"新增关系 {self._record_label(record)}")
            elif action == "update_relation":
                record = self._find_record(
                    snapshot["relations"].get("relations", []),
                    operation.get("id"),
                )
                self._merge_record(record, operation.get("changes"))
                changed_sections.add("relations")
                summaries.append(f"更新关系 {self._record_label(record)}")
            elif action == "delete_relation":
                relation_id = operation.get("id")
                self._delete_record(
                    snapshot["relations"].get("relations", []),
                    relation_id,
                )
                changed_sections.add("relations")
                summaries.append(f"删除关系 {relation_id}")
            elif action == "upsert_property_definition":
                property_id = operation.get("property_id")
                definition = deepcopy(operation.get("definition"))
                if not isinstance(property_id, str) or not isinstance(definition, dict):
                    raise ChangeValidationError([f"changes[{index}]: 属性定义不完整"])
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
    def _stats(
        objects: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> dict[str, Any]:
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

    def _validate_snapshot(self, snapshot: dict[str, dict[str, Any]]) -> list[str]:
        return ModelValidator(
            snapshot["ontology"],
            snapshot["objects"],
            snapshot["relations"],
            snapshot["model"],
        ).validate().errors

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
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _snapshot_digest(self, snapshot: dict[str, dict[str, Any]]) -> str:
        return self._digest({
            key: snapshot[key]
            for key in ("model", "objects", "relations")
        })

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
