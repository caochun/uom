from __future__ import annotations

import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
OAG_PATH = ROOT / "oag-agent"
if str(OAG_PATH) not in sys.path:
    sys.path.insert(0, str(OAG_PATH))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from openai import OpenAI  # noqa: E402
except ModuleNotFoundError:  # noqa: E402
    OpenAI = None

from oag.ontology.loader import load_domain  # noqa: E402


DOMAIN_DIR = ROOT / "oms"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_CONTEXT = {"type": "PayrollRun", "id": "PAYROLL_202604"}
DEFAULT_EMPLOYEE = "EMP074"
DEFAULT_COMPANY = "COMP_SCNY"

RESOURCE_GROUPS = [
    ("人员资源", ["Person", "Employee", "EmploymentRelationship", "SalaryProfile"]),
    ("组织主体", ["Company", "InternalAffiliation"]),
    ("薪资结算", ["PayrollRun", "PayrollInputSnapshot", "PayrollEmployeeSnapshot", "PayrollLine", "PayrollItem"]),
    ("社保公积金", ["SocialInsuranceContribution", "HousingFundContribution", "ContributionDeduction"]),
    ("税务与成本", ["TaxLedger", "CostEntry", "ConsultantEngagement", "ConsultantFeeSettlement"]),
    ("治理输出", ["PayrollValidationResult", "ApprovalRecord", "PayrollExport", "Payslip"]),
    ("规则配置", ["SalarySplitRule", "PerformanceGradeRule", "SocialInsuranceRule", "HousingFundRule", "TaxRateRule"]),
]

DISPLAY_OVERRIDES = {
    "Person": "自然人",
    "Employee": "员工身份",
    "EmploymentRelationship": "任职关系",
    "Company": "公司主体",
    "InternalAffiliation": "内部归属",
    "SalaryProfile": "薪资档案版本",
    "PayrollRun": "薪资批次",
    "PayrollInputSnapshot": "薪资输入快照",
    "PayrollEmployeeSnapshot": "员工薪资快照",
    "PayrollLine": "工资明细",
    "PayrollItem": "工资项明细",
    "AttendanceSummary": "考勤汇总",
    "PerformanceRecord": "绩效记录",
    "PayrollAdjustment": "薪资补扣调整",
    "SocialInsuranceContribution": "社保缴费记录",
    "HousingFundContribution": "公积金缴费记录",
    "ContributionDeduction": "社保公积金扣款台账",
    "TaxLedger": "个税台账",
    "ConsultantEngagement": "顾问服务关系",
    "ConsultantFeeSettlement": "顾问劳务费结算",
    "Payslip": "工资条",
    "CostEntry": "成本归集明细",
    "PayrollValidationResult": "薪资校验结果",
    "ApprovalRecord": "审批记录",
    "PayrollExport": "薪资导出归档",
    "SalarySplitRule": "薪资拆分规则",
    "PerformanceGradeRule": "绩效等级规则",
    "SocialInsuranceRule": "社保规则",
    "HousingFundRule": "公积金规则",
    "TaxRateRule": "个税税率规则",
}

STATUS_LABELS = {
    "draft": "草稿",
    "calculating": "计算中",
    "validated": "已校验",
    "submitted": "已提交",
    "locked": "已锁定",
    "paid": "已发放",
    "archived": "已归档",
    "cancelled": "已取消",
    "built": "已构建",
    "used": "已使用",
    "void": "已作废",
    "deducted": "已扣除",
    "pending": "待处理",
    "active": "有效",
    "有效": "有效",
    "在职": "在职",
    "离职": "离职",
}

CAPABILITY_ORDER = [
    "resolve_employee_state_at",
    "resolve_rules_at",
    "build_payroll_snapshot",
    "generate_payroll_lines",
    "calculate_contributions",
    "calculate_payroll",
    "validate_payroll",
    "submit_payroll_for_approval",
    "approve_payroll",
    "export_payroll_outputs",
]

EXECUTABLE_FUNCTIONS = {
    "resolve_employee_state_at",
    "resolve_rules_at",
    "build_payroll_snapshot",
    "generate_payroll_lines",
    "calculate_contributions",
    "calculate_payroll",
}

PREVIEW_ONLY = {
    "build_payroll_snapshot",
    "generate_payroll_lines",
    "calculate_contributions",
    "calculate_payroll",
    "resolve_employee_state_at",
    "resolve_rules_at",
}

PAYROLL_SIGNAL_TYPES = {
    "PayrollRun",
    "PayrollLine",
    "PayrollItem",
    "PayrollEmployeeSnapshot",
    "ContributionDeduction",
    "SocialInsuranceContribution",
    "HousingFundContribution",
    "TaxLedger",
    "Payslip",
    "CostEntry",
    "PayrollValidationResult",
    "ApprovalRecord",
    "PayrollExport",
}


