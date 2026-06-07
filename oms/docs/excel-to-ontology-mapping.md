# Excel 到薪资领域模型映射说明

来源文件：`202604工资明细.xlsx`

对应本体：`../ontology.yaml`

本文档用于把现有 Excel 工作簿结构映射到薪资系统领域模型。它不是导入模板终稿，而是建模评审和后续导入开发的对照表。

当前 `domains/oms/data/` 采用“输入事实与校对基准分离”的结构：

- `data/*.csv` 只作为 object repository 的输入事实和规则种子。工资明细、社保公积金缴费、扣款台账、工资条、成本、审批、导出等计算结果对象只保留表头，等待函数计算生成。
- `data/benchmarks/*_expected.csv` 保存从 Excel 结果表抽取出的期望结果，用于校对系统计算结果，不作为事实输入。
- `data/tax_ledger.csv` 是一个例外中的输入表：它只保留计算前历史累计输入，例如上期累计收入、上期累计专项扣除、上月累计已扣税；当前期收入、当前期税额和当前期累计结果保存在 `data/benchmarks/tax_ledger_expected.csv` 中作为校对基准。

因此主线应理解为：

```text
Excel mock
-> 抽取输入事实和规则到 data/*.csv
-> 系统函数基于快照和规则计算结果
-> 与 data/benchmarks/*_expected.csv 做差异校对
```

## 1. 总体判断

`202604工资明细.xlsx` 不是单一数据表，而是一组围绕月度薪资批次形成的输入、计算表和导出视图。

系统建模时不应按 sheet 直接建表，而应按以下核心对象承载业务：

| 领域对象 | 用途 |
|---|---|
| `PayrollRun` | 一次月度薪资核算批次 |
| `Person` | 自然人身份主档 |
| `EmploymentRelationship` | 员工与公司在某时间段内的雇佣、任职或劳务关系 |
| `PayrollInputSnapshot` | 一次薪资批次计算前冻结的输入事实集合 |
| `PayrollEmployeeSnapshot` | 单个员工在薪资输入快照中的冻结状态 |
| `PayrollLine` | 员工在该批次中的工资明细 |
| `PayrollItem` | 工资明细中的单个工资项、扣款项、税务项或公司成本项 |
| `SalaryProfile` | 员工薪资档案版本 |
| `AttendanceSummary` | 月度考勤结果 |
| `PerformanceRecord` | 月度绩效等级 |
| `PayrollAdjustment` | 考勤或其他补扣 |
| `SocialInsuranceContribution` | 社保缴费记录 |
| `HousingFundContribution` | 公积金缴费记录 |
| `ContributionDeduction` | 社保公积金待扣、已扣、补扣台账 |
| `TaxLedger` | 工资薪金累计个税台账 |
| `Payslip` | 员工工资条 |
| `CostEntry` | 人力成本归集明细 |
| `ConsultantEngagement` | 顾问服务关系 |
| `ConsultantFeeSettlement` | 顾问劳务费结算 |

## 2. Sheet 到领域对象映射

