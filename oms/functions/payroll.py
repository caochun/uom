from __future__ import annotations

import json

from .utils import _as_number, _rule_ids, _trace


def _draft_payroll_line(
    payroll_run_id: str,
    payroll_period: str,
    employee_snapshot: dict,
    split_rules: list[dict],
    grade_rules: list[dict],
    performance_record: dict | None,
    adjustments: dict[str, float],
) -> dict:
    position = employee_snapshot.get("position_snapshot", "")
    monthly_salary_total = _as_number(employee_snapshot.get("monthly_salary_total"))
    monthly_salary_base = _as_number(employee_snapshot.get("monthly_salary_base"))
    split_rule = _match_split_rule(split_rules, position)
    basic_rate = _as_number(split_rule.get("basic_salary_rate", 1.0) if split_rule else 1.0)
    performance_base_rate = _as_number(
        split_rule.get("performance_base_rate", 0.0) if split_rule else 0.0
    )
    basic_salary = round(monthly_salary_total * basic_rate, 2)
    performance_salary_base = round(monthly_salary_total * performance_base_rate, 2)
    performance_grade = (
        performance_record.get("performance_grade", "") if performance_record else ""
    ) or "无等级"
    grade_rule = _match_grade_rule(grade_rules, performance_grade)
    coefficient = _as_number(grade_rule.get("coefficient")) if grade_rule else 0.0
    performance_salary = round(performance_salary_base * coefficient, 2)
    attendance_adjustment = adjustments.get("考勤", 0.0)
    other_adjustment = adjustments.get("其他", 0.0)
    gross_pay_before_deduction = round(
        basic_salary + performance_salary + attendance_adjustment + other_adjustment,
        2,
    )

    employee_id = employee_snapshot.get("employee_id", "")
    period_token = payroll_period.replace("-", "")
    return {
        "payroll_line_id": f"PL_{period_token}_{employee_id}",
        "payroll_run_id": payroll_run_id,
        "employee_snapshot_id": employee_snapshot.get("employee_snapshot_id", ""),
        "employee_id": employee_id,
        "person_id": employee_snapshot.get("person_id", ""),
        "employee_name_snapshot": employee_snapshot.get("employee_name_snapshot", ""),
        "employment_relationship_id": employee_snapshot.get("employment_relationship_id", ""),
        "payroll_company_id": employee_snapshot.get("payroll_company_id", ""),
        "payroll_company_name_snapshot": employee_snapshot.get("payroll_company_name_snapshot", ""),
        "internal_affiliation_id": employee_snapshot.get("internal_affiliation_id", ""),
        "internal_affiliation_name_snapshot": employee_snapshot.get(
            "internal_affiliation_name_snapshot",
            "",
        ),
        "salary_profile_id": employee_snapshot.get("salary_profile_id", ""),
        "monthly_salary_base": monthly_salary_base,
        "monthly_salary_total": monthly_salary_total,
        "position": position,
        "basic_salary": basic_salary,
        "performance_salary_base": performance_salary_base,
        "performance_grade": performance_grade,
        "performance_salary": performance_salary,
        "overtime_salary": 0.0,
        "attendance_adjustment": attendance_adjustment,
        "other_adjustment": other_adjustment,
        "gross_pay_before_deduction": gross_pay_before_deduction,
        "personal_social_security": "",
        "personal_housing_fund": "",
        "personal_income_tax": "",
        "net_pay": "",
        "employer_social_security": "",
        "employer_housing_fund": "",
        "company_total_cost": "",
        "exception_notes": "",
        "applied_rule_ids": _rule_ids(
            "payroll_salary_split_formula",
            "payroll_performance_salary_formula",
            "payroll_gross_before_deduction_formula",
        ),
        "calculation_trace": _trace({
            "salary_split": {
                "split_rule_id": split_rule.get("split_rule_id", "") if split_rule else "",
                "position": position,
                "monthly_salary_total": monthly_salary_total,
                "basic_salary_rate": basic_rate,
                "performance_base_rate": performance_base_rate,
                "basic_salary": basic_salary,
                "performance_salary_base": performance_salary_base,
            },
            "performance": {
                "performance_record_id": performance_record.get("performance_record_id", "") if performance_record else "",
                "grade_rule_id": grade_rule.get("grade_rule_id", "") if grade_rule else "",
                "performance_grade": performance_grade,
                "coefficient": coefficient,
                "performance_salary": performance_salary,
            },
            "gross_pay_before_deduction": {
                "formula": "basic_salary + performance_salary + attendance_adjustment + other_adjustment",
                "basic_salary": basic_salary,
                "performance_salary": performance_salary,
                "attendance_adjustment": attendance_adjustment,
                "other_adjustment": other_adjustment,
                "result": gross_pay_before_deduction,
            },
        }),
    }


