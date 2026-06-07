from __future__ import annotations

from pathlib import Path
from typing import Any

from oag.ontology.registry import FunctionRegistry
from oag.ontology.repository import ObjectRepository
from oag.ontology.schema import Ontology


from .adapter import OmsCsvFileAdapter
from .contributions import (
    _calculate_housing_fund,
    _calculate_social_security,
    _contribution_deduction_record,
    _housing_contribution_record,
    _social_contribution_record,
)
from .payroll import (
    _adjustments_by_employee,
    _draft_payroll_line,
    _payroll_items_from_calculated_line,
    _payroll_items_from_draft_line,
)
from .tax import _calculate_personal_income_tax, _tax_ledger_record
from .utils import (
    _as_number,
    _date_gte,
    _date_lte,
    _effective_rules,
    _line_diff,
    _load_benchmark_rows,
    _merge_rule_ids,
    _merge_trace,
    _record_diff,
    _select_effective,
    _select_period_rule,
)


def register(registry: FunctionRegistry, store: ObjectRepository, ontology: Ontology):
    domain_dir = Path(__file__).resolve().parent.parent
    registry.register_adapter("table", OmsCsvFileAdapter.factory(domain_dir))

    implemented = {
        "resolve_employee_state_at": lambda **kw: _resolve_employee_state_at(store, **kw),
        "resolve_rules_at": lambda **kw: _resolve_rules_at(store, **kw),
        "build_payroll_snapshot": lambda **kw: _build_payroll_snapshot(store, **kw),
        "generate_payroll_lines": lambda **kw: _generate_payroll_lines(store, **kw),
        "calculate_contributions": lambda **kw: _calculate_contributions(store, **kw),
        "calculate_payroll": lambda **kw: _calculate_payroll(store, **kw),
    }
    for name, func_def in ontology.functions.items():
        registry.register(name, implemented.get(name, _make_not_implemented(name)), func_def)


def _resolve_employee_state_at(
    store: ObjectRepository,
    employee_id: str = "",
    as_of_date: str = "",
    **kwargs,
) -> dict:
    employee = store.query_by_id("Employee", employee_id)
    if not employee:
        return {"error": f"未找到员工 {employee_id}"}
    person = (
        store.query_by_id("Person", employee.get("person_id", ""))
        if employee.get("person_id") else None
    )

    relationship = _select_effective(
        store.query("EmploymentRelationship", {"employee_id": employee_id}),
        as_of_date,
    )
    salary_profile = _select_effective(
        store.query("SalaryProfile", {"employee_id": employee_id}),
        as_of_date,
    )
    company = (
        store.query_by_id("Company", relationship.get("company_id"))
        if relationship else None
    )
    affiliation = (
        store.query_by_id("InternalAffiliation", relationship.get("internal_affiliation_id"))
        if relationship and relationship.get("internal_affiliation_id") else None
    )

    missing = []
    if not person:
        missing.append("Person")
    if not relationship:
        missing.append("EmploymentRelationship")
    if not salary_profile:
        missing.append("SalaryProfile")

    return {
        "employee_id": employee_id,
        "person_id": employee.get("person_id", ""),
        "employee_name": person.get("name", "") if person else "",
        "as_of_date": as_of_date,
        "employment_status": employee.get("status", ""),
        "employment_relationship_id": (
            relationship.get("employment_relationship_id", "") if relationship else ""
        ),
        "relationship_type": relationship.get("relationship_type", "") if relationship else "",
        "company_id": relationship.get("company_id", "") if relationship else "",
        "payroll_company_id": relationship.get("company_id", "") if relationship else "",
        "payroll_company_name": company.get("company_name", "") if company else "",
        "internal_affiliation_id": relationship.get("internal_affiliation_id", "") if relationship else "",
        "internal_affiliation_name": affiliation.get("name", "") if affiliation else "",
        "salary_profile_id": salary_profile.get("salary_profile_id", "") if salary_profile else "",
        "monthly_salary_base": salary_profile.get("monthly_salary_base", "") if salary_profile else "",
        "social_security_base": salary_profile.get("social_security_base", "") if salary_profile else "",
        "housing_fund_base": salary_profile.get("housing_fund_base", "") if salary_profile else "",
        "position_or_type": salary_profile.get("position_or_type") or employee.get("position", ""),
        "missing": missing,
    }


