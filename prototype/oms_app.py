from __future__ import annotations

import json
import os
import sys
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
PAYROLL_RUN_ID = "PAYROLL_202604"
DEFAULT_COMPANY_ID = "COMP_SCNY"


class OmsRuntime:
    def __init__(self):
        self.ontology, self.repository, self.registry = load_domain(DOMAIN_DIR)
        self.actions = _load_actions(DOMAIN_DIR / "actions.yaml")

    def action_ref(self, action_id: str, context: dict | None = None, label: str = "") -> dict:
        action_context = self._default_action_context()
        action_context.update(context or {})
        return _instantiate_action(
            self.actions.get(action_id, {}),
            action_id,
            action_context,
            label,
        )

    def _default_action_context(self) -> dict:
        run = self.repository.query_by_id("PayrollRun", PAYROLL_RUN_ID) or {}
        period = run.get("payroll_period") or "2026-04"
        company_id = DEFAULT_COMPANY_ID
        snapshots = self.repository.query(
            "PayrollEmployeeSnapshot",
            {"payroll_run_id": PAYROLL_RUN_ID},
            limit=1,
        )
        if snapshots and snapshots[0].get("payroll_company_id"):
            company_id = snapshots[0].get("payroll_company_id")
        return {
            "payroll_run_id": PAYROLL_RUN_ID,
            "employee_id": "EMP074",
            "object_type": "Employee",
            "object_id": "",
            "company_id": company_id,
            "period": period,
            "as_of_date": f"{period}-30",
        }

    def app_state(self) -> dict:
        payroll = self.payroll_overview()
        return {
            "product": {
                "name": "Fox OMS",
                "tagline": "Ontology-native enterprise resource management",
                "description": self.ontology.description,
            },
            "modules": [
                {"id": "home", "label": "总览", "object_types": ["PayrollRun", "Employee", "Company"]},
                {"id": "people", "label": "人员", "object_types": ["Person", "Employee", "EmploymentRelationship", "SalaryProfile"]},
                {"id": "payroll", "label": "薪资", "object_types": ["PayrollRun", "PayrollLine", "PayrollItem", "TaxLedger"]},
                {"id": "ontology", "label": "本体", "object_types": list(self.ontology.objects.keys())[:30]},
            ],
            "dashboard": {
                "metrics": [
                    {"label": "员工", "value": self.repository.count("Employee"), "detail": "Employee"},
                    {"label": "发薪主体", "value": self.repository.count("Company", {"payroll_enabled": 1}), "detail": "Company"},
                    {"label": "本体对象", "value": len(self.ontology.objects), "detail": "Ontology"},
                    {"label": "业务能力", "value": len(self.ontology.functions), "detail": "Functions"},
                ],
                "attention": self._attention_items(payroll),
                "resource_map": self._resource_map(),
            },
            "payroll": payroll,
            "agent": self._agent_panel(
                title="系统态势",
                summary=(
                    "OMS 保留稳定的资源管理骨架；本体提供对象、关系、规则和能力；"
                    "智能层负责解释当前状态、推荐下一步和追溯依据。"
                ),
                next_actions=self.resolve_actions(
                    "PayrollRun",
                    PAYROLL_RUN_ID,
                    signals=payroll["counts"],
                    limit=5,
                ),
                evidence=[
                    "PayrollRun.status",
                    "calculate_payroll.diff_count",
                    "ContributionDeduction.status",
                ],
            ),
        }

    def employees(self, query: str = "", limit: int = 80) -> dict:
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
                or needle in row.get("payroll_company_name_snapshot", "").lower()
            ]
        rows = [
            {
                "employee_id": row.get("employee_id", ""),
                "name": row.get("employee_name_snapshot", ""),
                "company": row.get("payroll_company_name_snapshot", ""),
                "position": row.get("position_snapshot", ""),
                "monthly_salary_total": row.get("monthly_salary_total", ""),
            }
            for row in snapshots[:limit]
        ]
        return {
            "total": len(snapshots),
            "rows": rows,
            "agent": self._agent_panel(
                title="人员资源视图",
                summary="人员模块展示企业内自然人、员工身份、任职关系和薪资档案。进入员工后，智能层会自动串联薪资、扣款和个税上下文。",
                next_actions=self.resolve_actions(
                    "Employee",
                    "EMP074",
                    context={"employee_id": "EMP074"},
                    seed_actions=["people.search", "employee.open_current"],
                    limit=5,
                ),
                evidence=["Employee", "EmploymentRelationship", "SalaryProfile", "PayrollEmployeeSnapshot"],
            ),
        }

    def employee_detail(self, employee_id: str) -> dict:
        employee = self.repository.query_by_id("Employee", employee_id) or {}
        person = self.repository.query_by_id("Person", employee.get("person_id", "")) if employee else {}
        relationships = self.repository.query("EmploymentRelationship", {"employee_id": employee_id})
        salary_profiles = self.repository.query("SalaryProfile", {"employee_id": employee_id})
        payroll = self.payroll_employee(employee_id)
        return {
            "employee": employee,
            "person": person or {},
            "relationships": relationships,
            "salary_profiles": salary_profiles,
            "payroll": payroll,
            "agent": self._agent_panel(
                title=f"{employee_id} 资源上下文",
                summary=self._employee_summary(employee_id, payroll),
                next_actions=self._employee_next_actions(employee_id, payroll),
                evidence=[
                    "Employee.person_id -> Person",
                    "EmploymentRelationship.effective_date",
                    "SalaryProfile.effective_date",
                    "PayrollEmployeeSnapshot",
                    "calculate_payroll",
                ],
            ),
        }

    def actions_for_context(
        self,
        object_type: str = "PayrollRun",
        object_id: str = PAYROLL_RUN_ID,
        employee_id: str = "EMP074",
    ) -> dict:
        context = {
            "object_type": object_type,
            "object_id": object_id,
            "employee_id": employee_id,
            "payroll_run_id": PAYROLL_RUN_ID,
            "company_id": DEFAULT_COMPANY_ID,
            "period": "2026-04",
            "as_of_date": "2026-04-30",
        }
        if object_type == "Employee":
            payroll = self.payroll_employee(employee_id)
            line = payroll.get("line") or {}
            context["object_id"] = employee_id
            context["company_id"] = line.get("payroll_company_id") or DEFAULT_COMPANY_ID
            actions = self._employee_next_actions(employee_id, payroll)
        elif object_type == "PayrollRun":
            calculated = self.registry.call(
                "calculate_payroll",
                payroll_run_id=object_id or PAYROLL_RUN_ID,
                include_warnings=True,
            )
            actions = self._payroll_next_actions(calculated)
        else:
            actions = self.resolve_actions(object_type, object_id, context=context, limit=8)
        return {
            "context": context,
            "actions": actions,
        }

    def resolve_actions(
        self,
        object_type: str,
        object_id: str = "",
        context: dict | None = None,
        signals: dict | None = None,
        seed_actions: list[str] | None = None,
        limit: int = 6,
    ) -> list[dict]:
        action_context = self._context_for_object(object_type, object_id)
        action_context.update(context or {})
        signals = signals or {}
        candidate_ids = self._ontology_candidate_action_ids(object_type)
        candidate_ids.extend(seed_actions or [])
        candidate_ids.extend(self._signal_action_ids(object_type, signals))
        candidate_ids.extend(["ontology.open", "home.open"])

        scored = []
        for action_id in _dedupe(candidate_ids):
            action = self.action_ref(action_id, action_context)
            action = self._apply_relation_filter(action, object_type, action_context)
            action = self._apply_ontology_guards(action, object_type, object_id)
            action["inferred_from"] = self._action_inference(action, object_type, signals)
            scored.append((self._action_score(action, object_type, signals), action))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [action for _, action in scored[:limit]]

    def _context_for_object(self, object_type: str, object_id: str = "") -> dict:
        context = self._default_action_context()
        context.update({
            "object_type": object_type,
            "object_id": object_id,
        })
        if object_type == "Employee":
            employee_id = object_id or context.get("employee_id") or "EMP074"
            context["employee_id"] = employee_id
            payroll = self.payroll_employee(employee_id)
            line = payroll.get("line") or {}
            if line.get("payroll_company_id"):
                context["company_id"] = line.get("payroll_company_id")
        elif object_type == "PayrollRun":
            context["payroll_run_id"] = object_id or PAYROLL_RUN_ID
            run = self.repository.query_by_id("PayrollRun", context["payroll_run_id"]) or {}
            if run.get("payroll_period"):
                context["period"] = run.get("payroll_period")
                context["as_of_date"] = f"{run.get('payroll_period')}-30"
        elif object_type == "Company":
            context["company_id"] = object_id or context.get("company_id") or DEFAULT_COMPANY_ID
        return context

    def _ontology_candidate_action_ids(self, object_type: str) -> list[str]:
        candidates = []
        related_objects = {object_type}
        for link in self.ontology.links.values():
            if link.source == object_type:
                related_objects.add(link.target)
            if link.target == object_type:
                related_objects.add(link.source)

        for action_id, action_def in self.actions.items():
            if not self._action_namespace_matches(action_id, object_type):
                continue
            if action_id == "ontology.employee" and object_type != "Employee":
                continue
            if action_id == "ontology.payroll_run" and object_type != "PayrollRun":
                continue
            target = action_def.get("target", {}) or {}
            function_name = target.get("function", "")
            target_object = target.get("object_type", "")
            if function_name and self._function_matches_object(function_name, object_type):
                candidates.append(action_id)
            elif target_object and target_object in related_objects:
                candidates.append(action_id)
        return candidates

    def _action_namespace_matches(self, action_id: str, object_type: str) -> bool:
        if action_id.startswith("resources.") or action_id.startswith("ontology."):
            return True
        if object_type == "Employee":
            return action_id.startswith("employee.")
        if object_type == "PayrollRun":
            return action_id.startswith("payroll.")
        if object_type == "Company":
            return action_id.startswith("company.")
        if object_type in {
            "AttendanceSummary",
            "PerformanceRecord",
            "PayrollAdjustment",
            "ContributionDeduction",
            "TaxLedger",
            "Payslip",
            "CostEntry",
            "ApprovalRecord",
            "SalaryProfile",
            "EmploymentRelationship",
        }:
            return action_id.startswith("resources.")
        return False

    def _function_matches_object(self, function_name: str, object_type: str) -> bool:
        fn = self.ontology.functions.get(function_name)
        if not fn:
            return False
        if object_type in (fn.involves_objects or []) or object_type in (fn.writes_to or []):
            return True
        params = fn.params or {}
        if object_type == "Employee" and "employee_id" in params:
            return True
        if object_type == "PayrollRun" and "payroll_run_id" in params:
            return True
        if object_type == "Company" and "company_id" in params:
            return True
        return False

    def _signal_action_ids(self, object_type: str, signals: dict) -> list[str]:
        if object_type != "PayrollRun":
            return []
        actions = []
        if signals.get("diffs") or signals.get("diff_count"):
            actions.append("payroll.review_diffs")
        if signals.get("warnings") or signals.get("warning_count") or signals.get("deduction_warning_employees"):
            actions.append("payroll.confirm_deductions")
        actions.append("payroll.approval_summary")
        return actions

    def _apply_ontology_guards(self, action: dict, object_type: str, object_id: str = "") -> dict:
        function_name = (action.get("target") or {}).get("function", "")
        if not function_name:
            return action
        guarded = dict(action)
        status_reason = self._status_guard_reason(function_name, object_type, object_id)
        if status_reason:
            guarded["enabled"] = False
            guarded["disabled_reason"] = status_reason
        if guarded.get("enabled", True):
            precondition_reason = self._precondition_guard_reason(function_name, object_type, object_id)
            if precondition_reason:
                guarded["enabled"] = False
                guarded["disabled_reason"] = precondition_reason
        return guarded

    def _apply_relation_filter(self, action: dict, object_type: str, context: dict) -> dict:
        target = action.get("target") or {}
        target_object = target.get("object_type", "")
        if action.get("kind") != "navigate" or not target_object or target_object == object_type:
            return action

        current_id_field = self.ontology.get_id_column(object_type)
        current_id = context.get(current_id_field or "") or context.get("object_id", "")
        if not current_id:
            return action

        for link_name, link in self.ontology.links.items():
            filters = {}
            if link.source == object_type and link.target == target_object:
                filters[link.join.get("target_key", "")] = context.get(link.join.get("source_key", ""), current_id)
            elif link.target == object_type and link.source == target_object:
                filters[link.join.get("source_key", "")] = context.get(link.join.get("target_key", ""), current_id)
            filters = {key: value for key, value in filters.items() if key and value}
            if not filters:
                continue
            enriched = dict(action)
            enriched_target = dict(target)
            enriched_target["filters"] = filters
            enriched_target["via_link"] = link_name
            enriched["target"] = enriched_target
            return enriched
        return action

    def _status_guard_reason(self, function_name: str, object_type: str, object_id: str = "") -> str:
        obj_def = self.ontology.objects.get(object_type)
        if not obj_def:
            return ""
        record = self.repository.query_by_id(object_type, object_id) if object_id else {}
        status = (record or {}).get("status", "")
        if not status:
            return ""
        for constraint in obj_def.constraints or []:
            if constraint.when.get("status") == status and function_name in constraint.excluded_functions:
                return constraint.reason
        return ""

    def _precondition_guard_reason(self, function_name: str, object_type: str, object_id: str = "") -> str:
        fn = self.ontology.functions.get(function_name)
        if not fn:
            return ""
        for precondition in fn.preconditions or []:
            if precondition.object != object_type or precondition.field != "status":
                continue
            record = self.repository.query_by_id(object_type, object_id) if object_id else {}
            current = (record or {}).get("status", "")
            if precondition.operator == "eq" and current != precondition.value:
                return f"需要 {object_type}.status = {precondition.value}，当前为 {current or '未知'}。"
        return ""

    def _action_score(self, action: dict, object_type: str, signals: dict) -> int:
        score = 0
        action_id = action.get("id", "")
        if action.get("enabled", True):
            score += 20
        else:
            score -= 30
        if action.get("kind") == "ontology_function":
            score += 12
        if action.get("kind") == "navigate":
            score += 4
        if object_type == "PayrollRun":
            if action_id == "payroll.review_diffs" and (signals.get("diffs") or signals.get("diff_count")):
                score += 60
            if action_id == "payroll.confirm_deductions" and (
                signals.get("warnings") or signals.get("warning_count") or signals.get("deduction_warning_employees")
            ):
                score += 55
            if action_id in {"payroll.build_snapshot_status", "payroll.calculate_batch_preview", "company.resolve_rules"}:
                score += 20
        if object_type == "Employee":
            if action_id in {"employee.resolve_state", "employee.calculate_payroll_preview", "employee.calculate_contributions_preview"}:
                score += 35
            if action_id == "employee.explain_payroll":
                score += 28
        if action_id.startswith("resources."):
            score += 8
        if action_id in {"home.open", "ontology.open"}:
            score -= 10
        return score

    def _action_inference(self, action: dict, object_type: str, signals: dict) -> list[str]:
        action_id = action.get("id", "")
        function_name = (action.get("target") or {}).get("function", "")
        inferred = [f"context.object_type={object_type}"]
        if function_name:
            fn = self.ontology.functions.get(function_name)
            inferred.append(f"ontology.functions.{function_name}")
            if fn:
                if object_type in (fn.involves_objects or []):
                    inferred.append("function.involves_objects")
                if object_type in (fn.writes_to or []):
                    inferred.append("function.writes_to")
                if fn.depends_on:
                    inferred.append(f"function.depends_on={','.join(fn.depends_on)}")
                if fn.preconditions:
                    inferred.append("function.preconditions")
        target_object = (action.get("target") or {}).get("object_type", "")
        if target_object:
            inferred.append(f"target.object_type={target_object}")
        if action_id == "payroll.review_diffs" and (signals.get("diffs") or signals.get("diff_count")):
            inferred.append("runtime.diff_count>0")
        if action_id == "payroll.confirm_deductions" and (
            signals.get("warnings") or signals.get("warning_count") or signals.get("deduction_warning_employees")
        ):
            inferred.append("runtime.warning_count>0")
        if action.get("disabled_reason"):
            inferred.append("runtime.guard.disabled")
        return inferred

    def execute_action(self, action_id: str, context: dict | None = None) -> dict:
        action_context = self._default_action_context()
        action_context.update(context or {})
        action = self.action_ref(action_id, action_context)
        if not action.get("enabled", True):
            return {
                "status": "disabled",
                "action": action,
                "message": action.get("disabled_reason") or "该动作当前不可执行。",
            }
        if action.get("kind") != "ontology_function":
            return {
                "status": "unsupported",
                "action": action,
                "message": "当前执行通道只支持 ontology_function action。",
            }
        if action.get("side_effect") not in {"read_only", "preview"}:
            return {
                "status": "disabled",
                "action": action,
                "message": "当前原型只允许执行只读或预览类本体函数。",
            }

        function_name = (action.get("target") or {}).get("function", "")
        if not function_name:
            return {"status": "error", "action": action, "message": "Action 未声明目标函数。"}
        try:
            result = self.registry.call(function_name, **(action.get("params") or {}))
            presentation = self.present_action_result(action, result)
            return {
                "status": "success",
                "action": action,
                "result": result,
                "presentation": presentation,
                "message": _action_result_message(function_name, result),
            }
        except Exception as exc:
            return {
                "status": "error",
                "action": action,
                "message": str(exc),
            }

    def present_action_result(self, action: dict, result) -> dict:
        function_name = (action.get("target") or {}).get("function", "")
        if not isinstance(result, dict):
            return {"summary": str(result), "highlights": [], "next_actions": []}
        if result.get("error"):
            return {"summary": str(result.get("error")), "highlights": [], "next_actions": []}

        if function_name == "calculate_payroll":
            return self._present_payroll_calculation(action, result)
        if function_name == "calculate_contributions":
            return self._present_contribution_calculation(action, result)
        if function_name == "resolve_employee_state_at":
            return self._present_employee_state(result)
        if function_name == "resolve_rules_at":
            return self._present_rules(result)
        if function_name == "build_payroll_snapshot":
            return self._present_snapshot(result)
        if function_name == "generate_payroll_lines":
            return self._present_generate_lines(result)
        return {
            "summary": _action_result_message(function_name, result),
            "highlights": _result_highlights(result),
            "next_actions": [],
        }

    def _present_payroll_calculation(self, action: dict, result: dict) -> dict:
        summary_rows = result.get("answer_summary") or []
        employee_id = result.get("employee_id", "")
        if employee_id and summary_rows:
            row = summary_rows[0]
            summary = (
                f"{employee_id} 本次薪资试算完成：扣前应发 {_money(row.get('gross_pay_before_deduction'))}，"
                f"个人社保 {_money(row.get('personal_social_security'))}，"
                f"个人公积金 {_money(row.get('personal_housing_fund'))}，"
                f"个税 {_money(row.get('personal_income_tax'))}，"
                f"实发 {_money(row.get('net_pay'))}。"
            )
        else:
            summary = (
                f"{result.get('payroll_run_id', PAYROLL_RUN_ID)} 整批薪资试算完成，"
                f"共 {result.get('calculated_count', 0)} 条工资明细，"
                f"{result.get('diff_count', 0)} 个差异，{result.get('warning_count', 0)} 条提示。"
            )
        highlights = [
            {"label": "工资行", "value": result.get("calculated_count", 0)},
            {"label": "工资项", "value": result.get("payroll_item_count", 0)},
            {"label": "差异", "value": result.get("diff_count", 0)},
            {"label": "提示", "value": result.get("warning_count", 0)},
        ]
        if employee_id:
            highlights.append({"label": "员工", "value": employee_id})
        return {
            "summary": summary,
            "highlights": highlights,
            "warnings": [w.get("message", str(w)) for w in (result.get("warnings") or result.get("sample_warnings") or [])[:3]],
            "next_actions": [
                self.action_ref("employee.explain_payroll", {"employee_id": employee_id}) if employee_id else self.action_ref("payroll.review_diffs"),
                self._contextual_action_ref(
                    "resources.tax_ledger",
                    "Employee" if employee_id else "PayrollRun",
                    employee_id or result.get("payroll_run_id", PAYROLL_RUN_ID),
                ),
            ],
        }

    def _present_contribution_calculation(self, action: dict, result: dict) -> dict:
        employee_id = result.get("employee_id", "")
        scope = employee_id or result.get("payroll_run_id", PAYROLL_RUN_ID)
        summary = (
            f"{scope} 社保公积金试算完成：社保 {result.get('social_contribution_count', 0)} 条，"
            f"公积金 {result.get('housing_fund_count', 0)} 条，扣款台账 {result.get('deduction_count', 0)} 条；"
            f"{result.get('warning_count', 0)} 条提示，{result.get('diff_count', 0)} 个差异。"
        )
        return {
            "summary": summary,
            "highlights": [
                {"label": "社保记录", "value": result.get("social_contribution_count", 0)},
                {"label": "公积金记录", "value": result.get("housing_fund_count", 0)},
                {"label": "扣款台账", "value": result.get("deduction_count", 0)},
                {"label": "缴费月", "value": result.get("contribution_period", "")},
            ],
            "warnings": [w.get("message", str(w)) for w in (result.get("warnings") or result.get("sample_warnings") or [])[:3]],
            "next_actions": [
                self._contextual_action_ref(
                    "resources.contribution_deductions",
                    "Employee" if employee_id else "PayrollRun",
                    employee_id or result.get("payroll_run_id", PAYROLL_RUN_ID),
                )
            ],
        }

    def _present_employee_state(self, result: dict) -> dict:
        missing = result.get("missing") or []
        summary = (
            f"{result.get('employee_id', '')} 在 {result.get('as_of_date', '')} 的状态已解析："
            f"{result.get('employment_status', '')}，"
            f"发薪主体 {result.get('payroll_company_name', '') or result.get('payroll_company_id', '')}，"
            f"薪资档案 {result.get('salary_profile_id', '')}。"
        )
        if missing:
            summary += f" 缺少输入：{', '.join(missing)}。"
        return {
            "summary": summary,
            "highlights": [
                {"label": "员工", "value": result.get("employee_id", "")},
                {"label": "公司", "value": result.get("payroll_company_name", "")},
                {"label": "任职关系", "value": result.get("employment_relationship_id", "")},
                {"label": "薪资档案", "value": result.get("salary_profile_id", "")},
            ],
            "warnings": [f"缺少 {item}" for item in missing],
            "next_actions": [
                self._contextual_action_ref("resources.relationships", "Employee", result.get("employee_id", "")),
                self._contextual_action_ref("resources.salary_profiles", "Employee", result.get("employee_id", "")),
            ],
        }

    def _present_rules(self, result: dict) -> dict:
        missing = []
        if not result.get("social_insurance_rule"):
            missing.append("社保规则")
        if not result.get("housing_fund_rule"):
            missing.append("公积金规则")
        summary = (
            f"{result.get('company_name', result.get('company_id', ''))} / {result.get('period', '')} 规则解析完成："
            f"薪资拆分规则 {len(result.get('salary_split_rules') or [])} 条，"
            f"绩效规则 {len(result.get('performance_grade_rules') or [])} 条，"
            f"个税税率 {len(result.get('tax_rate_rules') or [])} 档。"
        )
        if missing:
            summary += f" 当前未找到 {', '.join(missing)}。"
        return {
            "summary": summary,
            "highlights": [
                {"label": "公司", "value": result.get("company_name", "")},
                {"label": "月份", "value": result.get("period", "")},
                {"label": "薪资拆分", "value": len(result.get("salary_split_rules") or [])},
                {"label": "绩效规则", "value": len(result.get("performance_grade_rules") or [])},
            ],
            "warnings": [f"未找到 {item}" for item in missing],
            "next_actions": [self.action_ref("resources.rules", {"object_type": "Company", "company_id": result.get("company_id", "")})],
        }

    def _present_snapshot(self, result: dict) -> dict:
        return {
            "summary": (
                f"{result.get('payroll_run_id', '')} 快照状态为 {result.get('status', '')}，"
                f"快照 {result.get('snapshot_id', '')} 覆盖 {result.get('employee_snapshot_count', 0)} 名员工，"
                f"校验提示 {result.get('validation_warning_count', 0)} 条。"
            ),
            "highlights": [
                {"label": "快照", "value": result.get("snapshot_id", "")},
                {"label": "员工快照", "value": result.get("employee_snapshot_count", 0)},
                {"label": "工资行", "value": result.get("payroll_line_count", 0)},
                {"label": "提示", "value": result.get("validation_warning_count", 0)},
            ],
            "next_actions": [self.action_ref("payroll.generate_lines_preview")],
        }

    def _present_generate_lines(self, result: dict) -> dict:
        return {
            "summary": (
                f"{result.get('payroll_run_id', '')} 工资明细预览完成，"
                f"生成 {result.get('generated_count', 0)} 条工资行，"
                f"{result.get('diff_count', 0)} 个差异，{result.get('warning_count', 0)} 条提示。"
            ),
            "highlights": _result_highlights(result),
            "next_actions": [self.action_ref("payroll.calculate_batch_preview")],
        }

    def _contextual_action_ref(self, action_id: str, object_type: str, object_id: str = "") -> dict:
        context = self._context_for_object(object_type, object_id)
        action = self.action_ref(action_id, context)
        return self._apply_relation_filter(action, object_type, context)

    def payroll_overview(self) -> dict:
        run = self.repository.query_by_id("PayrollRun", PAYROLL_RUN_ID) or {}
        calculated = self.registry.call(
            "calculate_payroll",
            payroll_run_id=PAYROLL_RUN_ID,
            include_result_set=True,
            include_warnings=True,
        )
        lines = calculated.get("result_set", {}).get("PayrollLine", [])
        warnings = calculated.get("warnings") or calculated.get("sample_warnings") or []
        deduction_warnings = [
            warning for warning in warnings
            if warning.get("rule_code") in {"social_deduction_unconfirmed", "housing_deduction_unconfirmed"}
        ]
        diff_rows = calculated.get("sample_diffs", [])
        totals = {
            "gross": round(sum(_num(row.get("gross_pay_before_deduction")) for row in lines), 2),
            "tax": round(sum(_num(row.get("personal_income_tax")) for row in lines), 2),
            "net": round(sum(_num(row.get("net_pay")) for row in lines), 2),
            "cost": round(sum(_num(row.get("company_total_cost")) for row in lines), 2),
        }
        return {
            "run": run,
            "counts": {
                "employees": len(lines),
                "diffs": calculated.get("diff_count", 0),
                "warnings": calculated.get("warning_count", 0),
                "deduction_warning_employees": len({w.get("employee_id") for w in deduction_warnings if w.get("employee_id")}),
            },
            "totals": totals,
            "sample_lines": lines[:12],
            "sample_diffs": diff_rows[:8],
            "agent": self._agent_panel(
                title="薪资批次判断",
                summary=self._payroll_summary(calculated, totals),
                next_actions=self._payroll_next_actions(calculated),
                evidence=[
                    "PayrollInputSnapshot",
                    "PayrollEmployeeSnapshot",
                    "SalarySplitRule",
                    "PerformanceGradeRule",
                    "TaxRateRule",
                    "ContributionDeduction",
                ],
            ),
        }

    def payroll_employee(self, employee_id: str) -> dict:
        result = self.registry.call(
            "calculate_payroll",
            payroll_run_id=PAYROLL_RUN_ID,
            employee_id=employee_id,
        )
        line = (result.get("sample_calculated_lines") or [{}])[0]
        return {
            "status": result.get("status", ""),
            "line": line,
            "items": result.get("sample_payroll_items", []),
            "warnings": result.get("warnings", []),
            "diffs": result.get("diffs", []),
            "summary": (result.get("answer_summary") or [{}])[0],
        }

    def object_context(self, object_type: str, object_id: str = "", filters: dict | None = None) -> dict:
        object_def = self.ontology.objects.get(object_type)
        filters = {key: value for key, value in (filters or {}).items() if value}
        rows = self.repository.query(object_type, filters, limit=20) if not object_id else []
        if object_id:
            row = self.repository.query_by_id(object_type, object_id) or {}
            rows = [row] if row else []
        related = []
        for name, link in self.ontology.links.items():
            if link.source == object_type or link.target == object_type:
                related.append({
                    "name": name,
                    "source": link.source,
                    "target": link.target,
                    "description": link.description,
                })
        functions = [
            {"name": name, "summary": fn.summary, "group": fn.group}
            for name, fn in self.ontology.functions.items()
            if object_type in (fn.involves_objects or []) or object_type in (fn.writes_to or [])
        ]
        return {
            "object": {
                "type": object_type,
                "summary": object_def.summary if object_def else object_type,
                "description": object_def.description if object_def else "",
                "count": (
                    self.repository.count(object_type, filters)
                    if object_type in self.ontology.objects else 0
                ),
                "filters": filters,
            },
            "rows": rows,
            "related": related[:12],
            "functions": functions[:12],
            "agent": self._agent_panel(
                title=f"{object_type} 本体上下文",
                summary="本体层把资源对象、关系和可执行能力组织成业务语义网络，供页面、工具和智能层共同使用。",
                next_actions=self.resolve_actions(object_type, object_id, limit=8),
                evidence=[object_type, "ontology.links", "ontology.functions"],
            ),
        }

    def explain_payroll(self, employee_id: str) -> dict:
        payroll = self.payroll_employee(employee_id)
        fallback = self._deterministic_payroll_explanation(employee_id, payroll)
        client = _llm_client()
        if not client:
            return {"mode": "deterministic", "text": fallback}
        prompt = (
            "请用企业薪资管理系统内的业务说明口吻解释该员工工资。"
            "必须包含扣前应发、社保、公积金、个税、实发，以及社保公积金为 0 的原因。"
            "不要说自己是 AI。\n\n"
            f"{json.dumps(payroll, ensure_ascii=False)[:16000]}"
        )
        try:
            response = client.chat.completions.create(
                model=os.environ.get("LLM_MODEL", ""),
                messages=[
                    {"role": "system", "content": "你是 OMS 内嵌的薪资业务说明层，只输出业务说明。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            text = response.choices[0].message.content or fallback
            return {"mode": "llm", "text": text}
        except Exception as exc:
            return {"mode": "fallback", "text": fallback, "error": str(exc)}

    def _attention_items(self, payroll: dict) -> list[dict]:
        return [
            {
                "title": "薪资批次待复核",
                "detail": f"{payroll['counts']['diffs']} 个差异，{payroll['counts']['deduction_warning_employees']} 名员工扣款待确认",
                "module": "payroll",
                "severity": "high" if payroll["counts"]["diffs"] else "medium",
            },
            {
                "title": "人员与薪资档案已形成快照",
                "detail": f"{payroll['counts']['employees']} 名员工进入 {PAYROLL_RUN_ID}",
                "module": "people",
                "severity": "low",
            },
            {
                "title": "本体能力可用",
                "detail": f"{len(self.ontology.functions)} 个函数，{len(self.ontology.rules)} 条规则索引",
                "module": "ontology",
                "severity": "low",
            },
        ]

    def _resource_map(self) -> list[dict]:
        groups = [
            ("人员资源", ["Person", "Employee", "EmploymentRelationship", "SalaryProfile"]),
            ("薪资资源", ["PayrollRun", "PayrollEmployeeSnapshot", "PayrollLine", "PayrollItem", "TaxLedger"]),
            ("社保公积金", ["SocialInsuranceContribution", "HousingFundContribution", "ContributionDeduction"]),
            ("治理输出", ["PayrollValidationResult", "ApprovalRecord", "PayrollExport", "CostEntry"]),
        ]
        return [
            {
                "label": label,
                "objects": [
                    {
                        "type": object_type,
                        "summary": self.ontology.objects.get(object_type).summary if object_type in self.ontology.objects else object_type,
                        "count": self.repository.count(object_type) if object_type in self.ontology.objects else 0,
                    }
                    for object_type in object_types
                ],
            }
            for label, object_types in groups
        ]

    def _agent_panel(self, title: str, summary: str, next_actions: list[dict], evidence: list[str]) -> dict:
        return {
            "title": title,
            "summary": summary,
            "next_actions": next_actions,
            "evidence": evidence,
        }

    def _payroll_summary(self, calculated: dict, totals: dict) -> str:
        if calculated.get("diff_count", 0):
            return (
                f"{PAYROLL_RUN_ID} 已完成试算，实发合计 {_money(totals['net'])}。"
                f"当前仍有 {calculated.get('diff_count', 0)} 个工资行差异，建议先复核。"
            )
        return f"{PAYROLL_RUN_ID} 工资行与 benchmark 对齐，实发合计 {_money(totals['net'])}。"

    def _payroll_next_actions(self, calculated: dict) -> list[dict]:
        return self.resolve_actions(
            "PayrollRun",
            PAYROLL_RUN_ID,
            signals={
                "diff_count": calculated.get("diff_count", 0),
                "warning_count": calculated.get("warning_count", 0),
            },
            limit=6,
        )

    def _employee_summary(self, employee_id: str, payroll: dict) -> str:
        summary = payroll.get("summary", {})
        if not summary:
            return f"{employee_id} 暂无本批次工资结果。"
        return (
            f"{employee_id} 扣前应发 {_money(summary.get('gross_pay_before_deduction'))}，"
            f"个税 {_money(summary.get('personal_income_tax'))}，"
            f"实发 {_money(summary.get('net_pay'))}。"
        )

    def _employee_next_actions(self, employee_id: str, payroll: dict) -> list[dict]:
        line = payroll.get("line") or {}
        context = {
            "employee_id": employee_id,
            "object_type": "Employee",
            "company_id": line.get("payroll_company_id") or DEFAULT_COMPANY_ID,
        }
        seed_actions = ["employee.explain_payroll", "ontology.employee"]
        if payroll.get("diffs"):
            seed_actions.append("payroll.review_diffs")
        if payroll.get("warnings"):
            seed_actions.append("payroll.confirm_deductions")
        return self.resolve_actions(
            "Employee",
            employee_id,
            context=context,
            seed_actions=seed_actions,
            limit=8,
        )

    def _deterministic_payroll_explanation(self, employee_id: str, payroll: dict) -> str:
        summary = payroll.get("summary", {})
        if not summary:
            return f"{employee_id} 暂无可解释的工资结果。"
        lines = [
            f"{employee_id} 本次扣前应发为 {_money(summary.get('gross_pay_before_deduction'))}。",
            (
                f"个人社保 {_money(summary.get('personal_social_security'))}，"
                f"个人公积金 {_money(summary.get('personal_housing_fund'))}，"
                f"个人所得税 {_money(summary.get('personal_income_tax'))}，"
                f"最终实发 {_money(summary.get('net_pay'))}。"
            ),
        ]
        if payroll.get("warnings"):
            lines.append("系统提示该员工存在未确认扣款或税务输入，工资实扣以已确认台账为准。")
        return "\n".join(lines)


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
        params = parse_qs(parsed.query)
        if parsed.path == "/api/app":
            return self._json(RUNTIME.app_state())
        if parsed.path == "/api/employees":
            return self._json(RUNTIME.employees(params.get("q", [""])[0]))
        if parsed.path == "/api/employee":
            return self._json(RUNTIME.employee_detail(params.get("employee_id", ["EMP074"])[0]))
        if parsed.path == "/api/payroll":
            return self._json(RUNTIME.payroll_overview())
        if parsed.path == "/api/object":
            filters = {
                key.removeprefix("filter_"): values[0]
                for key, values in params.items()
                if key.startswith("filter_")
            }
            return self._json(RUNTIME.object_context(
                params.get("object_type", ["Employee"])[0],
                params.get("object_id", [""])[0],
                filters=filters,
            ))
        if parsed.path == "/api/actions":
            return self._json(RUNTIME.actions_for_context(
                object_type=params.get("object_type", ["PayrollRun"])[0],
                object_id=params.get("object_id", [PAYROLL_RUN_ID])[0],
                employee_id=params.get("employee_id", ["EMP074"])[0],
            ))
        if parsed.path == "/api/action/execute":
            context = {
                key: values[0]
                for key, values in params.items()
                if key != "action_id"
            }
            return self._json(RUNTIME.execute_action(
                params.get("action_id", [""])[0],
                context=context,
            ))
        if parsed.path == "/api/explain/payroll":
            return self._json(RUNTIME.explain_payroll(params.get("employee_id", ["EMP074"])[0]))
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


def _llm_client():
    if OpenAI is None:
        return None
    load_env(ROOT / ".env")
    api_key = os.environ.get("LLM_API_KEY", "")
    base_url = os.environ.get("LLM_API_URL", "")
    model = os.environ.get("LLM_MODEL", "")
    if not api_key or not base_url or not model:
        return None
    return OpenAI(base_url=base_url, api_key=api_key, timeout=30.0)


def _num(value) -> float:
    if value in (None, ""):
        return 0.0
    return float(value)


def _money(value) -> str:
    return f"{_num(value):,.2f} 元"


def _action_result_message(function_name: str, result) -> str:
    if isinstance(result, dict):
        if result.get("error"):
            return str(result.get("error"))
        if result.get("message"):
            return str(result.get("message"))
        status = result.get("status")
        if status:
            return f"{function_name} 执行完成，状态：{status}。"
    return f"{function_name} 执行完成。"


def _result_highlights(result: dict) -> list[dict]:
    preferred = [
        ("status", "状态"),
        ("payroll_run_id", "薪资批次"),
        ("employee_id", "员工"),
        ("payroll_period", "工资归属月"),
        ("contribution_period", "缴费月"),
        ("snapshot_id", "快照"),
        ("employee_snapshot_count", "员工快照"),
        ("generated_count", "生成工资行"),
        ("calculated_count", "工资行"),
        ("payroll_item_count", "工资项"),
        ("social_contribution_count", "社保记录"),
        ("housing_fund_count", "公积金记录"),
        ("deduction_count", "扣款台账"),
        ("tax_ledger_count", "个税台账"),
        ("diff_count", "差异"),
        ("warning_count", "提示"),
    ]
    highlights = []
    for key, label in preferred:
        value = result.get(key)
        if value not in (None, ""):
            highlights.append({"label": label, "value": value})
    return highlights[:8]


def _load_actions(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    import yaml
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw.get("actions", {}) or {}


def _instantiate_action(defn: dict, action_id: str, context: dict, label: str = "") -> dict:
    if not defn:
        return _action(
            label or action_id,
            "",
            enabled=False,
            requires_confirmation=False,
        ) | {
            "id": action_id,
            "disabled_reason": "Action registry 中未找到该动作。",
        }
    return {
        "id": action_id,
        "label": label or defn.get("label", action_id),
        "kind": defn.get("kind", ""),
        "target": _resolve_action_value(defn.get("target", {}) or {}, context),
        "params": _resolve_action_value(defn.get("params", {}) or {}, context),
        "enabled": defn.get("enabled", True),
        "requires_confirmation": defn.get("requires_confirmation", False),
        "disabled_reason": defn.get("disabled_reason", ""),
        "side_effect": defn.get("side_effect", ""),
    }


def _resolve_action_value(value, context: dict):
    if isinstance(value, dict):
        return {
            key: _resolve_action_value(child, context)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_resolve_action_value(item, context) for item in value]
    if isinstance(value, str) and value.startswith("{context.") and value.endswith("}"):
        key = value.removeprefix("{context.").removesuffix("}")
        return context.get(key, "")
    return value


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _action(
    label: str,
    kind: str,
    target: dict | None = None,
    enabled: bool = True,
    requires_confirmation: bool = False,
) -> dict:
    return {
        "label": label,
        "kind": kind,
        "target": target or {},
        "enabled": enabled,
        "requires_confirmation": requires_confirmation,
    }


RUNTIME = OmsRuntime()


def main():
    port = int(os.environ.get("OMS_PROTOTYPE_PORT", "8765"))
    host = os.environ.get("OMS_PROTOTYPE_HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"OMS prototype running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
