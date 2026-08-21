"""SQLite data-source adapter for the UOM object-relation graph."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from oag.ontology.schema import (
    DataBindingDef,
    DataSourceDef,
    Ontology,
)


_DATABASE_SCHEMA_VERSION = "4"
_WRITE_LOCKS: dict[Path, threading.RLock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def _write_lock_for(path: Path) -> threading.RLock:
    with _WRITE_LOCKS_GUARD:
        return _WRITE_LOCKS.setdefault(path, threading.RLock())


class UomSqliteGraphStore:
    """SQLite property-graph store used by the UOM source adapter."""

    def __init__(
        self,
        kind: str,
        database: str | Path,
        domain_dir: Path,
    ) -> None:
        self.kind = str(kind).lower()
        self.object_type = "Object" if self.kind == "object" else "Relation"
        if self.kind not in {"object", "relation"}:
            raise ValueError("kind 必须是 object 或 relation")
        self.table = "objects" if self.kind == "object" else "relations"
        path = Path(str(database))
        self.database_path = path.resolve() if path.is_absolute() else (domain_dir / path).resolve()
        self._write_lock = _write_lock_for(self.database_path)
        self._ensure_database()

    def query_records(
        self,
        object_type: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        order_by: str | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        self._assert_object_type(object_type)
        with self._connect() as connection:
            where, parameters = self._where_clause(filters)
            order_clause = self._order_clause(order_by)
            paging = ""
            if limit is not None:
                paging += " LIMIT ?"
                parameters.append(max(0, int(limit)))
            if offset is not None:
                # SQLite requires LIMIT when OFFSET is present.
                if limit is None:
                    paging += " LIMIT -1"
                paging += " OFFSET ?"
                parameters.append(max(0, int(offset)))
            rows = connection.execute(
                f"SELECT payload, revision, created_at, updated_at, retired_at "
                f"FROM {self.table}{where}{order_clause}{paging}",
                parameters,
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def count_records(
        self,
        object_type: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        self._assert_object_type(object_type)
        with self._connect() as connection:
            where, parameters = self._where_clause(filters)
            row = connection.execute(
                f"SELECT COUNT(*) AS total FROM {self.table}{where}",
                parameters,
            ).fetchone()
        return int(row["total"] if row else 0)

    def query_record_by_id(self, object_type: str, id_value: Any) -> dict[str, Any] | None:
        self._assert_object_type(object_type)
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload, revision, created_at, updated_at, retired_at "
                f"FROM {self.table} WHERE id = ? AND retired_at IS NULL",
                (id_value,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def search_records(
        self,
        keyword: str,
        object_types: list[str] | None = None,
        limit: int = 20,
        *,
        record_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if not keyword or (object_types and self.object_type not in object_types):
            return []
        needle = keyword.lower()
        results = []
        where = "retired_at IS NULL"
        parameters: list[Any] = []
        if record_type:
            where += " AND type = ?"
            parameters.append(record_type)
        parameters.extend((f"%{needle}%", max(1, min(int(limit) * 4, 5000))))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload, revision, created_at, updated_at, retired_at "
                f"FROM {self.table} WHERE {where} AND "
                "lower(CAST(payload AS TEXT)) LIKE ? ORDER BY rowid LIMIT ?",
                parameters,
            ).fetchall()
        for raw_row in rows:
            row = self._row_to_record(raw_row)
            matched_fields = [
                field
                for field, value in row.items()
                if needle in json.dumps(value, ensure_ascii=False).lower()
            ]
            if not matched_fields:
                continue
            result = deepcopy(row)
            result["_object_type"] = self.object_type
            result["_matched_field"] = ", ".join(matched_fields)
            results.append(result)
            if len(results) >= limit:
                break
        return results

    def create_record(self, object_type: str, data: dict[str, Any]) -> dict[str, Any]:
        self._assert_object_type(object_type)
        record = deepcopy(data)
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_record(connection, self.kind, record)
            self._increment_revision(connection)
            connection.commit()
        return {"inserted": 1}

    def update_record(
        self,
        object_type: str,
        id_value: Any,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        self._assert_object_type(object_type)
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"SELECT payload, revision, created_at, updated_at, retired_at "
                f"FROM {self.table} WHERE id = ? AND retired_at IS NULL",
                (id_value,),
            ).fetchone()
            if not row:
                connection.rollback()
                return {"updated": 0}
            record = self._row_to_record(row)
            self._merge_record(record, data, self.kind)
            self._update_record(
                connection,
                self.kind,
                id_value,
                record,
                revision=int(row["revision"]) + 1,
                created_at=str(row["created_at"]),
                updated_at=self._now(),
                retired_at=row["retired_at"],
            )
            self._increment_revision(connection)
            connection.commit()
        return {"updated": 1}

    def retire_record(self, object_type: str, id_value: Any) -> dict[str, Any]:
        self._assert_object_type(object_type)
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self.kind == "object":
                linked = connection.execute(
                    "SELECT 1 FROM relations WHERE retired_at IS NULL "
                    "AND (source_id = ? OR target_id = ?) LIMIT 1",
                    (id_value, id_value),
                ).fetchone()
                if linked:
                    connection.rollback()
                    raise ValueError(f"对象 {id_value} 仍有有效关系，不能退役")
            cursor = connection.execute(
                f"UPDATE {self.table} SET retired_at = ?, updated_at = ?, "
                "revision = revision + 1 WHERE id = ? AND retired_at IS NULL",
                (self._now(), self._now(), id_value),
            )
            if cursor.rowcount:
                self._increment_revision(connection)
            connection.commit()
        return {"deleted": cursor.rowcount}

    def type_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT type, COUNT(*) AS total FROM {self.table} "
                "WHERE retired_at IS NULL GROUP BY type ORDER BY type"
            ).fetchall()
        return {str(row["type"]): int(row["total"]) for row in rows}

    def record_exists(self, kind: str, record_id: str) -> bool:
        if kind not in {"object", "relation"}:
            raise ValueError("kind 必须是 object 或 relation")
        table = "objects" if kind == "object" else "relations"
        with self._connect() as connection:
            return connection.execute(
                f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1",
                (record_id,),
            ).fetchone() is not None

    def get_record_version(self, kind: str, record_id: str) -> dict[str, Any] | None:
        if kind not in {"object", "relation"}:
            raise ValueError("kind 必须是 object 或 relation")
        table = "objects" if kind == "object" else "relations"
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT revision, retired_at FROM {table} WHERE id = ?",
                (record_id,),
            ).fetchone()
        if not row:
            return None
        return {"revision": int(row["revision"]), "retired_at": row["retired_at"]}

    def apply_changeset(
        self,
        operations: list[dict[str, Any]],
        *,
        expected_revisions: dict[str, int] | None = None,
        acyclic_relation_types: set[str] | None = None,
        before_commit: Callable[[], None] | None = None,
        audit_entry: dict[str, Any] | None = None,
    ) -> None:
        """Apply only the records touched by a runtime ChangeSet.

        ``replace_graph`` remains the seed/rebuild API. Runtime changes use this
        method so SQLite does not rewrite unrelated rows.
        """
        data_operations = [
            operation for operation in operations
            if str(operation.get("action") or "").endswith(("_object", "_relation"))
        ]
        if not data_operations:
            raise ValueError("ChangeSet 没有数据操作")
        ordered_operations = [
            operation for operation in data_operations
            if operation.get("action") == "create_object"
        ] + [
            operation for operation in data_operations
            if operation.get("action") != "create_object"
        ]
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_expected_revisions(connection, expected_revisions or {})
                for operation in ordered_operations:
                    self._apply_data_operation(
                        connection,
                        operation,
                        acyclic_relation_types or set(),
                    )
                if audit_entry is not None:
                    self._insert_action_log(connection, audit_entry)
                self._increment_revision(connection)
                if before_commit:
                    before_commit()
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @classmethod
    def _check_expected_revisions(
        cls,
        connection: sqlite3.Connection,
        expected_revisions: dict[str, int],
    ) -> None:
        for key, expected in expected_revisions.items():
            try:
                kind, record_id = str(key).split(":", 1)
            except ValueError as exc:
                raise ValueError(f"无效的读集键: {key}") from exc
            if kind not in {"object", "relation"}:
                raise ValueError(f"无效的读集类型: {kind}")
            table = "objects" if kind == "object" else "relations"
            row = connection.execute(
                f"SELECT revision FROM {table} WHERE id = ?",
                (record_id,),
            ).fetchone()
            if not row or int(row["revision"]) != int(expected):
                actual = row["revision"] if row else "missing"
                raise ValueError(
                    f"记录 {record_id} 已被其他操作修改，请刷新后重试 "
                    f"(expected revision {expected}, actual {actual})"
                )

    @classmethod
    def _apply_data_operation(
        cls,
        connection: sqlite3.Connection,
        operation: dict[str, Any],
        acyclic_relation_types: set[str],
    ) -> None:
        action = str(operation.get("action") or "")
        kind = "object" if action.endswith("_object") else "relation"
        table = "objects" if kind == "object" else "relations"
        if action.startswith("create_"):
            record = deepcopy(operation.get("record"))
            if not isinstance(record, dict):
                raise ValueError("create 操作缺少 record")
            if connection.execute(
                f"SELECT 1 FROM {table} WHERE id = ?", (record.get("id"),)
            ).fetchone():
                raise ValueError(f"稳定 ID {record.get('id')} 已存在或曾经使用，不能重复创建")
            if kind == "relation" and record.get("type") in acyclic_relation_types:
                cls._assert_relation_remains_acyclic(connection, record)
            cls._insert_record(connection, kind, record)
            return

        record_id = operation.get("id")
        row = connection.execute(
            f"SELECT payload, revision, created_at, updated_at, retired_at "
            f"FROM {table} WHERE id = ?",
            (record_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"未找到记录 {record_id}")
        if row["retired_at"] is not None:
            raise ValueError(f"记录 {record_id} 已经退役")
        current = cls._row_to_record(row)
        if action.startswith("update_"):
            cls._merge_record(current, operation.get("changes"), kind)
            cls._update_record(
                connection,
                kind,
                record_id,
                current,
                revision=int(row["revision"]) + 1,
                created_at=str(row["created_at"]),
                updated_at=cls._now(),
                retired_at=row["retired_at"],
            )
            return
        if action == "delete_object":
            linked = connection.execute(
                "SELECT 1 FROM relations WHERE retired_at IS NULL "
                "AND (source_id = ? OR target_id = ?) LIMIT 1",
                (record_id, record_id),
            ).fetchone()
            if linked:
                raise ValueError(f"对象 {record_id} 仍有有效关系，不能退役")
        if action not in {"delete_object", "delete_relation"}:
            raise ValueError(f"未知数据操作 {action}")
        connection.execute(
            f"UPDATE {table} SET retired_at = ?, updated_at = ?, revision = revision + 1 "
            "WHERE id = ? AND retired_at IS NULL",
            (cls._now(), cls._now(), record_id),
        )

    @staticmethod
    def _assert_relation_remains_acyclic(
        connection: sqlite3.Connection,
        record: dict[str, Any],
    ) -> None:
        source = record.get("from")
        target = record.get("to")
        relation_type = record.get("type")
        reachable = connection.execute(
            "WITH RECURSIVE reachable(id) AS ("
            "SELECT target_id FROM relations "
            "WHERE type = ? AND source_id = ? AND retired_at IS NULL "
            "UNION "
            "SELECT r.target_id FROM relations r JOIN reachable p ON r.source_id = p.id "
            "WHERE r.type = ? AND r.retired_at IS NULL"
            ") SELECT 1 FROM reachable WHERE id = ? LIMIT 1",
            (relation_type, target, relation_type, source),
        ).fetchone()
        if source == target or reachable:
            raise ValueError(f"关系类型 {relation_type} 不允许形成环")

    def replace_graph(
        self,
        objects: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        before_commit: Callable[[], None] | None = None,
        audit_entry: dict[str, Any] | None = None,
    ) -> None:
        """Destructively replace a graph for explicit seed/rebuild workflows."""
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM relations")
                connection.execute("DELETE FROM objects")
                for record in objects:
                    self._insert_record(connection, "object", record)
                for record in relations:
                    self._insert_record(connection, "relation", record)
                if audit_entry is not None:
                    self._insert_action_log(connection, audit_entry)
                self._increment_revision(connection)
                if before_commit:
                    before_commit()
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def close(self) -> None:
        """Connections are scoped to individual operations."""

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA synchronous = NORMAL")
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_database(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self._connect() as connection:
            # WAL lets readers continue while a ChangeSet holds the single writer.
            connection.execute("PRAGMA journal_mode = WAL")
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
                    payload TEXT NOT NULL CHECK (json_valid(payload)),
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    retired_at TEXT
                );

                CREATE TABLE IF NOT EXISTS relations (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    payload TEXT NOT NULL CHECK (json_valid(payload)),
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    retired_at TEXT,
                    FOREIGN KEY (source_id) REFERENCES objects(id) ON DELETE RESTRICT,
                    FOREIGN KEY (target_id) REFERENCES objects(id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS action_log (
                    id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL CHECK (json_valid(payload))
                );

                CREATE TABLE IF NOT EXISTS action_changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_log_id TEXT NOT NULL,
                    change_index INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    before_payload TEXT CHECK (before_payload IS NULL OR json_valid(before_payload)),
                    after_payload TEXT CHECK (after_payload IS NULL OR json_valid(after_payload)),
                    FOREIGN KEY (action_log_id) REFERENCES action_log(id) ON DELETE CASCADE,
                    UNIQUE (action_log_id, change_index)
                );

                CREATE INDEX IF NOT EXISTS idx_objects_type ON objects(type);
                CREATE INDEX IF NOT EXISTS idx_objects_name ON objects(name);
                CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(type);
                CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
                CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
                CREATE INDEX IF NOT EXISTS idx_action_log_created_at ON action_log(created_at);
                CREATE INDEX IF NOT EXISTS idx_action_changes_record ON action_changes(kind, record_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_action_changes_log ON action_changes(action_log_id);
                CREATE INDEX IF NOT EXISTS idx_objects_active_type ON objects(type) WHERE retired_at IS NULL;
                CREATE INDEX IF NOT EXISTS idx_relations_active_source ON relations(source_id) WHERE retired_at IS NULL;
                CREATE INDEX IF NOT EXISTS idx_relations_active_target ON relations(target_id) WHERE retired_at IS NULL;
                """
            )
            schema_version = self._metadata(connection, "schema_version")
            if schema_version and schema_version not in {"1", "2", "3", _DATABASE_SCHEMA_VERSION}:
                raise ValueError(
                    f"unsupported UOM database schema {schema_version}; "
                    f"expected {_DATABASE_SCHEMA_VERSION}"
                )
            connection.execute("BEGIN IMMEDIATE")
            for table in ("objects", "relations"):
                self._ensure_column(connection, table, "revision", "INTEGER NOT NULL DEFAULT 1")
                self._ensure_column(connection, table, "created_at", "TEXT NOT NULL DEFAULT ''")
                self._ensure_column(connection, table, "updated_at", "TEXT NOT NULL DEFAULT ''")
                self._ensure_column(connection, table, "retired_at", "TEXT")
            now = self._now()
            connection.execute(
                "UPDATE objects SET created_at = ?, updated_at = ? "
                "WHERE created_at = '' OR updated_at = ''",
                (now, now),
            )
            connection.execute(
                "UPDATE relations SET created_at = ?, updated_at = ? "
                "WHERE created_at = '' OR updated_at = ''",
                (now, now),
            )
            self._set_metadata(connection, "schema_version", _DATABASE_SCHEMA_VERSION)
            self._backfill_action_changes(connection)
            if self._metadata(connection, "data_revision") is None:
                self._set_metadata(connection, "data_revision", "0")
            connection.commit()

    @classmethod
    def _backfill_action_changes(cls, connection: sqlite3.Connection) -> None:
        """Materialize legacy JSON change arrays into the indexed history table."""
        rows = connection.execute("SELECT id, payload FROM action_log").fetchall()
        for row in rows:
            try:
                changes = json.loads(row["payload"]).get("changes", [])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(changes, list):
                continue
            for change_index, change in enumerate(changes):
                if not isinstance(change, dict):
                    continue
                kind = str(change.get("kind") or "")
                record_id = str(change.get("id") or "")
                operation = str(change.get("operation") or "")
                if kind not in {"object", "relation"} or not record_id or not operation:
                    continue
                before = change.get("before")
                after = change.get("after")
                connection.execute(
                    "INSERT OR IGNORE INTO action_changes("
                    "action_log_id, change_index, kind, record_id, operation, before_payload, after_payload) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["id"], change_index, kind, record_id, operation,
                        cls._encode_record(before) if before is not None else None,
                        cls._encode_record(after) if after is not None else None,
                    ),
                )

    def list_action_log(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, action_id, actor, channel, created_at, payload "
                "FROM action_log ORDER BY created_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "action_id": row["action_id"],
                "actor": row["actor"],
                "channel": row["channel"],
                "created_at": row["created_at"],
                "payload": json.loads(row["payload"]),
            }
            for row in rows
        ]

    def list_record_history(
        self,
        kind: str,
        record_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if kind not in {"object", "relation"}:
            raise ValueError("kind 必须是 object 或 relation")
        safe_limit = max(1, min(int(limit), 500))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT l.id, l.action_id, l.actor, l.channel, l.created_at, l.payload, "
                "c.kind, c.record_id, c.operation, c.before_payload, c.after_payload "
                "FROM action_changes c JOIN action_log l ON l.id = c.action_log_id "
                "WHERE c.kind = ? AND c.record_id = ? "
                "ORDER BY l.created_at DESC, c.id DESC LIMIT ?",
                (kind, record_id, safe_limit),
            ).fetchall()
        history: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload"])
            history.append({
                "id": row["id"],
                "action_id": row["action_id"],
                "action_name": payload.get("action_name") or row["action_id"],
                "actor": row["actor"],
                "channel": row["channel"],
                "created_at": row["created_at"],
                "reason": payload.get("reason") or "",
                "change": {
                    "operation": row["operation"],
                    "kind": row["kind"],
                    "id": row["record_id"],
                    "before": json.loads(row["before_payload"])
                    if row["before_payload"] is not None else None,
                    "after": json.loads(row["after_payload"])
                    if row["after_payload"] is not None else None,
                },
            })
        return history

    def query_adjacent(
        self,
        object_ids: list[str] | set[str] | tuple[str, ...],
        *,
        include_retired: bool = False,
    ) -> list[dict[str, Any]]:
        """Return relations touching any endpoint in ``object_ids``.

        This is intentionally an adapter extension rather than a new ontology
        concept; graph traversal can use the indexed endpoint columns without
        materializing the whole relation table.
        """
        ids = [str(value) for value in object_ids if value is not None]
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        active = "" if include_retired else " AND retired_at IS NULL"
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload, revision, created_at, updated_at, retired_at "
                "FROM relations WHERE (source_id IN (" + placeholders + ") "
                "OR target_id IN (" + placeholders + "))" + active + " ORDER BY rowid",
                ids + ids,
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def query_by_ids(
        self,
        object_ids: list[str] | set[str] | tuple[str, ...],
        *,
        include_retired: bool = False,
    ) -> list[dict[str, Any]]:
        ids = [str(value) for value in object_ids if value is not None]
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        active = "" if include_retired else " AND retired_at IS NULL"
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload, revision, created_at, updated_at, retired_at "
                f"FROM {self.table} WHERE id IN ({placeholders}){active}",
                ids,
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _insert_record(
        connection: sqlite3.Connection,
        kind: str,
        record: dict[str, Any],
    ) -> None:
        lifecycle = record.get("lifecycle") if isinstance(record.get("lifecycle"), dict) else {}
        now = UomSqliteGraphStore._now()
        revision = int(lifecycle.get("revision") or 1)
        created_at = str(lifecycle.get("created_at") or now)
        updated_at = str(lifecycle.get("updated_at") or created_at)
        retired_at = lifecycle.get("retired_at")
        payload = UomSqliteGraphStore._encode_record(
            UomSqliteGraphStore._without_lifecycle(record)
        )
        if kind == "object":
            connection.execute(
                "INSERT INTO objects(id, type, name, payload, revision, created_at, updated_at, retired_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["id"], record["type"], record["name"], payload,
                    revision, created_at, updated_at, retired_at,
                ),
            )
            return
        connection.execute(
            "INSERT INTO relations(id, type, source_id, target_id, payload, revision, created_at, updated_at, retired_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record["id"], record["type"], record["from"], record["to"], payload,
                revision, created_at, updated_at, retired_at,
            ),
        )

    @staticmethod
    def _update_record(
        connection: sqlite3.Connection,
        kind: str,
        id_value: Any,
        record: dict[str, Any],
        *,
        revision: int,
        created_at: str,
        updated_at: str,
        retired_at: str | None,
    ) -> None:
        payload = UomSqliteGraphStore._encode_record(
            UomSqliteGraphStore._without_lifecycle(record)
        )
        if kind == "object":
            connection.execute(
                "UPDATE objects SET type = ?, name = ?, payload = ?, revision = ?, "
                "created_at = ?, updated_at = ?, retired_at = ? WHERE id = ?",
                (
                    record["type"], record["name"], payload, revision,
                    created_at, updated_at, retired_at, id_value,
                ),
            )
            return
        connection.execute(
            "UPDATE relations SET type = ?, source_id = ?, target_id = ?, payload = ?, "
            "revision = ?, created_at = ?, updated_at = ?, retired_at = ? WHERE id = ?",
            (
                record["type"], record["from"], record["to"], payload, revision,
                created_at, updated_at, retired_at, id_value,
            ),
        )

    @staticmethod
    def _insert_action_log(
        connection: sqlite3.Connection,
        entry: dict[str, Any],
    ) -> None:
        required = ("id", "action_id", "actor", "channel", "created_at", "payload")
        missing = [key for key in required if key not in entry]
        if missing:
            raise ValueError(f"action audit 缺少字段: {', '.join(missing)}")
        connection.execute(
            "INSERT INTO action_log(id, action_id, actor, channel, created_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                entry["id"],
                entry["action_id"],
                entry["actor"],
                entry["channel"],
                entry["created_at"],
                UomSqliteGraphStore._encode_record(entry["payload"]),
            ),
        )
        changes = entry["payload"].get("changes", [])
        if not isinstance(changes, list):
            raise ValueError("action audit.payload.changes 必须是列表")
        for change_index, change in enumerate(changes):
            if not isinstance(change, dict):
                raise ValueError("action audit.payload.changes 项必须是对象")
            kind = str(change.get("kind") or "")
            record_id = str(change.get("id") or "")
            operation = str(change.get("operation") or "")
            if kind not in {"object", "relation"} or not record_id or not operation:
                raise ValueError("action audit change 缺少 kind/id/operation")
            before = change.get("before")
            after = change.get("after")
            connection.execute(
                "INSERT INTO action_changes("
                "action_log_id, change_index, kind, record_id, operation, before_payload, after_payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry["id"], change_index, kind, record_id, operation,
                    UomSqliteGraphStore._encode_record(before) if before is not None else None,
                    UomSqliteGraphStore._encode_record(after) if after is not None else None,
                ),
            )

    @staticmethod
    def _encode_record(record: dict[str, Any]) -> str:
        return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _without_lifecycle(record: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(record)
        result.pop("lifecycle", None)
        return result

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
        record = json.loads(row["payload"])
        record["lifecycle"] = {
            "revision": int(row["revision"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "retired_at": row["retired_at"],
        }
        return record

    @staticmethod
    def _merge_record(
        record: dict[str, Any],
        changes: dict[str, Any],
        kind: str,
    ) -> None:
        immutable = {"id", "type", "lifecycle"}
        if kind == "relation":
            immutable.update({"from", "to"})
        for key, value in changes.items():
            if key in immutable:
                raise ValueError(f"不允许修改稳定身份字段 {key}")
            if key == "properties" and isinstance(value, dict):
                record.setdefault("properties", {}).update(deepcopy(value))
            else:
                record[key] = deepcopy(value)

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

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

    @classmethod
    def _increment_revision(cls, connection: sqlite3.Connection) -> None:
        current = int(cls._metadata(connection, "data_revision") or "0")
        cls._set_metadata(connection, "data_revision", str(current + 1))

    def _assert_object_type(self, object_type: str) -> None:
        if object_type != self.object_type:
            raise ValueError(
                f"{self.object_type} adapter 不能访问对象类型 {object_type}"
            )

    def _where_clause(
        self,
        filters: dict[str, Any] | None,
        *,
        include_retired: bool = False,
    ) -> tuple[str, list[Any]]:
        clauses = [] if include_retired else ["retired_at IS NULL"]
        parameters: list[Any] = []
        for field, expected in (filters or {}).items():
            name, operator = field.rsplit("__", 1) if "__" in field else (field, "eq")
            if operator not in {"eq", "ne", "like", "gt", "gte", "lt", "lte", "in"}:
                raise ValueError(f"不支持的查询操作符: {operator}")
            expression = self._field_expression(name)
            if operator == "like":
                clauses.append(f"lower(CAST({expression} AS TEXT)) LIKE ?")
                parameters.append(f"%{str(expected).lower()}%")
            elif operator == "in":
                values = list(expected) if isinstance(expected, (list, tuple, set)) else [expected]
                if not values:
                    clauses.append("0")
                    continue
                placeholders = ", ".join("?" for _ in values)
                clauses.append(f"{expression} IN ({placeholders})")
                parameters.extend(values)
            elif operator == "eq":
                if expected is None:
                    clauses.append(f"{expression} IS NULL")
                else:
                    clauses.append(f"{expression} = ?")
                    parameters.append(expected)
            elif operator == "ne":
                if expected is None:
                    clauses.append(f"{expression} IS NOT NULL")
                else:
                    clauses.append(f"({expression} IS NULL OR {expression} <> ?)")
                    parameters.append(expected)
            else:
                comparator = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[operator]
                clauses.append(f"{expression} {comparator} ?")
                parameters.append(expected)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", parameters

    def _field_expression(self, field: str) -> str:
        """Map a query field to a column or a safe JSON path expression."""
        if not isinstance(field, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", field):
            raise ValueError(f"无效的查询字段: {field!r}")
        columns = {
            "id": "id",
            "type": "type",
            "name": "name" if self.kind == "object" else None,
            "from": "source_id" if self.kind == "relation" else None,
            "to": "target_id" if self.kind == "relation" else None,
            "source_id": "source_id" if self.kind == "relation" else None,
            "target_id": "target_id" if self.kind == "relation" else None,
            "revision": "revision",
            "created_at": "created_at",
            "updated_at": "updated_at",
            "retired_at": "retired_at",
        }
        column = columns.get(field)
        if column:
            return column
        path = "$." + field
        return f"json_extract(payload, '{path}')"

    def _order_clause(self, order_by: str | None) -> str:
        if not order_by:
            return " ORDER BY rowid"
        descending = order_by.startswith("-")
        field = order_by[1:] if descending else order_by
        direction = "DESC" if descending else "ASC"
        return f" ORDER BY {self._field_expression(field)} {direction}, rowid ASC"


class UomSqliteGraphSource:
    """Source-level OAG adapter for a pre-existing UOM SQLite property graph."""

    def __init__(
        self,
        ontology: Ontology,
        source_name: str,
        source: DataSourceDef,
        domain_dir: Path,
    ) -> None:
        config = deepcopy(source.config)
        database = config.get("database") or config.get("db_path") or config.get("path")
        if not database:
            raise ValueError(f"数据源 {source_name} 缺少 config.database")
        self._object_store = UomSqliteGraphStore("object", database, domain_dir)
        self._relation_store = UomSqliteGraphStore("relation", database, domain_dir)
        if self._object_store.database_path != self._relation_store.database_path:
            raise ValueError("UOM Object 和 Relation 必须绑定到同一个图数据库")
        self.location = self._object_store.database_path

    @classmethod
    def factory(cls, domain_dir: str | Path):
        base_dir = Path(domain_dir).resolve()

        def build(
            ontology: Ontology,
            source_name: str,
            source: DataSourceDef,
            **_: Any,
        ) -> "UomSqliteGraphSource":
            return cls(ontology, source_name, source, base_dir)

        return build

    def query_records(
        self,
        kind: str,
        type_name: str,
        binding: DataBindingDef,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        order_by: str | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        physical_type = self._physical_type(kind)
        selector_type = self._selector_type(binding, kind)
        rows = self._store(kind).query_records(
            physical_type,
            self._physical_filters(filters, selector_type),
            limit,
            self._physical_field(order_by),
            offset,
        )
        return [self._to_logical(row, type_name, kind) for row in rows]

    def count_records(
        self,
        kind: str,
        type_name: str,
        binding: DataBindingDef,
        filters: dict[str, Any] | None = None,
    ) -> int:
        selector_type = self._selector_type(binding, kind)
        return self._store(kind).count_records(
            self._physical_type(kind),
            self._physical_filters(filters, selector_type),
        )

    def query_record_by_id(
        self,
        kind: str,
        type_name: str,
        binding: DataBindingDef,
        id_value: Any,
    ) -> dict[str, Any] | None:
        selector_type = self._selector_type(binding, kind)
        row = self._store(kind).query_record_by_id(self._physical_type(kind), id_value)
        if row is None or row.get("type") != selector_type:
            return None
        return self._to_logical(row, type_name, kind)

    def query_relations(
        self,
        relation_type: str,
        binding: DataBindingDef,
        *,
        filters: dict[str, Any] | None = None,
        from_id: Any = None,
        to_id: Any = None,
        direction: str = "out",
        limit: int | None = None,
        order_by: str | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        selector_type = self._selector_type(binding, "relation")
        physical_filters = self._physical_filters(filters, selector_type)
        if direction == "both" and from_id is not None and to_id is None:
            outgoing = self._relation_store.query_records(
                "Relation", {**physical_filters, "from": from_id},
                order_by=self._physical_field(order_by),
            )
            incoming = self._relation_store.query_records(
                "Relation", {**physical_filters, "to": from_id},
                order_by=self._physical_field(order_by),
            )
            rows = list({row["id"]: row for row in [*outgoing, *incoming]}.values())
            start = max(0, int(offset or 0))
            end = None if limit is None else start + max(0, int(limit))
            return [self._to_logical(row, relation_type, "relation") for row in rows[start:end]]
        endpoint_filters = physical_filters
        if from_id is not None:
            endpoint_filters["to" if direction == "in" else "from"] = from_id
        if to_id is not None:
            endpoint_filters["to"] = to_id
        rows = self._relation_store.query_records(
            "Relation", endpoint_filters, limit, self._physical_field(order_by), offset,
        )
        return [
            self._to_logical(row, relation_type, "relation")
            for row in rows
        ]

    def search_records(
        self,
        kind: str,
        type_name: str,
        binding: DataBindingDef,
        keyword: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        selector_type = self._selector_type(binding, kind)
        rows = self._store(kind).search_records(
            keyword,
            [self._physical_type(kind)],
            limit,
            record_type=selector_type,
        )
        return [
            self._to_logical(row, type_name, kind)
            for row in rows if row.get("type") == selector_type
        ][:limit]

    def create_record(
        self, kind: str, type_name: str, binding: DataBindingDef, data: dict[str, Any],
    ) -> dict[str, Any]:
        return self._store(kind).create_record(
            self._physical_type(kind),
            self._to_physical(data, self._selector_type(binding, kind), kind),
        )

    def update_record(
        self, kind: str, type_name: str, binding: DataBindingDef,
        id_value: Any, data: dict[str, Any],
    ) -> dict[str, Any]:
        current = self._store(kind).query_record_by_id(self._physical_type(kind), id_value)
        if current is None or current.get("type") != self._selector_type(binding, kind):
            raise ValueError(f"未找到 {type_name}: {id_value}")
        return self._store(kind).update_record(
            self._physical_type(kind), id_value, self._logical_changes(data, kind),
        )

    def retire_record(
        self, kind: str, type_name: str, binding: DataBindingDef, id_value: Any,
    ) -> dict[str, Any]:
        current = self._store(kind).query_record_by_id(self._physical_type(kind), id_value)
        if current is None or current.get("type") != self._selector_type(binding, kind):
            raise ValueError(f"未找到 {type_name}: {id_value}")
        return self._store(kind).retire_record(self._physical_type(kind), id_value)

    def query_by_ids(
        self, kind: str, type_name: str, binding: DataBindingDef, ids,
        *, include_retired: bool = False,
    ) -> list[dict[str, Any]]:
        selector_type = self._selector_type(binding, kind)
        return [
            self._to_logical(row, type_name, kind)
            for row in self._store(kind).query_by_ids(ids, include_retired=include_retired)
            if row.get("type") == selector_type
        ]

    def query_adjacent(
        self, relation_type: str, binding: DataBindingDef, object_ids,
        *, include_retired: bool = False,
    ) -> list[dict[str, Any]]:
        selector_type = self._selector_type(binding, "relation")
        return [
            self._to_logical(row, relation_type, "relation")
            for row in self._relation_store.query_adjacent(object_ids, include_retired=include_retired)
            if row.get("type") == selector_type
        ]

    def type_counts(
        self, kind: str, type_name: str, binding: DataBindingDef,
    ) -> dict[str, int]:
        return {type_name: self.count_records(kind, type_name, binding)}

    def record_exists(
        self, kind: str, type_name: str, binding: DataBindingDef, record_id: str,
    ) -> bool:
        row = self._store(kind).query_record_by_id(self._physical_type(kind), record_id)
        return bool(row and row.get("type") == self._selector_type(binding, kind))

    def get_record_version(
        self, kind: str, type_name: str, binding: DataBindingDef, record_id: str,
    ) -> dict[str, Any] | None:
        if not self.record_exists(kind, type_name, binding, record_id):
            return None
        return self._store(kind).get_record_version(kind, record_id)

    def apply_changeset(
        self,
        operations: list[dict[str, Any]],
        *,
        object_binding: DataBindingDef,
        relation_binding: DataBindingDef,
        **kwargs: Any,
    ) -> None:
        self._assert_binding("object", object_binding)
        self._assert_binding("relation", relation_binding)
        self._object_store.apply_changeset(operations, **kwargs)

    def replace_graph(self, objects, relations, **kwargs: Any) -> None:
        self._object_store.replace_graph(objects, relations, **kwargs)

    def list_action_log(self, limit: int = 100):
        return self._object_store.list_action_log(limit)

    def list_record_history(self, kind: str, record_id: str, limit: int = 100):
        return self._object_store.list_record_history(kind, record_id, limit)

    def close(self) -> None:
        self._object_store.close()
        self._relation_store.close()

    def _store(self, kind: str) -> UomSqliteGraphStore:
        if kind == "object":
            return self._object_store
        if kind == "relation":
            return self._relation_store
        raise ValueError("kind 必须是 object 或 relation")

    @staticmethod
    def _assert_binding(kind: str, binding: DataBindingDef) -> None:
        selected_kind = str(binding.selector.get("kind") or kind)
        if selected_kind != kind:
            raise ValueError(f"binding selector.kind 应为 {kind}")

    def _selector_type(self, binding: DataBindingDef, expected_kind: str) -> str:
        self._assert_binding(expected_kind, binding)
        value = binding.selector.get("type")
        if not isinstance(value, str) or not value:
            raise ValueError("UOM semantic binding requires selector.type")
        return value

    @staticmethod
    def _physical_type(kind: str) -> str:
        return "Object" if kind == "object" else "Relation"

    @staticmethod
    def _physical_field(field: str | None) -> str | None:
        if not field:
            return field
        prefix = "-" if field.startswith("-") else ""
        name = field[1:] if prefix else field
        if name in {"id", "name", "from", "to", "revision", "created_at", "updated_at"}:
            return field
        return prefix + "properties." + name

    @classmethod
    def _physical_filters(
        cls, filters: dict[str, Any] | None, selector_type: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"type": selector_type}
        for field, value in (filters or {}).items():
            name, suffix = field.rsplit("__", 1) if "__" in field else (field, "")
            physical = name if name in {"id", "name", "from", "to"} else f"properties.{name}"
            result[physical + (f"__{suffix}" if suffix else "")] = value
        return result

    @staticmethod
    def _to_logical(record: dict[str, Any], type_name: str, kind: str) -> dict[str, Any]:
        base_keys = ("id", "name") if kind == "object" else ("id", "from", "to")
        result = {key: deepcopy(record.get(key)) for key in base_keys}
        result.update(deepcopy(record.get("properties") or {}))
        result["_object_type"] = type_name
        for key in ("_matched_field",):
            if key in record:
                result[key] = record[key]
        return result

    @staticmethod
    def _to_physical(data: dict[str, Any], selector_type: str, kind: str) -> dict[str, Any]:
        base_keys = {"id", "name"} if kind == "object" else {"id", "from", "to"}
        record = {key: deepcopy(value) for key, value in data.items() if key in base_keys}
        record["type"] = selector_type
        record["properties"] = {
            key: deepcopy(value) for key, value in data.items()
            if key not in base_keys and not key.startswith("_")
        }
        return record

    @staticmethod
    def _logical_changes(data: dict[str, Any], kind: str) -> dict[str, Any]:
        base_keys = {"name"} if kind == "object" else set()
        changes = {key: deepcopy(value) for key, value in data.items() if key in base_keys}
        properties = {
            key: deepcopy(value) for key, value in data.items()
            if key not in base_keys and key not in {"id", "from", "to"} and not key.startswith("_")
        }
        if properties:
            changes["properties"] = properties
        return changes


class UomGraphAccess:
    """Internal raw graph access used by UOM ChangeSets and domain services."""

    def __init__(self, domain_dir: str | Path, database: str | Path) -> None:
        base = Path(domain_dir).resolve()
        self._objects = UomSqliteGraphStore("object", database, base)
        self._relations = UomSqliteGraphStore("relation", database, base)
        self.database_path = self._objects.database_path

    def query_objects(self, object_type: str = "Object", filters=None, limit=None,
                      order_by=None, offset=None):
        return self._objects.query_records(object_type, filters, limit, order_by, offset)

    def query_relations(self, relation_type: str = "Relation", filters=None, *,
                        from_id=None, to_id=None, direction="out", limit=None,
                        order_by=None, offset=None):
        endpoint_filters = dict(filters or {})
        if direction == "both" and from_id is not None and to_id is None:
            outgoing = self._relations.query_records(
                relation_type, {**endpoint_filters, "from": from_id}, order_by=order_by,
            )
            incoming = self._relations.query_records(
                relation_type, {**endpoint_filters, "to": from_id}, order_by=order_by,
            )
            rows = list({row["id"]: row for row in [*outgoing, *incoming]}.values())
            start = max(0, int(offset or 0))
            end = None if limit is None else start + max(0, int(limit))
            return rows[start:end]
        if from_id is not None:
            endpoint_filters["to" if direction == "in" else "from"] = from_id
        if to_id is not None:
            endpoint_filters["to"] = to_id
        return self._relations.query_records(
            relation_type, endpoint_filters, limit, order_by, offset,
        )

    def count_objects(self, object_type: str = "Object", filters=None) -> int:
        return self._objects.count_records(object_type, filters)

    def count_relations(self, relation_type: str = "Relation", filters=None) -> int:
        return self._relations.count_records(relation_type, filters)

    def get_object(self, object_type: str, record_id: Any):
        return self._objects.query_record_by_id(object_type, record_id)

    def get_relation(self, relation_type: str, record_id: Any):
        return self._relations.query_record_by_id(relation_type, record_id)

    def create_object(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._objects.create_record("Object", record)

    def update_object(self, record_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        return self._objects.update_record("Object", record_id, changes)

    def retire_object(self, record_id: str) -> dict[str, Any]:
        return self._objects.retire_record("Object", record_id)

    def create_relation(self, record: dict[str, Any]) -> dict[str, Any]:
        return self._relations.create_record("Relation", record)

    def update_relation(self, record_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        return self._relations.update_record("Relation", record_id, changes)

    def retire_relation(self, record_id: str) -> dict[str, Any]:
        return self._relations.retire_record("Relation", record_id)

    def query_by_ids(self, kind: str, type_name: str, ids, *, include_retired=False):
        return self._store(kind).query_by_ids(ids, include_retired=include_retired)

    def query_adjacent(self, relation_type: str, object_ids, *, include_retired=False):
        return self._relations.query_adjacent(object_ids, include_retired=include_retired)

    def type_counts(self, kind: str, type_name: str) -> dict[str, int]:
        return self._store(kind).type_counts()

    def record_exists(self, kind: str, type_name: str, record_id: str) -> bool:
        return self._store(kind).record_exists(kind, record_id)

    def get_record_version(self, kind: str, type_name: str, record_id: str):
        return self._store(kind).get_record_version(kind, record_id)

    def apply_changeset(self, operations, **kwargs) -> None:
        self._objects.apply_changeset(operations, **kwargs)

    def replace_graph(self, objects, relations, **kwargs) -> None:
        self._objects.replace_graph(objects, relations, **kwargs)

    def source_location(self, kind: str = "object", type_name: str = "Object") -> Path:
        return self.database_path

    def list_action_log(self, limit: int = 100):
        return self._objects.list_action_log(limit)

    def list_record_history(self, kind: str, record_id: str, limit: int = 100):
        return self._objects.list_record_history(kind, record_id, limit)

    def _store(self, kind: str) -> UomSqliteGraphStore:
        if kind == "object":
            return self._objects
        if kind == "relation":
            return self._relations
        raise ValueError("kind 必须是 object 或 relation")
