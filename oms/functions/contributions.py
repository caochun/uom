from __future__ import annotations

from .utils import _as_number, _rule_ids, _trace


def _calculate_social_security(employee_snapshot: dict, rule: dict | None) -> dict:
    if not rule:
        return {"base": 0.0, "employer_total": 0.0, "personal_total": 0.0}
    raw_base = (
        employee_snapshot.get("social_security_base")
        or employee_snapshot.get("monthly_salary_base")
        or employee_snapshot.get("monthly_salary_total")
    )
    base = _bounded_base(
        _as_number(raw_base),
        _as_number(rule.get("lower_bound")),
        _as_number(rule.get("upper_bound")),
    )
    employer_pension = round(base * _as_number(rule.get("employer_pension_rate")), 2)
    employer_injury = round(base * _as_number(rule.get("employer_injury_rate")), 2)
    employer_unemployment = round(base * _as_number(rule.get("employer_unemployment_rate")), 2)
    employer_medical = round(base * _as_number(rule.get("employer_medical_rate")), 2)
    employer_maternity = round(base * _as_number(rule.get("employer_maternity_rate")), 2)
    personal_pension = round(base * _as_number(rule.get("personal_pension_rate")), 2)
    personal_unemployment = round(base * _as_number(rule.get("personal_unemployment_rate")), 2)
    personal_medical = round(base * _as_number(rule.get("personal_medical_rate")), 2)
    personal_serious_illness = _as_number(rule.get("personal_serious_illness_amount"))
    return {
        "base": base,
        "employer_pension": employer_pension,
        "employer_injury": employer_injury,
        "employer_unemployment": employer_unemployment,
        "employer_medical": employer_medical,
        "employer_maternity": employer_maternity,
        "employer_total": round(
            employer_pension
            + employer_injury
            + employer_unemployment
            + employer_medical
            + employer_maternity,
            2,
        ),
        "personal_pension": personal_pension,
        "personal_unemployment": personal_unemployment,
        "personal_medical": personal_medical,
        "personal_serious_illness": personal_serious_illness,
        "personal_total": round(
            personal_pension
            + personal_unemployment
            + personal_medical
            + personal_serious_illness,
            2,
        ),
        "lower_bound": _as_number(rule.get("lower_bound")),
        "upper_bound": _as_number(rule.get("upper_bound")),
    }


def _calculate_housing_fund(employee_snapshot: dict, rule: dict | None) -> dict:
    if not rule:
        return {"base": 0.0, "employer_amount": 0.0, "personal_amount": 0.0, "total_amount": 0.0}
    base = _as_number(
        employee_snapshot.get("housing_fund_base")
        or employee_snapshot.get("monthly_salary_base")
        or employee_snapshot.get("monthly_salary_total")
    )
    employer_amount = base * _as_number(rule.get("employer_rate"))
    personal_amount = base * _as_number(rule.get("personal_rate"))
    if rule.get("rounding_rule") == "ROUND0":
        employer_amount = round(employer_amount)
        personal_amount = round(personal_amount)
    return {
        "base": base,
        "employer_amount": round(float(employer_amount), 2),
        "personal_amount": round(float(personal_amount), 2),
        "total_amount": round(float(employer_amount) + float(personal_amount), 2),
        "employer_rate": _as_number(rule.get("employer_rate")),
        "personal_rate": _as_number(rule.get("personal_rate")),
        "rounding_rule": rule.get("rounding_rule", ""),
    }


def _social_contribution_record(
    contribution_id: str,
    employee_snapshot: dict,
    contribution_period: str,
    social: dict,
) -> dict:
    return {
        "contribution_id": contribution_id,
        "employee_id": employee_snapshot.get("employee_id", ""),
        "contribution_company_id": employee_snapshot.get("payroll_company_id", ""),
        "contribution_period": contribution_period,
        "contribution_base": social.get("base", 0.0),
        "employer_pension": social.get("employer_pension", 0.0),
        "employer_injury": social.get("employer_injury", 0.0),
        "employer_unemployment": social.get("employer_unemployment", 0.0),
        "employer_medical": social.get("employer_medical", 0.0),
        "employer_maternity": social.get("employer_maternity", 0.0),
        "employer_total": social.get("employer_total", 0.0),
        "personal_pension": social.get("personal_pension", 0.0),
        "personal_unemployment": social.get("personal_unemployment", 0.0),
        "personal_medical": social.get("personal_medical", 0.0),
        "personal_serious_illness": social.get("personal_serious_illness", 0.0),
        "personal_total": social.get("personal_total", 0.0),
        "status": "deducted",
        "applied_rule_ids": _rule_ids(
            "social_security_base_bounds",
            "social_security_employer_formula",
            "social_security_personal_formula",
        ),
        "calculation_trace": _trace({
            "social_security": {
                "contribution_base": social.get("base", 0.0),
                "lower_bound": social.get("lower_bound", 0.0),
                "upper_bound": social.get("upper_bound", 0.0),
                "personal_total": social.get("personal_total", 0.0),
                "employer_total": social.get("employer_total", 0.0),
            },
        }),
    }


