# OMS 薪资计算规则目录

本文档把 V3.0 薪资系统需求中的计算规则显式列出。`ontology.yaml.rules` 保存机器可读的规则索引，函数返回的 `applied_rule_ids` 和 `calculation_trace` 用于把每条计算结果追溯到这里。

## 规则分层

- 主数据事实：`Person`、`Employee`、`EmploymentRelationship`、`SalaryProfile`、`Company`、`InternalAffiliation` 描述某个时点的客观状态。
- 快照事实：`PayrollInputSnapshot`、`PayrollEmployeeSnapshot` 冻结某次薪资计算使用的员工、公司、归属和基数。
- 规则表：`SalarySplitRule`、`PerformanceGradeRule`、`SocialInsuranceRule`、`HousingFundRule`、`TaxRateRule` 保存可配置的比例、系数和税率。
- 计算结果：`PayrollLine` 保存员工月度工资汇总，`PayrollItem` 保存可扩展工资项明细；`SocialInsuranceContribution`、`HousingFundContribution`、`ContributionDeduction`、当前期 `TaxLedger` 等由函数计算生成，并用 `applied_rule_ids` 和 `calculation_trace` 说明来源。
- Excel 校对基准：`data/benchmarks/*_expected.csv` 保存 mock workbook 中的结果视图，只用于 diff 校对，不作为正式事实输入。

当前根目录 `data/*.csv` 只保留输入事实和规则种子；`PayrollLine`、`PayrollItem`、社保公积金缴费、扣款台账、工资条、成本和顾问费结算等结果对象 CSV 只有表头。`TaxLedger` 根目录文件只保留计算前历史累计输入，当前期完整个税结果在 `data/benchmarks/tax_ledger_expected.csv`。

## 已实现规则

| 规则 ID | 作用对象 | 结果字段 | 规则摘要 |
| --- | --- | --- | --- |
| `payroll_salary_split_formula` | `PayrollLine` | `basic_salary`, `performance_salary_base` | 按岗位薪资拆分规则计算基本薪资和绩效薪资基数。 |
| `payroll_performance_salary_formula` | `PayrollLine` | `performance_salary` | 按绩效等级系数计算绩效薪资。 |
| `payroll_gross_before_deduction_formula` | `PayrollLine` | `gross_pay_before_deduction` | 扣除前应发工资 = 基本薪资 + 绩效薪资 + 考勤补扣 + 其他补扣。 |
| `social_security_base_bounds` | `SocialInsuranceContribution`, `PayrollLine` | `contribution_base` | 社保基数按公司规则套用上下限。 |
| `social_security_employer_formula` | `SocialInsuranceContribution`, `PayrollLine` | `employer_total`, `employer_social_security` | 单位社保 = 单位养老 + 工伤 + 失业 + 医疗 + 生育。 |
| `social_security_personal_formula` | `SocialInsuranceContribution`, `ContributionDeduction`, `PayrollLine` | `personal_total`, `personal_social_security` | 个人社保 = 个人养老 + 失业 + 医疗 + 大病固定金额。 |
| `housing_fund_formula` | `HousingFundContribution`, `ContributionDeduction`, `PayrollLine` | `personal_housing_fund`, `employer_housing_fund` | 公积金按公司比例和基数计算。 |
| `housing_fund_round0` | `HousingFundContribution`, `PayrollLine` | `personal_amount`, `employer_amount` | 公积金规则为 `ROUND0` 时金额取整数。 |
| `contribution_normal_month` | `ContributionDeduction` | `deduction_reason`, `status` | 正常月份社保公积金在当前薪资批次扣除。 |
| `tax_cumulative_withholding` | `TaxLedger`, `PayrollLine` | `personal_income_tax` | 工资薪金个税按累计预扣法计算。 |
| `net_pay_formula` | `PayrollLine`, `Payslip` | `net_pay` | 实发工资 = 扣除前应发 - 个人社保 - 个人公积金 - 个税。 |
| `company_total_cost_formula` | `PayrollLine`, `CostEntry` | `company_total_cost` | 公司总成本 = 扣除前应发 + 单位社保 + 单位公积金。 |
| `negative_net_pay_warning` | `PayrollLine` | `exception_notes` | 实发工资为负数时保留结果并提示复核。 |

## 已建模但未完整实现规则

| 规则 ID | 状态 | 说明 |
| --- | --- | --- |
| `contribution_onboarding_two_months` | planned | 入职首次发薪可能扣两个月社保公积金，需要结合入职、起薪、参保起始月和首个发薪批次判断。 |
| `contribution_termination_stop` | planned | 离职后是否停扣发薪月社保公积金，需要结合停缴状态判断。 |
| `contribution_transfer_pending` | planned | 公司调转时，费用产生公司和实际扣款批次可能分离，需要 pending 台账跨月追踪。 |
| `consultant_not_salary_tax` | modeled | 顾问劳务费不进入工资薪金累计个税，后续顾问费计算函数需要继续落地。 |
| `payslip_net_pay_reconciliation` | planned | 工资条实发金额必须与工资明细实发金额一致。 |
| `cost_company_split` | modeled | 成本按费用产生公司和内部归属归集，后续成本生成函数需要实现。 |

## 追踪字段约定

- `applied_rule_ids` 使用逗号分隔的规则 ID，例如 `payroll_salary_split_formula,tax_cumulative_withholding,net_pay_formula`。
- `calculation_trace` 使用 JSON 字符串，记录命中的规则表行、关键输入、公式输出和最终结果。
- 根目录结果对象 CSV 当前可以为空；函数计算预览必须返回这两个字段，作为后续写回和审计依据。

## EMP030 示例

以 `EMP030` 的 2026-04 工资批次为例：

- `gross_pay_before_deduction = 6000 + 4000 + 0 + 0 = 10000`
- 个人社保 = `800 + 50 + 200 + 10 = 1060`
- 个人公积金 = `10000 * 12% = 1200`
- 累计预扣个税当前计算结果 = `595.76`
- `net_pay = 10000 - 1060 - 1200 - 595.76 = 7144.24`
- `company_total_cost = 10000 + 2450 + 1200 = 13650`

函数会同时生成 `PayrollItem` 明细，例如基本薪资、绩效薪资、个人社保、个人公积金、个税、公司社保、公司公积金和公司总成本，用于后续落库、工资条和成本归集。
