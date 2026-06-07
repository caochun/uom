from __future__ import annotations

from .utils import _as_number, _trace


def _tax_ledger_record(line: dict, tax_period: str, tax_result: dict) -> dict:
    return {
        "tax_ledger_id": f"TAX_{tax_period.replace('-', '')}_{line.get('employee_id', '')}",
        "employee_id": line.get("employee_id", ""),
        "payroll_run_id": line.get("payroll_run_id", ""),
        "tax_period": tax_period,
        "tax_entity_company_id": line.get("payroll_company_id", ""),
        "current_income": tax_result.get("current_income", 0.0),
        "cumulative_income": tax_result.get("cumulative_income", 0.0),
        "cumulative_deductions": tax_result.get("cumulative_deductions", 0.0),
        "cumulative_basic_deduction": tax_result.get("cumulative_basic_deduction", 0.0),
        "cumulative_taxable_income": tax_result.get("cumulative_taxable_income", 0.0),
        "cumulative_tax_payable": tax_result.get("cumulative_tax_payable", 0.0),
        "previous_cumulative_tax_withheld": tax_result.get("previous_cumulative_tax_withheld", 0.0),
        "current_tax": tax_result.get("current_tax", 0.0),
        "source": "system_calculated_preview",
        "reconciliation_status": "未核对",
        "applied_rule_ids": "tax_cumulative_withholding",
        "calculation_trace": _trace({"tax": tax_result}),
    }


def _calculate_personal_income_tax(
    line: dict,
    tax_ledger: dict | None,
    tax_rules: list[dict],
    personal_social_security: float,
    personal_housing_fund: float,
) -> dict:
    current_income = _as_number(line.get("gross_pay_before_deduction"))
    if tax_ledger:
        if tax_ledger.get("current_income") in ("", None):
            previous_income = _as_number(tax_ledger.get("cumulative_income"))
            previous_deductions = _as_number(tax_ledger.get("cumulative_deductions"))
        else:
            previous_income = max(
                _as_number(tax_ledger.get("cumulative_income"))
                - _as_number(tax_ledger.get("current_income")),
                0.0,
            )
            previous_deductions = max(
                _as_number(tax_ledger.get("cumulative_deductions"))
                - personal_social_security
                - personal_housing_fund,
                0.0,
            )
        cumulative_basic_deduction = _as_number(tax_ledger.get("cumulative_basic_deduction"))
        previous_tax_withheld = _as_number(tax_ledger.get("previous_cumulative_tax_withheld"))
    else:
        previous_income = 0.0
        previous_deductions = 0.0
        cumulative_basic_deduction = 5000.0
        previous_tax_withheld = 0.0

    cumulative_income = previous_income + current_income
    cumulative_deductions = previous_deductions + personal_social_security + personal_housing_fund
    taxable_income = max(
        cumulative_income - cumulative_deductions - cumulative_basic_deduction,
        0.0,
    )
    tax_rule = _match_tax_rule(tax_rules, taxable_income)
    cumulative_tax_payable = round(
        taxable_income * _as_number(tax_rule.get("tax_rate") if tax_rule else 0.0)
        - _as_number(tax_rule.get("quick_deduction") if tax_rule else 0.0),
        2,
    )
    current_tax = max(round(cumulative_tax_payable - previous_tax_withheld, 2), 0.0)
    return {
        "rule_id": tax_rule.get("tax_rule_id", "") if tax_rule else "",
        "formula": "max((cumulative_taxable_income * tax_rate - quick_deduction) - previous_cumulative_tax_withheld, 0)",
        "current_income": current_income,
        "previous_income": previous_income,
        "cumulative_income": cumulative_income,
        "previous_deductions": previous_deductions,
        "current_personal_social_security": personal_social_security,
        "current_personal_housing_fund": personal_housing_fund,
        "cumulative_deductions": cumulative_deductions,
        "cumulative_basic_deduction": cumulative_basic_deduction,
        "cumulative_taxable_income": taxable_income,
        "tax_rate": _as_number(tax_rule.get("tax_rate") if tax_rule else 0.0),
        "quick_deduction": _as_number(tax_rule.get("quick_deduction") if tax_rule else 0.0),
        "cumulative_tax_payable": cumulative_tax_payable,
        "previous_cumulative_tax_withheld": previous_tax_withheld,
        "current_tax": current_tax,
    }


def _match_tax_rule(rules: list[dict], taxable_income: float) -> dict | None:
    for rule in rules:
        lower = _as_number(rule.get("lower_bound"))
        upper_raw = rule.get("upper_bound")
        upper = _as_number(upper_raw) if upper_raw not in ("", None) else None
        if taxable_income >= lower and (upper is None or taxable_income <= upper):
            return rule
    return rules[-1] if rules else None