def _payroll_items_from_draft_line(line: dict) -> list[dict]:
    items = [
        _payroll_item(
            line,
            "BASIC_SALARY",
            "基本薪资",
            "earning",
            _as_number(line.get("basic_salary")),
            taxable=1,
            affects_net_pay=1,
            source_object_type="SalarySplitRule",
            applied_rule_ids="payroll_salary_split_formula",
            trace_section="salary_split",
        ),
        _payroll_item(
            line,
            "PERFORMANCE_SALARY",
            "绩效薪资",
            "earning",
            _as_number(line.get("performance_salary")),
            taxable=1,
            affects_net_pay=1,
            source_object_type="PerformanceGradeRule",
            applied_rule_ids="payroll_performance_salary_formula",
            trace_section="performance",
        ),
    ]
    attendance_adjustment = _as_number(line.get("attendance_adjustment"))
    if attendance_adjustment:
        items.append(_payroll_item(
            line,
            "ATTENDANCE_ADJUSTMENT",
            "考勤补扣",
            "earning" if attendance_adjustment > 0 else "deduction",
            abs(attendance_adjustment),
            taxable=1,
            affects_net_pay=1,
            source_object_type="PayrollAdjustment",
            applied_rule_ids="payroll_gross_before_deduction_formula",
            trace_section="gross_pay_before_deduction",
        ))
    other_adjustment = _as_number(line.get("other_adjustment"))
    if other_adjustment:
        items.append(_payroll_item(
            line,
            "OTHER_ADJUSTMENT",
            "其他补扣",
            "earning" if other_adjustment > 0 else "deduction",
            abs(other_adjustment),
            taxable=1,
            affects_net_pay=1,
            source_object_type="PayrollAdjustment",
            applied_rule_ids="payroll_gross_before_deduction_formula",
            trace_section="gross_pay_before_deduction",
        ))
    return [item for item in items if _as_number(item.get("amount")) != 0]


def _payroll_items_from_calculated_line(
    line: dict,
    social: dict,
    housing: dict,
    tax_result: dict,
    personal_social_security: float,
    personal_housing_fund: float,
    personal_income_tax: float,
    employer_social_security: float,
    employer_housing_fund: float,
    company_total_cost: float,
) -> list[dict]:
    items = _payroll_items_from_draft_line(line)
    items.extend([
        _payroll_item(
            line,
            "PERSONAL_SOCIAL_SECURITY",
            "个人社保",
            "deduction",
            personal_social_security,
            taxable=0,
            affects_net_pay=1,
            source_object_type="ContributionDeduction",
            applied_rule_ids="social_security_personal_formula,contribution_normal_month",
            trace_data={
                "base": social.get("base", 0.0),
                "personal_total": personal_social_security,
            },
        ),
        _payroll_item(
            line,
            "PERSONAL_HOUSING_FUND",
            "个人公积金",
            "deduction",
            personal_housing_fund,
            taxable=0,
            affects_net_pay=1,
            source_object_type="ContributionDeduction",
            applied_rule_ids="housing_fund_formula,contribution_normal_month",
            trace_data={
                "base": housing.get("base", 0.0),
                "personal_amount": personal_housing_fund,
            },
        ),
        _payroll_item(
            line,
            "PERSONAL_INCOME_TAX",
            "个人所得税",
            "tax",
            personal_income_tax,
            taxable=0,
            affects_net_pay=1,
            source_object_type="TaxLedger",
            applied_rule_ids="tax_cumulative_withholding",
            trace_data=tax_result,
        ),
        _payroll_item(
            line,
            "EMPLOYER_SOCIAL_SECURITY",
            "公司社保",
            "employer_cost",
            employer_social_security,
            taxable=0,
            affects_net_pay=0,
            source_object_type="SocialInsuranceContribution",
            applied_rule_ids="social_security_employer_formula,company_total_cost_formula",
            trace_data={
                "base": social.get("base", 0.0),
                "employer_total": employer_social_security,
            },
        ),
        _payroll_item(
            line,
            "EMPLOYER_HOUSING_FUND",
            "公司公积金",
            "employer_cost",
            employer_housing_fund,
            taxable=0,
            affects_net_pay=0,
            source_object_type="HousingFundContribution",
            applied_rule_ids="housing_fund_formula,company_total_cost_formula",
            trace_data={
                "base": housing.get("base", 0.0),
                "employer_amount": employer_housing_fund,
            },
        ),
        _payroll_item(
            line,
            "COMPANY_TOTAL_COST",
            "公司总成本",
            "info",
            company_total_cost,
            taxable=0,
            affects_net_pay=0,
            source_object_type="PayrollLine",
            source_object_id=line.get("payroll_line_id", ""),
            applied_rule_ids="company_total_cost_formula",
            trace_section="company_total_cost",
        ),
    ])
    return [item for item in items if _as_number(item.get("amount")) != 0]


