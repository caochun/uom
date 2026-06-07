from __future__ import annotations

# Compatibility re-exports. New code should import from utils/payroll/contributions/tax directly.
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
    _first_id,
    _line_diff,
    _load_benchmark_rows,
    _merge_rule_ids,
    _merge_trace,
    _record_diff,
    _rule_ids,
    _select_effective,
    _select_period_rule,
    _trace,
)
