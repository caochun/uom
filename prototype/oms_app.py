from __future__ import annotations

import json
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
OAG_PATH = ROOT / "oag-agent"
if str(OAG_PATH) not in sys.path:
    sys.path.insert(0, str(OAG_PATH))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from openai import OpenAI  # noqa: E402

from oag.agent import Agent  # noqa: E402
from oag.harness import Harness  # noqa: E402
from oag.ontology.loader import load_domain  # noqa: E402
from oag.runtime import HarnessConfig  # noqa: E402
from oag.runtime.events import TextEvent, ToolCallEvent  # noqa: E402


DOMAIN_DIR = ROOT / "oms"
STATIC_DIR = Path(__file__).resolve().parent / "static"
PAYROLL_RUN_ID = "PAYROLL_202604"


class OmsRuntime:
    def __init__(self):
        self.ontology, self.repository, self.registry = load_domain(DOMAIN_DIR)
        self._agent_harness: Harness | None = None

    def domain(self) -> dict:
        payroll = self.overview()
        run = payroll["run"]
        employee_count = self.repository.count("Employee")
        company_count = self.repository.count("Company", {"payroll_enabled": 1})
        consultant_count = self.repository.count("ConsultantEngagement")
        rule_count = (
            self.repository.count("SalarySplitRule")
            + self.repository.count("PerformanceGradeRule")
            + self.repository.count("SocialInsuranceRule")
            + self.repository.count("HousingFundRule")
            + self.repository.count("TaxRateRule")
        )
        validation_count = self.repository.count("PayrollValidationResult", {"payroll_run_id": PAYROLL_RUN_ID})
        approval_count = self.repository.count("ApprovalRecord", {"payroll_run_id": PAYROLL_RUN_ID})
        export_count = self.repository.count("PayrollExport", {"payroll_run_id": PAYROLL_RUN_ID})
        return {
            "domain": {
                "name": self.ontology.name,
                "description": self.ontology.description,
            },
            "health": [
                {
                    "label": "员工主数据",
                    "value": employee_count,
                    "detail": f"{company_count} 个发薪主体，{rule_count} 条当前规则数据可参与核算",
                    "object_type": "Employee",
                    "object_id": "",
                },
                {
                    "label": "月度薪资批次",
                    "value": payroll["counts"]["calculated"],
                    "detail": f"{run.get('payroll_period', '')} 工资归属月，状态 {run.get('status', '')}",
                    "object_type": "PayrollRun",
                    "object_id": PAYROLL_RUN_ID,
                },
                {
                    "label": "待处理风险",
                    "value": payroll["counts"]["diffs"] + payroll["counts"]["warnings"],
                    "detail": f"{payroll['counts']['diffs']} 个差异，{payroll['counts']['warnings']} 条系统提示",
                    "object_type": "PayrollRun",
                    "object_id": PAYROLL_RUN_ID,
                },
                {
                    "label": "顾问结算",
                    "value": consultant_count,
                    "detail": "顾问劳务费与工资薪金个税分开处理",
                    "object_type": "ConsultantEngagement",
                    "object_id": "",
                },
            ],
            "flows": [
                self._flow_card(
                    "薪资核算闭环",
                    "PayrollRun",
                    PAYROLL_RUN_ID,
                    ["PayrollInputSnapshot", "PayrollEmployeeSnapshot", "PayrollLine", "PayrollItem", "TaxLedger"],
                    ["build_payroll_snapshot", "generate_payroll_lines", "calculate_payroll"],
                ),
                self._flow_card(
                    "社保公积金扣款",
                    "ContributionDeduction",
                    "",
                    ["SocialInsuranceContribution", "HousingFundContribution", "ContributionDeduction"],
                    ["calculate_contributions"],
                ),
                self._flow_card(
                    "校验审批与输出",
                    "PayrollValidationResult",
                    "",
                    ["PayrollValidationResult", "ApprovalRecord", "PayrollExport"],
                    ["validate_payroll", "submit_payroll_for_approval", "export_payroll_outputs"],
                ),
                self._flow_card(
                    "成本归集",
                    "CostEntry",
                    "",
                    ["CostEntry", "ConsultantFeeSettlement"],
                    ["calculate_consultant_fees", "generate_cost_entries"],
                ),
            ],
            "spotlight": {
                "object_type": "PayrollRun",
                "object_id": PAYROLL_RUN_ID,
                "title": f"{PAYROLL_RUN_ID} · {run.get('payroll_period', '')}",
                "summary": payroll["agent_brief"],
            },
            "counts": {
                "validations": validation_count,
                "approvals": approval_count,
                "exports": export_count,
            },
        }

    def context(self, object_type: str, object_id: str = "") -> dict:
        current = self._object_header(object_type, object_id)
        related = self._related_entries(object_type, object_id)
        capabilities = self._capability_entries(object_type, object_id)
        narrative = self._context_narrative(current, related, capabilities)
        return {
            "current": current,
            "narrative": narrative,
            "related": related,
            "capabilities": capabilities,
        }

    def object_detail(self, object_type: str, object_id: str = "") -> dict:
        if object_type == "PayrollRun":
            return {"type": "payroll_run", "data": self.overview()}
        if object_type == "Employee" and object_id:
            return {"type": "employee", "data": self.payroll(object_id)}
        if object_type == "Employee":
            return {
                "type": "employee_collection",
                "object_type": "Employee",
                "rows": self.employees().get("employees", [])[:40],
                "total": self.repository.count("Employee"),
            }
        rows = self._query_object_rows(object_type, object_id, limit=20)
        return {
            "type": "table",
            "object_type": object_type,
            "object_id": object_id,
            "rows": rows,
            "fields": list(rows[0].keys())[:8] if rows else [],
        }

    def overview(self) -> dict:
        run = self.repository.query_by_id("PayrollRun", PAYROLL_RUN_ID) or {}
        snapshot = self.repository.query(
            "PayrollInputSnapshot",
            {"payroll_run_id": PAYROLL_RUN_ID},
            limit=1,
        )
        employees = self.repository.query(
            "PayrollEmployeeSnapshot",
            {"payroll_run_id": PAYROLL_RUN_ID},
        )
        calculated = self.registry.call(
            "calculate_payroll",
            payroll_run_id=PAYROLL_RUN_ID,
            include_result_set=True,
        )
        lines = calculated.get("result_set", {}).get("PayrollLine", [])
        net_total = sum(_num(row.get("net_pay")) for row in lines)
        gross_total = sum(_num(row.get("gross_pay_before_deduction")) for row in lines)
        tax_total = sum(_num(row.get("personal_income_tax")) for row in lines)
        return {
            "run": run,
            "snapshot": snapshot[0] if snapshot else {},
            "counts": {
                "employees": len(employees),
                "calculated": calculated.get("calculated_count", 0),
                "diffs": calculated.get("diff_count", 0),
                "warnings": calculated.get("warning_count", 0),
            },
            "totals": {
                "gross": round(gross_total, 2),
                "tax": round(tax_total, 2),
                "net": round(net_total, 2),
            },
            "agent_brief": self._build_overview_brief(calculated),
            "next_actions": [
                {
                    "action": "review_diffs",
                    "title": "复核剩余差异",
                    "detail": "全量工资预览仍存在少量 benchmark 差异，建议先按员工定位原因。",
                    "severity": "medium" if calculated.get("diff_count", 0) else "low",
                },
                {
                    "action": "confirm_deductions",
                    "title": "确认社保公积金扣款台账",
                    "detail": "当前工资实扣只采纳已确认 ContributionDeduction，未确认记录只作为缴费建议。",
                    "severity": "medium",
                },
                {
                    "action": "approval_summary",
                    "title": "提交审批前生成摘要",
                    "detail": "审批摘要应包含批次、人数、应发、个税、实发、差异和未确认扣款。",
                    "severity": "low",
                },
            ],
        }

    def employees(self, query: str = "") -> dict:
        snapshots = self.repository.query(
            "PayrollEmployeeSnapshot",
            {"payroll_run_id": PAYROLL_RUN_ID},
            order_by="employee_id",
        )
        if query:
            needle = query.lower()
            snapshots = [
                row for row in snapshots
                if needle in row.get("employee_id", "").lower()
                or needle in row.get("employee_name_snapshot", "").lower()
            ]
        return {
            "employees": [
                {
                    "employee_id": row.get("employee_id", ""),
                    "name": row.get("employee_name_snapshot", ""),
                    "company": row.get("payroll_company_name_snapshot", ""),
                    "position": row.get("position_snapshot", ""),
                    "monthly_salary_total": row.get("monthly_salary_total", ""),
                }
                for row in snapshots[:80]
            ]
        }

    def _flow_card(
        self,
        title: str,
        object_type: str,
        object_id: str,
        objects: list[str],
        functions: list[str],
    ) -> dict:
        object_summaries = []
        for name in objects:
            object_def = self.ontology.objects.get(name)
            object_summaries.append({
                "name": name,
                "summary": object_def.summary if object_def else name,
                "count": self._safe_count(name),
            })
        function_summaries = []
        for name in functions:
            func = self.ontology.functions.get(name)
            function_summaries.append({
                "name": name,
                "summary": func.summary if func else name,
                "group": func.group if func else "",
            })
        return {
            "title": title,
            "object_type": object_type,
            "object_id": object_id,
            "objects": object_summaries,
            "functions": function_summaries,
        }

    def _object_header(self, object_type: str, object_id: str = "") -> dict:
        object_def = self.ontology.objects.get(object_type)
        record = self._find_record(object_type, object_id)
        return {
            "object_type": object_type,
            "object_id": object_id,
            "summary": object_def.summary if object_def else object_type,
            "description": object_def.description if object_def else "",
            "count": self._safe_count(object_type),
            "record": record,
            "display": self._display_name(object_type, object_id, record),
        }

    def _related_entries(self, object_type: str, object_id: str = "") -> list[dict]:
        entries = []
        for name, link in self.ontology.links.items():
            direction = ""
            target_type = ""
            filters = {}
            if link.source == object_type:
                direction = "out"
                target_type = link.target
                source_value = self._link_source_value(object_type, object_id, link.join.get("source_key", ""))
                if source_value not in ("", None):
                    filters = {link.join.get("target_key", ""): source_value}
            elif link.target == object_type:
                direction = "in"
                target_type = link.source
                target_value = self._link_source_value(object_type, object_id, link.join.get("target_key", ""))
                if target_value not in ("", None):
                    filters = {link.join.get("source_key", ""): target_value}
            else:
                continue
            count = self._safe_count(target_type, filters)
            samples = self.repository.query(target_type, filters, limit=3) if filters else self.repository.query(target_type, limit=3)
            entries.append({
                "name": name,
                "direction": direction,
                "target_type": target_type,
                "target_summary": self.ontology.objects.get(target_type).summary if target_type in self.ontology.objects else target_type,
                "description": link.description,
                "link_type": link.link_type,
                "cardinality": link.cardinality,
                "count": count,
                "filters": filters,
                "samples": [
                    {
                        "id": self._record_id(target_type, row),
                        "label": self._display_name(target_type, self._record_id(target_type, row), row),
                    }
                    for row in samples
                ],
            })
        return entries

    def _capability_entries(self, object_type: str, object_id: str = "") -> list[dict]:
        entries = []
        for name, func in self.ontology.functions.items():
            if object_type not in (func.involves_objects or []) and object_type not in (func.writes_to or []):
                continue
            params = self._params_for_context(func, object_type, object_id)
            runnable = name in {"calculate_payroll", "calculate_contributions", "build_payroll_snapshot", "generate_payroll_lines"}
            action = self._action_for_function(name)
            entries.append({
                "name": name,
                "summary": func.summary,
                "group": func.group,
                "description": func.description,
                "function_type": func.function_type,
                "depends_on": func.depends_on,
                "writes_to": func.writes_to,
                "params": params,
                "runnable": runnable or bool(action),
                "action": action,
            })
        group_order = {"输入导入": 0, "快照解析": 1, "薪资核算": 2, "社保公积金": 3, "校验审批": 4, "输出生成": 5, "成本归集": 6}
        return sorted(entries, key=lambda item: (group_order.get(item["group"], 99), item["name"]))

    def _params_for_context(self, func, object_type: str, object_id: str) -> dict:
        params = {}
        if "payroll_run_id" in func.params:
            params["payroll_run_id"] = object_id if object_type == "PayrollRun" and object_id else PAYROLL_RUN_ID
        if "employee_id" in func.params and object_type == "Employee" and object_id:
            params["employee_id"] = object_id
        return params

    def _action_for_function(self, function_name: str) -> str:
        return {
            "calculate_payroll": "approval_summary",
            "calculate_contributions": "confirm_deductions",
            "validate_payroll": "review_diffs",
            "submit_payroll_for_approval": "approval_summary",
        }.get(function_name, "")

    def _context_narrative(self, current: dict, related: list[dict], capabilities: list[dict]) -> str:
        relation_count = sum(item["count"] for item in related[:6])
        top_functions = "、".join(item["summary"] for item in capabilities[:3])
        return (
            f"当前对象是 {current['summary']}，本体中有 {len(related)} 类直接关系入口，"
            f"当前可见关联记录约 {relation_count} 条。"
            f"运行时根据 involves_objects 和 writes_to 暴露能力入口：{top_functions or '暂无'}。"
        )

    def _query_object_rows(self, object_type: str, object_id: str = "", limit: int = 20) -> list[dict]:
        if object_id:
            row = self._find_record(object_type, object_id)
            return [row] if row else []
        return self.repository.query(object_type, limit=limit)

    def _find_record(self, object_type: str, object_id: str = "") -> dict:
        if not object_id:
            return {}
        row = self.repository.query_by_id(object_type, object_id)
        if row:
            return row
        key = self._id_field(object_type)
        rows = self.repository.query(object_type, {key: object_id}, limit=1) if key else []
        return rows[0] if rows else {}

    def _link_source_value(self, object_type: str, object_id: str, key: str):
        record = self._find_record(object_type, object_id)
        if record and key in record:
            return record.get(key)
        return object_id if key == self._id_field(object_type) else ""

    def _safe_count(self, object_type: str, filters: dict | None = None) -> int:
        try:
            return self.repository.count(object_type, filters or {})
        except Exception:
            return 0

    def _record_id(self, object_type: str, row: dict) -> str:
        return row.get(self._id_field(object_type), "")

    def _id_field(self, object_type: str) -> str:
        snake = "".join([f"_{ch.lower()}" if ch.isupper() else ch for ch in object_type]).strip("_")
        candidates = [
            f"{snake}_id",
            "employee_id",
            "person_id",
            "company_id",
            "payroll_run_id",
            "payroll_line_id",
        ]
        object_def = self.ontology.objects.get(object_type)
        if object_def:
            for name, prop in object_def.properties.items():
                if getattr(prop, "required", False) and name.endswith("_id"):
                    return name
        for candidate in candidates:
            if object_def and candidate in object_def.properties:
                return candidate
        return candidates[0]

    def _display_name(self, object_type: str, object_id: str, record: dict) -> str:
        for key in (
            "employee_name_snapshot",
            "name",
            "company_name",
            "payroll_run_id",
            "payroll_line_id",
            "validation_id",
            "approval_id",
            "export_id",
        ):
            if record.get(key):
                return f"{object_id} · {record[key]}" if object_id and record[key] != object_id else str(record[key])
        return object_id or object_type

    def payroll(self, employee_id: str) -> dict:
        result = self.registry.call(
            "calculate_payroll",
            payroll_run_id=PAYROLL_RUN_ID,
            employee_id=employee_id,
        )
        line = (result.get("sample_calculated_lines") or [{}])[0]
        return {
            "status": result.get("status"),
            "diff_count": result.get("diff_count", 0),
            "warning_count": result.get("warning_count", 0),
            "answer_summary": result.get("answer_summary", []),
            "line": line,
            "items": result.get("sample_payroll_items", []),
            "warnings": result.get("warnings", []),
            "agent_explanation": self._deterministic_explanation(result),
        }

    def agent_explain(self, employee_id: str) -> dict:
        result = self.payroll(employee_id)
        fallback = result["agent_explanation"]
        harness = self._build_agent_harness()
        if not harness:
            return {"mode": "deterministic", "text": fallback, "tool_calls": []}

        tool = harness.tools.get("calculate_payroll")
        if tool:
            tool.max_result_chars = 100000

        prompt = (
            f"请解释 {PAYROLL_RUN_ID} 中 {employee_id} 的工资结果。"
            "只需要业务说明，不要展开工具 JSON。说明应包含应发、个人社保、个人公积金、个税、实发，"
            "并解释为什么社保公积金本次为 0。"
        )
        try:
            with tempfile.TemporaryDirectory() as tmp:
                client = harness.context_mgr.client
                agent = Agent(harness, client, model=harness.context_mgr.model, db_dir=tmp)
                text_parts: list[str] = []
                tool_calls: list[dict] = []
                for event in agent.chat_stream(prompt, session_id=f"explain-{employee_id}"):
                    if isinstance(event, TextEvent):
                        text_parts.append(event.content)
                    elif isinstance(event, ToolCallEvent):
                        tool_calls.append({"name": event.name, "args": event.args})
                text = "".join(text_parts).strip()
                if text:
                    return {"mode": "llm", "text": text, "tool_calls": tool_calls}
        except Exception as exc:
            return {"mode": "fallback", "text": fallback, "error": str(exc), "tool_calls": []}
        return {"mode": "fallback", "text": fallback, "tool_calls": []}

    def run_action(self, action: str, employee_id: str = "") -> dict:
        calculated = self.registry.call(
            "calculate_payroll",
            payroll_run_id=PAYROLL_RUN_ID,
            employee_id=employee_id,
            include_result_set=True,
            include_warnings=True,
        )
        if action == "review_diffs":
            return self._action_review_diffs(calculated, employee_id)
        if action == "confirm_deductions":
            return self._action_confirm_deductions(calculated, employee_id)
        if action == "approval_summary":
            return self._action_approval_summary(calculated, employee_id)
        return {
            "title": "未知动作",
            "markdown": f"未识别的动作 `{action}`。",
            "focus_employee_id": "",
        }

    def _build_agent_harness(self) -> Harness | None:
        if self._agent_harness:
            return self._agent_harness
        load_env(ROOT / ".env")
        api_key = os.environ.get("LLM_API_KEY", "")
        base_url = os.environ.get("LLM_API_URL", "")
        model = os.environ.get("LLM_MODEL", "")
        if not api_key or not base_url or not model:
            return None
        client = OpenAI(base_url=base_url, api_key=api_key)
        self._agent_harness = Harness(
            ontology=self.ontology,
            repository=self.repository,
            registry=self.registry,
            llm_client=client,
            model=model,
            config=HarnessConfig(
                enable_write_confirmation=False,
                max_turns=4,
                append_system_prompt=(
                    "你嵌在 OMS 业务界面里，不是通用聊天助手。"
                    "单个员工工资问题必须调用 calculate_payroll，并传 payroll_run_id 和 employee_id。"
                    "工具返回后直接根据 answer_summary 或 sample_calculated_lines 给出简洁业务说明。"
                ),
            ),
        )
        return self._agent_harness

    def _build_overview_brief(self, calculated: dict) -> str:
        diff_count = calculated.get("diff_count", 0)
        warning_count = calculated.get("warning_count", 0)
        if diff_count:
            return (
                f"批次 {PAYROLL_RUN_ID} 已完成预览计算，但仍有 {diff_count} 个工资行差异；"
                f"同时有 {warning_count} 条未确认扣款等提示。建议先处理差异员工，再进入审批。"
            )
        return (
            f"批次 {PAYROLL_RUN_ID} 已完成预览计算，工资行与当前 benchmark 对齐；"
            f"仍需关注 {warning_count} 条扣款确认提示。"
        )

    def _deterministic_explanation(self, result: dict) -> str:
        summary = (result.get("answer_summary") or [{}])[0]
        warnings = result.get("warnings", [])
        employee = summary.get("employee_id", "")
        name = summary.get("employee_name", "")
        lines = [
            f"{employee}（{name}）本次扣除前应发工资为 {_money(summary.get('gross_pay_before_deduction'))}。",
            (
                f"本次个人社保 {_money(summary.get('personal_social_security'))}，"
                f"个人公积金 {_money(summary.get('personal_housing_fund'))}，"
                f"个人所得税 {_money(summary.get('personal_income_tax'))}，"
                f"最终实发 {_money(summary.get('net_pay'))}。"
            ),
        ]
        if warnings:
            lines.append("系统提示：该员工当前没有已确认社保/公积金扣款台账，所以本次工资实扣按 0 处理，规则试算只作为缴费建议。")
        if result.get("diff_count", 0) == 0:
            lines.append("该员工工资结果与当前 benchmark 对齐。")
        return "\n".join(lines)

    def _action_review_diffs(self, calculated: dict, employee_id: str = "") -> dict:
        diffs = calculated.get("diffs") or calculated.get("sample_diffs") or []
        title = f"复核 {employee_id} 差异" if employee_id else "复核剩余差异"
        if not diffs:
            return {
                "title": title,
                "markdown": (
                    f"{employee_id} 工资行与 benchmark 对齐，没有需要复核的工资差异。"
                    if employee_id else "当前批次工资行与 benchmark 对齐，没有需要复核的工资差异。"
                ),
                "focus_employee_id": "",
            }
        first = diffs[0]
        rows = [
            "| 员工 | 差异字段 |",
            "| --- | --- |",
        ]
        for diff in diffs[:8]:
            fields = ", ".join(diff.get("fields", {}).keys())
            rows.append(f"| {diff.get('employee_id', '')} | {fields} |")
        return {
            "title": title,
            "markdown": (
                f"发现 **{calculated.get('diff_count', len(diffs))}** 个工资行差异。"
                + ("请优先检查该员工的输入快照、薪资规则和最终实发公式。\n\n" if employee_id else "系统已定位第一位差异员工，建议从该员工开始复核。\n\n")
                + "\n".join(rows)
            ),
            "focus_employee_id": first.get("employee_id", ""),
        }

    def _action_confirm_deductions(self, calculated: dict, employee_id: str = "") -> dict:
        warnings = [
            warning for warning in (calculated.get("warnings") or [])
            if warning.get("rule_code") in {
                "social_deduction_unconfirmed",
                "housing_deduction_unconfirmed",
            }
        ]
        title = f"确认 {employee_id} 扣款" if employee_id else "确认社保公积金扣款台账"
        if employee_id:
            if not warnings:
                return {
                    "title": title,
                    "markdown": f"{employee_id} 没有未确认社保/公积金扣款提示，可进入后续复核。",
                    "focus_employee_id": "",
                }
            rows = [
                "| 规则 | 提示 |",
                "| --- | --- |",
            ]
            for warning in warnings:
                rows.append(f"| {warning.get('rule_code', '')} | {warning.get('message', '')} |")
            return {
                "title": title,
                "markdown": (
                    f"{employee_id} 有 **{len(warnings)}** 条未确认扣款提示。\n\n"
                    + "\n".join(rows)
                    + "\n\n处理建议：确认该员工 `ContributionDeduction` 台账后复算工资。"
                ),
                "focus_employee_id": "",
            }
        employees = sorted({warning.get("employee_id", "") for warning in warnings if warning.get("employee_id")})
        sample = ", ".join(employees[:12])
        more = len(employees) - 12
        tail = f" 等 {len(employees)} 人" if more > 0 else ""
        return {
            "title": title,
            "markdown": (
                f"当前有 **{len(warnings)}** 条未确认扣款提示，涉及 **{len(employees)}** 名员工。\n\n"
                f"样例员工：{sample}{tail}\n\n"
                "处理建议：\n"
                "1. 导入或确认 `ContributionDeduction` 台账。\n"
                "2. 再运行 `calculate_payroll` 复算实扣金额。\n"
                "3. 审批前确认未确认扣款提示已清零或有人工说明。"
            ),
            "focus_employee_id": employees[0] if employees else "",
        }

    def _action_approval_summary(self, calculated: dict, employee_id: str = "") -> dict:
        lines = calculated.get("result_set", {}).get("PayrollLine", [])
        gross_total = sum(_num(row.get("gross_pay_before_deduction")) for row in lines)
        tax_total = sum(_num(row.get("personal_income_tax")) for row in lines)
        net_total = sum(_num(row.get("net_pay")) for row in lines)
        if employee_id:
            line = lines[0] if lines else {}
            return {
                "title": f"生成 {employee_id} 审批说明",
                "markdown": (
                    f"### {employee_id} 员工工资审批说明\n\n"
                    f"- 员工姓名：**{line.get('employee_name_snapshot', '')}**\n"
                    f"- 扣前应发：**{_money(line.get('gross_pay_before_deduction'))}**\n"
                    f"- 个人社保：**{_money(line.get('personal_social_security'))}**\n"
                    f"- 个人公积金：**{_money(line.get('personal_housing_fund'))}**\n"
                    f"- 个人所得税：**{_money(line.get('personal_income_tax'))}**\n"
                    f"- 实发工资：**{_money(line.get('net_pay'))}**\n"
                    f"- 工资行差异：**{calculated.get('diff_count', 0)}**\n"
                    f"- 系统提示：**{calculated.get('warning_count', 0)}**\n\n"
                    "审批建议：若差异为 0，仅需确认扣款提示是否已有人工说明。"
                ),
                "focus_employee_id": "",
            }
        return {
            "title": "提交审批前摘要",
            "markdown": (
                "### PAYROLL_202604 审批摘要\n\n"
                f"- 计算人数：**{calculated.get('calculated_count', 0)}**\n"
                f"- 扣前应发合计：**{_money(gross_total)}**\n"
                f"- 个税合计：**{_money(tax_total)}**\n"
                f"- 实发合计：**{_money(net_total)}**\n"
                f"- 工资行差异：**{calculated.get('diff_count', 0)}**\n"
                f"- 系统提示：**{calculated.get('warning_count', 0)}**\n\n"
                "审批建议：先复核剩余差异和未确认扣款提示，再提交审批。"
            ),
            "focus_employee_id": "",
        }