| Excel sheet | Excel 角色 | 当前落地口径 | 备注 |
|---|---|---|---|
| `202604工资表` | 总工资表、核算入口 | 输入事实: `PayrollRun`, `PayrollInputSnapshot`, `PayrollEmployeeSnapshot`, `Person`, `Employee`, `EmploymentRelationship`, `SalaryProfile`, `PerformanceRecord`, `PayrollAdjustment`；校对基准: `payroll_line_expected.csv` | 工资明细结果不写入根目录 `payroll_line.csv`，由函数计算生成。 |
| `202604工资明细表（尚诚能源）` | 分公司工资明细 | 校对基准: `payroll_line_expected.csv` | 是按公司过滤后的工资明细视图，不作为事实输入。 |
| `202604工资明细表（南大尚诚）` | 分公司工资明细 | 校对基准: `payroll_line_expected.csv` | 同上。 |
| `202604工资明细表（基石）` | 分公司工资明细 | 校对基准: `payroll_line_expected.csv` | 同上。 |
| `202604社保 (尚诚能源)` | 社保缴费明细 | 规则种子: `SocialInsuranceRule`；校对基准: `social_insurance_contribution_expected.csv`, `contribution_deduction_expected.csv` | 社保所属月份为发放月相关缴费月，不等同于工资归属月。 |
| `202604社保(南大尚诚)` | 社保缴费明细 | 规则种子: `SocialInsuranceRule`；校对基准同上 | 需要解析社保产生公司。 |
| `202604社保(基石)` | 社保缴费明细 | 规则种子: `SocialInsuranceRule`；校对基准同上 | 工伤比例按公司配置。 |
| `202604公积金(尚诚能源)` | 公积金缴费明细 | 规则种子: `HousingFundRule`；校对基准: `housing_fund_contribution_expected.csv`, `contribution_deduction_expected.csv` | 尚诚能源样例比例为 10%/10%。 |
| `202604公积金(南大尚诚)` | 公积金缴费明细 | 规则种子: `HousingFundRule`；校对基准同上 | 南大尚诚样例比例为 10%/10%。 |
| `202604公积金(基石)` | 公积金缴费明细 | 规则种子: `HousingFundRule`；校对基准同上 | 基石样例比例为 12%/12%。 |
| `202604综合所得申报税款计算(...)` | 个税申报/累计计算 | 输入事实: 历史累计 `TaxLedger`；校对基准: `tax_ledger_expected.csv` | 根目录 `tax_ledger.csv` 只保留计算前历史累计输入。 |
| `202604钉钉工资卡` | 员工工资条导出 | 校对基准: `payslip_expected.csv` | 是面向员工的发扣展示，不是标准工资档案。 |
| `202604月成本汇总` | 月人力成本汇总 | 校对基准: `cost_entry_expected.csv` | 成本口径应由系统按费用来源重新生成。 |
| `202604考勤` | 月度考勤汇总 | 待抽取: `AttendanceSummary`, `PayrollAdjustment` | 一期尚未抽取完整考勤汇总。 |
| `马骏老师202604` | 顾问劳务费样例 | 输入事实: `Person`, `ConsultantEngagement`；校对基准: `consultant_fee_settlement_expected.csv`, `cost_entry_expected.csv` | “马骏老师”只是样例，模型应支持多个公司顾问。 |

## 3. 关键字段映射

### 3.1 总工资表

Sheet：`202604工资表`

| Excel 字段 | 领域字段 | 说明 |
|---|---|---|
| 姓名 | `Person.name`, `PayrollEmployeeSnapshot.employee_name_snapshot`, `PayrollLine.employee_name_snapshot` | 只作展示和导入匹配辅助，系统主键应使用员工编号。 |
| 公司 | `EmploymentRelationship.company_id`, `PayrollEmployeeSnapshot.payroll_company_id`, `PayrollLine.payroll_company_id` | Excel 中包含内部归属语义时，系统需拆成薪资结算公司和内部归属；按期间判断任职关系应使用 `EmploymentRelationship`。 |
| 起薪时间 | `Employee.salary_start_date` | 用于判断起薪和入职补扣。 |
| 花名册薪资 | `SalaryProfile.roster_salary` | 薪资档案字段。 |
| 月薪基数 | `SalaryProfile.monthly_salary_base`, `PayrollLine.monthly_salary_base` | 薪资档案和当月快照都应保留。 |
| 月薪资总额 | `PayrollLine.monthly_salary_total` | 当月计算基数。 |
| 岗位 | `SalaryProfile.position_or_type`, `PayrollEmployeeSnapshot.position_snapshot`, `PayrollLine.position`, `SalarySplitRule.position_or_type` | 决定基本薪资和绩效薪资基数拆分，计算时应使用快照中的岗位或人员类型。 |
| 基本薪资 | `PayrollLine.basic_salary` | 由岗位拆分规则计算。 |
| 绩效薪资基数 | `PayrollLine.performance_salary_base` | 由岗位拆分规则计算。 |
| 绩效等级 | `PerformanceRecord.performance_grade`, `PayrollLine.performance_grade` | 工资归属月使用同月绩效。 |
| 绩效薪资 | `PayrollLine.performance_salary` | 由绩效等级系数计算。 |
| 补发扣 | `PayrollAdjustment.amount`, `PayrollLine.attendance_adjustment`, `PayrollLine.other_adjustment` | 系统中至少拆成考勤和其他。 |
| 实际应发薪资 | `PayrollLine.gross_pay_before_deduction` | Excel 名称容易误解，本质是扣除前应发工资。 |

### 3.1.1 自然人、员工身份和任职关系

自然人、员工身份和任职关系是三层概念：`Person` 表示自然人，`Employee` 表示员工身份，`EmploymentRelationship` 表示员工与公司在某段时间内建立的雇佣、任职或劳务关系。公司和内部归属都可能随时间变化，因此系统不应把公司和内部归属放在 `Employee` 主档案上。

当前模型新增：