def _housing_contribution_record(
    housing_fund_id: str,
    employee_snapshot: dict,
    contribution_period: str,
    housing: dict,
    rule: dict | None,
) -> dict:
    return {
        "housing_fund_id": housing_fund_id,
        "employee_id": employee_snapshot.get("employee_id", ""),
        "contribution_company_id": employee_snapshot.get("payroll_company_id", ""),
        "contribution_period": contribution_period,
        "contribution_base": housing.get("base", 0.0),
        "employer_rate": _as_number(rule.get("employer_rate")) if rule else 0.0,
        "personal_rate": _as_number(rule.get("personal_rate")) if rule else 0.0,
        "employer_amount": housing.get("employer_amount", 0.0),
        "personal_amount": housing.get("personal_amount", 0.0),
        "total_amount": housing.get("total_amount", 0.0),
        "rounding_rule": rule.get("rounding_rule", "") if rule else "",
        "status": "deducted",
        "applied_rule_ids": _rule_ids(
            "housing_fund_formula",
            "housing_fund_round0" if rule and rule.get("rounding_rule") == "ROUND0" else "",
        ),
        "calculation_trace": _trace({
            "housing_fund": {
                "housing_rule_id": rule.get("housing_rule_id", "") if rule else "",
                "contribution_base": housing.get("base", 0.0),
                "employer_rate": _as_number(rule.get("employer_rate")) if rule else 0.0,
                "personal_rate": _as_number(rule.get("personal_rate")) if rule else 0.0,
                "rounding_rule": rule.get("rounding_rule", "") if rule else "",
                "employer_amount": housing.get("employer_amount", 0.0),
                "personal_amount": housing.get("personal_amount", 0.0),
                "total_amount": housing.get("total_amount", 0.0),
            },
        }),
    }


def _contribution_deduction_record(
    deduction_id: str,
    employee_snapshot: dict,
    deduction_type: str,
    contribution_record_id: str,
    contribution_period: str,
    payroll_run_id: str,
    payroll_period: str,
    personal_amount: float,
    employer_amount: float,
) -> dict:
    return {
        "deduction_id": deduction_id,
        "employee_id": employee_snapshot.get("employee_id", ""),
        "person_id": employee_snapshot.get("person_id", ""),
        "employee_snapshot_id": employee_snapshot.get("employee_snapshot_id", ""),
        "employment_relationship_id": employee_snapshot.get("employment_relationship_id", ""),
        "deduction_type": deduction_type,
        "contribution_record_id": contribution_record_id,
        "contribution_company_id": employee_snapshot.get("payroll_company_id", ""),
        "contribution_period": contribution_period,
        "personal_amount": personal_amount,
        "employer_amount": employer_amount,
        "deducted_payroll_run_id": payroll_run_id,
        "deducted_payroll_period": payroll_period,
        "deduction_reason": "正常扣款",
        "status": "deducted",
        "applied_rule_ids": _rule_ids("contribution_normal_month"),
        "calculation_trace": _trace({
            "contribution_deduction": {
                "deduction_type": deduction_type,
                "contribution_record_id": contribution_record_id,
                "contribution_company_id": employee_snapshot.get("payroll_company_id", ""),
                "contribution_period": contribution_period,
                "deducted_payroll_run_id": payroll_run_id,
                "deducted_payroll_period": payroll_period,
                "personal_amount": personal_amount,
                "employer_amount": employer_amount,
                "deduction_reason": "正常扣款",
            },
        }),
    }


def _bounded_base(value: float, lower: float, upper: float) -> float:
    if lower:
        value = max(value, lower)
    if upper:
        value = min(value, upper)
    return value