def _resolve_rules_at(
    store: ObjectRepository,
    company_id: str = "",
    period: str = "",
    **kwargs,
) -> dict:
    company = store.query_by_id("Company", company_id)
    if not company:
        return {"error": f"未找到公司 {company_id}"}

    return {
        "company_id": company_id,
        "company_name": company.get("company_name", ""),
        "period": period,
        "salary_split_rules": _effective_rules(store.query("SalarySplitRule"), period),
        "performance_grade_rules": _effective_rules(store.query("PerformanceGradeRule"), period),
        "social_insurance_rule": _select_period_rule(
            store.query("SocialInsuranceRule", {"company_id": company_id}),
            period,
        ),
        "housing_fund_rule": _select_period_rule(
            store.query("HousingFundRule", {"company_id": company_id}),
            period,
        ),
        "tax_rate_rules": store.query("TaxRateRule", order_by="lower_bound"),
    }


def _build_payroll_snapshot(
    store: ObjectRepository,
    payroll_run_id: str = "",
    **kwargs,
) -> dict:
    payroll_run = store.query_by_id("PayrollRun", payroll_run_id)
    if not payroll_run:
        return {"error": f"未找到薪资批次 {payroll_run_id}"}

    snapshots = store.query(
        "PayrollInputSnapshot",
        {"payroll_run_id": payroll_run_id},
        limit=1,
        order_by="-snapshot_time",
    )
    if not snapshots:
        return {
            "status": "missing_snapshot",
            "payroll_run_id": payroll_run_id,
            "message": "未找到已抽取的薪资输入快照；请先运行 Excel 抽取脚本生成 CSV 种子数据。",
        }

    snapshot = snapshots[0]
    employee_snapshots = store.query(
        "PayrollEmployeeSnapshot",
        {"snapshot_id": snapshot.get("snapshot_id", "")},
        order_by="employee_snapshot_id",
    )
    warnings = store.query(
        "PayrollValidationResult",
        {"payroll_run_id": payroll_run_id, "severity": "warning"},
        limit=10,
        order_by="validation_id",
    )

    return {
        "status": snapshot.get("status") or "built",
        "payroll_run_id": payroll_run_id,
        "payroll_period": snapshot.get("payroll_period", ""),
        "snapshot_id": snapshot.get("snapshot_id", ""),
        "snapshot_time": snapshot.get("snapshot_time", ""),
        "source_note": snapshot.get("source_note", ""),
        "employee_snapshot_count": len(employee_snapshots),
        "payroll_line_count": store.count("PayrollLine", {"payroll_run_id": payroll_run_id}),
        "validation_warning_count": store.count(
            "PayrollValidationResult",
            {"payroll_run_id": payroll_run_id, "severity": "warning"},
        ),
        "sample_employee_snapshots": employee_snapshots[:3],
        "sample_warnings": warnings,
    }