| 领域字段 | 说明 |
|---|---|
| `EmploymentRelationship.employment_relationship_id` | 任职关系记录编号 |
| `EmploymentRelationship.employee_id` | 员工编号 |
| `EmploymentRelationship.effective_date` | 任职关系生效日期 |
| `EmploymentRelationship.expiry_date` | 任职关系失效日期，空表示当前有效 |
| `EmploymentRelationship.company_id` | 该期间建立关系的公司主体 |
| `EmploymentRelationship.internal_affiliation_id` | 该期间内部归属 |
| `EmploymentRelationship.relationship_reason` | 入职、公司调转、内部归属调整、导入初始化、人工更正等 |

`Person` 保存姓名、证件、联系方式等自然人信息；`Employee` 保存员工身份；`PayrollEmployeeSnapshot`、`PayrollLine` 和 `CostEntry` 保留公司与内部归属快照，并通过 `employment_relationship_id` 追溯当期任职关系来源。

### 3.1.2 薪资输入快照

薪资计算应先取快照，再基于快照计算。客观事实源可以变化，但某次工资计算使用的输入事实应被冻结。

当前模型新增两层快照：

| 对象 | 说明 |
|---|---|
| `PayrollInputSnapshot` | 某个 `PayrollRun` 在计算前冻结的输入事实集合。 |
| `PayrollEmployeeSnapshot` | 快照中单个员工的姓名、归属、公司、内部归属、薪资档案和计算基数。 |

主线变成：

```text
Person / Employee / EmploymentRelationship / SalaryProfile / Rule
-> PayrollInputSnapshot / PayrollEmployeeSnapshot
-> PayrollLine / Payslip / CostEntry
```

`PayrollLine` 现在通过 `employee_snapshot_id` 引用员工薪资输入快照，同时保留员工、公司和内部归属的 ID 与名称快照，方便展示、审计和追溯。

### 3.2 分公司工资明细表

Sheets：

- `202604工资明细表（尚诚能源）`
- `202604工资明细表（南大尚诚）`
- `202604工资明细表（基石）`

| Excel 字段 | 领域字段 | 说明 |
|---|---|---|
| 姓名 | `PayrollLine.employee_name` | 需要用员工编号替代姓名匹配。 |
| 月薪基数 | `PayrollLine.monthly_salary_base` | 当月快照。 |
| 实际应发工资 | `PayrollLine.gross_pay_before_deduction` | 扣个人社保、公积金、个税前。 |
| 基本养老保险费/失业保险费/基本医疗保险费/大病保险费 | `SocialInsuranceContribution.personal_*`, `ContributionDeduction.personal_amount` | 工资明细里展示的是个人扣款结果。 |
| 社保合计 | `PayrollLine.personal_social_security` | 本次工资扣除的个人社保合计。 |
| 住房公积金 | `PayrollLine.personal_housing_fund` | 本次工资扣除的个人公积金。 |
| 专项附加扣除相关列 | `TaxLedger.cumulative_deductions` | 进入累计扣除口径。 |
| 上月累计收入 | `TaxLedger` 上期累计相关字段 | 系统应保存上月累计数据，不依赖复制 Excel。 |
| 累计收入 | `TaxLedger.cumulative_income` | 累计预扣法字段。 |
| 减除费用 | `TaxLedger.cumulative_basic_deduction` | 通常按月份累计。 |
| 累计计税部分 | `TaxLedger.cumulative_taxable_income` | 小于 0 时按 0 处理。 |
| 累计个税 | `TaxLedger.cumulative_tax_payable` | 累计应纳税额。 |
| 上月累计个税 | `TaxLedger.previous_cumulative_tax_withheld` | 本月个税计算依赖。 |
| 本月个税 | `PayrollLine.personal_income_tax`, `TaxLedger.current_tax` | 工资明细和个税台账均需保存。 |
| 实发工资 | `PayrollLine.net_pay` | 员工最终到手金额，允许为负数但要提醒。 |

### 3.3 社保表

Sheets：

- `202604社保 (尚诚能源)`
- `202604社保(南大尚诚)`
- `202604社保(基石)`