class OmsRuntime:
    def __init__(self):
        self.ontology, self.repository, self.registry = load_domain(DOMAIN_DIR)
        self._llm_client = None
        self._llm_checked = False
        self._llm_cache: dict[str, dict] = {}
        self._llm_executor = ThreadPoolExecutor(max_workers=2)
        self._llm_tasks: dict[str, dict] = {}

    def shell(self, object_type: str = "", object_id: str = "") -> dict:
        object_type = object_type or DEFAULT_CONTEXT["type"]
        object_id = object_id or DEFAULT_CONTEXT["id"]
        return {
            "product": {
                "name": "Fox OMS",
                "title": "企业资源操作壳",
                "description": "任一企业资源都可以成为操作中心；本体决定它周围出现的关系、能力、约束、证据和对话入口。",
            },
            "atlas": self.resource_atlas(),
            "context": self.resource_context(object_type, object_id),
        }

    def resource_atlas(self) -> list[dict]:
        groups = []
        for group_name, object_types in RESOURCE_GROUPS:
            resources = []
            for object_type in object_types:
                if object_type not in self.ontology.objects:
                    continue
                resources.append({
                    "type": object_type,
                    "name": self.display_name(object_type),
                    "summary": self.object_summary(object_type),
                    "count": self.safe_count(object_type),
                    "source": self.source_label(object_type),
                    "sample_id": self.sample_id(object_type),
                })
            if resources:
                groups.append({"name": group_name, "resources": resources})
        return groups

    def resource_context(self, object_type: str, object_id: str = "") -> dict:
        if object_type not in self.ontology.objects:
            object_type = DEFAULT_CONTEXT["type"]
        object_id = object_id or self.sample_id(object_type)
        vocab = self.vocabulary(object_type)
        record = self.find_record(object_type, object_id)
        signals = self.runtime_signals(object_type, object_id, record)
        neighborhood = self.semantic_neighborhood(object_type, object_id, record)
        capabilities = self.capabilities_for(object_type, object_id, record, signals)
        work_surface = self.work_surface(object_type, object_id, record, signals)
        conversation = self.conversation_rail(object_type, object_id, record, signals, capabilities, neighborhood)
        return {
            "resource": vocab,
            "id": object_id,
            "title": self.resource_title(object_type, object_id, record),
            "subtitle": self.resource_subtitle(object_type, record),
            "record": self.present_record(object_type, record),
            "browser": self.resource_browser(object_type, object_id),
            "detail": self.resource_detail(object_type, object_id, record, neighborhood, capabilities),
            "metrics": self.context_metrics(object_type, object_id, record, signals, neighborhood, capabilities),
            "signals": signals,
            "neighborhood": neighborhood,
            "capabilities": capabilities,
            "work_surface": work_surface,
            "conversation": conversation,
            "sample_records": self.sample_records(object_type),
        }

    def execute(self, function_name: str, object_type: str, object_id: str = "", employee_id: str = "") -> dict:
        if function_name not in self.ontology.functions:
            return {"status": "error", "message": "未找到该本体能力。"}
        if function_name not in EXECUTABLE_FUNCTIONS:
            return {"status": "not_implemented", "message": "该能力在当前原型中只展示语义，不执行写入。"}
        params = self.params_for(function_name, object_type, object_id, employee_id)
        try:
            result = self.registry.call(function_name, **params)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}
        presented = self.present_result(function_name, result)
        presented["mode"] = "rules"
        task_id = self.schedule_result_llm(function_name, presented, result)
        if task_id:
            presented["llm_task"] = task_id
            presented["llm_status"] = "pending"
        return {
            "status": "success" if not result.get("error") else "error",
            "function": self.capability_vocabulary(function_name),
            "params": self.present_params(function_name, params),
            "result": presented,
            "raw": result,
            "conversation": self.result_conversation(function_name, result),
        }

    def display_name(self, object_type: str) -> str:
        obj = self.ontology.objects.get(object_type)
        return DISPLAY_OVERRIDES.get(object_type) or (obj.summary if obj and obj.summary else object_type)

    def object_summary(self, object_type: str) -> str:
        obj = self.ontology.objects.get(object_type)
        if not obj:
            return ""
        return obj.summary or self.display_name(object_type)

    def vocabulary(self, object_type: str) -> dict:
        obj = self.ontology.objects.get(object_type)
        id_field = self.ontology.get_id_column(object_type) or ""
        return {
            "type": object_type,
            "name": self.display_name(object_type),
            "summary": self.object_summary(object_type),
            "description": obj.description if obj else "",
            "id_field": id_field,
            "id_label": self.property_label(object_type, id_field) if id_field else "编号",
            "kind": self.kind_label(obj.kind if obj else ""),
            "source": self.source_label(object_type),
            "mutability": self.mutability_label(obj.mutability if obj else ""),
        }

    def capability_vocabulary(self, function_name: str) -> dict:
        fn = self.ontology.functions.get(function_name)
        return {
            "name": function_name,
            "label": fn.summary if fn else function_name,
            "group": fn.group if fn else "",
            "description": fn.description if fn else "",
            "reads": [self.display_name(item) for item in (fn.involves_objects or [])] if fn else [],
            "writes": [self.display_name(item) for item in (fn.writes_to or [])] if fn else [],
            "depends_on": [self.ontology.functions[item].summary for item in (fn.depends_on or []) if item in self.ontology.functions] if fn else [],
        }

    def property_label(self, object_type: str, field: str) -> str:
        obj = self.ontology.objects.get(object_type)
        prop = (obj.properties or {}).get(field) if obj else None
        if prop and prop.description:
            return prop.description.split("，")[0].split(":")[0]
        return field

    def kind_label(self, kind: str) -> str:
        return {
            "entity": "业务实体",
            "lookup_table": "基础资料",
            "rule_table": "规则表",
            "config": "配置",
        }.get(kind, kind or "资源")

    def source_label(self, object_type: str) -> str:
        obj = self.ontology.objects.get(object_type)
        source = obj.data_source if obj else ""
        return {
            "external_api": "外部系统",
            "human_confirmed": "人工确认",
            "agent_generated": "系统生成",
        }.get(source, source or "领域数据")

    def mutability_label(self, value: str) -> str:
        return {
            "read_only": "只读",
            "append_only": "追加不可改",
            "mutable": "可维护",
        }.get(value, value or "")

    def safe_count(self, object_type: str, filters: dict | None = None) -> int:
        try:
            return self.repository.count(object_type, filters)
        except Exception:
            return 0

    def sample_id(self, object_type: str) -> str:
        id_field = self.ontology.get_id_column(object_type)
        try:
            rows = self.repository.query(object_type, limit=1)
        except Exception:
            rows = []
        return str(rows[0].get(id_field, "")) if rows and id_field else ""

    def sample_records(self, object_type: str) -> list[dict]:
        id_field = self.ontology.get_id_column(object_type) or ""
        try:
            rows = self.repository.query(object_type, limit=8)
        except Exception:
            rows = []
        return [
            {
                "id": str(row.get(id_field, "")),
                "title": self.record_title(object_type, row),
                "description": self.record_description(object_type, row),
            }
            for row in rows
        ]

    def resource_browser(self, object_type: str, selected_id: str = "") -> dict:
        id_field = self.ontology.get_id_column(object_type) or ""
        columns = self.browser_columns(object_type)
        try:
            raw_rows = self.repository.query(object_type, limit=60)
        except Exception:
            raw_rows = []
        rows = []
        for row in raw_rows:
            row_id = str(row.get(id_field, ""))
            rows.append({
                "id": row_id,
                "selected": bool(selected_id and row_id == selected_id),
                "title": self.record_title(object_type, row),
                "description": self.record_description(object_type, row),
                "cells": [
                    {
                        "field": column["field"],
                        "label": column["label"],
                        "value": self.format_value(row.get(column["field"], "")),
                    }
                    for column in columns
                ],
            })
        return {
            "columns": columns,
            "rows": rows,
            "total": self.safe_count(object_type),
        }

    def browser_columns(self, object_type: str) -> list[dict]:
        obj = self.ontology.objects.get(object_type)
        if not obj:
            return []
        id_field = self.ontology.get_id_column(object_type) or ""
        preferred_by_type = {
            "Person": ["person_id", "name", "phone", "status"],
            "Employee": ["employee_id", "department", "position", "employment_type", "status"],
            "EmploymentRelationship": ["employment_relationship_id", "employee_id", "company_id", "relationship_type", "effective_date"],
            "Company": ["company_id", "company_name", "payroll_enabled", "tax_entity_name"],
            "SalaryProfile": ["salary_profile_id", "employee_id", "monthly_salary_base", "effective_date"],
            "PayrollRun": ["payroll_run_id", "payroll_period", "pay_date", "status"],
            "PayrollInputSnapshot": ["snapshot_id", "payroll_run_id", "payroll_period", "status"],
            "PayrollEmployeeSnapshot": ["employee_snapshot_id", "employee_id", "employee_name_snapshot", "payroll_company_name_snapshot"],
            "PayrollLine": ["payroll_line_id", "employee_id", "employee_name_snapshot", "gross_pay_before_deduction", "net_pay"],
            "PayrollItem": ["payroll_item_id", "employee_id", "item_name", "amount"],
            "ContributionDeduction": ["deduction_id", "employee_id", "deduction_type", "personal_amount", "status"],
            "TaxLedger": ["tax_ledger_id", "employee_id", "tax_period", "current_tax", "reconciliation_status"],
            "CostEntry": ["cost_entry_id", "payroll_run_id", "employee_id", "cost_type", "amount"],
            "PayrollValidationResult": ["validation_id", "payroll_run_id", "severity", "message", "status"],
        }
        fields = preferred_by_type.get(object_type, [])
        if id_field and id_field not in fields:
            fields.insert(0, id_field)
        if not fields:
            fields = [name for name in obj.properties.keys()][:5]
        columns = []
        for field in fields[:5]:
            if field in obj.properties:
                columns.append({"field": field, "label": self.property_label(object_type, field)})
        return columns

    def resource_detail(self, object_type: str, object_id: str, record: dict, neighborhood: dict, capabilities: list[dict]) -> dict:
        return {
            "facts": self.detail_fact_groups(object_type, record),
            "related": self.related_record_groups(object_type, record, neighborhood),
            "actions": self.inline_actions(capabilities),
        }

    def detail_fact_groups(self, object_type: str, record: dict) -> list[dict]:
        obj = self.ontology.objects.get(object_type)
        if not obj or not record:
            return []
        groups = [
            ("基本信息", []),
            ("业务状态", []),
            ("金额与期间", []),
            ("来源与追踪", []),
        ]
        for field, prop in obj.properties.items():
            value = record.get(field)
            if value in (None, ""):
                continue
            item = {"label": self.property_label(object_type, field), "value": self.format_value(value)}
            lower = field.lower()
            if any(token in lower for token in ["status", "type", "department", "position", "relationship"]):
                groups[1][1].append(item)
            elif any(token in lower for token in ["date", "period", "salary", "amount", "tax", "cost", "base", "pay"]):
                groups[2][1].append(item)
            elif any(token in lower for token in ["source", "trace", "rule", "note", "reason"]):
                groups[3][1].append(item)
            else:
                groups[0][1].append(item)
        return [
            {"title": title, "rows": rows[:8]}
            for title, rows in groups
            if rows
        ]

    def related_record_groups(self, object_type: str, record: dict, neighborhood: dict) -> list[dict]:
        groups = []
        for edge in neighborhood.get("edges", [])[:8]:
            target_type = edge.get("target_type", "")
            if not target_type or target_type not in self.ontology.objects:
                continue
            filters = None
            for link in self.ontology.links.values():
                if {link.source, link.target} == {object_type, target_type}:
                    filters = self.relation_filters(object_type, target_type, link, record)
                    break
            try:
                rows = self.repository.query(target_type, filters or None, limit=4)
            except Exception:
                rows = []
            groups.append({
                "title": self.display_name(target_type),
                "description": edge.get("name", ""),
                "type": target_type,
                "count": edge.get("count", 0),
                "rows": [
                    {
                        "id": row.get(self.ontology.get_id_column(target_type) or "", ""),
                        "title": self.record_title(target_type, row),
                        "description": self.record_description(target_type, row),
                    }
                    for row in rows
                ],
            })
        return groups

    def inline_actions(self, capabilities: list[dict]) -> list[dict]:
        actions = []
        for capability in capabilities:
            actions.append({
                "label": capability.get("label", ""),
                "function": capability.get("name", ""),
                "enabled": capability.get("enabled", False),
                "reason": capability.get("reason", ""),
                "group": capability.get("group", ""),
                "reads": capability.get("reads", [])[:4],
                "writes": capability.get("writes", [])[:4],
            })
        return actions[:6]

    def find_record(self, object_type: str, object_id: str) -> dict:
        if object_id:
            try:
                return self.repository.query_by_id(object_type, object_id) or {}
            except Exception:
                return {}
        rows = self.sample_records(object_type)
        if rows:
            return self.find_record(object_type, rows[0]["id"])
        return {}

    def resource_title(self, object_type: str, object_id: str, record: dict) -> str:
        name = self.display_name(object_type)
        title = self.record_title(object_type, record)
        if title and title != object_id:
            return f"{name} · {title}"
        return f"{name} · {object_id or '未选中'}"

    def resource_subtitle(self, object_type: str, record: dict) -> str:
        obj = self.ontology.objects.get(object_type)
        parts = [self.kind_label(obj.kind if obj else ""), self.source_label(object_type)]
        status = record.get("status") or record.get("reconciliation_status") or ""
        if status:
            parts.append(f"状态：{STATUS_LABELS.get(str(status), status)}")
        return " / ".join(part for part in parts if part)

    def record_title(self, object_type: str, row: dict) -> str:
        if not row:
            return ""
        preferred = [
            "name", "employee_name_snapshot", "company_name", "payroll_company_name_snapshot",
            "item_name", "rule_code", "message", "export_type", "settlement_period",
        ]
        id_field = self.ontology.get_id_column(object_type) or ""
        for field in preferred:
            if row.get(field):
                ident = row.get(id_field, "")
                return f"{row[field]}（{ident}）" if ident and str(row[field]) != str(ident) else str(row[field])
        return str(row.get(id_field, ""))

    def record_description(self, object_type: str, row: dict) -> str:
        if not row:
            return ""
        fields = [
            "department", "position", "employment_type", "payroll_period", "tax_period",
            "contribution_period", "company_name", "amount", "net_pay", "status",
        ]
        chunks = []
        for field in fields:
            value = row.get(field)
            if value not in (None, ""):
                chunks.append(f"{self.property_label(object_type, field)}：{self.format_value(value)}")
        return "；".join(chunks[:3])

    def present_record(self, object_type: str, record: dict) -> list[dict]:
        obj = self.ontology.objects.get(object_type)
        if not obj or not record:
            return []
        fields = []
        for name, prop in obj.properties.items():
            value = record.get(name)
            if value in (None, ""):
                continue
            fields.append({"label": self.property_label(object_type, name), "value": self.format_value(value)})
            if len(fields) >= 10:
                break
        return fields

    def format_value(self, value) -> str:
        if isinstance(value, float):
            return f"{value:,.2f}"
        return str(value)

    def semantic_neighborhood(self, object_type: str, object_id: str, record: dict) -> dict:
        nodes = [{
            "type": object_type,
            "name": self.display_name(object_type),
            "role": "当前资源",
            "count": 1 if record else self.safe_count(object_type),
            "sample_id": object_id,
        }]
        edges = []
        seen = {object_type}
        for link_name, link in self.ontology.links.items():
            if link.source != object_type and link.target != object_type:
                continue
            other = link.target if link.source == object_type else link.source
            if other not in self.ontology.objects:
                continue
            filters = self.relation_filters(object_type, other, link, record)
            count = self.safe_count(other, filters) if filters is not None else self.safe_count(other)
            if other not in seen:
                nodes.append({
                    "type": other,
                    "name": self.display_name(other),
                    "role": "相关资源",
                    "count": count,
                    "sample_id": self.first_related_id(other, filters),
                })
                seen.add(other)
            edges.append({
                "name": link.description or link_name,
                "from": self.display_name(link.source),
                "to": self.display_name(link.target),
                "target_type": other,
                "count": count,
                "cardinality": link.cardinality,
                "link_type": link.link_type,
            })
        return {"nodes": nodes[:12], "edges": edges[:16]}

    def relation_filters(self, current_type: str, other_type: str, link, record: dict) -> dict | None:
        if not record:
            return None
        source_key = link.join.get("source_key", "")
        target_key = link.join.get("target_key", "")
        if link.source == current_type and link.target == other_type and source_key and target_key:
            value = record.get(source_key)
            return {target_key: value} if value not in (None, "") else None
        if link.target == current_type and link.source == other_type and source_key and target_key:
            value = record.get(target_key)
            return {source_key: value} if value not in (None, "") else None
        return None

    def first_related_id(self, object_type: str, filters: dict | None) -> str:
        id_field = self.ontology.get_id_column(object_type) or ""
        try:
            rows = self.repository.query(object_type, filters or None, limit=1)
        except Exception:
            rows = []
        return str(rows[0].get(id_field, "")) if rows and id_field else ""

    def capabilities_for(self, object_type: str, object_id: str, record: dict, signals: dict) -> list[dict]:
        candidates = []
        for name, fn in self.ontology.functions.items():
            if object_type in (fn.involves_objects or []) or object_type in (fn.writes_to or []):
                candidates.append(name)
            elif object_type == "Employee" and "employee_id" in (fn.params or {}):
                candidates.append(name)
            elif object_type == "Company" and "company_id" in (fn.params or {}):
                candidates.append(name)
            elif object_type == "PayrollRun" and "payroll_run_id" in (fn.params or {}):
                candidates.append(name)
        candidates = sorted(set(candidates), key=lambda name: CAPABILITY_ORDER.index(name) if name in CAPABILITY_ORDER else 99)
        return [self.capability_state(name, object_type, object_id, record, signals) for name in candidates[:10]]

    def capability_state(self, function_name: str, object_type: str, object_id: str, record: dict, signals: dict) -> dict:
        fn = self.ontology.functions.get(function_name)
        enabled = function_name in EXECUTABLE_FUNCTIONS
        reason = "当前原型可执行预览。" if enabled else "当前原型展示该能力的语义，执行通道尚未接入。"
        if function_name not in PREVIEW_ONLY and fn and fn.writes_to:
            enabled = False
            reason = "该能力会形成正式写入或流程状态变化，原型中只展示不执行。"
        status_guard = self.status_guard(function_name, object_type, record)
        if status_guard:
            enabled = False
            reason = status_guard
        precondition = self.precondition_guard(function_name, object_type, record)
        if precondition:
            enabled = False
            reason = precondition
        return {
            "name": function_name,
            "label": fn.summary if fn else function_name,
            "group": fn.group if fn else "",
            "description": fn.description if fn else "",
            "reads": [self.display_name(item) for item in (fn.involves_objects or [])] if fn else [],
            "writes": [self.display_name(item) for item in (fn.writes_to or [])] if fn else [],
            "depends_on": [self.ontology.functions[item].summary for item in (fn.depends_on or []) if item in self.ontology.functions] if fn else [],
            "enabled": enabled,
            "reason": reason,
            "mode": "预览" if function_name in PREVIEW_ONLY else "流程",
            "evidence": self.capability_evidence(function_name, object_type, signals),
        }

    def status_guard(self, function_name: str, object_type: str, record: dict) -> str:
        obj = self.ontology.objects.get(object_type)
        status = record.get("status", "") if record else ""
        if not obj or not status:
            return ""
        for constraint in obj.constraints or []:
            if constraint.when.get("status") == status and function_name in constraint.excluded_functions:
                return constraint.reason
        return ""

    def precondition_guard(self, function_name: str, object_type: str, record: dict) -> str:
        fn = self.ontology.functions.get(function_name)
        if not fn:
            return ""
        for precondition in fn.preconditions or []:
            if precondition.object != object_type or precondition.field != "status":
                continue
            current = record.get("status", "") if record else ""
            if precondition.operator == "eq" and current != precondition.value:
                return f"需要状态为“{STATUS_LABELS.get(str(precondition.value), precondition.value)}”，当前为“{STATUS_LABELS.get(str(current), current or '未知')}”。"
        return ""

    def capability_evidence(self, function_name: str, object_type: str, signals: dict) -> list[str]:
        labels = [self.display_name(object_type)]
        if function_name == "calculate_payroll":
            labels.extend(["薪资输入快照", "薪资拆分规则", "绩效等级规则", "个税台账"])
        elif function_name == "calculate_contributions":
            labels.extend(["社保规则", "公积金规则", "扣款台账"])
        elif function_name == "resolve_employee_state_at":
            labels.extend(["自然人", "任职关系", "薪资档案版本"])
        elif function_name == "resolve_rules_at":
            labels.extend(["公司主体", "规则配置"])
        if signals.get("diff_count"):
            labels.append("差异校对")
        if signals.get("warning_count"):
            labels.append("风险提示")
        return labels[:6]

    def runtime_signals(self, object_type: str, object_id: str, record: dict) -> dict:
        signals = {"items": [], "severity": "normal", "scope": "resource"}
        payroll_run_id = self.resolve_payroll_run_id(object_type, object_id, record)
        if object_type in PAYROLL_SIGNAL_TYPES and payroll_run_id:
            calc = self.registry.call("calculate_payroll", payroll_run_id=payroll_run_id, include_result_set=True, include_warnings=True)
            lines = (calc.get("result_set") or {}).get("PayrollLine", [])
            totals = {
                "扣前应发": round(sum(_num(row.get("gross_pay_before_deduction")) for row in lines), 2),
                "个税": round(sum(_num(row.get("personal_income_tax")) for row in lines), 2),
                "实发": round(sum(_num(row.get("net_pay")) for row in lines), 2),
                "公司成本": round(sum(_num(row.get("company_total_cost")) for row in lines), 2),
            }
            signals.update({
                "scope": "payroll",
                "payroll_run_id": payroll_run_id,
                "calculated_count": calc.get("calculated_count", 0),
                "diff_count": calc.get("diff_count", 0),
                "warning_count": calc.get("warning_count", 0),
                "totals": totals,
                "sample_diffs": calc.get("sample_diffs", [])[:5],
                "sample_warnings": (calc.get("warnings") or calc.get("sample_warnings") or [])[:6],
            })
            if calc.get("diff_count") or calc.get("warning_count"):
                signals["severity"] = "attention"
                signals["items"].append(f"薪资试算发现 {calc.get('diff_count', 0)} 个差异、{calc.get('warning_count', 0)} 条提示。")
            else:
                signals["items"].append("薪资试算与当前校对基准未发现差异。")
        if object_type == "Employee" and object_id:
            employee_result = self.registry.call("calculate_payroll", payroll_run_id=payroll_run_id or DEFAULT_CONTEXT["id"], employee_id=object_id)
            summary = (employee_result.get("answer_summary") or [{}])[0]
            signals["employee_payroll"] = summary
            if summary:
                signals["items"].append(
                    f"该员工本月实发预览为 {_money(summary.get('net_pay'))}，扣前应发 {_money(summary.get('gross_pay_before_deduction'))}。"
                )
            if employee_result.get("warnings"):
                signals["severity"] = "attention"
                signals["employee_warning_count"] = len(employee_result.get("warnings") or [])
                signals["items"].append(f"该员工存在 {signals['employee_warning_count']} 条薪资相关提示，建议在薪资操作中查看。")
        if object_type == "Company" and object_id:
            employee_count = self.safe_count("EmploymentRelationship", {"company_id": object_id})
            social_rule_count = self.safe_count("SocialInsuranceRule", {"company_id": object_id})
            housing_rule_count = self.safe_count("HousingFundRule", {"company_id": object_id})
            signals["company"] = {
                "employee_relationships": employee_count,
                "social_rules": social_rule_count,
                "housing_rules": housing_rule_count,
            }
            if social_rule_count == 0 or housing_rule_count == 0:
                signals["severity"] = "attention"
                signals["items"].append("该公司主体存在社保或公积金规则缺失，涉及缴费计算时需要确认。")
        if not signals["items"]:
            status = record.get("status") or record.get("reconciliation_status") or ""
            if status:
                signals["items"].append(f"当前资源状态为“{STATUS_LABELS.get(str(status), status)}”。")
            else:
                signals["items"].append("当前资源可查看字段详情、相关资源和可用操作。")
        return signals

    def resolve_payroll_run_id(self, object_type: str, object_id: str, record: dict) -> str:
        if object_type == "PayrollRun":
            return object_id or record.get("payroll_run_id", "")
        for field in ("payroll_run_id", "deducted_payroll_run_id"):
            if record.get(field):
                return record.get(field)
        return DEFAULT_CONTEXT["id"] if object_type in PAYROLL_SIGNAL_TYPES or object_type == "Employee" else ""

    def context_metrics(self, object_type: str, object_id: str, record: dict, signals: dict, neighborhood: dict, capabilities: list[dict]) -> list[dict]:
        status = record.get("status") or record.get("reconciliation_status") or ""
        metrics = [
            {"label": "资源记录", "value": self.safe_count(object_type), "tone": "normal"},
            {"label": "相关资源", "value": max(len(neighborhood.get("nodes", [])) - 1, 0), "tone": "normal"},
            {"label": "可执行能力", "value": len([cap for cap in capabilities if cap.get("enabled")]), "tone": "good"},
        ]
        if signals.get("scope") == "payroll" and signals.get("diff_count") is not None:
            metrics.append({"label": "校对差异", "value": signals.get("diff_count", 0), "tone": "warn" if signals.get("diff_count") else "good"})
        if signals.get("scope") == "payroll" and signals.get("warning_count") is not None:
            metrics.append({"label": "运行提示", "value": signals.get("warning_count", 0), "tone": "warn" if signals.get("warning_count") else "good"})
        metrics.append({"label": "数据来源", "value": self.source_label(object_type), "tone": "normal"})
        if status:
            metrics.append({"label": "当前状态", "value": STATUS_LABELS.get(str(status), status), "tone": "normal"})
        return metrics[:5]

    def work_surface(self, object_type: str, object_id: str, record: dict, signals: dict) -> dict:
        sections = []
        if signals.get("totals"):
            sections.append({
                "title": "业务汇总",
                "kind": "metrics",
                "rows": [{"label": key, "value": _money(value)} for key, value in signals["totals"].items()],
            })
        if signals.get("sample_warnings"):
            sections.append({
                "title": "需要业务判断的提示",
                "kind": "list",
                "rows": [
                    {
                        "title": item.get("message", ""),
                        "meta": item.get("employee_id", ""),
                    }
                    for item in signals.get("sample_warnings", [])
                ],
            })
        if signals.get("sample_diffs"):
            sections.append({
                "title": "校对差异样本",
                "kind": "list",
                "rows": [
                    {
                        "title": self.diff_title(item),
                        "meta": item.get("record_id", item.get("employee_id", "")),
                    }
                    for item in signals.get("sample_diffs", [])
                ],
            })
        if record:
            sections.append({
                "title": "当前资源事实",
                "kind": "facts",
                "rows": self.present_record(object_type, record),
            })
        return {"sections": sections}

    def diff_title(self, diff: dict) -> str:
        field = diff.get("field", "字段")
        calculated = diff.get("calculated", "")
        expected = diff.get("expected", "")
        return f"{field}：当前 {calculated} / 基准 {expected}"

    def conversation_rail(self, object_type: str, object_id: str, record: dict, signals: dict, capabilities: list[dict], neighborhood: dict) -> dict:
        prompts = []
        actions = []
        if signals.get("scope") == "payroll" and signals.get("warning_count"):
            prompts.append({
                "label": "先解释这些运行提示",
                "intent": "explain_warnings",
                "text": "把当前提示按扣款、规则、个税输入分类，并说明先处理哪一类。",
            })
        if signals.get("scope") == "payroll" and signals.get("diff_count"):
            prompts.append({
                "label": "复核校对差异",
                "intent": "review_diffs",
                "text": "展示差异样本，并解释差异可能来自规则、输入还是基准口径。",
            })
        if object_type == "Employee":
            prompts.append({"label": "解释该员工本月工资", "intent": "explain_employee", "text": "沿员工身份、薪资快照、工资明细、扣款和个税台账解释本月实发。"})
        elif object_type == "Company":
            prompts.append({"label": "查看该主体承担的成本", "intent": "explain_company_cost", "text": "按员工、社保公积金和成本归集说明该公司主体的本月责任。"})
        else:
            prompts.append({"label": "说明这个资源的上下游", "intent": "explain_neighborhood", "text": "用中文说明当前资源连接了哪些企业资源，以及为什么这些关系重要。"})
        for capability in capabilities:
            if capability.get("enabled"):
                actions.append({
                    "label": capability.get("label"),
                    "function": capability.get("name"),
                    "description": capability.get("reason"),
                    "mode": capability.get("mode"),
                })
            if len(actions) >= 4:
                break
        judgment = self.current_judgment(object_type, object_id, record, signals, capabilities)
        fallback = {
            "title": "当前可以这样推进",
            "judgment": judgment,
            "prompts": prompts[:4],
            "actions": actions,
            "evidence": self.rail_evidence(object_type, signals, neighborhood),
            "mode": "rules",
        }
        task_id = self.schedule_conversation_llm(
            fallback, object_type, object_id, record, signals, capabilities, neighborhood,
        )
        if task_id:
            fallback["llm_task"] = task_id
            fallback["llm_status"] = "pending"
        return fallback

    def schedule_conversation_llm(
        self,
        fallback: dict,
        object_type: str,
        object_id: str,
        record: dict,
        signals: dict,
        capabilities: list[dict],
        neighborhood: dict,
    ) -> str:
        client = self.llm_client()
        model = os.environ.get("LLM_MODEL", "")
        if not client or not model:
            return ""
        cache_key = f"conversation:{object_type}:{object_id}:{signals.get('scope')}:{signals.get('severity')}:{signals.get('diff_count')}:{signals.get('warning_count')}"
        if cache_key in self._llm_cache:
            task_id = self.new_llm_task("conversation", cache_key)
            self._llm_tasks[task_id].update({"status": "done", "result": self._llm_cache[cache_key]})
            return task_id
        task_id = self.new_llm_task("conversation", cache_key)
        self._llm_executor.submit(
            self.run_conversation_llm_task,
            task_id,
            fallback,
            object_type,
            object_id,
            record,
            signals,
            capabilities,
            neighborhood,
        )
        return task_id

    def current_judgment(self, object_type: str, object_id: str, record: dict, signals: dict, capabilities: list[dict]) -> str:
        name = self.display_name(object_type)
        if signals.get("scope") == "payroll" and (signals.get("warning_count") or signals.get("diff_count")):
            return f"当前{name}已经形成可运行的业务语境，但存在需要人工判断的提示或校对差异。建议先沿证据链解释问题，再执行后续流程能力。"
        if signals.get("severity") == "attention":
            return f"当前{name}有需要复核的资源状态。建议先查看字段详情和相关资源，再执行会影响计算或流程的操作。"
        enabled = [cap.get("label") for cap in capabilities if cap.get("enabled")]
        if enabled:
            return f"当前{name}可直接进入“{enabled[0]}”等预览能力。系统会先说明读取哪些资源、应用哪些规则，再展示结果。"
        return f"当前{name}适合先查看字段详情和相关资源，再决定是否进入后续业务操作。"

    def rail_evidence(self, object_type: str, signals: dict, neighborhood: dict) -> list[str]:
        evidence = [self.display_name(object_type)]
        evidence.extend(edge.get("to", "") for edge in neighborhood.get("edges", [])[:3])
        if signals.get("payroll_run_id"):
            evidence.append("薪资试算预览")
        return [item for item in evidence if item][:6]

    def run_conversation_llm_task(
        self,
        task_id: str,
        fallback: dict,
        object_type: str,
        object_id: str,
        record: dict,
        signals: dict,
        capabilities: list[dict],
        neighborhood: dict,
    ):
        cache_key = f"conversation:{object_type}:{object_id}:{signals.get('scope')}:{signals.get('severity')}:{signals.get('diff_count')}:{signals.get('warning_count')}"
        if cache_key in self._llm_cache:
            self.finish_llm_task(task_id, self._llm_cache[cache_key])
            return
        client = self.llm_client()
        model = os.environ.get("LLM_MODEL", "")
        if not client or not model:
            self.fail_llm_task(task_id, "LLM 未配置")
            return

        context = {
            "resource": {
                "name": self.display_name(object_type),
                "id": object_id,
                "title": self.resource_title(object_type, object_id, record),
                "subtitle": self.resource_subtitle(object_type, record),
                "record": self.present_record(object_type, record)[:10],
            },
            "signals": {
                "items": signals.get("items", [])[:4],
                "scope": signals.get("scope", "resource"),
                "diff_count": signals.get("diff_count") if signals.get("scope") == "payroll" else None,
                "warning_count": signals.get("warning_count") if signals.get("scope") == "payroll" else None,
                "employee_payroll": signals.get("employee_payroll", {}),
                "company": signals.get("company", {}),
                "totals": signals.get("totals", {}),
                "sample_warnings": signals.get("sample_warnings", [])[:3],
            },
            "related_resources": [
                {"name": edge.get("to"), "relation": edge.get("name"), "count": edge.get("count")}
                for edge in neighborhood.get("edges", [])[:6]
            ],
            "available_actions": [
                {
                    "label": cap.get("label"),
                    "enabled": cap.get("enabled"),
                    "reason": cap.get("reason"),
                    "reads": cap.get("reads", [])[:4],
                    "writes": cap.get("writes", [])[:4],
                }
                for cap in capabilities[:6]
            ],
            "fallback": fallback,
        }
        prompt = (
            "你是企业 OMS 页面中的业务引导层。只基于给定 JSON 生成右侧栏文案，"
            "不要编造事实、不要计算工资、不要声称已写入数据。"
            "输出 JSON，字段为 title, judgment, prompts, evidence。"
            "prompts 是 2-4 个对象，每个对象有 label 和 text。"
            "judgment 用 1-2 句中文，像业务系统提示，不像聊天机器人。"
        )
        data = self.call_llm_json(prompt, context)
        if not data:
            self.fail_llm_task(task_id, "LLM 未返回可用内容")
            return
        enhanced = dict(fallback)
        enhanced["title"] = str(data.get("title") or fallback.get("title") or "当前可以这样推进")
        enhanced["judgment"] = str(data.get("judgment") or fallback.get("judgment") or "")
        prompts = data.get("prompts")
        if isinstance(prompts, list) and prompts:
            enhanced["prompts"] = [
                {
                    "label": str(item.get("label", ""))[:40],
                    "text": str(item.get("text", ""))[:180],
                }
                for item in prompts
                if isinstance(item, dict) and item.get("label")
            ][:4] or fallback.get("prompts", [])
        evidence = data.get("evidence")
        if isinstance(evidence, list) and evidence:
            enhanced["evidence"] = [str(item)[:40] for item in evidence[:6]]
        enhanced["mode"] = "llm"
        enhanced.pop("llm_task", None)
        enhanced.pop("llm_status", None)
        self._llm_cache[cache_key] = enhanced
        self.finish_llm_task(task_id, enhanced)

    def params_for(self, function_name: str, object_type: str, object_id: str, employee_id: str = "") -> dict:
        params = {}
        fn = self.ontology.functions.get(function_name)
        if not fn:
            return params
        record = self.find_record(object_type, object_id)
        payroll_run_id = self.resolve_payroll_run_id(object_type, object_id, record) or DEFAULT_CONTEXT["id"]
        if "payroll_run_id" in fn.params:
            params["payroll_run_id"] = payroll_run_id
        if "employee_id" in fn.params:
            params["employee_id"] = employee_id or (object_id if object_type == "Employee" else DEFAULT_EMPLOYEE)
        if "company_id" in fn.params:
            params["company_id"] = object_id if object_type == "Company" else record.get("payroll_company_id") or record.get("company_id") or DEFAULT_COMPANY
        if "period" in fn.params:
            run = self.find_record("PayrollRun", payroll_run_id)
            params["period"] = run.get("payroll_period", "2026-04")
        if "as_of_date" in fn.params:
            run = self.find_record("PayrollRun", payroll_run_id)
            period = run.get("payroll_period", "2026-04")
            params["as_of_date"] = f"{period}-30"
        return params

    def present_params(self, function_name: str, params: dict) -> list[dict]:
        fn = self.ontology.functions.get(function_name)
        rows = []
        for key, value in params.items():
            label = fn.params[key].description.split("，")[0] if fn and key in fn.params else key
            rows.append({"label": label, "value": value})
        return rows

    def present_result(self, function_name: str, result: dict) -> dict:
        if result.get("error"):
            return {"summary": result.get("error"), "highlights": [], "sections": []}
        if function_name == "resolve_employee_state_at":
            return self.present_employee_state_result(result)
        if function_name == "resolve_rules_at":
            return self.present_rules_result(result)
        if function_name == "build_payroll_snapshot":
            return self.present_snapshot_result(result)
        if function_name == "generate_payroll_lines":
            return self.present_generate_lines_result(result)
        if function_name == "calculate_contributions":
            return self.present_contributions_result(result)
        if function_name == "calculate_payroll":
            return self.present_payroll_result(result)

        return self.present_generic_result(function_name, result)

    def present_generic_result(self, function_name: str, result: dict) -> dict:
        highlights = []
        for key, label in [
            ("status", "状态"), ("payroll_run_id", "薪资批次"), ("employee_id", "员工"),
            ("calculated_count", "工资明细"), ("payroll_item_count", "工资项"),
            ("social_contribution_count", "社保记录"), ("housing_fund_count", "公积金记录"),
            ("deduction_count", "扣款台账"), ("tax_ledger_count", "个税台账"),
            ("diff_count", "差异"), ("warning_count", "提示"),
            ("employee_snapshot_count", "员工快照"), ("generated_count", "生成明细"),
        ]:
            if result.get(key) not in (None, ""):
                highlights.append({"label": label, "value": result.get(key)})
        summary = self.result_summary(function_name, result)
        sections = []
        if result.get("answer_summary"):
            sections.append({"title": "工资摘要", "rows": result.get("answer_summary")[:6]})
        if result.get("sample_warnings") or result.get("warnings"):
            sections.append({"title": "运行提示", "rows": (result.get("warnings") or result.get("sample_warnings") or [])[:6]})
        if result.get("sample_diffs") or result.get("diffs"):
            sections.append({"title": "差异样本", "rows": (result.get("diffs") or result.get("sample_diffs") or [])[:6]})
        return {"summary": summary, "highlights": highlights[:8], "sections": sections}

    def result_summary(self, function_name: str, result: dict) -> str:
        label = self.ontology.functions[function_name].summary if function_name in self.ontology.functions else function_name
        if function_name == "resolve_employee_state_at":
            missing = result.get("missing") or []
            base = (
                f"{result.get('employee_id', '')} 在 {result.get('as_of_date', '')} 的薪资状态已解析："
                f"{result.get('employment_status', '') or '状态未知'}，"
                f"发薪主体为 {result.get('payroll_company_name') or result.get('payroll_company_id') or '未知'}，"
                f"使用薪资档案 {result.get('salary_profile_id') or '未找到'}。"
            )
            return base + (f" 缺少输入：{'、'.join(missing)}。" if missing else " 必要输入已解析到。")
        if function_name == "resolve_rules_at":
            missing = []
            if not result.get("social_insurance_rule"):
                missing.append("社保规则")
            if not result.get("housing_fund_rule"):
                missing.append("公积金规则")
            base = (
                f"{result.get('company_name') or result.get('company_id', '')} / {result.get('period', '')} "
                f"规则解析完成：薪资拆分 {len(result.get('salary_split_rules') or [])} 条，"
                f"绩效等级 {len(result.get('performance_grade_rules') or [])} 条，"
                f"个税税率 {len(result.get('tax_rate_rules') or [])} 档。"
            )
            return base + (f" 当前缺少：{'、'.join(missing)}。" if missing else " 社保和公积金规则均已找到。")
        if function_name == "build_payroll_snapshot":
            return (
                f"{result.get('payroll_run_id', '')} 的薪资输入快照为"
                f"“{STATUS_LABELS.get(str(result.get('status', '')), result.get('status', ''))}”："
                f"快照 {result.get('snapshot_id', '')} 覆盖 {result.get('employee_snapshot_count', 0)} 名员工。"
            )
        if function_name == "generate_payroll_lines":
            return (
                f"{result.get('payroll_run_id', '')} 工资明细预览完成："
                f"生成 {result.get('generated_count', 0)} 条工资明细和 {result.get('payroll_item_count', 0)} 条工资项，"
                f"发现 {result.get('diff_count', 0)} 个差异、{result.get('warning_count', 0)} 条提示。"
            )
        if function_name == "calculate_payroll":
            employee = result.get("employee_id")
            if employee and result.get("answer_summary"):
                row = result.get("answer_summary")[0]
                return (
                    f"{employee} 薪资实发预览完成：扣前应发 {_money(row.get('gross_pay_before_deduction'))}，"
                    f"个人社保 {_money(row.get('personal_social_security'))}，"
                    f"个人公积金 {_money(row.get('personal_housing_fund'))}，"
                    f"个税 {_money(row.get('personal_income_tax'))}，实发 {_money(row.get('net_pay'))}。"
                )
            return f"{label}完成：生成 {result.get('calculated_count', 0)} 条工资明细、{result.get('payroll_item_count', 0)} 条工资项、{result.get('tax_ledger_count', 0)} 条个税台账预览。"
        if function_name == "calculate_contributions":
            return f"{label}完成：形成 {result.get('social_contribution_count', 0)} 条社保记录、{result.get('housing_fund_count', 0)} 条公积金记录和 {result.get('deduction_count', 0)} 条扣款台账预览。"
        if result.get("message"):
            return result.get("message")
        return f"{label}完成，结果已按本体证据整理。"

    def present_employee_state_result(self, result: dict) -> dict:
        missing = result.get("missing") or []
        highlights = [
            {"label": "员工", "value": result.get("employee_id", "")},
            {"label": "姓名", "value": result.get("employee_name", "")},
            {"label": "状态", "value": result.get("employment_status", "")},
            {"label": "发薪主体", "value": result.get("payroll_company_name") or result.get("payroll_company_id", "")},
            {"label": "薪资档案", "value": result.get("salary_profile_id", "")},
            {"label": "缺失输入", "value": len(missing)},
        ]
        sections = [
            {
                "title": "时点状态",
                "kind": "facts",
                "rows": [
                    {"label": "员工编号", "value": result.get("employee_id", "")},
                    {"label": "员工姓名", "value": result.get("employee_name", "")},
                    {"label": "时点日期", "value": result.get("as_of_date", "")},
                    {"label": "员工状态", "value": result.get("employment_status", "")},
                ],
            },
            {
                "title": "关系定位",
                "kind": "facts",
                "rows": [
                    {"label": "自然人编号", "value": result.get("person_id", "")},
                    {"label": "任职关系", "value": result.get("employment_relationship_id", "")},
                    {"label": "关系类型", "value": result.get("relationship_type", "")},
                    {"label": "发薪主体", "value": result.get("payroll_company_name") or result.get("payroll_company_id", "")},
                    {"label": "内部归属", "value": result.get("internal_affiliation_name") or "无"},
                ],
            },
            {
                "title": "薪资计算输入",
                "kind": "facts",
                "rows": [
                    {"label": "薪资档案版本", "value": result.get("salary_profile_id", "")},
                    {"label": "月薪基数", "value": _money(result.get("monthly_salary_base"))},
                    {"label": "社保基数", "value": self.present_empty(result.get("social_security_base"))},
                    {"label": "公积金基数", "value": self.present_empty(result.get("housing_fund_base"))},
                    {"label": "岗位/人员类型", "value": result.get("position_or_type", "")},
                ],
            },
        ]
        if missing:
            sections.append({
                "title": "缺失输入",
                "kind": "list",
                "rows": [{"title": f"缺少 {item}", "meta": "会影响后续薪资计算"} for item in missing],
            })
        return {"summary": self.result_summary("resolve_employee_state_at", result), "highlights": highlights, "sections": sections}

    def present_rules_result(self, result: dict) -> dict:
        missing = []
        if not result.get("social_insurance_rule"):
            missing.append("社保规则")
        if not result.get("housing_fund_rule"):
            missing.append("公积金规则")
        highlights = [
            {"label": "公司", "value": result.get("company_name") or result.get("company_id", "")},
            {"label": "月份", "value": result.get("period", "")},
            {"label": "薪资拆分", "value": len(result.get("salary_split_rules") or [])},
            {"label": "绩效等级", "value": len(result.get("performance_grade_rules") or [])},
            {"label": "个税税率", "value": len(result.get("tax_rate_rules") or [])},
            {"label": "缺失规则", "value": len(missing)},
        ]
        sections = [
            {
                "title": "规则覆盖",
                "kind": "facts",
                "rows": [
                    {"label": "公司主体", "value": result.get("company_name") or result.get("company_id", "")},
                    {"label": "适用月份", "value": result.get("period", "")},
                    {"label": "社保规则", "value": self.rule_identity(result.get("social_insurance_rule"), "social_rule_id")},
                    {"label": "公积金规则", "value": self.rule_identity(result.get("housing_fund_rule"), "housing_rule_id")},
                    {"label": "个税税率档", "value": f"{len(result.get('tax_rate_rules') or [])} 档"},
                ],
            },
            {
                "title": "薪资拆分规则",
                "kind": "list",
                "rows": [
                    {
                        "title": f"{row.get('position_or_type', '')}：基本薪资 {self.percent(row.get('basic_salary_rate'))} / 绩效基数 {self.percent(row.get('performance_base_rate'))}",
                        "meta": row.get("split_rule_id", ""),
                    }
                    for row in (result.get("salary_split_rules") or [])[:8]
                ],
            },
            {
                "title": "绩效等级规则",
                "kind": "list",
                "rows": [
                    {
                        "title": f"{row.get('performance_grade', '')}：系数 {row.get('coefficient', '')}",
                        "meta": row.get("grade_rule_id", ""),
                    }
                    for row in (result.get("performance_grade_rules") or [])[:8]
                ],
            },
        ]
        if missing:
            sections.append({
                "title": "缺失规则",
                "kind": "list",
                "rows": [{"title": f"未找到 {item}", "meta": "后续计算会形成提示或按 0 处理"} for item in missing],
            })
        return {"summary": self.result_summary("resolve_rules_at", result), "highlights": highlights, "sections": sections}

    def present_snapshot_result(self, result: dict) -> dict:
        sections = [
            {
                "title": "快照状态",
                "kind": "facts",
                "rows": [
                    {"label": "薪资批次", "value": result.get("payroll_run_id", "")},
                    {"label": "工资归属月", "value": result.get("payroll_period", "")},
                    {"label": "快照编号", "value": result.get("snapshot_id", "")},
                    {"label": "快照时间", "value": result.get("snapshot_time", "")},
                    {"label": "来源说明", "value": result.get("source_note", "")},
                ],
            },
            {
                "title": "快照覆盖",
                "kind": "metrics",
                "rows": [
                    {"label": "员工快照", "value": result.get("employee_snapshot_count", 0)},
                    {"label": "现有工资行", "value": result.get("payroll_line_count", 0)},
                    {"label": "校验提示", "value": result.get("validation_warning_count", 0)},
                ],
            },
            {
                "title": "员工快照样本",
                "kind": "list",
                "rows": [
                    {
                        "title": f"{row.get('employee_name_snapshot', '')}（{row.get('employee_id', '')}）：{row.get('payroll_company_name_snapshot', '')}",
                        "meta": f"薪资档案 {row.get('salary_profile_id', '')} / 月薪 {_money(row.get('monthly_salary_total'))}",
                    }
                    for row in (result.get("sample_employee_snapshots") or [])[:6]
                ],
            },
        ]
        return {
            "summary": self.result_summary("build_payroll_snapshot", result),
            "highlights": [
                {"label": "状态", "value": STATUS_LABELS.get(str(result.get("status", "")), result.get("status", ""))},
                {"label": "薪资批次", "value": result.get("payroll_run_id", "")},
                {"label": "员工快照", "value": result.get("employee_snapshot_count", 0)},
                {"label": "校验提示", "value": result.get("validation_warning_count", 0)},
            ],
            "sections": sections,
        }

    def present_generate_lines_result(self, result: dict) -> dict:
        sections = [
            {
                "title": "生成结果",
                "kind": "metrics",
                "rows": [
                    {"label": "工资明细", "value": result.get("generated_count", 0)},
                    {"label": "工资项", "value": result.get("payroll_item_count", 0)},
                    {"label": "基准行", "value": result.get("expected_line_count", 0)},
                    {"label": "差异", "value": result.get("diff_count", 0)},
                    {"label": "提示", "value": result.get("warning_count", 0)},
                ],
            },
            {
                "title": "工资明细样本",
                "kind": "list",
                "rows": [
                    self.payroll_line_row(row)
                    for row in (result.get("sample_generated_lines") or [])[:8]
                ],
            },
        ]
        sections.extend(self.warning_and_diff_sections(result))
        return {
            "summary": self.result_summary("generate_payroll_lines", result),
            "highlights": sections[0]["rows"][:5],
            "sections": sections,
        }

    def present_contributions_result(self, result: dict) -> dict:
        sections = [
            {
                "title": "缴费与扣款结果",
                "kind": "metrics",
                "rows": [
                    {"label": "社保记录", "value": result.get("social_contribution_count", 0)},
                    {"label": "公积金记录", "value": result.get("housing_fund_count", 0)},
                    {"label": "扣款台账", "value": result.get("deduction_count", 0)},
                    {"label": "差异", "value": result.get("diff_count", 0)},
                    {"label": "提示", "value": result.get("warning_count", 0)},
                ],
            },
            {
                "title": "社保记录样本",
                "kind": "list",
                "rows": [
                    {
                        "title": f"{row.get('employee_id', '')}：个人 {_money(row.get('personal_total'))} / 公司 {_money(row.get('employer_total'))}",
                        "meta": f"{row.get('contribution_company_id', '')} / {row.get('contribution_period', '')} / 基数 {_money(row.get('contribution_base'))}",
                    }
                    for row in (result.get("sample_social_contributions") or [])[:6]
                ],
            },
            {
                "title": "公积金记录样本",
                "kind": "list",
                "rows": [
                    {
                        "title": f"{row.get('employee_id', '')}：个人 {_money(row.get('personal_amount'))} / 公司 {_money(row.get('employer_amount'))}",
                        "meta": f"{row.get('contribution_company_id', '')} / {row.get('contribution_period', '')} / 基数 {_money(row.get('contribution_base'))}",
                    }
                    for row in (result.get("sample_housing_fund_contributions") or [])[:6]
                ],
            },
            {
                "title": "扣款台账样本",
                "kind": "list",
                "rows": [
                    {
                        "title": f"{row.get('employee_id', '')} {row.get('deduction_type', '')}：个人 {_money(row.get('personal_amount'))} / 公司 {_money(row.get('employer_amount'))}",
                        "meta": f"{row.get('deduction_id', '')} / {row.get('status', '')}",
                    }
                    for row in (result.get("sample_deductions") or [])[:8]
                ],
            },
        ]
        sections.extend(self.warning_and_diff_sections(result))
        return {
            "summary": self.result_summary("calculate_contributions", result),
            "highlights": [
                {"label": "薪资批次", "value": result.get("payroll_run_id", "")},
                {"label": "员工", "value": result.get("employee_id") or "整批"},
                {"label": "缴费月", "value": result.get("contribution_period", "")},
                {"label": "社保记录", "value": result.get("social_contribution_count", 0)},
                {"label": "公积金记录", "value": result.get("housing_fund_count", 0)},
                {"label": "扣款台账", "value": result.get("deduction_count", 0)},
            ],
            "sections": sections,
        }

    def present_payroll_result(self, result: dict) -> dict:
        sections = [
            {
                "title": "薪资实发结果",
                "kind": "metrics",
                "rows": [
                    {"label": "工资明细", "value": result.get("calculated_count", 0)},
                    {"label": "工资项", "value": result.get("payroll_item_count", 0)},
                    {"label": "个税台账", "value": result.get("tax_ledger_count", 0)},
                    {"label": "差异", "value": result.get("diff_count", 0)},
                    {"label": "提示", "value": result.get("warning_count", 0)},
                ],
            },
            {
                "title": "工资摘要",
                "kind": "list",
                "rows": [
                    {
                        "title": (
                            f"{row.get('employee_name') or row.get('employee_id', '')}（{row.get('employee_id', '')}）："
                            f"扣前 {_money(row.get('gross_pay_before_deduction'))}，实发 {_money(row.get('net_pay'))}"
                        ),
                        "meta": (
                            f"社保 {_money(row.get('personal_social_security'))} / "
                            f"公积金 {_money(row.get('personal_housing_fund'))} / "
                            f"个税 {_money(row.get('personal_income_tax'))}"
                        ),
                    }
                    for row in (result.get("answer_summary") or [])[:8]
                ],
            },
        ]
        if result.get("sample_payroll_items") or result.get("payroll_items"):
            sections.append({
                "title": "工资项样本",
                "kind": "list",
                "rows": [
                    {
                        "title": f"{row.get('item_name', '')}：{_money(row.get('amount'))}",
                        "meta": f"{row.get('employee_id', '')} / {row.get('item_category', '')}",
                    }
                    for row in (result.get("payroll_items") or result.get("sample_payroll_items") or [])[:8]
                ],
            })
        if result.get("sample_tax_ledgers") or result.get("tax_ledgers"):
            sections.append({
                "title": "个税台账样本",
                "kind": "list",
                "rows": [
                    {
                        "title": f"{row.get('employee_id', '')}：本月个税 {_money(row.get('current_tax'))}",
                        "meta": f"累计收入 {_money(row.get('cumulative_income'))} / 税期 {row.get('tax_period', '')}",
                    }
                    for row in (result.get("tax_ledgers") or result.get("sample_tax_ledgers") or [])[:6]
                ],
            })
        sections.extend(self.warning_and_diff_sections(result))
        return {
            "summary": self.result_summary("calculate_payroll", result),
            "highlights": [
                {"label": "薪资批次", "value": result.get("payroll_run_id", "")},
                {"label": "员工", "value": result.get("employee_id") or "整批"},
                {"label": "工资明细", "value": result.get("calculated_count", 0)},
                {"label": "工资项", "value": result.get("payroll_item_count", 0)},
                {"label": "个税台账", "value": result.get("tax_ledger_count", 0)},
                {"label": "提示", "value": result.get("warning_count", 0)},
            ],
            "sections": sections,
        }

    def warning_and_diff_sections(self, result: dict) -> list[dict]:
        sections = []
        warnings = result.get("warnings") or result.get("sample_warnings") or []
        if warnings:
            sections.append({
                "title": "运行提示",
                "kind": "list",
                "rows": [
                    {
                        "title": row.get("message", str(row)),
                        "meta": row.get("employee_id") or row.get("rule_code", ""),
                    }
                    for row in warnings[:8]
                ],
            })
        diffs = result.get("diffs") or result.get("sample_diffs") or []
        if diffs:
            sections.append({
                "title": "差异样本",
                "kind": "list",
                "rows": [self.diff_row(row) for row in diffs[:8]],
            })
        return sections

    def diff_row(self, diff: dict) -> dict:
        if diff.get("field"):
            return {
                "title": f"{diff.get('field')}：当前 {diff.get('calculated')} / 基准 {diff.get('expected')}",
                "meta": diff.get("record_id") or diff.get("employee_id", ""),
            }
        fields = diff.get("fields") or {}
        if fields:
            first_key = next(iter(fields))
            values = fields.get(first_key) or {}
            current = values.get("generated", values.get("calculated", "present"))
            expected = values.get("existing", values.get("expected", ""))
            return {
                "title": f"{first_key}：当前 {current} / 基准 {expected}",
                "meta": diff.get("record_id") or diff.get("object_type", ""),
            }
        return {"title": str(diff), "meta": diff.get("record_id", "")}

    def payroll_line_row(self, row: dict) -> dict:
        return {
            "title": (
                f"{row.get('employee_name_snapshot') or row.get('employee_id', '')}（{row.get('employee_id', '')}）："
                f"扣前 {_money(row.get('gross_pay_before_deduction'))}"
            ),
            "meta": (
                f"基本 {_money(row.get('basic_salary'))} / "
                f"绩效 {_money(row.get('performance_salary'))} / "
                f"考勤调整 {_money(row.get('attendance_adjustment'))}"
            ),
        }

    def rule_identity(self, row: dict | None, id_field: str) -> str:
        if not row:
            return "未找到"
        return str(row.get(id_field) or "已找到")

    def present_empty(self, value) -> str:
        if value in (None, ""):
            return "空"
        if isinstance(value, (int, float)):
            return _money(value)
        return str(value)

    def percent(self, value) -> str:
        if value in (None, ""):
            return "空"
        return f"{_num(value) * 100:.0f}%"

    def schedule_result_llm(self, function_name: str, presented: dict, raw_result: dict) -> str:
        client = self.llm_client()
        model = os.environ.get("LLM_MODEL", "")
        if not client or not model:
            return ""
        cache_key = (
            f"result:{function_name}:{raw_result.get('payroll_run_id', '')}:"
            f"{raw_result.get('employee_id', '')}:{raw_result.get('diff_count', '')}:"
            f"{raw_result.get('warning_count', '')}"
        )
        cached = self._llm_cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("text"):
            task_id = self.new_llm_task("result", cache_key)
            self._llm_tasks[task_id].update({
                "status": "done",
                "result": cached,
                "partial": cached.get("text", ""),
                "finished_at": time.time(),
            })
            return task_id
        task_id = self.new_llm_task("result", cache_key)
        self._llm_executor.submit(
            self.run_result_llm_task,
            task_id,
            cache_key,
            function_name,
            presented,
            raw_result,
        )
        return task_id

    def run_result_llm_task(self, task_id: str, cache_key: str, function_name: str, presented: dict, raw_result: dict):
        context = {
            "function": self.capability_vocabulary(function_name),
            "summary": presented.get("summary", ""),
            "highlights": presented.get("highlights", [])[:8],
            "sections": presented.get("sections", [])[:4],
            "warnings": (raw_result.get("warnings") or raw_result.get("sample_warnings") or [])[:5],
            "diffs": (raw_result.get("diffs") or raw_result.get("sample_diffs") or [])[:5],
            "note": raw_result.get("note", ""),
        }
        prompt = (
            "你是 OMS 资源详情页里的结果解释层。只基于给定 JSON，"
            "用 2-4 句中文解释这个预览结果。必须说明关键数值、风险或缺失输入。"
            "不要编造事实，不要说自己是 AI，不要使用 Markdown 列表。"
            "只输出解释正文，不要输出 JSON。"
        )
        text = self.call_llm_text_stream(task_id, prompt, context).strip()
        if not text:
            self.fail_llm_task(task_id, "LLM 未返回解释")
            return
        result = {"text": text, "mode": "llm"}
        self._llm_cache[cache_key] = result
        self.finish_llm_task(task_id, result)

    def new_llm_task(self, kind: str, cache_key: str) -> str:
        task_id = uuid.uuid4().hex
        self._llm_tasks[task_id] = {
            "id": task_id,
            "kind": kind,
            "cache_key": cache_key,
            "status": "pending",
            "created_at": time.time(),
            "result": None,
            "partial": "",
            "error": "",
        }
        self.cleanup_llm_tasks()
        return task_id

    def finish_llm_task(self, task_id: str, result: dict):
        task = self._llm_tasks.get(task_id)
        if not task:
            return
        task.update({
            "status": "done",
            "result": result,
            "partial": result.get("text", task.get("partial", "")),
            "finished_at": time.time(),
        })

    def fail_llm_task(self, task_id: str, error: str):
        task = self._llm_tasks.get(task_id)
        if not task:
            return
        task.update({
            "status": "error",
            "error": error,
            "finished_at": time.time(),
        })

    def get_llm_task(self, task_id: str) -> dict:
        return self._llm_tasks.get(task_id) or {
            "id": task_id,
            "status": "missing",
            "result": None,
            "partial": "",
            "error": "任务不存在或已过期",
        }

    def cleanup_llm_tasks(self):
        if len(self._llm_tasks) < 200:
            return
        cutoff = time.time() - 900
        for task_id, task in list(self._llm_tasks.items()):
            if task.get("created_at", 0) < cutoff:
                self._llm_tasks.pop(task_id, None)

    def result_conversation(self, function_name: str, result: dict) -> dict:
        prompts = []
        if result.get("warning_count"):
            prompts.append({"label": "解释这些提示", "text": "把提示按原因分类，并说明哪些需要人工确认。"})
        if result.get("diff_count"):
            prompts.append({"label": "查看差异来源", "text": "沿规则、输入和 benchmark 三个方向解释差异。"})
        if function_name == "resolve_employee_state_at":
            prompts.append({"label": "继续试算该员工薪资", "text": "基于已解析的任职关系和薪资档案，继续查看该员工本月工资实发。"})
            prompts.append({"label": "检查社保公积金输入", "text": "查看社保基数、公积金基数和公司规则是否足够支撑扣款计算。"})
        elif function_name == "resolve_rules_at":
            prompts.append({"label": "解释缺失规则影响", "text": "说明缺失社保或公积金规则会如何影响后续计算。"})
            prompts.append({"label": "用这些规则试算薪资", "text": "基于当前月份规则继续进行薪资或社保公积金预览。"})
        elif function_name == "build_payroll_snapshot":
            prompts.append({"label": "继续生成工资明细", "text": "基于快照生成工资明细和工资项草稿。"})
        elif function_name == "generate_payroll_lines":
            prompts.append({"label": "继续计算薪资实发", "text": "把工资明细草稿与扣款台账、个税台账合并为实发预览。"})
        elif function_name == "calculate_contributions":
            prompts.append({"label": "解释扣款台账如何入薪资", "text": "说明待扣、已扣和本次工资实扣之间的关系。"})
        elif function_name == "calculate_payroll":
            prompts.append({"label": "解释实发工资构成", "text": "沿扣前应发、社保、公积金、个税和实发公式解释结果。"})
        prompts.append({"label": "下一步该做什么", "text": "根据本次执行结果给出下一步能力和阻塞条件。"})
        return {
            "title": "执行后建议继续这样看",
            "judgment": self.result_summary(function_name, result),
            "prompts": prompts[:3],
            "actions": [],
            "evidence": ["本体能力", "确定性运行结果", "计算轨迹", "业务提示"],
        }

    def llm_client(self):
        if self._llm_checked:
            return self._llm_client
        self._llm_checked = True
        load_env(ROOT / ".env")
        if OpenAI is None:
            return None
        api_key = os.environ.get("LLM_API_KEY", "")
        base_url = os.environ.get("LLM_API_URL", "")
        model = os.environ.get("LLM_MODEL", "")
        if not api_key or not base_url or not model:
            return None
        try:
            self._llm_client = OpenAI(base_url=base_url, api_key=api_key, timeout=20.0)
        except Exception:
            self._llm_client = None
        return self._llm_client

    def call_llm_json(self, instruction: str, payload: dict) -> dict | None:
        client = self.llm_client()
        model = os.environ.get("LLM_MODEL", "")
        if not client or not model:
            return None
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "你只输出严格 JSON，不输出解释性前后缀。",
                    },
                    {
                        "role": "user",
                        "content": instruction + "\n\n输入 JSON:\n" + json.dumps(payload, ensure_ascii=False, default=str)[:18000],
                    },
                ],
                temperature=0.2,
            )
            content = response.choices[0].message.content or ""
            parsed = parse_json_object(content)
            if parsed:
                return parsed
            cleaned = content.strip()
            if cleaned:
                return {"judgment": cleaned, "text": cleaned}
            return None
        except Exception:
            return None

    def call_llm_text_stream(self, task_id: str, instruction: str, payload: dict) -> str:
        client = self.llm_client()
        model = os.environ.get("LLM_MODEL", "")
        if not client or not model:
            return ""
        messages = [
            {
                "role": "system",
                "content": "你是企业 OMS 页面中的业务解释层。只输出中文解释正文。",
            },
            {
                "role": "user",
                "content": instruction + "\n\n输入 JSON:\n" + json.dumps(payload, ensure_ascii=False, default=str)[:18000],
            },
        ]
        parts: list[str] = []
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None) or ""
                if not piece:
                    continue
                parts.append(piece)
                self.update_llm_partial(task_id, "".join(parts))
            return "".join(parts)
        except Exception:
            return ""

    def update_llm_partial(self, task_id: str, text: str):
        task = self._llm_tasks.get(task_id)
        if not task or task.get("status") != "pending":
            return
        task["partial"] = text