RUNTIME = OmsRuntime()


class Handler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            path = STATIC_DIR / "index.html"
        elif parsed.path.startswith("/static/"):
            path = STATIC_DIR / parsed.path.removeprefix("/static/")
        else:
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
        if parsed.path == "/":
            return self._static("index.html")
        if parsed.path.startswith("/static/"):
            return self._static(parsed.path.removeprefix("/static/"))
        if parsed.path == "/api/domain":
            return self._json(RUNTIME.domain())
        if parsed.path == "/api/context":
            params = parse_qs(parsed.query)
            object_type = params.get("object_type", ["PayrollRun"])[0]
            object_id = params.get("object_id", [PAYROLL_RUN_ID])[0]
            return self._json(RUNTIME.context(object_type, object_id))
        if parsed.path == "/api/object":
            params = parse_qs(parsed.query)
            object_type = params.get("object_type", ["PayrollRun"])[0]
            object_id = params.get("object_id", [""])[0]
            return self._json(RUNTIME.object_detail(object_type, object_id))
        if parsed.path == "/api/overview":
            return self._json(RUNTIME.overview())
        if parsed.path == "/api/employees":
            params = parse_qs(parsed.query)
            return self._json(RUNTIME.employees(params.get("q", [""])[0]))
        if parsed.path == "/api/payroll":
            params = parse_qs(parsed.query)
            employee_id = params.get("employee_id", ["EMP074"])[0]
            return self._json(RUNTIME.payroll(employee_id))
        if parsed.path == "/api/agent/explain":
            params = parse_qs(parsed.query)
            employee_id = params.get("employee_id", ["EMP074"])[0]
            return self._json(RUNTIME.agent_explain(employee_id))
        if parsed.path == "/api/action":
            params = parse_qs(parsed.query)
            action = params.get("action", [""])[0]
            employee_id = params.get("employee_id", [""])[0]
            return self._json(RUNTIME.run_action(action, employee_id))
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


def load_env(path: Path):
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"").strip("'"))


def _num(value) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _money(value) -> str:
    return f"{_num(value):,.2f} 元"


def main():
    port = int(os.environ.get("OMS_PROTOTYPE_PORT", "8765"))
    host = os.environ.get("OMS_PROTOTYPE_HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"OMS prototype running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