| Excel 字段 | 领域字段 | 说明 |
|---|---|---|
| 单位名称 | `Company.company_name`, `SocialInsuranceContribution.contribution_company_id` | 表示社保产生公司。 |
| 所属月份 | `SocialInsuranceContribution.contribution_period` | 样例为 2026-05，不等同工资归属月 2026-04。 |
| 个人代码 | 可作为外部社保标识 | ontology 初版暂未单独建字段，可后续补充。 |
| 姓名 | `Person.name` | 仅辅助匹配。 |
| 缴费基数 | `SocialInsuranceContribution.contribution_base` | 需受上下限规则约束。 |
| 单位养老/工伤/失业/医疗/生育 | `SocialInsuranceContribution.employer_*` | 工伤比例按公司配置。 |
| 单位合计 | `SocialInsuranceContribution.employer_total` | 公司承担社保。 |
| 个人养老/失业/医疗/大病 | `SocialInsuranceContribution.personal_*` | 个人承担社保。 |
| 个人合计 | `SocialInsuranceContribution.personal_total` | 用于工资扣款和成本汇总。 |

社保表导入后还要生成或更新 `ContributionDeduction`：

| 台账字段 | 口径 |
|---|---|
| `contribution_company_id` | 社保产生公司 |
| `contribution_period` | 社保缴费月 |
| `deducted_payroll_period` | 实际扣在哪个工资归属月 |
| `status` | `pending` / `deducted` / `waived` |
| `deduction_reason` | 正常扣款、入职补扣、调转补扣、离职停扣等 |

### 3.4 公积金表

Sheets：

- `202604公积金(尚诚能源)`
- `202604公积金(南大尚诚)`
- `202604公积金(基石)`

| Excel 字段 | 领域字段 | 说明 |
|---|---|---|
| 单位 | `Company.company_name`, `HousingFundContribution.contribution_company_id` | 表示公积金产生公司。 |
| 姓名 | `Person.name` | 仅辅助匹配。 |
| 基数 | `HousingFundContribution.contribution_base` | 公积金基数。 |
| 单位比例列 | `HousingFundContribution.employer_rate`, `employer_amount` | 比例按公司和月份配置。 |
| 个人比例列 | `HousingFundContribution.personal_rate`, `personal_amount` | 比例按公司和月份配置。 |
| 合计 | `HousingFundContribution.total_amount` | 单位和个人合计。 |

公积金也必须进入 `ContributionDeduction`，不能只在工资明细里保存一个扣款合计。

### 3.5 个税申报表

Sheets：

- `202604综合所得申报税款计算(尚诚能源)`
- `202604综合所得申报税款计算(南大尚诚)`
- `202604综合所得申报税款计算(基石)`

| Excel 字段 | 领域字段 | 说明 |
|---|---|---|
| 工号 | `Employee.employee_id` 或外部工号 | 如果为空，不能依赖姓名作为长期主键。 |
| 姓名 | `Person.name` | 仅辅助匹配。 |
| 证件类型/证件号码 | `Person.id_type`, `Person.id_number` | 敏感字段。 |
| 税款所属期起/止 | `TaxLedger.tax_period` | 应与发放月一致。 |
| 所得项目 | 计算口径 | 正式员工为正常工资薪金；顾问劳务费不进入该台账。 |
| 本期收入 | `TaxLedger.current_income` | 本月扣除前应发工资。 |
| 本期养老/医疗/失业/住房公积金 | `TaxLedger.cumulative_deductions` 的组成 | 与社保公积金扣款数据核对。 |
| 累计收入额 | `TaxLedger.cumulative_income` | 累计预扣法核心字段。 |
| 累计减除费用 | `TaxLedger.cumulative_basic_deduction` | 累计减除费用。 |
| 累计专项扣除 | `TaxLedger.cumulative_deductions` | 累计扣除组成。 |
| 累计应纳税所得额 | `TaxLedger.cumulative_taxable_income` | 小于 0 时按 0。 |
| 税率/速算扣除数 | `TaxRateRule.tax_rate`, `quick_deduction` | 系统规则配置。 |
| 累计应纳税额 | `TaxLedger.cumulative_tax_payable` | 累计税额。 |
| 已缴税额/应补(退)税额 | `TaxLedger.previous_cumulative_tax_withheld`, `current_tax` | 本月个税要与工资明细一致。 |

注意：南大尚诚个税 sheet 的行数非常大，导入时必须按有效姓名、所得项目、税款所属期等过滤，不能按 `max_row` 全量当作有效数据。

### 3.6 钉钉工资卡

Sheet：`202604钉钉工资卡`