def _generate_payroll_lines(
    store: ObjectRepository,
    payroll_run_id: str = "",
    **kwargs,
) -> dict:
    payroll_run = store.query_by_id("PayrollRun", payroll_run_id)
    if not payroll_run:
        return {"error": f"未找到薪资批次 {payroll_run_id}"}

    snapshots = store.query(
        "PayrollInputSnapshot",
        {"payroll_run_id": payroll_run_id},
        limit=1,
        order_by="-snapshot_time",
    )
    if not snapshots:
        return {
            "status": "missing_snapshot",
            "payroll_run_id": payroll_run_id,
            "message": "请先构建 PayrollInputSnapshot，再生成工资明细。",
        }

    snapshot = snapshots[0]
    period = snapshot.get("payroll_period") or payroll_run.get("payroll_period", "")
    employee_snapshots = store.query(
        "PayrollEmployeeSnapshot",
        {"snapshot_id": snapshot.get("snapshot_id", "")},
        order_by="employee_snapshot_id",
    )
    split_rules = _effective_rules(store.query("SalarySplitRule"), period)
    grade_rules = _effective_rules(store.query("PerformanceGradeRule"), period)
    performance_by_employee = {
        row.get("employee_id"): row
        for row in store.query("PerformanceRecord", {"performance_period": period})
    }
    adjustments_by_employee = _adjustments_by_employee(
        store.query("PayrollAdjustment", {"payroll_run_id": payroll_run_id})
    )
    expected_lines = {
        row.get("employee_snapshot_id"): row
        for row in _load_benchmark_rows(store, "PayrollLine")
        if row.get("payroll_run_id") == payroll_run_id
    }

    generated = []
    generated_items = []
    diffs = []
    warnings = []
    for employee_snapshot in employee_snapshots:
        line = _draft_payroll_line(
            payroll_run_id,
            period,
            employee_snapshot,
            split_rules,
            grade_rules,
            performance_by_employee.get(employee_snapshot.get("employee_id")),
            adjustments_by_employee.get(employee_snapshot.get("employee_id"), {}),
        )
        generated.append(line)
        generated_items.extend(_payroll_items_from_draft_line(line))

        expected = expected_lines.get(employee_snapshot.get("employee_snapshot_id"))
        if expected:
            diff = _line_diff(line, expected)
            if diff:
                diffs.append(diff)
        else:
            warnings.append({
                "employee_snapshot_id": employee_snapshot.get("employee_snapshot_id", ""),
                "employee_id": employee_snapshot.get("employee_id", ""),
                "message": "Excel benchmark 中没有对应 PayrollLine 校对行。",
            })

    return {
        "status": "generated_preview",
        "payroll_run_id": payroll_run_id,
        "snapshot_id": snapshot.get("snapshot_id", ""),
        "payroll_period": period,
        "generated_count": len(generated),
        "payroll_item_count": len(generated_items),
        "expected_line_count": len(expected_lines),
        "diff_count": len(diffs),
        "warning_count": len(warnings),
        "sample_generated_lines": generated[:5],
        "sample_payroll_items": generated_items[:10],
        "result_set": {
            "PayrollLine": generated,
            "PayrollItem": generated_items,
        } if kwargs.get("include_result_set") else {},
        "sample_diffs": diffs[:10],
        "sample_warnings": warnings[:10],
        "note": "当前 OMS CSV adapter 为只读；本函数返回基于快照和规则生成的工资明细、工资项预览，并与 data/benchmarks 中的 Excel 校对基准对比。",
    }


