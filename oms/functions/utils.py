from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from oag.ontology.repository import ObjectRepository

from .adapter import OmsCsvFileAdapter


def _load_benchmark_rows(store: ObjectRepository, object_type: str) -> list[dict]:
    adapter = store.adapter_for(object_type)
    if not isinstance(adapter, OmsCsvFileAdapter):
        return []
    path = (
        adapter.domain_dir
        / "data"
        / "benchmarks"
        / f"{adapter.ontology.table_name(object_type)}_expected.csv"
    )
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [adapter.coerce_row(row) for row in csv.DictReader(f)]


def _select_effective(rows: list[dict], as_of_date: str) -> dict | None:
    candidates = [
        row for row in rows
        if _date_lte(row.get("effective_date", ""), as_of_date)
        and _date_gte(row.get("expiry_date", ""), as_of_date)
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: row.get("effective_date", ""), reverse=True)[0]


def _rule_ids(*rule_ids: str) -> str:
    return ",".join(rule_id for rule_id in rule_ids if rule_id)


def _merge_rule_ids(existing: str, *rule_ids: str) -> str:
    merged = []
    for rule_id in (existing or "").split(","):
        if rule_id and rule_id not in merged:
            merged.append(rule_id)
    for rule_id in rule_ids:
        if rule_id and rule_id not in merged:
            merged.append(rule_id)
    return ",".join(merged)


def _trace(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _merge_trace(existing: str, **sections: dict) -> str:
    base = {}
    if existing:
        try:
            loaded = json.loads(existing)
            if isinstance(loaded, dict):
                base = loaded
        except json.JSONDecodeError:
            base = {"previous_trace": existing}
    base.update({key: value for key, value in sections.items() if value})
    return _trace(base)


def _record_diff(
    generated: dict,
    existing: dict | None,
    fields: list[str],
    object_type: str,
) -> dict:
    if not existing:
        return {
            "object_type": object_type,
            "record_id": _first_id(generated),
            "fields": {"_missing_existing": {"generated": "present", "existing": ""}},
        }
    changed = {}
    for field in fields:
        left = generated.get(field, "")
        right = existing.get(field, "")
        if isinstance(left, float) or isinstance(right, float) or isinstance(left, int):
            if round(_as_number(left), 2) != round(_as_number(right), 2):
                changed[field] = {"generated": left, "existing": right}
        elif left != right:
            changed[field] = {"generated": left, "existing": right}
    if not changed:
        return {}
    return {
        "object_type": object_type,
        "record_id": _first_id(generated),
        "fields": changed,
    }


def _first_id(row: dict) -> str:
    for key in ("contribution_id", "housing_fund_id", "deduction_id"):
        if row.get(key):
            return row[key]
    return ""


def _line_diff(
    generated: dict,
    existing: dict,
    include_final_pay: bool = False,
) -> dict:
    fields = [
        "basic_salary",
        "performance_salary_base",
        "performance_grade",
        "performance_salary",
        "attendance_adjustment",
        "other_adjustment",
        "gross_pay_before_deduction",
    ]
    if include_final_pay:
        fields.extend([
            "personal_social_security",
            "personal_housing_fund",
            "personal_income_tax",
            "net_pay",
        ])
    changed = {}
    for field in fields:
        left = generated.get(field, "")
        right = existing.get(field, "")
        if isinstance(left, float) or isinstance(right, float):
            if round(_as_number(left), 2) != round(_as_number(right), 2):
                changed[field] = {"generated": left, "existing": right}
        elif left != right:
            changed[field] = {"generated": left, "existing": right}
    if not changed:
        return {}
    return {
        "employee_id": generated.get("employee_id", ""),
        "employee_snapshot_id": generated.get("employee_snapshot_id", ""),
        "fields": changed,
    }


def _effective_rules(rows: list[dict], period: str) -> list[dict]:
    effective = [
        row for row in rows
        if not row.get("effective_period") or row.get("effective_period") <= period
    ]
    return sorted(effective, key=lambda row: row.get("effective_period", ""))


def _select_period_rule(rows: list[dict], period: str) -> dict | None:
    candidates = [
        row for row in rows
        if not row.get("effective_period") or row.get("effective_period") <= period
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: row.get("effective_period", ""), reverse=True)[0]


def _as_number(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _date_lte(left: str, right: str) -> bool:
    if not left:
        return True
    if not right:
        return True
    return left <= right


def _date_gte(left: str, right: str) -> bool:
    if not left:
        return True
    if not right:
        return True
    return left >= right