| Excel 字段 | 领域字段 | 说明 |
|---|---|---|
| 姓名 | `Payslip.employee_id` 间接关联员工 | 导出时显示姓名，内部仍用员工编号。 |
| 基本工资 | `PayrollLine.basic_salary` | 工资条展示字段。 |
| 绩效薪资基数 | `PayrollLine.performance_salary_base` | 工资条展示字段。 |
| 绩效等级 | `PayrollLine.performance_grade` | 工资条展示字段。 |
| 绩效薪资 | `PayrollLine.performance_salary` | 工资条展示字段。 |
| 加班薪资 | `PayrollLine.overtime_salary` | 当前样例多为不适用，模型保留。 |
| 考勤补扣 | `PayrollLine.attendance_adjustment` | 来自考勤或导入。 |
| 其他补扣 | `PayrollLine.other_adjustment` | 需有原因。 |
| 实际应发工资 | `Payslip.gross_pay_before_deduction` | 等于扣除前应发。 |
| 社保合计 | `Payslip.social_security_deduction` | 还需要展示扣款月份和产生公司。 |
| 住房公积金 | `Payslip.housing_fund_deduction` | 同上。 |
| 个人所得税 | `Payslip.personal_income_tax` | 与工资明细本月个税一致。 |
| 实发金额 | `Payslip.net_pay` | 必须等于 `PayrollLine.net_pay`。 |

系统工资条比 Excel 多出的关键字段：

| 字段 | 原因 |
|---|---|
| `deduction_periods` | 展示本次扣了哪些缴费月。 |
| `deduction_company_ids` | 展示费用在哪家公司产生。 |
| `deduction_note` | 说明正常扣、入职补扣、调转补扣、离职停扣等。 |

### 3.7 月成本汇总

Sheet：`202604月成本汇总`

| Excel 字段 | 领域字段 | 说明 |
|---|---|---|
| 姓名 | `CostEntry.employee_id`、`person_id` 或 `consultant_engagement_id` | 内部不要按姓名聚合。 |
| 月工资总额（应发） | `CostEntry.cost_type=扣除前应发工资` | 成本组成之一。 |
| 月工资总额（实发） | 可由 `PayrollLine.net_pay` 派生 | 不应作为唯一成本口径。 |
| 社保费用（公司） | `CostEntry.cost_type=公司社保` | 按社保产生公司归集。 |
| 社保费用（个人） | `CostEntry.cost_type=个人社保` | 用于还原应发和核对。 |
| 公积金费用（公司） | `CostEntry.cost_type=公司公积金` | 按公积金产生公司归集。 |
| 公积金费用（个人） | `CostEntry.cost_type=个人公积金` | 用于还原应发和核对。 |
| 个人所得税 | `CostEntry.cost_type=个税` | 与工资薪金个税一致。 |
| 其他 | `CostEntry.cost_type=其他费用` 或 `顾问劳务费` | 顾问费应单独口径。 |
| 合计 | `CostEntry` 聚合结果 | 不是单条事实，建议由明细聚合。 |

成本汇总的主线是：

```text
公司总成本 = 扣除前应发工资 + 公司承担社保 + 公司承担公积金 + 顾问劳务费 + 其他费用
```

如果员工发生公司调转，`CostEntry.cost_company_id` 必须能拆开显示。

### 3.8 考勤表

Sheet：`202604考勤`

该表是横向日期型考勤汇总，列数较多。系统一期建议先解析为两层：

| 层次 | 领域对象 | 说明 |
|---|---|---|
| 月度汇总 | `AttendanceSummary` | 用于薪资计算和补扣。 |
| 原始明细 | 暂不进入 ontology 初版 | 可保留在导入附件或后续排班模块。 |

系统当前更关注：

| 数据 | 目标字段 |
|---|---|
| 员工 | `AttendanceSummary.employee_id` |
| 考勤月份 | `AttendanceSummary.attendance_period` |
| 病假/事假/旷工等汇总 | `sick_leave_days`, `personal_leave_days`, `absenteeism_days` |
| 考勤补扣金额 | `AttendanceSummary.attendance_adjustment`, `PayrollAdjustment.amount` |

### 3.9 顾问劳务费表

Sheet：`马骏老师202604`

这个 sheet 只是顾问劳务费样例，不应把“马骏老师”建成特殊对象。