def _calculate_contributions(
    store: ObjectRepository,
    payroll_run_id: str = "",
    employee_id: str = "",
    **kwargs,
) -> dict:
    payroll_run = store.query_by_id("PayrollRun", payroll_run_id)
    if not payroll_run:
        return {"error": f"未找到薪资批次 {payroll_run_id}"}

    contribution_period = payroll_run.get("contribution_period", "")
    payroll_period = payroll_run.get("payroll_period", "")
    employee_snapshots = store.query(
        "PayrollEmployeeSnapshot",
        {"payroll_run_id": payroll_run_id},
        order_by="employee_snapshot_id",
    )
    if employee_id:
        employee_snapshots = [
            snapshot for snapshot in employee_snapshots
            if snapshot.get("employee_id") == employee_id
        ]

    social_rules_by_company = {
        row.get("company_id"): row
        for row in store.query("SocialInsuranceRule", {"effective_period__lte": contribution_period})
    }
    housing_rules_by_company = {
        row.get("company_id"): row
        for row in store.query("HousingFundRule", {"effective_period__lte": contribution_period})
    }
    expected_social = {
        row.get("contribution_id"): row
        for row in _load_benchmark_rows(store, "SocialInsuranceContribution")
        if row.get("contribution_period") == contribution_period
    }
    expected_housing = {
        row.get("housing_fund_id"): row
        for row in _load_benchmark_rows(store, "HousingFundContribution")
        if row.get("contribution_period") == contribution_period
    }
    expected_deductions = {
        row.get("deduction_id"): row
        for row in _load_benchmark_rows(store, "ContributionDeduction")
        if row.get("deducted_payroll_run_id") == payroll_run_id
    }

    social_records = []
    housing_records = []
    deduction_records = []
    diffs = []
    warnings = []
    for snapshot in employee_snapshots:
        company_id = snapshot.get("payroll_company_id", "")
        employee = store.query_by_id("Employee", snapshot.get("employee_id", ""))
        if employee and employee.get("termination_date") and employee.get("termination_date") <= f"{payroll_period}-31":
            warnings.append({
                "employee_id": snapshot.get("employee_id", ""),
                "rule_code": "termination_contribution_rule_not_fully_modeled",
                "message": "员工离职后的社保公积金停扣规则需要结合真实参保状态进一步判断；当前预览仍按正常规则计算。",
            })

        social_rule = social_rules_by_company.get(company_id)
        housing_rule = housing_rules_by_company.get(company_id)
        if not social_rule:
            warnings.append({
                "employee_id": snapshot.get("employee_id", ""),
                "rule_code": "social_rule_missing",
                "message": f"缺少 {company_id}/{contribution_period} 社保规则。",
            })
        if not housing_rule:
            warnings.append({
                "employee_id": snapshot.get("employee_id", ""),
                "rule_code": "housing_rule_missing",
                "message": f"缺少 {company_id}/{contribution_period} 公积金规则。",
            })

        social = _calculate_social_security(snapshot, social_rule)
        housing = _calculate_housing_fund(snapshot, housing_rule)
        contribution_month = contribution_period.replace("-", "")
        employee_id_value = snapshot.get("employee_id", "")
        social_id = f"SI_{contribution_month}_{company_id}_{employee_id_value}"
        housing_id = f"HF_{contribution_month}_{company_id}_{employee_id_value}"
        social_record = _social_contribution_record(social_id, snapshot, contribution_period, social)
        housing_record = _housing_contribution_record(
            housing_id,
            snapshot,
            contribution_period,
            housing,
            housing_rule,
        )
        social_records.append(social_record)
        housing_records.append(housing_record)
        deduction_records.extend([
            _contribution_deduction_record(
                f"DED_SI_{contribution_month}_{company_id}_{employee_id_value}",
                snapshot,
                "社保",
                social_id,
                contribution_period,
                payroll_run_id,
                payroll_period,
                social["personal_total"],
                social["employer_total"],
            ),
            _contribution_deduction_record(
                f"DED_HF_{contribution_month}_{company_id}_{employee_id_value}",
                snapshot,
                "公积金",
                housing_id,
                contribution_period,
                payroll_run_id,
                payroll_period,
                housing["personal_amount"],
                housing["employer_amount"],
            ),
        ])

        social_diff = _record_diff(
            social_record,
            expected_social.get(social_id),
            ["contribution_base", "employer_total", "personal_total"],
            "SocialInsuranceContribution",
        )
        housing_diff = _record_diff(
            housing_record,
            expected_housing.get(housing_id),
            ["contribution_base", "employer_amount", "personal_amount", "total_amount"],
            "HousingFundContribution",
        )
        if social_diff:
            diffs.append(social_diff)
        if housing_diff:
            diffs.append(housing_diff)
        for deduction in deduction_records[-2:]:
            diff = _record_diff(
                deduction,
                expected_deductions.get(deduction.get("deduction_id")),
                ["personal_amount", "employer_amount", "status", "deduction_reason"],
                "ContributionDeduction",
            )
            if diff:
                diffs.append(diff)

    return {
        "status": "calculated_preview",
        "payroll_run_id": payroll_run_id,
        "employee_id": employee_id,
        "contribution_period": contribution_period,
        "social_contribution_count": len(social_records),
        "housing_fund_count": len(housing_records),
        "deduction_count": len(deduction_records),
        "diff_count": len(diffs),
        "warning_count": len(warnings),
        "sample_social_contributions": social_records[:5],
        "sample_housing_fund_contributions": housing_records[:5],
        "sample_deductions": deduction_records[:10],
        "social_contributions": social_records if employee_id else [],
        "housing_fund_contributions": housing_records if employee_id else [],
        "deductions": deduction_records if employee_id else [],
        "result_set": {
            "SocialInsuranceContribution": social_records,
            "HousingFundContribution": housing_records,
            "ContributionDeduction": deduction_records,
        } if kwargs.get("include_result_set") or employee_id else {},
        "sample_diffs": diffs[:10],
        "diffs": diffs if employee_id else [],
        "sample_warnings": warnings[:10],
        "warnings": warnings if employee_id else [],
        "note": "当前 OMS CSV adapter 为只读；本函数按文档公式返回社保、公积金和扣款台账预览，并与 data/benchmarks 中的 Excel 校对基准对比。",
    }


