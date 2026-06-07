from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from oag.ontology.schema import ObjectSourceDef, Ontology


class OmsCsvFileAdapter:
    """Read-only CSV adapter for OMS ontology objects."""

    def __init__(
        self,
        ontology: Ontology,
        object_type: str,
        source: ObjectSourceDef,
        domain_dir: Path,
    ):
        self.ontology = ontology
        self.object_type = object_type
        self.source = source
        self.domain_dir = domain_dir
        self.id_field = source.id_field or ontology.get_id_column(object_type)

    @classmethod
    def factory(cls, domain_dir: str | Path):
        base_dir = Path(domain_dir).resolve()

        def build(ontology: Ontology, object_type: str, source, **kwargs):
            return cls(ontology, object_type, source, base_dir)

        return build

    def query(
        self,
        object_type: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        order_by: str | None = None,
        offset: int | None = None,
    ) -> list[dict]:
        rows = _apply_filters(self._load_rows(), filters)
        rows = _apply_order(rows, order_by)
        return _apply_window(rows, limit, offset)

    def count(self, object_type: str, filters: dict[str, Any] | None = None) -> int:
        return len(self.query(object_type, filters))

    def query_by_id(self, object_type: str, id_value: Any) -> dict | None:
        if not self.id_field:
            return None
        rows = self.query(object_type, {self.id_field: str(id_value)}, limit=1)
        return rows[0] if rows else None

    def search_text(
        self,
        keyword: str,
        object_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        if not keyword:
            return []
        obj_def = self.ontology.objects.get(self.object_type)
        text_cols = [
            name for name, prop in (obj_def.properties if obj_def else {}).items()
            if prop.type == "str"
        ]
        results = []
        for row in self._load_rows():
            matched = [
                col for col in text_cols
                if row.get(col) and keyword in str(row[col])
            ]
            if matched:
                record = dict(row)
                record["_object_type"] = self.object_type
                record["_matched_field"] = ", ".join(matched)
                results.append(record)
            if len(results) >= limit:
                break
        return results

    def insert_record(self, object_type: str, data: dict) -> dict:
        raise ValueError(f"{object_type} 是只读 OMS CSV 文件对象")

    def update_record(self, object_type: str, id_value: Any, data: dict) -> dict:
        raise ValueError(f"{object_type} 是只读 OMS CSV 文件对象")

    def delete_record(self, object_type: str, id_value: Any) -> dict:
        raise ValueError(f"{object_type} 是只读 OMS CSV 文件对象")

    def table_count(self, object_type: str) -> int:
        return self.count(object_type)

    def _load_rows(self) -> list[dict]:
        path = self._path()
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8-sig") as f:
            return [self._coerce(row) for row in csv.DictReader(f)]

    def _path(self) -> Path:
        raw = self.source.config.get("path") or self.source.config.get("file")
        if raw:
            path = Path(raw)
        else:
            path = Path("data") / f"{self.ontology.table_name(self.object_type)}.csv"
        if path.is_absolute():
            return path
        return self.domain_dir / path

    def coerce_row(self, row: dict[str, str]) -> dict:
        return self._coerce(row)

    def _coerce(self, row: dict[str, str]) -> dict:
        obj_def = self.ontology.objects.get(self.object_type)
        if not obj_def:
            return dict(row)
        result = {}
        for key, prop in obj_def.properties.items():
            value = row.get(key, "")
            if value == "":
                result[key] = ""
            elif prop.type == "int":
                result[key] = int(float(value))
            elif prop.type == "float":
                result[key] = float(value)
            else:
                result[key] = value
        return result


def _apply_filters(rows: list[dict], filters: dict[str, Any] | None) -> list[dict]:
    result = list(rows)
    for key, value in (filters or {}).items():
        field, op = key.split("__", 1) if "__" in key else (key, "eq")
        if op == "gt":
            result = [row for row in result if row.get(field) > value]
        elif op == "gte":
            result = [row for row in result if row.get(field) >= value]
        elif op == "lt":
            result = [row for row in result if row.get(field) < value]
        elif op == "lte":
            result = [row for row in result if row.get(field) <= value]
        elif op == "ne":
            result = [row for row in result if row.get(field) != value]
        elif op == "like":
            result = [row for row in result if str(value) in str(row.get(field, ""))]
        else:
            result = [row for row in result if row.get(field) == value]
    return result


def _apply_order(rows: list[dict], order_by: str | None) -> list[dict]:
    if not order_by:
        return rows
    reverse = order_by.startswith("-")
    field = order_by.lstrip("-")
    return sorted(rows, key=lambda row: row.get(field), reverse=reverse)


def _apply_window(
    rows: list[dict],
    limit: int | None,
    offset: int | None,
) -> list[dict]:
    if offset:
        rows = rows[offset:]
    if limit:
        rows = rows[:limit]
    return rows