| Excel 字段 | 领域字段 | 说明 |
|---|---|---|
| 姓名 | `Person.name` | 公司顾问自然人姓名。 |
| 公司 | `ConsultantFeeSettlement.company_id` | 结算公司。 |
| 含税劳务金额 | `ConsultantFeeSettlement.gross_service_fee` | 顾问费含税金额。 |
| 不含税劳务金额 | `ConsultantFeeSettlement.net_of_tax_fee` | 按劳务费规则计算。 |
| 税额/代扣劳务个税 | `ConsultantFeeSettlement.withheld_tax` | 劳务报酬个税，不进入工资薪金累计台账。 |
| 应纳税所得额 | `ConsultantFeeSettlement.taxable_income` | 劳务报酬口径。 |
| 实发金额 | `ConsultantFeeSettlement.net_payment` | 顾问最终收款。 |
| 起薪时间 | `ConsultantEngagement.service_start_date` | 顾问服务开始日期。 |

顾问费可进入 `CostEntry`：

| 字段 | 建议值 |
|---|---|
| `cost_type` | `顾问劳务费` |
| `consultant_engagement_id` | 对应顾问服务关系 |
| `cost_company_id` | 结算或成本产生公司 |
| `cost_period` | 顾问费归属月 |

## 4. 代表性样例建议

下一轮建议从 Excel 中抽取少量脱敏样例，不需要全量导入：

| 样例类型 | 用途 |
|---|---|
| 正常员工 | 验证总工资表、分公司明细、工资条、成本汇总的一般链路。 |
| 入职补扣员工 | 验证入职月和发放月两个月社保公积金扣款。 |
| 离职员工 | 验证发上月工资时不扣发放月社保公积金。 |
| 公司调转员工 | 验证社保公积金产生公司和扣款工资公司一致。 |
| 负数实发员工 | 验证允许负数实发并生成提醒。 |
| 公司顾问 | 验证顾问劳务费不进入工资薪金累计个税，但进入成本。 |

每个样例建议整理为：

```text
员工/顾问编号
工资归属月
薪资结算公司
内部归属
社保公积金产生公司和缴费月
扣款工资归属月
个税所属期
扣除前应发
个人社保
个人公积金
本月个税
实发
公司成本
期望校验结果
```

## 5. 待确认问题

| 问题 | 影响 |
|---|---|
| 员工编号来源是什么，Excel 中是否已有稳定工号列？ | 决定导入主键和历史数据匹配方式。 |
| `南大尚诚（人力）` 等内部归属在 Excel 中具体有哪些取值？ | 决定 `InternalAffiliation` 初始字典。 |
| 个税表中的工号为空时如何匹配员工？ | 避免继续按姓名匹配。 |
| 社保个人代码、公积金账号是否需要纳入员工外部标识？ | 影响社保公积金导入稳定性。 |
| 非 1 号调转是否要一期支持工资拆分？ | 影响 `PayrollLine` 是否需要支持同人同月多行工资。 |
| 顾问费是否每位顾问都固定月额，还是需要合同/服务期间/发票信息？ | 影响是否增加顾问合同或服务项目对象。 |
| 银行代发是否一期导出？ | 影响 `PayrollExport.export_type` 和敏感字段权限。 |

## 6. 初版导入顺序建议

1. 导入或维护 `Company`、`InternalAffiliation`、规则表。
2. 导入 `Employee` 和 `SalaryProfile`。
3. 创建 `PayrollRun`。
4. 导入 `AttendanceSummary`、`PerformanceRecord`、`PayrollAdjustment`。
5. 计算 `PayrollLine` 草稿。
6. 计算 `SocialInsuranceContribution`、`HousingFundContribution` 和 `ContributionDeduction`。
7. 基于历史累计输入计算当前期 `TaxLedger` 和 `PayrollLine.net_pay`。
8. 生成 `Payslip` 和 `CostEntry`。
9. 执行 `PayrollValidationResult`，并可与 `data/benchmarks/*_expected.csv` 做差异校对。
10. 审批锁定并导出。

## 7. 当前数据抽取落地

已新增一套初版工程化落地：

| 文件 | 用途 |
|---|---|
| `../scripts/extract_excel_to_csv.py` | 从 `202604工资明细.xlsx` 抽取输入事实、规则种子和 Excel 校对基准。 |
| `../functions/__init__.py` | 注册 OMS 专用 `table` CSV adapter，使 `ObjectRepository` 可以直接查询 CSV。 |
| `../data/*.csv` | object repository 的输入事实和规则种子；计算结果对象 CSV 只保留表头。 |
| `../data/benchmarks/*_expected.csv` | 从 Excel 结果视图抽取的校对基准，不进入正式事实输入。 |

抽取命令：

```bash
python3 domains/oms/scripts/extract_excel_to_csv.py
```

Repository 验证命令：