def _calculate_payroll(
    store: ObjectRepository,
    payroll_run_id: str = "",
    employee_id: str = "",
    **kwargs,
) -> dict:
    generated_preview = _generate_payroll_lines(store, payroll_run_id=payroll_run_id)
    if generated_preview.get("error") or generated_preview.get("status") == "missing_snapshot":
        return generated_preview

    payroll_run = store.query_by_id("PayrollRun", payroll_run_id)
    tax_period = payroll_run.get("tax_period", "") if payroll_run else ""
    contribution_period = payroll_run.get("contribution_period", "") if payroll_run else ""
    generated_lines = _generate_full_payroll_line_previews(store, payroll_run_id)
    if employee_id:
        generated_lines = [
            line for line in generated_lines
            if line.get("employee_id") == employee_id
        ]
    tax_by_employee = {
        row.get("employee_id"): row
        for row in store.query("TaxLedger", {"payroll_run_id": payroll_run_id})
    }
    employee_snapshots_by_employee = {
        row.get("employee_id"): row
        for row in store.query("PayrollEmployeeSnapshot", {"payroll_run_id": payroll_run_id})
    }
    confirmed_deductions_by_employee = _confirmed_deductions_by_employee(
        store,
        payroll_run_id,
    )
    social_rules_by_company = {
        row.get("company_id"): row
        for row in store.query("SocialInsuranceRule", {"effective_period__lte": contribution_period})
    }
    housing_rules_by_company = {
        row.get("company_id"): row
        for row in store.query("HousingFundRule", {"effective_period__lte": contribution_period})
    }
    tax_rules = store.query("TaxRateRule", order_by="lower_bound")
    expected_lines = {
        row.get("employee_snapshot_id"): row
        for row in _load_benchmark_rows(store, "PayrollLine")
        if row.get("payroll_run_id") == payroll_run_id
    }

    calculated = []
    payroll_items = []
    social_records = []
    housing_records = []
    deduction_records = []
    tax_ledgers = []
    diffs = []
    warnings = []
    for line in generated_lines:
        employee_id = line.get("employee_id", "")
        employee_snapshot = employee_snapshots_by_employee.get(employee_id, {})
        company_id = line.get("payroll_company_id", "")
        social_rule = social_rules_by_company.get(company_id)
        housing_rule = housing_rules_by_company.get(company_id)
        tax = tax_by_employee.get(employee_id)
        social = _calculate_social_security(employee_snapshot, social_rule)
        housing = _calculate_housing_fund(employee_snapshot, housing_rule)
        confirmed_deductions = confirmed_deductions_by_employee.get(employee_id, {})
        social_deduction = confirmed_deductions.get("社保")
        housing_deduction = confirmed_deductions.get("公积金")
        personal_social_security = _as_number(
            social_deduction.get("personal_amount") if social_deduction else 0.0
        )
        employer_social_security = _as_number(
            social_deduction.get("employer_amount") if social_deduction else 0.0
        )
        personal_housing_fund = _as_number(
            housing_deduction.get("personal_amount") if housing_deduction else 0.0
        )
        employer_housing_fund = _as_number(
            housing_deduction.get("employer_amount") if housing_deduction else 0.0
        )
        contribution_month = contribution_period.replace("-", "")
        social_id = f"SI_{contribution_month}_{company_id}_{employee_id}"
        housing_id = f"HF_{contribution_month}_{company_id}_{employee_id}"
        social_record = _social_contribution_record(
            social_id,
            employee_snapshot,
            contribution_period,
            social,
        )
        housing_record = _housing_contribution_record(
            housing_id,
            employee_snapshot,
            contribution_period,
            housing,
            housing_rule,
        )
        social_records.append(social_record)
        housing_records.append(housing_record)
        deduction_records.extend([
            _contribution_deduction_record(
                f"DED_SI_{contribution_month}_{company_id}_{employee_id}",
                employee_snapshot,
                "社保",
                social_id,
                contribution_period,
                payroll_run_id,
                generated_preview.get("payroll_period", ""),
                personal_social_security,
                employer_social_security,
            ),
            _contribution_deduction_record(
                f"DED_HF_{contribution_month}_{company_id}_{employee_id}",
                employee_snapshot,
                "公积金",
                housing_id,
                contribution_period,
                payroll_run_id,
                generated_preview.get("payroll_period", ""),
                personal_housing_fund,
                employer_housing_fund,
            ),
        ])
        tax_result = _calculate_personal_income_tax(
            line,
            tax,
            tax_rules,
            personal_social_security,
            personal_housing_fund,
        )
        personal_income_tax = tax_result["current_tax"]
        if not social_rule:
            warnings.append({
                "employee_id": employee_id,
                "rule_code": "social_rule_missing",
                "message": f"{employee_id} 缺少 {company_id}/{contribution_period} 社保规则，社保按 0 计算。",
            })
        elif not social_deduction:
            warnings.append({
                "employee_id": employee_id,
                "rule_code": "social_deduction_unconfirmed",
                "message": f"{employee_id} 没有已确认社保扣款台账，本次工资个人社保和公司社保按 0 扣；规则试算仅作为缴费建议。",
            })
        if not housing_rule:
            warnings.append({
                "employee_id": employee_id,
                "rule_code": "housing_rule_missing",
                "message": f"{employee_id} 缺少 {company_id}/{contribution_period} 公积金规则，公积金按 0 计算。",
            })
        elif not housing_deduction:
            warnings.append({
                "employee_id": employee_id,
                "rule_code": "housing_deduction_unconfirmed",
                "message": f"{employee_id} 没有已确认公积金扣款台账，本次工资个人公积金和公司公积金按 0 扣；规则试算仅作为缴费建议。",
            })
        if not tax:
            warnings.append({
                "employee_id": employee_id,
                "rule_code": "tax_ledger_missing",
                "message": f"{employee_id} 缺少 {tax_period} 个税历史累计输入，个税按本月数据和税率表计算。",
            })

        net_pay = round(
            _as_number(line.get("gross_pay_before_deduction"))
            - personal_social_security
            - personal_housing_fund
            - personal_income_tax,
            2,
        )
        company_total_cost = round(
            _as_number(line.get("gross_pay_before_deduction"))
            + employer_social_security
            + employer_housing_fund,
            2,
        )
        line = dict(line)
        applied_rule_ids = [
            "tax_cumulative_withholding",
            "net_pay_formula",
            "company_total_cost_formula",
        ]
        if social_rule:
            applied_rule_ids.extend([
                "social_security_base_bounds",
                "social_security_employer_formula",
                "social_security_personal_formula",
            ])
        if housing_rule:
            applied_rule_ids.append("housing_fund_formula")
            if housing_rule.get("rounding_rule") == "ROUND0":
                applied_rule_ids.append("housing_fund_round0")
        if net_pay < 0:
            applied_rule_ids.append("negative_net_pay_warning")
        line.update({
            "personal_social_security": personal_social_security,
            "personal_housing_fund": personal_housing_fund,
            "personal_income_tax": personal_income_tax,
            "net_pay": net_pay,
            "employer_social_security": employer_social_security,
            "employer_housing_fund": employer_housing_fund,
            "company_total_cost": company_total_cost,
            "exception_notes": "实发工资为负数，请确认扣款是否正确" if net_pay < 0 else "",
            "applied_rule_ids": _merge_rule_ids(line.get("applied_rule_ids", ""), *applied_rule_ids),
            "calculation_trace": _merge_trace(
                line.get("calculation_trace", ""),
                social_security={
                    "rule_id": social_rule.get("social_rule_id", "") if social_rule else "",
                    "base": social.get("base", 0.0),
                    "personal_total": personal_social_security,
                    "employer_total": employer_social_security,
                    "suggested_personal_total": social.get("personal_total", 0.0),
                    "suggested_employer_total": social.get("employer_total", 0.0),
                    "deduction_source": social_deduction.get("deduction_id", "") if social_deduction else "",
                },
                housing_fund={
                    "rule_id": housing_rule.get("housing_rule_id", "") if housing_rule else "",
                    "base": housing.get("base", 0.0),
                    "personal_amount": personal_housing_fund,
                    "employer_amount": employer_housing_fund,
                    "suggested_personal_amount": housing.get("personal_amount", 0.0),
                    "suggested_employer_amount": housing.get("employer_amount", 0.0),
                    "deduction_source": housing_deduction.get("deduction_id", "") if housing_deduction else "",
                    "rounding_rule": housing_rule.get("rounding_rule", "") if housing_rule else "",
                },
                tax=tax_result,
                net_pay={
                    "formula": "gross_pay_before_deduction - personal_social_security - personal_housing_fund - personal_income_tax",
                    "gross_pay_before_deduction": _as_number(line.get("gross_pay_before_deduction")),
                    "personal_social_security": personal_social_security,
                    "personal_housing_fund": personal_housing_fund,
                    "personal_income_tax": personal_income_tax,
                    "result": net_pay,
                },
                company_total_cost={
                    "formula": "gross_pay_before_deduction + employer_social_security + employer_housing_fund",
                    "gross_pay_before_deduction": _as_number(line.get("gross_pay_before_deduction")),
                    "employer_social_security": employer_social_security,
                    "employer_housing_fund": employer_housing_fund,
                    "result": company_total_cost,
                },
            ),
        })
        calculated.append(line)
        payroll_items.extend(
            _payroll_items_from_calculated_line(
                line,
                social,
                housing,
                tax_result,
                personal_social_security,
                personal_housing_fund,
                personal_income_tax,
                employer_social_security,
                employer_housing_fund,
                company_total_cost,
            )
        )
        tax_ledgers.append(_tax_ledger_record(line, tax_period, tax_result))

        expected = expected_lines.get(line.get("employee_snapshot_id"))
        if expected:
            diff = _line_diff(line, expected, include_final_pay=True)
            if diff:
                diffs.append(diff)

    return {
        "status": "calculated_preview",
        "payroll_run_id": payroll_run_id,
        "employee_id": employee_id,
        "payroll_period": generated_preview.get("payroll_period", ""),
        "tax_period": tax_period,
        "calculated_count": len(calculated),
        "payroll_item_count": len(payroll_items),
        "social_contribution_count": len(social_records),
        "housing_fund_count": len(housing_records),
        "deduction_count": len(deduction_records),
        "tax_ledger_count": len(tax_ledgers),
        "expected_line_count": len(expected_lines),
        "diff_count": len(diffs),
        "warning_count": len(warnings),
        "sample_calculated_lines": calculated[:5],
        "sample_payroll_items": payroll_items[:10],
        "sample_social_contributions": social_records[:5],
        "sample_housing_fund_contributions": housing_records[:5],
        "sample_deductions": deduction_records[:10],
        "sample_tax_ledgers": tax_ledgers[:5],
        "calculated_lines": calculated if employee_id else [],
        "payroll_items": payroll_items if employee_id else [],
        "social_contributions": social_records if employee_id else [],
        "housing_fund_contributions": housing_records if employee_id else [],
        "deductions": deduction_records if employee_id else [],
        "tax_ledgers": tax_ledgers if employee_id else [],
        "result_set": {
            "PayrollLine": calculated,
            "PayrollItem": payroll_items,
            "SocialInsuranceContribution": social_records,
            "HousingFundContribution": housing_records,
            "ContributionDeduction": deduction_records,
            "TaxLedger": tax_ledgers,
        } if kwargs.get("include_result_set") or employee_id else {},
        "sample_diffs": diffs[:10],
        "diffs": diffs if employee_id else [],
        "sample_warnings": warnings[:10],
        "warnings": warnings if employee_id else [],
        "note": "当前 OMS CSV adapter 为只读；本函数返回薪资实发、工资项和当前期个税台账预览，并与 data/benchmarks 中的 Excel 校对基准对比。",
    }