def _num(value) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _money(value) -> str:
    return f"{_num(value):,.2f} 元"


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = STATIC_DIR / "index.html" if parsed.path == "/" else STATIC_DIR / parsed.path.removeprefix("/static/")
        if parsed.path != "/" and not parsed.path.startswith("/static/"):
            self.send_error(404)
            return
        if not path.exists():
            self.send_error(404)
            return
        self.send_response(200)
        self._send_no_cache_headers()
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/":
            return self._static("index.html")
        if parsed.path.startswith("/static/"):
            return self._static(parsed.path.removeprefix("/static/"))
        if parsed.path == "/api/shell":
            return self._json(RUNTIME.shell(params.get("type", [""])[0], params.get("id", [""])[0]))
        if parsed.path == "/api/context":
            return self._json(RUNTIME.resource_context(params.get("type", ["PayrollRun"])[0], params.get("id", [""])[0]))
        if parsed.path == "/api/execute":
            return self._json(RUNTIME.execute(
                params.get("function", [""])[0],
                params.get("type", ["PayrollRun"])[0],
                params.get("id", [""])[0],
                employee_id=params.get("employee_id", [""])[0],
            ))
        if parsed.path == "/api/llm/task":
            return self._json(RUNTIME.get_llm_task(params.get("id", [""])[0]))
        self.send_error(404)

    def log_message(self, fmt, *args):
        return

    def _static(self, name: str):
        path = (STATIC_DIR / name).resolve()
        if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.exists():
            self.send_error(404)
            return
        content_type = "text/html"
        if path.suffix == ".css":
            content_type = "text/css"
        elif path.suffix == ".js":
            content_type = "application/javascript"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self._send_no_cache_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: dict):
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_no_cache_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_no_cache_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")


RUNTIME = OmsRuntime()


def load_env(path: Path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"").strip("'"))


def parse_json_object(content: str) -> dict | None:
    text = (content or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end + 1])
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def main():
    port = int(os.environ.get("OMS_PROTOTYPE_PORT", "8765"))
    host = os.environ.get("OMS_PROTOTYPE_HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"OMS prototype running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