```bash
PYTHONPATH=agent python3 - <<'PY'
from oag.ontology.loader import load_domain

ontology, repo, registry = load_domain("domains/oms")
for obj in [
    "Employee",
    "PayrollRun",
    "PayrollLine",
    "PayrollItem",
    "SocialInsuranceContribution",
    "HousingFundContribution",
    "ContributionDeduction",
    "TaxLedger",
    "Payslip",
    "CostEntry",
    "ConsultantFeeSettlement",
    "PayrollValidationResult",
]:
    print(obj, repo.count(obj))
PY
```

当前根目录 `data/*.csv` 输入事实和规则种子数量如下：

| 对象 | 记录数 |
|---|---:|
| `PayrollRun` | 1 |
| `PayrollInputSnapshot` | 1 |
| `PayrollEmployeeSnapshot` | 188 |
| `Person` | 189 |
| `Employee` | 188 |
| `EmploymentRelationship` | 188 |
| `SalaryProfile` | 188 |
| `PerformanceRecord` | 188 |
| `TaxLedger` | 184 |
| `ConsultantEngagement` | 1 |
| `SalarySplitRule` | 6 |
| `PerformanceGradeRule` | 6 |
| `SocialInsuranceRule` | 3 |
| `HousingFundRule` | 3 |
| `TaxRateRule` | 7 |

当前根目录中这些计算结果对象只保留表头，记录数为 0：`PayrollLine`、`PayrollItem`、`SocialInsuranceContribution`、`HousingFundContribution`、`ContributionDeduction`、`Payslip`、`CostEntry`、`ConsultantFeeSettlement`、`PayrollValidationResult`、`ApprovalRecord`、`PayrollExport`。

当前 `data/benchmarks` 中的 Excel 校对基准数量如下：

| Benchmark 文件 | 记录数 |
|---|---:|
| `payroll_line_expected.csv` | 188 |
| `social_insurance_contribution_expected.csv` | 177 |
| `housing_fund_contribution_expected.csv` | 148 |
| `contribution_deduction_expected.csv` | 325 |
| `tax_ledger_expected.csv` | 184 |
| `payslip_expected.csv` | 188 |
| `cost_entry_expected.csv` | 374 |
| `consultant_fee_settlement_expected.csv` | 1 |
| `payroll_validation_result_expected.csv` | 559 |

### 7.1 Adapter 设计

OMS 的 `ontology.yaml` 对象目前大多未显式声明 `source`，运行时默认是 `table` source。

在 OMS 域内，`functions/__init__.py` 把 `table` 注册为 `OmsCsvFileAdapter`：

```text
ObjectRepository
-> object source.type = table
-> OmsCsvFileAdapter
-> domains/oms/data/<object_snake_case>.csv
```

这样不需要在每个 object 上重复写 CSV 路径，同时也保留了以后切换 SQLite、数据库或外部 API 的空间。

### 7.2 当前抽取策略

这份 Excel 是为系统设计准备的 mock workbook，可能存在表间姓名、行数、公式区域等错误。抽取脚本不是原样 sheet dump，而是先按本体对象整理内部相对一致的数据，再分流为输入事实和校对基准：

| 来源 | 当前处理 |
|---|---|
| 总工资表 | 作为 canonical 员工、归属历史、薪资档案、员工快照、绩效和补扣来源；工资明细结果写入 `payroll_line_expected.csv`。 |
| 分公司工资明细 | 优先按姓名匹配 canonical 员工；匹配不上时按公司内行序对齐；结果字段写入 `payroll_line_expected.csv`。 |
| 社保表 | 只在姓名能匹配同公司 canonical 员工时写入 `social_insurance_contribution_expected.csv` 和 `contribution_deduction_expected.csv`；匹配失败只写校验警告。 |
| 公积金表 | 只在姓名能匹配同公司 canonical 员工时写入 `housing_fund_contribution_expected.csv` 和 `contribution_deduction_expected.csv`；匹配失败只写校验警告。 |
| 个税表 | 只在姓名能匹配同公司 canonical 员工时作为个税校对来源；工资薪金个税输入优先来自分公司工资明细。 |
| 钉钉工资卡 | 结果写入 `payslip_expected.csv`。 |
| 月成本汇总 | 结果写入 `cost_entry_expected.csv`。 |
| 顾问劳务费表 | 生成顾问自然人和顾问服务关系；顾问费结算和顾问费成本写入 benchmark。 |

由于当前 Excel 缺少稳定员工编号，脚本先基于工作簿生成 `EMP001` 这类临时员工编号。后续拿到真实工号或 HR 主数据后，应替换为真实 `employee_id`。

