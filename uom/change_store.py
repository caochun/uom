"""UOM-specific graph change, lifecycle, and history boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable


RecordKind = Literal["object", "relation"]


@runtime_checkable
class UomChangeSource(Protocol):
    """Physical graph capabilities required by the UOM workspace."""

    location: Any

    def query_graph_objects(self, filters=None, limit=None, order_by=None,
                            offset=None) -> list[dict]: ...
    def query_graph_relations(self, filters=None, *, from_id=None, to_id=None,
                              direction="out", limit=None, order_by=None,
                              offset=None) -> list[dict]: ...
    def count_graph_objects(self, filters=None) -> int: ...
    def count_graph_relations(self, filters=None) -> int: ...
    def get_graph_object(self, record_id: Any) -> dict | None: ...
    def get_graph_relation(self, record_id: Any) -> dict | None: ...
    def create_graph_object(self, record: dict) -> dict: ...
    def update_graph_object(self, record_id: str, changes: dict) -> dict: ...
    def retire_graph_object(self, record_id: str) -> dict: ...
    def create_graph_relation(self, record: dict) -> dict: ...
    def update_graph_relation(self, record_id: str, changes: dict) -> dict: ...
    def retire_graph_relation(self, record_id: str) -> dict: ...
    def query_graph_records_by_ids(self, kind: RecordKind, ids: Iterable[Any],
                                   *, include_retired: bool = False) -> list[dict]: ...
    def query_graph_adjacent(self, object_ids: Iterable[Any], *,
                             include_retired: bool = False) -> list[dict]: ...
    def graph_type_counts(self, kind: RecordKind) -> dict[str, int]: ...
    def graph_record_exists(self, kind: RecordKind, record_id: str) -> bool: ...
    def get_graph_record_version(self, kind: RecordKind,
                                 record_id: str) -> dict[str, Any] | None: ...
    def apply_graph_changeset(
        self,
        operations: list[dict[str, Any]],
        *,
        expected_revisions: dict[str, int] | None = None,
        acyclic_relation_types: set[str] | None = None,
        before_commit: Callable[[], None] | None,
        audit_entry: dict[str, Any] | None,
    ) -> None: ...
    def replace_property_graph(self, objects: list[dict], relations: list[dict],
                               **kwargs) -> None: ...
    def list_action_log(self, limit: int = 100) -> list[dict]: ...
    def list_record_history(self, kind: RecordKind, record_id: str,
                            limit: int = 100) -> list[dict]: ...


class UomChangeStore:
    """Workspace-facing facade for UOM physical graph administration."""

    def __init__(self, source: UomChangeSource, *, writable: bool):
        self._source = source
        self._writable = writable

    @property
    def database_path(self) -> Path:
        if not isinstance(self._source.location, Path):
            raise TypeError("UOM 数据源没有本地数据库路径")
        return self._source.location

    def query_objects(self, filters=None, limit=None, order_by=None, offset=None):
        return self._source.query_graph_objects(filters, limit, order_by, offset)

    def query_relations(self, filters=None, *, from_id=None, to_id=None,
                        direction="out", limit=None, order_by=None, offset=None):
        return self._source.query_graph_relations(
            filters, from_id=from_id, to_id=to_id, direction=direction,
            limit=limit, order_by=order_by, offset=offset,
        )

    def count_objects(self, filters=None) -> int:
        return self._source.count_graph_objects(filters)

    def count_relations(self, filters=None) -> int:
        return self._source.count_graph_relations(filters)

    def get_object(self, record_id: Any):
        return self._source.get_graph_object(record_id)

    def get_relation(self, record_id: Any):
        return self._source.get_graph_relation(record_id)

    def create_object(self, record: dict) -> dict:
        self._assert_writable()
        return self._source.create_graph_object(record)

    def update_object(self, record_id: str, changes: dict) -> dict:
        self._assert_writable()
        return self._source.update_graph_object(record_id, changes)

    def retire_object(self, record_id: str) -> dict:
        self._assert_writable()
        return self._source.retire_graph_object(record_id)

    def create_relation(self, record: dict) -> dict:
        self._assert_writable()
        return self._source.create_graph_relation(record)

    def update_relation(self, record_id: str, changes: dict) -> dict:
        self._assert_writable()
        return self._source.update_graph_relation(record_id, changes)

    def retire_relation(self, record_id: str) -> dict:
        self._assert_writable()
        return self._source.retire_graph_relation(record_id)

    def query_by_ids(self, kind: RecordKind, ids: Iterable[Any], *,
                     include_retired: bool = False):
        return self._source.query_graph_records_by_ids(
            kind, ids, include_retired=include_retired,
        )

    def query_adjacent(self, object_ids: Iterable[Any], *,
                       include_retired: bool = False):
        return self._source.query_graph_adjacent(
            object_ids, include_retired=include_retired,
        )

    def type_counts(self, kind: RecordKind) -> dict[str, int]:
        return self._source.graph_type_counts(kind)

    def record_exists(self, kind: RecordKind, record_id: str) -> bool:
        return self._source.graph_record_exists(kind, record_id)

    def get_record_version(self, kind: RecordKind, record_id: str):
        return self._source.get_graph_record_version(kind, record_id)

    def apply_changeset(
        self,
        operations: list[dict[str, Any]],
        *,
        expected_revisions: dict[str, int] | None = None,
        acyclic_relation_types: set[str] | None = None,
        before_commit: Callable[[], None] | None = None,
        audit_entry: dict[str, Any] | None = None,
    ) -> None:
        self._assert_writable()
        self._source.apply_graph_changeset(
            operations,
            expected_revisions=expected_revisions or {},
            acyclic_relation_types=acyclic_relation_types or set(),
            before_commit=before_commit,
            audit_entry=audit_entry,
        )

    def replace_graph(self, objects: list[dict], relations: list[dict], **kwargs) -> None:
        self._assert_writable()
        self._source.replace_property_graph(objects, relations, **kwargs)

    def list_action_log(self, limit: int = 100):
        return self._source.list_action_log(limit)

    def list_record_history(self, kind: RecordKind, record_id: str, limit: int = 100):
        return self._source.list_record_history(kind, record_id, limit)

    def _assert_writable(self) -> None:
        if not self._writable:
            raise ValueError("UOM 数据源是只读的")