def _payroll_item(
    line: dict,
    item_code: str,
    item_name: str,
    item_category: str,
    amount: float,
    taxable: int,
    affects_net_pay: int,
    source_object_type: str,
    applied_rule_ids: str,
    source_object_id: str = "",
    trace_section: str = "",
    trace_data: dict | None = None,
) -> dict:
    trace = trace_data or {}
    if trace_section:
        try:
            line_trace = json.loads(line.get("calculation_trace", "") or "{}")
            trace = line_trace.get(trace_section, {})
        except json.JSONDecodeError:
            trace = {}
    return {
        "payroll_item_id": f"PI_{line.get('payroll_line_id', '')}_{item_code}",
        "payroll_run_id": line.get("payroll_run_id", ""),
        "payroll_line_id": line.get("payroll_line_id", ""),
        "employee_snapshot_id": line.get("employee_snapshot_id", ""),
        "employee_id": line.get("employee_id", ""),
        "person_id": line.get("person_id", ""),
        "employment_relationship_id": line.get("employment_relationship_id", ""),
        "item_code": item_code,
        "item_name": item_name,
        "item_category": item_category,
        "amount": round(_as_number(amount), 2),
        "currency": "CNY",
        "taxable": taxable,
        "affects_net_pay": affects_net_pay,
        "cost_company_id": line.get("payroll_company_id", "") if item_category in ("earning", "employer_cost", "info") else "",
        "source_object_type": source_object_type,
        "source_object_id": source_object_id,
        "applied_rule_ids": applied_rule_ids,
        "calculation_trace": _trace({item_code.lower(): trace}),
    }


def _adjustments_by_employee(rows: list[dict]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        employee_id = row.get("employee_id", "")
        adjustment_type = row.get("adjustment_type", "") or "其他"
        result.setdefault(employee_id, {})
        result[employee_id][adjustment_type] = (
            result[employee_id].get(adjustment_type, 0.0)
            + _as_number(row.get("amount", 0.0))
        )
    return result


def _match_split_rule(rules: list[dict], position: str) -> dict | None:
    for rule in reversed(rules):
        if rule.get("position_or_type") == position:
            return rule
    for rule in reversed(rules):
        if rule.get("position_or_type") == "员工":
            return rule
    return rules[-1] if rules else None


def _grade_coefficient(rules: list[dict], grade: str) -> float:
    rule = _match_grade_rule(rules, grade)
    return _as_number(rule.get("coefficient")) if rule else 0.0


def _match_grade_rule(rules: list[dict], grade: str) -> dict | None:
    for rule in reversed(rules):
        if rule.get("performance_grade") == grade:
            return rule
    return None


def _deductions_by_employee(rows: list[dict]) -> dict[str, dict[str, dict[str, float]]]:
    result: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        employee_id = row.get("employee_id", "")
        deduction_type = row.get("deduction_type", "")
        result.setdefault(employee_id, {})
        result[employee_id].setdefault(
            deduction_type,
            {"personal_amount": 0.0, "employer_amount": 0.0},
        )
        result[employee_id][deduction_type]["personal_amount"] += _as_number(
            row.get("personal_amount")
        )
        result[employee_id][deduction_type]["employer_amount"] += _as_number(
            row.get("employer_amount")
        )
    return result