### 7.3 Mock 修正规则

当前 workbook 的表间数据不是完全一致的真实数据，因此抽取时允许修正 mock 错误。已采用的修正规则：

1. 以 `202604工资表` 作为 canonical 员工清单，不再让社保、公积金、个税表扩展员工集合。
2. 分公司工资明细中的姓名如果能匹配 canonical 员工，则直接匹配；匹配失败时可按公司内行序对齐以修正 mock 工资视图。
3. 社保、公积金、个税表中的姓名如果不能匹配同公司 canonical 员工，则只写入 `PayrollValidationResult`，不生成正式扣款或个税输入。
4. 如果来源行超出该公司 canonical 员工数量，则跳过该行。
5. 所有行序对齐、未匹配或跳过的情况都写入 `PayrollValidationResult`，作为 mock 风险说明。

这使得抽取后的输入事实更适合作为系统实现的种子数据，同时仍保留 workbook 结果视图作为 benchmark，用于验证系统计算是否接近原 Excel。

### 7.4 当前限制

| 限制 | 后续处理 |
|---|---|
| 员工编号是临时生成 | 接入真实员工编号或 HR 主数据。 |
| 任职关系当前每名员工只有一条初始化记录 | 后续用调转、内部归属调整等事件追加 `EmploymentRelationship` 版本。 |
| 社保、公积金、个税表缺少稳定员工标识 | 当前不再按公司内行序绑定员工；后续接入真实数据时应改为员工编号、证件号或外部系统主键匹配。 |
| 考勤表尚未抽取为 `AttendanceSummary` | 需要确认考勤汇总列和补扣金额来源。 |
| 审批和导出记录为空 | 这是 Excel 静态数据中没有的过程数据，后续由系统流程产生。 |
| 领域函数尚未全部实现 | 已实现 `resolve_employee_state_at`、`resolve_rules_at`、`build_payroll_snapshot`、`generate_payroll_lines`、`calculate_contributions`、`calculate_payroll` 预览，审批、导出等函数仍是占位。 |
| 根目录计算结果对象为空 | 当前函数返回计算预览，后续接入可写 repository 后再写入结果对象。 |
| `data/benchmarks` 中的结果来自 mock Excel | 只用于校对，不应作为生产事实输入。 |

### 7.5 当前函数层能力

`domains/oms/functions/__init__.py` 已把 `table` source 注册为 `OmsCsvFileAdapter`，并实现了六个快照、规则解析和工资计算相关函数：

| 函数 | 当前能力 |
|---|---|
| `resolve_employee_state_at` | 按员工和日期解析当时有效的员工归属、公司、内部归属和薪资档案。 |
| `resolve_rules_at` | 按公司和月份解析当时有效的薪资拆分、绩效、社保、公积金和个税规则。 |
| `build_payroll_snapshot` | 在当前 CSV 种子数据中读取指定薪资批次的 `PayrollInputSnapshot`、`PayrollEmployeeSnapshot` 和校验 warning 摘要。 |
| `generate_payroll_lines` | 基于 `PayrollEmployeeSnapshot`、绩效、补扣和薪资拆分规则生成 `PayrollLine` 草稿和 `PayrollItem` 应发项预览，并与 `data/benchmarks/payroll_line_expected.csv` 做差异摘要。 |
| `calculate_contributions` | 基于 `PayrollEmployeeSnapshot`、社保规则、公积金规则，按文档公式生成 `SocialInsuranceContribution`、`HousingFundContribution` 和 `ContributionDeduction` 预览。支持传入 `employee_id` 单人试算。 |
| `calculate_payroll` | 基于工资明细草稿、已确认扣款台账、`TaxRateRule` 和个税历史累计输入，计算实发工资和当前期 `TaxLedger`；`SocialInsuranceRule`、`HousingFundRule` 只生成缴费建议，不会在缺少已确认 `ContributionDeduction` 时直接扣入工资。支持传入 `employee_id` 单人试算。 |

当前 adapter 是只读 CSV adapter，所以 `build_payroll_snapshot` 暂时是“读取已抽取快照并返回摘要”，`generate_payroll_lines`、`calculate_contributions` 和 `calculate_payroll` 暂时是“返回生成预览和 benchmark 差异摘要”，不是现场写入新记录。`calculate_payroll.result_set` 已按未来落库对象集合组织，后续接入可写 repository 后可升级为真正的工资行、工资项、缴费记录、扣款台账和当前期个税台账写入动作。
