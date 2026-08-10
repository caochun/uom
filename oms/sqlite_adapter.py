"""SQLite data-source adapter for OMS ontology objects."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterator

from oag.ontology.schema import ObjectSourceDef, Ontology


_DATABASE_SCHEMA_VERSION = "2"
_DATABASE_LOCK = threading.RLock()


class OmsSqliteAdapter:
    """Expose the OMS Object/Relation graph through the OAG adapter contract."""

    def __init__(
        self,
        ontology: Ontology,
        object_type: str,
        source: ObjectSourceDef,
        domain_dir: Path,
    ) -> None:
        self.ontology = ontology
        self.object_type = object_type
        self.source = source
        self.domain_dir = domain_dir
        self.kind = str(source.config.get("kind") or "").lower()
        expected_kind = {"Object": "object", "Relation": "relation"}.get(object_type)
        if self.kind not in {"object", "relation"} or self.kind != expected_kind:
            raise ValueError(f"{object_type} 的 oms_sqlite source.config.kind 无效")
        self.table = "objects" if self.kind == "object" else "relations"
        self.id_field = source.id_field or ontology.get_id_column(object_type)
        self.database_path = self._database_path()
        self._ensure_database()

    @classmethod
    def factory(cls, domain_dir: str | Path):
        base_dir = Path(domain_dir).resolve()

        def build(
            ontology: Ontology,
            object_type: str,
            source: ObjectSourceDef,
            **_: Any,
        ) -> "OmsSqliteAdapter":
            return cls(ontology, object_type, source, base_dir)

        return build

    def query(
        self,
        object_type: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        order_by: str | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        self._assert_object_type(object_type)
        with _DATABASE_LOCK, self._connect() as connection:
            rows = self._read_records(connection, self.table)
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
        if offset is not None:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return rows

    def count(
        self,
        object_type: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        return len(self.query(object_type, filters=filters))

    def query_by_id(self, object_type: str, id_value: Any) -> dict[str, Any] | None:
        self._assert_object_type(object_type)
        with _DATABASE_LOCK, self._connect() as connection:
            row = connection.execute(
                f"SELECT payload FROM {self.table} WHERE id = ?",
                (id_value,),
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def search_text(
        self,
        keyword: str,
        object_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not keyword or (object_types and self.object_type not in object_types):
            return []
        needle = keyword.lower()
        results = []
        for row in self.query(self.object_type):
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

    def insert_record(self, object_type: str, data: dict[str, Any]) -> dict[str, Any]:
        self._assert_object_type(object_type)
        record = deepcopy(data)
        with _DATABASE_LOCK, self._connect() as connection:
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
        with _DATABASE_LOCK, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"SELECT payload FROM {self.table} WHERE id = ?",
                (id_value,),
            ).fetchone()
            if not row:
                connection.rollback()
                return {"updated": 0}
            record = json.loads(row["payload"])
            self._merge_record(record, data)
            self._update_record(connection, self.kind, id_value, record)
            self._increment_revision(connection)
            connection.commit()
        return {"updated": 1}

    def delete_record(self, object_type: str, id_value: Any) -> dict[str, Any]:
        self._assert_object_type(object_type)
        with _DATABASE_LOCK, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                f"DELETE FROM {self.table} WHERE id = ?",
                (id_value,),
            )
            if cursor.rowcount:
                self._increment_revision(connection)
            connection.commit()
        return {"deleted": cursor.rowcount}

    def table_count(self, object_type: str) -> int:
        self._assert_object_type(object_type)
        with _DATABASE_LOCK, self._connect() as connection:
            return int(connection.execute(f"SELECT COUNT(*) FROM {self.table}").fetchone()[0])

    def replace_graph(
        self,
        objects: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        before_commit: Callable[[], None] | None = None,
        audit_entry: dict[str, Any] | None = None,
    ) -> None:
        """Replace a validated graph in one SQLite transaction."""
        with _DATABASE_LOCK, self._connect() as connection:
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

    def _database_path(self) -> Path:
        raw = (
            self.source.config.get("database")
            or self.source.config.get("db_path")
            or self.source.config.get("path")
        )
        if not raw:
            raise ValueError(f"{self.object_type} 的 oms_sqlite source 需要 config.database")
        path = Path(str(raw))
        return path.resolve() if path.is_absolute() else (self.domain_dir / path).resolve()

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
        with _DATABASE_LOCK, self._connect() as connection:
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

                CREATE TABLE IF NOT EXISTS action_log (
                    id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL CHECK (json_valid(payload))
                );

                CREATE INDEX IF NOT EXISTS idx_objects_type ON objects(type);
                CREATE INDEX IF NOT EXISTS idx_objects_name ON objects(name);
                CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(type);
                CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
                CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
                CREATE INDEX IF NOT EXISTS idx_action_log_created_at ON action_log(created_at);
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            schema_version = self._metadata(connection, "schema_version")
            if schema_version and schema_version not in {"1", _DATABASE_SCHEMA_VERSION}:
                raise ValueError(
                    f"unsupported OMS database schema {schema_version}; "
                    f"expected {_DATABASE_SCHEMA_VERSION}"
                )
            self._set_metadata(connection, "schema_version", _DATABASE_SCHEMA_VERSION)
            if self._metadata(connection, "data_revision") is None:
                self._set_metadata(connection, "data_revision", "0")
            connection.commit()

    def list_action_log(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        with _DATABASE_LOCK, self._connect() as connection:
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

    @staticmethod
    def _read_records(
        connection: sqlite3.Connection,
        table: str,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(f"SELECT payload FROM {table} ORDER BY rowid").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    @staticmethod
    def _insert_record(
        connection: sqlite3.Connection,
        kind: str,
        record: dict[str, Any],
    ) -> None:
        payload = OmsSqliteAdapter._encode_record(record)
        if kind == "object":
            connection.execute(
                "INSERT INTO objects(id, type, name, payload) VALUES (?, ?, ?, ?)",
                (record["id"], record["type"], record["name"], payload),
            )
            return
        connection.execute(
            "INSERT INTO relations(id, type, source_id, target_id, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (record["id"], record["type"], record["from"], record["to"], payload),
        )

    @staticmethod
    def _update_record(
        connection: sqlite3.Connection,
        kind: str,
        id_value: Any,
        record: dict[str, Any],
    ) -> None:
        payload = OmsSqliteAdapter._encode_record(record)
        if kind == "object":
            connection.execute(
                "UPDATE objects SET type = ?, name = ?, payload = ? WHERE id = ?",
                (record["type"], record["name"], payload, id_value),
            )
            return
        connection.execute(
            "UPDATE relations SET type = ?, source_id = ?, target_id = ?, payload = ? "
            "WHERE id = ?",
            (record["type"], record["from"], record["to"], payload, id_value),
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
                OmsSqliteAdapter._encode_record(entry["payload"]),
            ),
        )

    @staticmethod
    def _encode_record(record: dict[str, Any]) -> str:
        return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _merge_record(record: dict[str, Any], changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "id":
                raise ValueError("不允许修改稳定 ID")
            if key == "properties" and isinstance(value, dict):
                record.setdefault("properties", {}).update(deepcopy(value))
            else:
                record[key] = deepcopy(value)

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

    @staticmethod
    def _matches(actual: Any, expected: Any, operator: str) -> bool:
        if operator == "like":
            return str(expected).lower() in str(actual or "").lower()
        if operator == "ne":
            return actual != expected
        comparators = {
            "gt": lambda left, right: left > right,
            "gte": lambda left, right: left >= right,
            "lt": lambda left, right: left < right,
            "lte": lambda left, right: left <= right,
        }
        if operator in comparators:
            try:
                return bool(comparators[operator](actual, expected))
            except TypeError:
                return False
        return actual == expected