def _confirmed_deductions_by_employee(
    store: ObjectRepository,
    payroll_run_id: str,
) -> dict[str, dict[str, dict]]:
    result: dict[str, dict[str, dict]] = {}
    rows = store.query(
        "ContributionDeduction",
        {"deducted_payroll_run_id": payroll_run_id, "status": "deducted"},
    )
    for row in rows:
        employee_id = row.get("employee_id", "")
        deduction_type = row.get("deduction_type", "")
        if employee_id and deduction_type:
            result.setdefault(employee_id, {})[deduction_type] = row
    return result


def _generate_full_payroll_line_previews(
    store: ObjectRepository,
    payroll_run_id: str,
) -> list[dict]:
    payroll_run = store.query_by_id("PayrollRun", payroll_run_id)
    snapshots = store.query(
        "PayrollInputSnapshot",
        {"payroll_run_id": payroll_run_id},
        limit=1,
        order_by="-snapshot_time",
    )
    if not payroll_run or not snapshots:
        return []
    snapshot = snapshots[0]
    period = snapshot.get("payroll_period") or payroll_run.get("payroll_period", "")
    employee_snapshots = store.query(
        "PayrollEmployeeSnapshot",
        {"snapshot_id": snapshot.get("snapshot_id", "")},
        order_by="employee_snapshot_id",
    )
    split_rules = _effective_rules(store.query("SalarySplitRule"), period)
    grade_rules = _effective_rules(store.query("PerformanceGradeRule"), period)
    performance_by_employee = {
        row.get("employee_id"): row
        for row in store.query("PerformanceRecord", {"performance_period": period})
    }
    adjustments_by_employee = _adjustments_by_employee(
        store.query("PayrollAdjustment", {"payroll_run_id": payroll_run_id})
    )
    return [
        _draft_payroll_line(
            payroll_run_id,
            period,
            employee_snapshot,
            split_rules,
            grade_rules,
            performance_by_employee.get(employee_snapshot.get("employee_id")),
            adjustments_by_employee.get(employee_snapshot.get("employee_id"), {}),
        )
        for employee_snapshot in employee_snapshots
    ]


def _make_not_implemented(name: str):
    def _fn(**kwargs):
        return {
            "status": "not_implemented",
            "function": name,
            "message": "OMS 领域函数尚未实现；当前已支持通过 ObjectRepository 查询抽取后的 CSV 对象数据。",
            "args": kwargs,
        }

    return _fn
