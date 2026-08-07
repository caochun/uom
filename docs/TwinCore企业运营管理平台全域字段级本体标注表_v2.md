# TwinCore 企业运营管理平台全域字段级本体标注表 V2

## 0. 文档定位

本文是 TwinCore 企业运营管理平台的全域字段级本体标注表。

上一版更多围绕招聘、采购、开票回款三类现实样本展开；本版回到企业运营管理平台全局，覆盖：

1. 客商 CRM
2. 招投标
3. 项目与经营承载
4. 合同、框架协议、执行单、结算、开票回款
5. 人事、招聘、用工、薪酬、发薪、成本
6. 采购、供应商、付款、交付
7. 固定资产、库存、行政资源
8. 知识产权
9. 审批、证据、风险、提醒和经营分析

本表的用途：

1. 给产品设计提供字段口径。
2. 给研发建模提供对象边界。
3. 给本体智能体提供字段语义、关系、规则和校验依据。
4. 给后续数据清洗、Excel 迁移、钉钉审批并入系统提供映射标准。

---

## 1. 字段角色图例

| 标记 | 含义 | 说明 |
|---|---|---|
| `PK` | 主键 | 对象唯一真身 |
| `FK` | 引用关系 | 指向另一个本体对象 |
| `SNAPSHOT` | 快照 | 保存发生当时的名称、规则、金额或文本 |
| `RULE` | 规则字段 | 决定匹配、计算、约束、分流 |
| `TIME` | 时间字段 | 生效、失效、发生、审批、账期 |
| `STATUS` | 状态字段 | 当前状态投影，变化应有事件 |
| `AMOUNT` | 金额/数量 | 合同额、人数、单价、比例、金额 |
| `RESULT` | 结果字段 | 由事件或规则计算得出 |
| `EVIDENCE` | 证据字段 | 附件、单号、凭证、证明材料 |
| `RISK` | 风险字段 | 风险等级、异常类型、预警状态 |
| `TEXT` | 描述字段 | 说明、备注、原因，不能承担主键职责 |

---

## 2. 全域对象总表

| 业务域 | 主对象 | 关系/规则/事件/结果对象 |
|---|---|---|
| 客商 CRM | `customer` `contact` `product` | `customer_department` `customer_billing_info` `customer_bid_site` `opportunity` `follow_up` `customer_follow_up` `sales_task` `sales_expense` `customer_change_log` `customer_name_history` `rfm_score` |
| 招投标 | `bid_pre_reg` `bid_tender` | `bid_research` `bid_account` `bid_pre_issuer` `bid_accompany` `bid_competitor` `bid_progress` `bid_notice_trace` `bid_review` `bid_service_fee_payment` `bid_partner_qual` |
| 项目 | `project` `virtual_project` | `project_estimate` `project_estimate_line` `project_member` `project_opportunity_link` `project_contract_link` `project_progress` `project_review` `project_acceptance` `operating_anchor_type` `operating_anchor` |
| 合同结算 | `contract` `contract_execution_order` | `contract_sub` `contract_service_item` `contract_labor_scope` `contract_internal_allocation` `internal_contract_bridge` `partner_transfer_settlement` `customer_settlement_rule` `internal_settlement_rule` `settlement_batch` `settlement_line` `settlement_progress` `contract_invoice_plan` `contract_payment_plan` `contract_invoice` `contract_payment` `receivable_item` `payment_allocation` |
| 人事薪酬 | `employee` `external_person` `candidate` | `staffing_request` `staffing_request_line` `position_definition` `staffing_demand_reason_definition` `staffing_nature_definition` `employee_employment` `employee_contribution_profile` `employee_compensation_profile` `emp_contract` `payroll_item_definition` `salary_structure_template` `salary_structure_component` `employment_type_definition` `employment_type_payroll_rule` |
| 发薪成本 | `payroll_batch` | `payroll_calendar_day` `payroll_split_rule` `payroll_parameter_rule` `payroll_line` `social_insurance_line` `housing_fund_line` `tax_filing_line` `labor_fee_line` `payslip_line` `employee_cost_component` `employee_cost_allocation` `employee_month_cost_summary` |
| 采购 | `purchase_request` `purchase_order` | `purchase_subject_type` `purchase_invoice` `purchase_payment` `purchase_delivery` `purchase_approval_event` `supplier_role_profile` `supplier_risk_profile` `purchase_cost_allocation` |
| 固定资产 | `fixed_asset` | `asset_assignment` `asset_inventory_check` `asset_partner_reconciliation` `inventory_transaction` |
| 知识产权 | `ip_application` `ip_asset` | `ip_classification_scheme` `ip_classification_item` `ip_application_classification` `ip_asset_classification` `ip_app_author` `ip_author` `ip_app_progress` |
| 平台治理 | `approval_flow` `document_evidence` `risk_event` | `reminder_task` `data_quality_issue` `operation_metric_snapshot` `contract_code_rule` `collection_escalation_rule` |

---

## 3. 客商 CRM 域

### 3.1 `customer` 外部组织主体

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 外部组织 ID | `PK` | - | 外部组织唯一真身 |
| `name` | 当前名称 | `SNAPSHOT` | - | 名称可变，不作唯一关联 |
| `short_name` | 简称 | `SNAPSHOT` | - | 可用于展示和搜索 |
| `unified_social_credit_code` | 统一社会信用代码 | `EVIDENCE` | - | 相同税号多主档提示重复 |
| `company_role_types` | 组织角色 | `RULE` | `customer_role_definition` | 客户、供应商、合作方、招标方多角色不重复建档 |
| `customer_level_id` | 客户等级 | `FK/RULE` | `customer_level_definition` | 可定义，不做死枚举 |
| `industry_id` | 行业 | `FK/RULE` | `industry_definition` | 可定义 |
| `region_id` | 区域 | `FK/RULE` | `region_definition` | 用于经营分析 |
| `owner_department_id` | 归属部门 | `FK` | `department` | 客户经营责任归属 |
| `owner_employee_id` | 客户负责人 | `FK` | `employee` | 客户跟进责任 |
| `status` | 状态 | `STATUS` | - | 有效、停用、待确认 |
| `risk_level` | 风险等级 | `RISK` | - | 简化高/中/低即可 |

### 3.2 `contact` 外部联系人

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 联系人 ID | `PK` | - | 外部自然人真身 |
| `name` | 姓名 | `SNAPSHOT` | - | 同名需客户/手机号辅助 |
| `customer_id` | 所属外部组织 | `FK` | `customer` | 不只存公司名 |
| `customer_department_id` | 客户部门 | `FK` | `customer_department` | 可选 |
| `position_title` | 职务 | `SNAPSHOT` | - | 岗位变化应保留历史 |
| `phone` | 电话 | `EVIDENCE` | - | 敏感信息需权限 |
| `email` | 邮箱 | `EVIDENCE` | - | 可用于沟通证据 |
| `relationship_level_id` | 关系等级 | `FK/RULE` | `relationship_level_definition` | 可定义 |
| `is_key_contact` | 是否关键联系人 | `RULE` | - | 影响客户风险和跟进 |
| `status` | 状态 | `STATUS` | - | 在职、离职、未知 |

### 3.3 `customer_department` 客户内部部门

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 客户部门 ID | `PK` | - | 客户组织树节点 |
| `customer_id` | 客户 | `FK` | `customer` | 必填 |
| `name` | 部门名称 | `SNAPSHOT` | - | 不作全局唯一 |
| `parent_department_id` | 上级部门 | `FK` | `customer_department` | 不允许循环 |
| `leader_contact_id` | 部门负责人 | `FK` | `contact` | 可选 |
| `status` | 状态 | `STATUS` | - | 有效、停用 |

### 3.4 `customer_billing_info` 客户开票信息

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 开票信息 ID | `PK` | - | 开票主数据 |
| `customer_id` | 客户 | `FK` | `customer` | 必填 |
| `invoice_title` | 发票抬头 | `SNAPSHOT/EVIDENCE` | - | 与客户税号一致 |
| `tax_id` | 税号 | `EVIDENCE` | - | 合同开票前需核验 |
| `bank_name` | 开户行 | `EVIDENCE` | - | 开票/收款参考 |
| `bank_account` | 银行账号 | `EVIDENCE` | - | 权限控制 |
| `effective_from` | 生效日期 | `TIME` | - | 信息变更可追溯 |
| `status` | 状态 | `STATUS` | - | 有效、停用 |

### 3.5 `opportunity` 商机

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 商机 ID | `PK` | - | 机会对象真身 |
| `opportunity_no` | 商机编号 | `RULE/SNAPSHOT` | `code_rule` | 自动生成 |
| `title` | 商机标题 | `SNAPSHOT` | - | 展示 |
| `customer_id` | 客户 | `FK` | `customer` | 商机必须有客户或潜在客户 |
| `main_contact_id` | 主要联系人 | `FK` | `contact` | 可选但建议 |
| `source_id` | 商机来源 | `FK/RULE` | `opportunity_source_definition` | 可定义 |
| `stage_id` | 阶段 | `FK/RULE` | `opportunity_stage_definition` | 不做死枚举 |
| `primary_project_id` | 主关联项目 | `FK` | `project` | 商机可提前生成或绑定内部真实项目 |
| `pre_project_required` | 是否需要前置项目 | `RULE` | - | 商机一旦发生人员、采购、方案或投标投入，应提示建项或绑定项目 |
| `investment_started` | 是否已发生投入 | `STATUS/RULE` | - | 有员工入项、采购申请、投标费用或方案任务即为已投入 |
| `estimated_amount` | 预计金额 | `AMOUNT` | - | 经营预测 |
| `estimated_cost` | 预计投入成本 | `AMOUNT` | - | 售前/专项投入预算 |
| `planned_sign_date` | 计划签约日期 | `TIME` | - | 计划，不是结果 |
| `owner_department_id` | 归属部门 | `FK` | `department` | 经营责任 |
| `owner_employee_id` | 负责人 | `FK` | `employee` | 跟进责任 |
| `recovery_tracking_required` | 是否跟踪投入回收 | `RULE` | - | 已发生投入的商机必须持续跟踪合同、开票、回款 |
| `status` | 状态 | `STATUS` | - | 跟进中、转投标、签约、丢单等 |

### 3.6 `follow_up` / `customer_follow_up` 跟进事件

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 跟进 ID | `PK` | - | 事件追加 |
| `customer_id` | 客户 | `FK` | `customer` | 客户跟进必填 |
| `opportunity_id` | 商机 | `FK` | `opportunity` | 商机跟进必填 |
| `contact_id` | 联系人 | `FK` | `contact` | 可选 |
| `follow_up_method_id` | 跟进方式 | `FK/RULE` | `follow_up_method_definition` | 电话、拜访、会议等可定义 |
| `follow_up_date` | 跟进日期 | `TIME` | - | 必填 |
| `content` | 跟进内容 | `TEXT` | - | 事件说明 |
| `next_plan` | 下一步计划 | `TEXT` | - | 后续任务 |
| `owner_employee_id` | 跟进人 | `FK` | `employee` | 必填 |
| `attachment_ids` | 证据 | `EVIDENCE` | `document_evidence` | 会议纪要等 |

### 3.7 `product` / `service_catalog` 产品与服务目录

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 目录 ID | `PK` | - | 产品/服务真身 |
| `code` | 编码 | `RULE/SNAPSHOT` | `code_rule` | 自动或手工规则 |
| `name` | 名称 | `SNAPSHOT` | - | 展示 |
| `catalog_type_id` | 目录类型 | `FK/RULE` | `catalog_type_definition` | 产品、服务、采购标的、IP 服务等 |
| `default_unit_id` | 默认单位 | `FK/RULE` | `unit_definition` | 人月、项、台、件等 |
| `default_unit_price` | 默认单价 | `AMOUNT/RULE` | - | 只是默认，不替代合同价格 |
| `status` | 状态 | `STATUS` | - | 有效、停用 |

---

## 4. 招投标域

### 4.1 `bid_pre_reg` 预投标登记

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 预投标 ID | `PK` | - | 承诺前对象 |
| `pre_reg_no` | 预登记编号 | `RULE/SNAPSHOT` | `code_rule` | 自动生成 |
| `opportunity_id` | 商机 | `FK` | `opportunity` | 可选但推荐 |
| `customer_id` | 客户/招标方 | `FK` | `customer` | 必填 |
| `project_name_snapshot` | 项目名称快照 | `SNAPSHOT` | - | 招标原始名称 |
| `our_role_id` | 我方角色 | `FK/RULE` | `bid_role_definition` | 主投、陪标、联合体等 |
| `decision_status` | 投标决策状态 | `STATUS` | - | 待评估、决定投、不投 |
| `owner_department_id` | 牵头部门 | `FK` | `department` | 必填 |
| `handler_employee_id` | 经办人 | `FK` | `employee` | 必填 |
| `created_date` | 登记日期 | `TIME` | - | 必填 |
| `status` | 状态 | `STATUS` | - | 预登记、转正式、取消 |

### 4.2 `bid_tender` 正式投标

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 投标 ID | `PK` | - | 正式投标主对象 |
| `tender_no` | 投标编号 | `RULE/SNAPSHOT` | `code_rule` | 自动生成 |
| `bid_pre_reg_id` | 预投标 | `FK` | `bid_pre_reg` | 从预投标转入 |
| `opportunity_id` | 商机 | `FK` | `opportunity` | 可选 |
| `customer_id` | 招标方/客户 | `FK` | `customer` | 必填 |
| `tender_section_name` | 标段名称 | `SNAPSHOT` | - | 原始快照 |
| `our_role_id` | 我方角色 | `FK/RULE` | `bid_role_definition` | 主投/陪标等 |
| `bid_amount` | 投标金额 | `AMOUNT` | - | 可选 |
| `bid_date` | 投标日期 | `TIME` | - | 必填 |
| `owner_department_id` | 牵头部门 | `FK` | `department` | 必填 |
| `handler_employee_id` | 经办人 | `FK` | `employee` | 必填 |
| `review_status` | 评审状态 | `STATUS` | - | 未审、初审、复审、通过 |
| `result_status` | 中标结果 | `STATUS` | - | 中标、未中、待定 |
| `contract_id` | 形成合同 | `FK` | `contract` | 中标后可关联 |
| `status` | 状态 | `STATUS` | - | 进行中、完成、取消 |
| `attachment_ids` | 标书/公告/文件 | `EVIDENCE` | `document_evidence` | 高风险必填 |

### 4.3 `bid_research` 投标调研

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 调研 ID | `PK` | - | 证据/判断对象 |
| `bid_pre_reg_id` | 预投标 | `FK` | `bid_pre_reg` | 可选 |
| `bid_tender_id` | 正式投标 | `FK` | `bid_tender` | 可选 |
| `qualification_match` | 资质匹配 | `RULE/STATUS` | - | 不满足需提示 |
| `competitor_analysis` | 竞争分析 | `TEXT` | - | 说明 |
| `risk_note` | 风险说明 | `RISK/TEXT` | - | 高风险必填 |
| `research_date` | 调研日期 | `TIME` | - | 必填 |
| `researcher_employee_id` | 调研人 | `FK` | `employee` | 必填 |
| `attachment_ids` | 调研证据 | `EVIDENCE` | `document_evidence` | 可选 |

### 4.4 投标过程事件对象

适用对象：`bid_progress`、`bid_notice_trace`、`bid_review`、`bid_service_fee_payment`。

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 事件 ID | `PK` | - | 事件追加 |
| `bid_tender_id` | 正式投标 | `FK` | `bid_tender` | 必填 |
| `event_type_id` | 事件类型 | `FK/RULE` | `bid_event_type_definition` | 进度、通知、评审、服务费等 |
| `event_date` | 发生日期 | `TIME` | - | 必填 |
| `owner_employee_id` | 责任人 | `FK` | `employee` | 必填 |
| `result_status` | 结果状态 | `STATUS` | - | 通过、驳回、完成等 |
| `amount` | 金额 | `AMOUNT` | - | 服务费等事件使用 |
| `counterparty_id` | 相对方 | `FK` | `customer` | 陪标、服务费等使用 |
| `content` | 内容 | `TEXT` | - | 事件说明 |
| `attachment_ids` | 证据 | `EVIDENCE` | `document_evidence` | 通知、评审、付款等必填 |

### 4.5 投标关系对象

适用对象：`bid_accompany`、`bid_competitor`、`bid_partner_qual`、`bid_pre_issuer`。

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 关系 ID | `PK` | - | 关系对象 |
| `bid_tender_id` | 正式投标 | `FK` | `bid_tender` | 必填 |
| `related_customer_id` | 相关组织 | `FK` | `customer` | 陪标、竞争对手、合作方 |
| `relationship_type_id` | 关系类型 | `FK/RULE` | `bid_relationship_type_definition` | 可定义 |
| `qualification_name` | 资质名称 | `SNAPSHOT` | - | 合作资质使用 |
| `price_amount` | 报价金额 | `AMOUNT` | - | 竞争对手使用 |
| `confirmed` | 是否确认 | `STATUS` | - | 招标单位确认等 |
| `status` | 状态 | `STATUS` | - | 有效、取消 |
| `attachment_ids` | 证据 | `EVIDENCE` | `document_evidence` | 资质、确认材料 |

---

## 5. 项目与经营承载域

### 5.1 `project` 项目

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 项目 ID | `PK` | - | 项目真身 |
| `project_no` | 项目编号 | `RULE/SNAPSHOT` | `code_rule` | 自动生成 |
| `name` | 项目名称 | `SNAPSHOT` | - | 不作唯一关系 |
| `project_type_id` | 项目类型 | `FK/RULE` | `project_type_definition` | 交付、售前、研发、战略、共通等 |
| `project_category_id` | 项目分类 | `FK/RULE` | `project_category_definition` | 可定义 |
| `source_opportunity_id` | 来源商机 | `FK` | `opportunity` | 售前/专项/预项目应优先绑定来源商机 |
| `customer_id` | 客户 | `FK` | `customer` | 客户项目必填 |
| `contract_id` | 主合同 | `FK` | `contract` | 可选 |
| `execution_order_id` | 执行单 | `FK` | `contract_execution_order` | 框架下项目建议关联 |
| `owner_department_id` | 归属部门 | `FK` | `department` | 必填 |
| `manager_employee_id` | 项目经理 | `FK` | `employee` | 必填 |
| `current_phase_id` | 当前阶段 | `FK/RULE` | `project_phase_definition` | 状态投影 |
| `commercialization_status_id` | 商业化状态 | `FK/RULE` | `project_commercialization_status_definition` | 售前投入、投标中、已签约、丢单沉没、已回收等可定义 |
| `revenue_recovery_tracking_required` | 是否需要收入回收跟踪 | `RULE` | - | 有前期投入或来源商机时必须跟踪合同、开票、回款 |
| `start_date` | 开始日期 | `TIME` | - | 必填 |
| `end_date` | 结束日期 | `TIME` | - | 可选 |
| `status` | 状态 | `STATUS` | - | 立项、执行、验收、完成、暂停 |

### 5.2 `virtual_project` 共通项目/过渡承接对象

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 共通项目 ID | `PK` | - | 过渡对象 |
| `name` | 名称 | `SNAPSHOT` | - | 共通、售前、战略投入 |
| `virtual_type_id` | 共通类型 | `FK/RULE` | `virtual_project_type_definition` | 可定义 |
| `owner_department_id` | 归属部门 | `FK` | `department` | 必填 |
| `customer_id` | 关联客户 | `FK` | `customer` | 可选 |
| `status` | 状态 | `STATUS` | - | 有效、停用 |

### 5.3 `project_estimate` / `project_estimate_line` 项目预估

| 对象 | 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|---|
| `project_estimate` | `id` | 预估 ID | `PK` | - | 主对象 |
| `project_estimate` | `project_id` | 项目 | `FK` | `project` | 售前投入建议先挂前置项目 |
| `project_estimate` | `opportunity_id` | 商机 | `FK` | `opportunity` | 售前预估使用 |
| `project_estimate` | `estimate_stage_id` | 预估阶段 | `FK/RULE` | `estimate_stage_definition` | 可定义 |
| `project_estimate` | `expected_total_cost` | 预计总成本 | `AMOUNT/RESULT` | - | 明细汇总 |
| `project_estimate_line` | `cost_type_id` | 成本类型 | `FK/RULE` | `cost_type_definition` | 可定义 |
| `project_estimate_line` | `amount` | 金额 | `AMOUNT` | - | 必填 |
| `project_estimate_line` | `basis_note` | 估算依据 | `TEXT/EVIDENCE` | - | 大额需依据 |

### 5.4 项目关系与事件对象

适用对象：`project_member`、`project_opportunity_link`、`project_contract_link`、`project_progress`、`project_review`、`project_acceptance`。

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 记录 ID | `PK` | - | 关系或事件 |
| `project_id` | 项目 | `FK` | `project` | 必填 |
| `employee_id` | 员工 | `FK` | `employee` | 成员/评审人等 |
| `opportunity_id` | 商机 | `FK` | `opportunity` | 项目-商机关联 |
| `contract_id` | 合同 | `FK` | `contract` | 项目-合同关联 |
| `link_type_id` | 关系类型 | `FK/RULE` | `project_link_type_definition` | 来源商机、售前支撑、合同回绑、执行单承接等 |
| `link_effective_date` | 关系生效日期 | `TIME` | - | 记录从什么时候发生绑定或升级 |
| `role_id` | 项目角色 | `FK/RULE` | `project_role_definition` | 可定义 |
| `event_type_id` | 事件类型 | `FK/RULE` | `project_event_type_definition` | 进度、评审、验收等 |
| `event_date` | 事件日期 | `TIME` | - | 事件必填 |
| `result_status` | 结果 | `STATUS` | - | 通过、未通过、完成 |
| `attachment_ids` | 证据 | `EVIDENCE` | `document_evidence` | 验收必填 |

### 5.5 `operating_anchor_type` / `operating_anchor` 经营归属对象

| 对象 | 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|---|
| `operating_anchor_type` | `id` | 归属类型 ID | `PK` | - | 主数据 |
| `operating_anchor_type` | `name` | 类型名称 | `SNAPSHOT` | - | 项目、商机、共通、客户专项等 |
| `operating_anchor_type` | `applies_to` | 适用范围 | `RULE` | - | 成本、资源、采购等 |
| `operating_anchor` | `id` | 归属对象 ID | `PK` | - | 具体归属 |
| `operating_anchor` | `anchor_type_id` | 归属类型 | `FK/RULE` | `operating_anchor_type` | 必填 |
| `operating_anchor` | `project_id` | 项目 | `FK` | `project` | 视类型必填 |
| `operating_anchor` | `opportunity_id` | 商机 | `FK` | `opportunity` | 视类型必填 |
| `operating_anchor` | `department_id` | 部门 | `FK` | `department` | 共通归属使用 |
| `operating_anchor` | `customer_id` | 客户 | `FK` | `customer` | 客户专项使用 |

---

## 6. 合同、执行单、结算、开票回款域

### 6.1 建模建议：框架协议下新增 `contract_execution_order`

建议采用四层结构：

1. `contract`：统一承载普通合同、框架协议、执行协议、订单型合同等正式协议主对象。
2. `contract_execution_order`：承载框架协议下的订单、执行协议、批次、范围和结算边界。
3. `contract_labor_scope`：承载劳务范围、甲方项目、内部项目、人员范围等细化范围。
4. `contract_sub`：只用于法律或商务意义上的子合同/拆分合同，不承载所有执行订单。

### 6.2 `contract` 合同/协议主对象

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 合同 ID | `PK` | - | 协议主真身 |
| `contract_no` | 合同编号 | `RULE/SNAPSHOT` | `contract_code_rule` | 系统自动生成 |
| `name` | 合同名称 | `SNAPSHOT` | - | 不作为唯一关系 |
| `agreement_type_id` | 协议类型 | `FK/RULE` | `agreement_type_definition` | 普通、框架、订单、执行协议等 |
| `is_framework_contract` | 是否框架 | `RULE` | - | 框架下需执行单或范围 |
| `parent_contract_id` | 上级合同 | `FK` | `contract` | 执行协议可挂框架 |
| `party_a_customer_id` | 甲方 | `FK` | `customer` | 原则不允许空 |
| `party_b_company_id` | 我方主体 | `FK` | `company_entity` | 南大尚诚/尚诚能源等 |
| `owner_department_id` | 归属部门 | `FK` | `department` | 收入、催收、责任 |
| `project_manager_id` | 项目经理 | `FK` | `employee` | 催收责任 |
| `contract_amount` | 合同金额 | `AMOUNT` | - | 与执行单/开票对账 |
| `signed_date` | 签署日期 | `TIME` | - | 高风险需附件 |
| `start_date` | 开始日期 | `TIME` | - | 有效期 |
| `end_date` | 结束日期 | `TIME` | - | 有效期 |
| `default_settlement_rule_id` | 默认结算规则 | `FK/RULE` | `customer_settlement_rule` | 可被执行单覆盖 |
| `status` | 状态 | `STATUS` | - | 拟定、已签、履约中、完成、终止 |
| `attachment_ids` | 合同附件 | `EVIDENCE` | `document_evidence` | 已签必填 |

### 6.3 `contract_execution_order` 合同执行单/订单

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 执行单 ID | `PK` | - | 执行边界真身 |
| `execution_no` | 执行单编号 | `RULE/SNAPSHOT` | `contract_code_rule` | 自动生成 |
| `parent_framework_contract_id` | 所属框架 | `FK` | `contract` | 框架订单必填 |
| `execution_type_id` | 执行类型 | `FK/RULE` | `execution_type_definition` | 订单、执行协议、批次、范围 |
| `name` | 执行单名称 | `SNAPSHOT` | - | 展示 |
| `customer_project_name` | 甲方项目名 | `SNAPSHOT` | - | 客户侧快照 |
| `internal_project_id` | 内部项目 | `FK` | `project` | 成本和履约归集 |
| `owner_department_id` | 归属部门 | `FK` | `department` | 责任归属 |
| `project_manager_id` | 项目经理 | `FK` | `employee` | 履约/催收 |
| `scope_start_date` | 范围开始 | `TIME` | - | 必填 |
| `scope_end_date` | 范围结束 | `TIME` | - | 超框架期提示 |
| `order_amount` | 执行金额 | `AMOUNT` | - | 与开票/结算对账 |
| `settlement_rule_id` | 结算规则 | `FK/RULE` | `customer_settlement_rule` | 可覆盖框架默认 |
| `resource_scope_required` | 是否需资源范围 | `RULE` | - | 劳务订单通常为真 |
| `status` | 状态 | `STATUS` | - | 待执行、执行中、完成、终止 |
| `attachment_ids` | 附件 | `EVIDENCE` | `document_evidence` | 订单/执行协议必填 |

### 6.4 `contract_sub` 子合同/拆分合同

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 子合同 ID | `PK` | - | 子合同真身 |
| `parent_contract_id` | 主合同 | `FK` | `contract` | 必填 |
| `sub_no` | 子合同编号 | `RULE/SNAPSHOT` | `contract_code_rule` | 自动生成 |
| `sub_name` | 子合同名称 | `SNAPSHOT` | - | 展示 |
| `sub_amount` | 子合同金额 | `AMOUNT` | - | 与主合同校验 |
| `party_customer_id` | 相对方 | `FK` | `customer` | 可不同于主合同 |
| `status` | 状态 | `STATUS` | - | 有效、终止 |
| `attachment_ids` | 附件 | `EVIDENCE` | `document_evidence` | 必填 |

### 6.5 `contract_labor_scope` 合同劳务范围

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 劳务范围 ID | `PK` | - | 范围对象 |
| `contract_id` | 合同 | `FK` | `contract` | 必填 |
| `execution_order_id` | 执行单 | `FK` | `contract_execution_order` | 有执行单时必填 |
| `client_project_name` | 甲方项目名 | `SNAPSHOT` | - | 客户侧快照 |
| `internal_project_id` | 内部项目 | `FK` | `project` | 成本归集 |
| `resource_scope_rule_id` | 资源范围规则 | `FK/RULE` | `resource_scope_rule` | 人员/岗位/级别 |
| `scope_amount` | 范围金额 | `AMOUNT` | - | 可选 |
| `scope_start_date` | 开始日期 | `TIME` | - | 必填 |
| `scope_end_date` | 结束日期 | `TIME` | - | 必填 |
| `status` | 状态 | `STATUS` | - | 有效、暂停、失效 |

### 6.6 `contract_service_item` 合同服务项

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 服务项 ID | `PK` | - | 合同明细 |
| `contract_id` | 合同 | `FK` | `contract` | 必填 |
| `execution_order_id` | 执行单 | `FK` | `contract_execution_order` | 可选 |
| `service_catalog_id` | 服务目录 | `FK` | `service_catalog` | 必填 |
| `quantity` | 数量 | `AMOUNT` | - | 必填 |
| `unit_price` | 单价 | `AMOUNT/SNAPSHOT` | - | 合同快照 |
| `amount` | 金额 | `AMOUNT/RESULT` | - | 数量 x 单价 |
| `settlement_rule_id` | 结算规则 | `FK/RULE` | `customer_settlement_rule` | 可选 |

### 6.7 `customer_settlement_rule` 客户结算规则

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 规则 ID | `PK` | - | 结算规则真身 |
| `customer_id` | 客户 | `FK` | `customer` | 必填 |
| `framework_contract_id` | 框架合同 | `FK` | `contract` | 必填 |
| `execution_order_id` | 执行单 | `FK` | `contract_execution_order` | 可覆盖框架 |
| `rule_type_id` | 规则类型 | `FK/RULE` | `settlement_rule_type_definition` | 可定义 |
| `role_category_id` | 岗位类别 | `FK/RULE` | `position_definition` | 可定义 |
| `role_level_id` | 级别 | `FK/RULE` | `role_level_definition` | 可定义 |
| `unit_price` | 标准单价 | `AMOUNT/RULE` | - | 必填 |
| `discounted_price` | 折扣价 | `AMOUNT/RULE` | - | 可选 |
| `settlement_cycle_id` | 结算周期 | `FK/RULE` | `settlement_cycle_definition` | 月度、季度、批次 |
| `effective_from` | 生效日期 | `TIME` | - | 必填 |
| `effective_to` | 失效日期 | `TIME` | - | 可选 |

### 6.8 `settlement_batch` / `settlement_line` 结算批次与明细

| 对象 | 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|---|
| `settlement_batch` | `id` | 批次 ID | `PK` | - | 批次真身 |
| `settlement_batch` | `batch_no` | 批次编号 | `RULE/SNAPSHOT` | `code_rule` | 自动生成 |
| `settlement_batch` | `settlement_month` | 结算月份 | `TIME` | - | 必填 |
| `settlement_batch` | `counterparty_id` | 结算相对方 | `FK` | `customer`/内部主体 | 必填 |
| `settlement_batch` | `status` | 状态 | `STATUS` | - | 草稿、对账、确认、完成 |
| `settlement_line` | `id` | 明细 ID | `PK` | - | 明细真身 |
| `settlement_line` | `settlement_batch_id` | 批次 | `FK` | `settlement_batch` | 必填 |
| `settlement_line` | `contract_id` | 合同 | `FK` | `contract` | 必填 |
| `settlement_line` | `execution_order_id` | 执行单 | `FK` | `contract_execution_order` | 框架下推荐 |
| `settlement_line` | `resource_assignment_id` | 资源入项 | `FK` | `resource_assignment` | 人力结算必填 |
| `settlement_line` | `settlement_rule_id` | 结算规则 | `FK/RULE` | `customer_settlement_rule` | 必填 |
| `settlement_line` | `amount` | 结算金额 | `RESULT/AMOUNT` | - | 应可由规则推导 |
| `settlement_line` | `rule_snapshot` | 规则快照 | `SNAPSHOT` | - | 历史追溯必填 |

### 6.9 内部结算与合同拆分

适用对象：`internal_settlement_rule`、`internal_settlement_rule_change`、`contract_internal_allocation`、`internal_contract_bridge`、`partner_transfer_settlement`。

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 记录 ID | `PK` | - | 规则/协议/结果对象 |
| `contract_id` | 合同 | `FK` | `contract` | 必填 |
| `source_company_id` | 来源主体 | `FK` | `company_entity` | 内部承接使用 |
| `target_company_id` | 承接主体 | `FK` | `company_entity`/`customer` | 内部或伙伴 |
| `department_id` | 部门 | `FK` | `department` | 内部拆分 |
| `allocation_ratio` | 拆分比例 | `AMOUNT/RULE` | - | 合计应为 100% |
| `amount` | 金额 | `AMOUNT` | - | 与合同金额校验 |
| `effective_from` | 生效日期 | `TIME` | - | 规则有效期 |
| `change_reason` | 变更原因 | `TEXT/RISK` | - | 规则变更必填 |
| `status` | 状态 | `STATUS` | - | 有效、停用 |

### 6.10 开票、回款、应收、核销

| 对象 | 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|---|
| `contract_invoice_plan` | `plan_date` | 计划开票日期 | `TIME` | `contract` | 计划不是事件 |
| `contract_invoice_plan` | `plan_amount` | 计划开票金额 | `AMOUNT` | `contract` | 与合同额校验 |
| `contract_payment_plan` | `plan_date` | 计划回款日期 | `TIME` | `contract` | 计划不是回款 |
| `contract_payment_plan` | `plan_amount` | 计划回款金额 | `AMOUNT` | `contract` | 与合同额校验 |
| `contract_invoice` | `invoice_no` | 发票号 | `EVIDENCE` | - | 重复提示 |
| `contract_invoice` | `invoice_date` | 开票日期 | `TIME` | - | 暂定账期起点 |
| `contract_invoice` | `invoice_amount` | 开票金额 | `AMOUNT` | - | 超合同提示 |
| `contract_invoice` | `contract_id` | 合同 | `FK` | `contract` | 必填 |
| `contract_invoice` | `execution_order_id` | 执行单 | `FK` | `contract_execution_order` | 框架下推荐 |
| `contract_payment` | `payment_date` | 回款日期 | `TIME` | - | 必填 |
| `contract_payment` | `amount` | 回款金额 | `AMOUNT` | - | 可跨多发票 |
| `contract_payment` | `allocation_status` | 核销状态 | `STATUS/RISK` | - | 未核销、部分、完成、待核销异常 |
| `payment_allocation` | `contract_invoice_id` | 核销发票 | `FK` | `contract_invoice` | 优先发票级 |
| `payment_allocation` | `contract_id` | 合同兜底 | `FK` | `contract` | 无法定位发票时必填 |
| `payment_allocation` | `allocated_amount` | 核销金额 | `AMOUNT` | - | 合计不得超过回款 |
| `receivable_item` | `outstanding_amount` | 未回款金额 | `RESULT/AMOUNT` | - | 小于 0 提示异常 |
| `receivable_item` | `aging_days` | 账龄天数 | `RESULT/RISK` | - | 90 天高频预警，半年中高风险 |
| `collection_follow_up` | `unpaid_reason_id` | 未回款原因 | `FK/RULE` | `unpaid_reason_definition` | 可定义 |
| `collection_follow_up` | `next_action` | 下一步动作 | `TEXT` | - | 催收闭环必填 |

### 6.11 `contract_code_rule` 合同编号规则

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 规则 ID | `PK` | - | 编号规则真身 |
| `rule_name` | 规则名称 | `SNAPSHOT` | - | 必填 |
| `applies_to_agreement_type_id` | 适用协议类型 | `FK/RULE` | `agreement_type_definition` | 合同、框架、执行单、采购合同等 |
| `company_segment_rule` | 公司段规则 | `RULE` | `company_entity` | 南大尚诚、尚诚能源 |
| `year_segment_rule` | 年度段规则 | `RULE` | - | 签署年度/归属年度待定 |
| `business_type_segment_rule` | 业务类型段 | `RULE` | `business_type_definition` | 劳务、科技、采购、框架等 |
| `counterparty_segment_rule` | 客户/供应商段 | `RULE` | `customer` | 编码或简称 |
| `agreement_type_segment_rule` | 协议类型段 | `RULE` | `agreement_type_definition` | HT/FW/DD/ZX 等可定义 |
| `sequence_rule` | 流水规则 | `RULE` | - | 防冲突 |
| `effective_from` | 生效日期 | `TIME` | - | 版本化 |
| `status` | 状态 | `STATUS` | - | 有效、停用 |

---

## 7. 人事、招聘、用工、薪酬与发薪

### 7.1 `employee` 员工主档

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 员工 ID | `PK` | - | 员工唯一真身 |
| `employee_no` | 员工编号 | `RULE/SNAPSHOT` | `code_rule` | 不替代 ID |
| `name` | 姓名 | `SNAPSHOT` | - | 同名需编号区分 |
| `current_department_id` | 当前部门 | `FK` | `department` | 当前投影，历史走调动 |
| `position_id` | 当前岗位 | `FK` | `position_definition` | 标准岗位 |
| `employment_status` | 在职状态 | `STATUS` | - | 在职、离职、待入职 |
| `entry_date` | 入职日期 | `TIME` | - | 必填 |
| `leave_date` | 离职日期 | `TIME` | - | 离职补缺可引用 |
| `identity_document_no` | 证件号 | `EVIDENCE` | - | 权限控制 |

### 7.2 `external_person` 外部服务人员

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 外部人员 ID | `PK` | - | 外部自然人真身 |
| `name` | 姓名 | `SNAPSHOT` | - | 必填 |
| `supplier_id` | 所属供应商 | `FK` | `customer`/`supplier_role_profile` | 人力外包必填 |
| `service_type_id` | 服务类型 | `FK/RULE` | `service_type_definition` | 可定义 |
| `settlement_mode_id` | 结算模式 | `FK/RULE` | `settlement_mode_definition` | 按月、人天、成果等 |
| `contract_required` | 是否需内部合同 | `RULE` | - | 劳务人力可多模式 |
| `status` | 状态 | `STATUS` | - | 在服、暂停、退出 |

### 7.3 `staffing_request` / `staffing_request_line` 用人需求

| 对象 | 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|---|
| `staffing_request` | `request_no` | 需求编号 | `RULE/SNAPSHOT` | `code_rule` | 自动生成 |
| `staffing_request` | `requesting_department_id` | 需求提出部门 | `FK` | `department` | 事业部等同内部部门 |
| `staffing_request` | `request_type_id` | 需求来源类型 | `FK/RULE` | `request_type_definition` | 内部招聘等可定义 |
| `staffing_request` | `approval_status` | 审批状态 | `STATUS` | - | 未审批只能预招聘 |
| `staffing_request_line` | `demand_reason_id` | 需求原因 | `FK/RULE` | `staffing_demand_reason_definition` | 可定义，不枚举 |
| `staffing_request_line` | `replacement_employee_id` | 补缺员工 | `FK` | `employee` | 离职补缺必填 |
| `staffing_request_line` | `position_id` | 内部标准岗位 | `FK` | `position_definition` | 必须映射 |
| `staffing_request_line` | `client_position_name` | 甲方原始岗位 | `SNAPSHOT` | - | 来源快照 |
| `staffing_request_line` | `staffing_nature_id` | 招聘性质 | `FK/RULE` | `staffing_nature_definition` | 影响用工、结算、发薪 |
| `staffing_request_line` | `employment_type_id` | 预期用工类型 | `FK/RULE` | `employment_type_definition` | 招人前确认 |
| `staffing_request_line` | `target_project_id` | 目标项目 | `FK` | `project` | 项目招聘必填 |
| `staffing_request_line` | `target_customer_id` | 目标客户 | `FK` | `customer` | 客户专项必填 |
| `staffing_request_line` | `headcount` | 需求人数 | `AMOUNT` | - | 不是到岗人数 |
| `staffing_request_line` | `line_status` | 明细状态 | `STATUS` | - | 预招聘、招聘中、已到岗等 |

### 7.4 招聘和候选人事件

适用对象：`candidate`、`candidate_interview`、`recruitment_approval_event`、`recruitment_status_event`。

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 记录 ID | `PK` | - | 主体或事件 |
| `staffing_request_line_id` | 招聘明细 | `FK` | `staffing_request_line` | 候选人来源 |
| `candidate_name` | 候选人姓名 | `SNAPSHOT` | - | 转员工前快照 |
| `candidate_phone` | 电话 | `EVIDENCE` | - | 权限控制 |
| `interview_date` | 面试日期 | `TIME` | - | 面试事件必填 |
| `interviewer_employee_id` | 面试人 | `FK` | `employee` | 必填 |
| `interview_result` | 面试结果 | `STATUS` | - | 通过、待定、不通过 |
| `approval_flow_id` | 审批流 | `FK/RULE` | `approval_flow` | 钉钉并入系统 |
| `approval_result` | 审批结果 | `STATUS` | - | 通过、驳回、撤回 |
| `attachment_ids` | 简历/审批证据 | `EVIDENCE` | `document_evidence` | 可选 |

### 7.5 `employment_type_definition` 用工类型

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 用工类型 ID | `PK` | - | 可维护主数据 |
| `type_code` | 类型编码 | `RULE/SNAPSHOT` | `code_rule` | 自动或手工规则 |
| `name` | 类型名称 | `SNAPSHOT` | - | 不做死枚举 |
| `personnel_category_id` | 人员类别 | `FK/RULE` | `personnel_category_definition` | 可定义 |
| `employment_mode_id` | 用工模式 | `FK/RULE` | `employment_mode_definition` | 内部、劳务、混合等 |
| `payroll_rule_required` | 是否需薪资规则 | `RULE` | - | 需要时必须配置 |
| `settlement_rule_required` | 是否需结算规则 | `RULE` | - | 劳务/外包通常需要 |
| `status` | 状态 | `STATUS` | - | 有效、停用 |

### 7.6 员工用工、缴纳、薪酬关系

适用对象：`employee_employment`、`employee_contribution_profile`、`employee_compensation_profile`。

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 关系 ID | `PK` | - | 关系对象 |
| `employee_id` | 员工 | `FK` | `employee` | 必填 |
| `management_company_id` | 管理主体 | `FK` | `company_entity` | 必填 |
| `contract_company_id` | 签约主体 | `FK` | `company_entity` | 必填 |
| `social_security_company_id` | 社保主体 | `FK` | `company_entity` | 缴纳关系使用 |
| `housing_fund_company_id` | 公积金主体 | `FK` | `company_entity` | 缴纳关系使用 |
| `tax_filing_company_id` | 个税申报主体 | `FK` | `company_entity` | 缴纳关系使用 |
| `payroll_company_id` | 发薪主体 | `FK` | `company_entity` | 薪酬关系使用 |
| `cost_bearing_company_id` | 成本承担主体 | `FK` | `company_entity` | 成本归集 |
| `employment_type_id` | 用工类型 | `FK/RULE` | `employment_type_definition` | 必填 |
| `effective_from` | 生效日期 | `TIME` | - | 必填 |
| `effective_to` | 失效日期 | `TIME` | - | 不覆盖历史 |

### 7.7 薪资项目、薪资方案、合同模板、员工合同

| 对象 | 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|---|
| `payroll_item_definition` | `item_code` | 薪资项目编码 | `RULE/SNAPSHOT` | `code_rule` | 可新增 |
| `payroll_item_definition` | `name` | 项目名称 | `SNAPSHOT` | - | 不做固定字段 |
| `payroll_item_definition` | `item_role_id` | 项目角色 | `FK/RULE` | `payroll_item_role_definition` | 应发、扣款、公司成本等 |
| `salary_structure_template` | `version_code` | 方案版本 | `RULE/SNAPSHOT` | - | 版本化 |
| `salary_structure_template` | `applies_to` | 适用范围 | `RULE` | - | 用工/合同版本 |
| `salary_structure_component` | `payroll_item_definition_id` | 薪资项目 | `FK` | `payroll_item_definition` | 从项目库选择 |
| `salary_structure_component` | `calculation_method_id` | 计算方式 | `FK/RULE` | `calculation_method_definition` | 可定义 |
| `salary_structure_component` | `formula_expression` | 公式表达 | `RULE` | - | 需治理 |
| `labor_contract_version_template` | `salary_structure_template_id` | 薪资方案 | `FK` | `salary_structure_template` | 合同模板只选方案 |
| `emp_contract` | `employee_id` | 员工 | `FK` | `employee` | 必填 |
| `emp_contract` | `labor_contract_version_template_id` | 合同版本模板 | `FK` | `labor_contract_version_template` | 必填 |
| `emp_contract` | `salary_structure_snapshot` | 薪资方案快照 | `SNAPSHOT` | - | 必填 |
| `emp_contract` | `signed_date` | 签约日期 | `TIME` | - | 必填 |
| `emp_contract` | `attachment_ids` | 合同附件 | `EVIDENCE` | `document_evidence` | 必填 |

### 7.8 发薪、社保、公积金、个税、工资条

| 对象 | 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|---|
| `payroll_batch` | `payroll_month` | 薪资月份 | `TIME` | - | 必填 |
| `payroll_batch` | `salary_belong_month` | 工资归属月 | `TIME` | - | 必填 |
| `payroll_batch` | `attendance_month` | 考勤月份 | `TIME` | - | 必填 |
| `payroll_batch` | `performance_month` | 绩效月份 | `TIME` | - | 必填 |
| `payroll_batch` | `pay_date` | 发薪日期 | `TIME` | - | 必填 |
| `payroll_batch` | `social_fund_month` | 社保公积金缴费月 | `TIME` | - | 必填 |
| `payroll_batch` | `tax_belong_month` | 个税所属期 | `TIME` | - | 必填 |
| `payroll_line` | `employee_id` | 员工 | `FK` | `employee` | 必填 |
| `payroll_line` | `gross_pay` | 应发 | `RESULT/AMOUNT` | - | 规则生成 |
| `payroll_line` | `net_pay` | 实发 | `RESULT/AMOUNT` | - | 规则生成 |
| `payroll_line` | `rule_snapshot` | 规则快照 | `SNAPSHOT` | - | 必填 |
| `social_insurance_line` | `payment_base` | 社保基数 | `SNAPSHOT/AMOUNT` | - | 历史口径 |
| `housing_fund_line` | `payment_base` | 公积金基数 | `SNAPSHOT/AMOUNT` | - | 历史口径 |
| `tax_filing_line` | `tax_belong_month` | 个税所属期 | `TIME` | - | 必填 |
| `labor_fee_line` | `external_person_id` | 外部人员 | `FK` | `external_person` | 劳务费 |
| `payslip_line` | `employee_id` | 员工 | `FK` | `employee` | 工资条投影 |

### 7.9 员工历史、合规与提醒

适用对象：`emp_education`、`emp_work_history`、`emp_transfer`、`emp_certificate`、`emp_training`、`emp_award`、`emp_project`、`employee_reminder`、`compliance_check`。

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 记录 ID | `PK` | - | 历史/事件 |
| `employee_id` | 员工 | `FK` | `employee` | 必填 |
| `event_type_id` | 事件类型 | `FK/RULE` | `employee_event_type_definition` | 调岗、培训、证书等 |
| `start_date` | 开始日期 | `TIME` | - | 历史关系 |
| `end_date` | 结束日期 | `TIME` | - | 历史关系 |
| `result_status` | 结果状态 | `STATUS` | - | 通过、完成、到期等 |
| `reminder_date` | 提醒日期 | `TIME` | - | 提醒对象 |
| `risk_level` | 风险等级 | `RISK` | - | 合规检查 |
| `attachment_ids` | 证据 | `EVIDENCE` | `document_evidence` | 证书、证明 |

---

## 8. 资源、成本与经营归集

### 8.1 `resource_assignment` 资源入项

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 入项 ID | `PK` | - | 资源入项真身 |
| `entry_context_type_id` | 入项上下文类型 | `FK/RULE` | `resource_entry_context_definition` | 内部真实项目入项、客户结算入项 |
| `resource_subject_type_id` | 资源主体类型 | `FK/RULE` | `resource_subject_type_definition` | 真实员工、真实外部人员、虚拟结算资源 |
| `assignment_track_id` | 入项轨道 | `FK/RULE` | `assignment_track_definition` | 可继续细分交付、售前、投标、结算等 |
| `employee_id` | 员工 | `FK` | `employee` | 内部人员 |
| `external_person_id` | 外部人员 | `FK` | `external_person` | 劳务人力 |
| `virtual_settlement_resource_id` | 虚拟结算资源 | `FK` | `virtual_settlement_resource` | 虚拟结算口径使用 |
| `customer_id` | 客户 | `FK` | `customer` | 必填 |
| `contract_id` | 合同 | `FK` | `contract` | 必填 |
| `execution_order_id` | 执行单 | `FK` | `contract_execution_order` | 框架下推荐 |
| `customer_settlement_rule_id` | 客户结算规则 | `FK/RULE` | `customer_settlement_rule` | 不能手填绕过 |
| `project_id` | 项目 | `FK` | `project` | 必填或挂归属对象 |
| `opportunity_id` | 商机 | `FK` | `opportunity` | 内部真实项目前期投入可关联 |
| `operating_anchor_id` | 归属对象 | `FK` | `operating_anchor` | 共通/售前等 |
| `cost_bearing_department_id` | 成本承担部门 | `FK` | `department` | 内部真实项目投入必须能归集 |
| `revenue_recovery_tracking_required` | 是否跟踪收入回收 | `RULE` | - | 前期投入项目通常为真 |
| `position_id` | 标准岗位 | `FK` | `position_definition` | 必填 |
| `grade_level_id` | 级别 | `FK/RULE` | `role_level_definition` | 来自规则 |
| `unit_price` | 单价 | `SNAPSHOT/AMOUNT` | - | 来自结算规则 |
| `start_date` | 开始日期 | `TIME` | - | 必填 |
| `end_date` | 结束日期 | `TIME` | - | 并发校验 |
| `pricing_rule_snapshot` | 定价规则快照 | `SNAPSHOT` | - | 历史追溯 |

### 8.1.1 `virtual_settlement_resource` 虚拟结算资源

该对象用于表达“客户、合同、结算规则真实存在，但对外结算资源不等同于真实投入人员”的场景。

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 虚拟资源 ID | `PK` | - | 虚拟结算资源真身 |
| `name` | 资源名称 | `SNAPSHOT` | - | 如结算岗位、资源包、名额 |
| `position_id` | 对应标准岗位 | `FK` | `position_definition` | 用于结算规则 |
| `role_level_id` | 级别 | `FK/RULE` | `role_level_definition` | 用于单价 |
| `customer_id` | 客户 | `FK` | `customer` | 可选 |
| `contract_id` | 合同 | `FK` | `contract` | 可选 |
| `execution_order_id` | 执行单 | `FK` | `contract_execution_order` | 可选 |
| `settlement_rule_id` | 结算规则 | `FK/RULE` | `customer_settlement_rule` | 可选 |
| `resource_quantity` | 资源数量 | `AMOUNT` | - | 人月、名额、资源包数量等 |
| `status` | 状态 | `STATUS` | - | 有效、停用 |

### 8.2 `employee_cost_component` 人员成本构成

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 成本 ID | `PK` | - | 成本发生事实 |
| `employee_id` | 员工 | `FK` | `employee` | 可选 |
| `external_person_id` | 外部人员 | `FK` | `external_person` | 可选 |
| `cost_month` | 成本月份 | `TIME` | - | 必填 |
| `cost_date` | 发生日期 | `TIME` | - | 必填 |
| `cost_type_id` | 成本类型 | `FK/RULE` | `cost_type_definition` | 可定义 |
| `amount` | 金额 | `AMOUNT` | - | 必填 |
| `cost_bucket_id` | 成本桶 | `FK/RULE` | `cost_bucket_definition` | 固定人力、绩效、项目费用等 |
| `resource_assignment_id` | 资源入项 | `FK` | `resource_assignment` | 可追溯 |
| `project_id` | 项目 | `FK` | `project` | 项目成本必填 |
| `department_id` | 部门 | `FK` | `department` | 归属 |
| `customer_id` | 客户 | `FK` | `customer` | 可选 |
| `contract_id` | 合同 | `FK` | `contract` | 可选 |
| `execution_order_id` | 执行单 | `FK` | `contract_execution_order` | 可选 |
| `rule_snapshot` | 规则快照 | `SNAPSHOT` | - | 必填 |

### 8.3 `employee_cost_allocation` / `expense_allocation` 成本分摊

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 分摊 ID | `PK` | - | 分摊结果 |
| `source_cost_id` | 来源成本 | `FK` | `employee_cost_component`/`business_expense` | 必填 |
| `allocation_month` | 分摊月份 | `TIME` | - | 必填 |
| `allocation_type_id` | 分摊类型 | `FK/RULE` | `allocation_type_definition` | 可定义 |
| `target_project_id` | 目标项目 | `FK` | `project` | 可选 |
| `target_department_id` | 目标部门 | `FK` | `department` | 可选 |
| `target_anchor_id` | 目标归属对象 | `FK` | `operating_anchor` | 可选 |
| `ratio` | 比例 | `AMOUNT/RULE` | - | 合计校验 |
| `amount` | 金额 | `RESULT/AMOUNT` | - | 来源金额分摊 |
| `rule_snapshot` | 规则快照 | `SNAPSHOT` | - | 必填 |

### 8.4 `employee_month_cost_summary` 月成本汇总

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 汇总 ID | `PK` | - | 汇总结果 |
| `employee_id` | 员工 | `FK` | `employee` | 必填 |
| `summary_month` | 汇总月份 | `TIME` | - | 必填 |
| `gross_salary_total` | 应发工资合计 | `RESULT/AMOUNT` | `payroll_line` | 明细汇总 |
| `employer_social_total` | 公司社保合计 | `RESULT/AMOUNT` | `social_insurance_line` | 明细汇总 |
| `employer_housing_total` | 公司公积金合计 | `RESULT/AMOUNT` | `housing_fund_line` | 明细汇总 |
| `other_amount` | 其他成本 | `RESULT/AMOUNT` | `employee_cost_component` | 明细汇总 |
| `total_amount` | 总成本 | `RESULT/AMOUNT` | - | 不替代明细 |
| `calculation_batch_id` | 计算批次 | `FK` | `calculation_batch` | 可追溯 |

---

## 9. 采购、供应商、付款与交付域

### 9.1 `supplier_role_profile` 供应商角色档案

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 供应商角色 ID | `PK` | - | 供应商角色，不另建主体 |
| `customer_id` | 外部组织 | `FK` | `customer` | 必填 |
| `supplier_category_id` | 供应商类别 | `FK/RULE` | `supplier_category_definition` | 可定义 |
| `first_cooperation_date` | 首次合作日期 | `TIME` | - | 风险参考 |
| `tax_id` | 税号 | `EVIDENCE` | - | 财务核验 |
| `bank_account_id` | 银行账户 | `FK/EVIDENCE` | `bank_account` | 付款核验 |
| `risk_level` | 风险等级 | `RISK` | - | 先用高/中/低 |
| `risk_reason` | 风险原因 | `RISK/TEXT` | - | 高风险必填 |
| `status` | 状态 | `STATUS` | - | 有效、暂停、黑名单 |

### 9.2 `purchase_request` 采购申请

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 采购申请 ID | `PK` | - | 钉钉申请并入 |
| `request_no` | 申请编号 | `RULE/SNAPSHOT` | `code_rule` | 自动生成 |
| `requesting_department_id` | 申请部门 | `FK` | `department` | 必填 |
| `requester_employee_id` | 申请人 | `FK` | `employee` | 必填 |
| `project_id` | 项目 | `FK` | `project` | 项目采购 |
| `sales_contract_id` | 上游销售合同 | `FK` | `contract` | 可选 |
| `operating_anchor_id` | 归属对象 | `FK` | `operating_anchor` | 共通/待确认池 |
| `purchase_subject_type_id` | 采购标的类型 | `FK/RULE` | `purchase_subject_type` | 不枚举 |
| `purchase_content` | 采购内容 | `TEXT` | - | 必填 |
| `estimated_amount` | 预计金额 | `AMOUNT` | - | 大额触发审批 |
| `approval_status` | 审批状态 | `STATUS` | - | 未审批下单提示 |
| `source_dingtalk_instance_id` | 钉钉实例 | `EVIDENCE` | - | 外部审批追溯 |

### 9.3 `purchase_order` 采购订单/采购合同

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 采购订单 ID | `PK` | - | 采购承诺 |
| `purchase_no` | 采购编号 | `RULE/SNAPSHOT` | `code_rule` | 自动生成 |
| `purchase_request_id` | 采购申请 | `FK` | `purchase_request` | 缺失提示流程断点 |
| `supplier_id` | 供应商 | `FK` | `customer`/`supplier_role_profile` | 必填 |
| `company_id` | 采购主体 | `FK` | `company_entity` | 必填 |
| `purchase_subject_type_id` | 标的类型 | `FK/RULE` | `purchase_subject_type` | 必填 |
| `project_id` | 项目 | `FK` | `project` | 可选 |
| `sales_contract_id` | 上游合同 | `FK` | `contract` | 可选 |
| `operating_anchor_id` | 归属对象 | `FK` | `operating_anchor` | 无项目时必填 |
| `contract_amount` | 采购合同额 | `AMOUNT` | - | 与收票付款校验 |
| `order_date` | 订单日期 | `TIME` | - | 必填 |
| `requires_supplier_contract` | 是否需供应商合同 | `RULE` | - | 为真附件必填 |
| `requires_delivery_acceptance` | 是否需交付验收 | `RULE` | - | 付款前置 |
| `status` | 状态 | `STATUS` | - | 草稿、已批、履约中、完成 |
| `attachment_ids` | 附件 | `EVIDENCE` | `document_evidence` | 合同、订单 |

### 9.4 `purchase_subject_type` 采购标的类型

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 类型 ID | `PK` | - | 可新增停用 |
| `name` | 类型名称 | `SNAPSHOT` | - | 项目转包、人力外包、专利、论文、软著、设备等 |
| `parent_id` | 上级类型 | `FK` | `purchase_subject_type` | 类型分级 |
| `requires_project` | 是否需项目 | `RULE` | - | 项目成本类 |
| `requires_delivery` | 是否需交付 | `RULE` | - | 付款前置 |
| `requires_asset` | 是否形成资产 | `RULE` | - | 设备/硬件 |
| `requires_ip_object` | 是否需 IP 对象 | `RULE` | - | 专利/论文/软著 |
| `requires_external_person` | 是否需外部人员 | `RULE` | - | 人力外包 |
| `default_cost_bucket_id` | 默认成本桶 | `FK/RULE` | `cost_bucket_definition` | 成本归集 |
| `status` | 状态 | `STATUS` | - | 有效、停用 |

### 9.5 `purchase_invoice` / `purchase_payment` / `purchase_delivery`

| 对象 | 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|---|
| `purchase_invoice` | `purchase_order_id` | 采购订单 | `FK` | `purchase_order` | 必填 |
| `purchase_invoice` | `invoice_no` | 发票号 | `EVIDENCE` | - | 重复提示 |
| `purchase_invoice` | `invoice_date` | 收票日期 | `TIME` | - | 付款周期起点 |
| `purchase_invoice` | `amount` | 收票金额 | `AMOUNT` | - | 超合同提示 |
| `purchase_payment` | `purchase_order_id` | 采购订单 | `FK` | `purchase_order` | 必填 |
| `purchase_payment` | `payment_date` | 付款日期 | `TIME` | - | 必填 |
| `purchase_payment` | `amount` | 付款金额 | `AMOUNT` | - | 超票付款提示 |
| `purchase_payment` | `is_prepayment` | 是否预付款 | `RULE/RISK` | - | 未收票先付款 |
| `purchase_payment` | `exception_approval_id` | 例外审批 | `FK/EVIDENCE` | `approval_flow` | 预付款必填 |
| `purchase_payment` | `upstream_collection_status` | 上游回款状态 | `SNAPSHOT/RISK` | `contract` | 未回款提示垫付风险 |
| `purchase_delivery` | `delivery_type_id` | 交付类型 | `FK/RULE` | `delivery_type_definition` | 到货、服务、成果、验收 |
| `purchase_delivery` | `accepted_by_employee_id` | 验收人 | `FK` | `employee` | 必填 |
| `purchase_delivery` | `acceptance_result` | 验收结果 | `STATUS` | - | 未通过不得付款 |
| `purchase_delivery` | `attachment_ids` | 验收证据 | `EVIDENCE` | `document_evidence` | 付款前置 |

---

## 10. 固定资产、库存与行政资源域

### 10.1 `fixed_asset` 固定资产

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 资产 ID | `PK` | - | 资产真身 |
| `asset_no` | 资产编号 | `RULE/SNAPSHOT` | `code_rule` | 自动生成 |
| `name` | 资产名称 | `SNAPSHOT` | - | 展示 |
| `asset_category_id` | 资产类别 | `FK/RULE` | `asset_category_definition` | 可定义 |
| `asset_usage_type_id` | 使用类型 | `FK/RULE` | `asset_usage_type_definition` | 公司共通、客户现场、员工领用 |
| `owner_company_id` | 权属公司 | `FK` | `company_entity` | 必填 |
| `purchase_order_id` | 采购来源 | `FK` | `purchase_order` | 采购形成资产必填 |
| `department_id` | 使用部门 | `FK` | `department` | 可选 |
| `project_id` | 使用项目 | `FK` | `project` | 项目资产 |
| `customer_id` | 客户现场 | `FK` | `customer` | 客户现场资产 |
| `current_holder_employee_id` | 当前持有人 | `FK` | `employee` | 领用状态 |
| `status` | 状态 | `STATUS` | - | 在库、领用、维修、报废 |
| `attachment_ids` | 证据 | `EVIDENCE` | `document_evidence` | 发票、入库、照片 |

### 10.2 `inventory_transaction` / `asset_assignment`

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 流转事件 ID | `PK` | - | 事件追加 |
| `fixed_asset_id` | 固定资产 | `FK` | `fixed_asset` | 必填 |
| `purchase_order_id` | 采购订单 | `FK` | `purchase_order` | 入库来源 |
| `transaction_type_id` | 流转类型 | `FK/RULE` | `asset_transaction_type_definition` | 入库、出库、领用、归还、报废、调拨 |
| `transaction_date` | 流转日期 | `TIME` | - | 必填 |
| `from_department_id` | 转出部门 | `FK` | `department` | 调拨使用 |
| `to_department_id` | 转入部门 | `FK` | `department` | 调拨使用 |
| `assignee_employee_id` | 领用人 | `FK` | `employee` | 领用必填 |
| `project_id` | 使用项目 | `FK` | `project` | 项目使用 |
| `customer_id` | 客户现场 | `FK` | `customer` | 客户现场 |
| `attachment_ids` | 凭证 | `EVIDENCE` | `document_evidence` | 入库单、领用单 |

### 10.3 `asset_inventory_check` / `asset_partner_reconciliation`

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 记录 ID | `PK` | - | 盘点/对账结果 |
| `fixed_asset_id` | 固定资产 | `FK` | `fixed_asset` | 必填 |
| `check_date` | 盘点日期 | `TIME` | - | 必填 |
| `difference_type_id` | 差异类型 | `FK/RULE` | `asset_difference_type_definition` | 盘盈、盘亏、位置不符等 |
| `confirmation_status` | 确认状态 | `STATUS` | - | 待确认、已确认 |
| `partner_customer_id` | 合作伙伴 | `FK` | `customer` | 代采对账 |
| `expected_amount` | 应对账金额 | `AMOUNT` | - | 对账口径 |
| `confirmed_amount` | 确认金额 | `AMOUNT/RESULT` | - | 差异提示 |
| `attachment_ids` | 证据 | `EVIDENCE` | `document_evidence` | 盘点表、确认单 |

---

## 11. 知识产权域

### 11.1 `ip_application` 知识产权申请

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 申请 ID | `PK` | - | 申请过程真身 |
| `application_no` | 申请编号 | `RULE/SNAPSHOT` | `code_rule` | 自动生成 |
| `name` | 名称 | `SNAPSHOT` | - | 专利名称、论文题名、软著名称 |
| `ip_type_id` | 类型 | `FK/RULE` | `ip_classification_item` | 专利、论文、软著等 |
| `legal_status_id` | 法律状态 | `FK/RULE` | `ip_legal_status_definition` | 申请中、授权、驳回等 |
| `owner_company_id` | 权利人/付款方 | `FK` | `company_entity` | 必填 |
| `applying_department_id` | 申请部门 | `FK` | `department` | 必填 |
| `project_id` | 关联项目 | `FK` | `project` | 项目型 IP 必填 |
| `customer_id` | 关联客户 | `FK` | `customer` | 可选 |
| `purchase_order_id` | 采购订单 | `FK` | `purchase_order` | 外采 IP 必填 |
| `application_date` | 申请日期 | `TIME` | - | 必填 |
| `status` | 状态 | `STATUS` | - | 申请中、授权、转资产、终止 |
| `attachment_ids` | 申请材料 | `EVIDENCE` | `document_evidence` | 必填 |

### 11.2 `ip_asset` 知识产权资产

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 资产 ID | `PK` | - | 已形成资产真身 |
| `asset_no` | 资产编号 | `RULE/SNAPSHOT` | `code_rule` | 自动生成 |
| `ip_application_id` | 来源申请 | `FK` | `ip_application` | 申请转资产必填 |
| `name` | 名称 | `SNAPSHOT` | - | 必填 |
| `asset_type_id` | 资产类型 | `FK/RULE` | `ip_classification_item` | 可定义 |
| `legal_status_id` | 法律状态 | `FK/RULE` | `ip_legal_status_definition` | 授权、有效、失效等 |
| `owner_company_id` | 权利人 | `FK` | `company_entity` | 必填 |
| `project_id` | 关联项目 | `FK` | `project` | 可选 |
| `customer_id` | 关联客户 | `FK` | `customer` | 可选 |
| `grant_date` | 授权/形成日期 | `TIME` | - | 必填 |
| `valid_until` | 有效期至 | `TIME` | - | 到期提醒 |
| `status` | 状态 | `STATUS` | - | 有效、失效、转让 |
| `attachment_ids` | 证据 | `EVIDENCE` | `document_evidence` | 授权书、证书 |

### 11.3 知识产权分类、作者、进度

适用对象：`ip_classification_scheme`、`ip_classification_item`、`ip_application_classification`、`ip_asset_classification`、`ip_app_author`、`ip_author`、`ip_app_progress`。

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 记录 ID | `PK` | - | 分类/关系/事件 |
| `scheme_id` | 分类方案 | `FK` | `ip_classification_scheme` | 必填 |
| `classification_item_id` | 分类项 | `FK` | `ip_classification_item` | 必填 |
| `ip_application_id` | 申请 | `FK` | `ip_application` | 申请分类/作者/进度 |
| `ip_asset_id` | 资产 | `FK` | `ip_asset` | 资产分类/作者 |
| `author_person_id` | 作者/发明人 | `FK` | `employee`/`external_person` | 必填 |
| `author_order` | 作者顺序 | `AMOUNT/RULE` | - | 必填 |
| `progress_type_id` | 进度类型 | `FK/RULE` | `ip_progress_type_definition` | 受理、补正、授权、驳回 |
| `progress_date` | 进度日期 | `TIME` | - | 必填 |
| `status` | 状态 | `STATUS` | - | 当前结果 |
| `attachment_ids` | 证据 | `EVIDENCE` | `document_evidence` | 通知书、证书 |

---

## 12. 审批、证据、风险、提醒与数据治理

### 12.1 `approval_flow` / `approval_event` 统一审批

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 审批 ID | `PK` | - | 审批流/事件 |
| `business_object_type` | 业务对象类型 | `RULE` | - | 招聘、采购、合同、付款等 |
| `business_object_id` | 业务对象 ID | `FK` | 多态引用 | 必填 |
| `approval_node_id` | 审批节点 | `FK/RULE` | `approval_node_definition` | 可定义 |
| `approver_employee_id` | 审批人 | `FK` | `employee` | 必填 |
| `approval_result` | 审批结果 | `STATUS` | - | 通过、驳回、撤回 |
| `approval_time` | 审批时间 | `TIME` | - | 必填 |
| `source_dingtalk_instance_id` | 钉钉实例 | `EVIDENCE` | - | 外部审批并入 |
| `approval_comment` | 审批意见 | `TEXT` | - | 驳回必填 |

### 12.2 `document_evidence` 统一证据

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 证据 ID | `PK` | - | 证据真身 |
| `evidence_type_id` | 证据类型 | `FK/RULE` | `evidence_type_definition` | 合同、发票、验收、付款、证书等 |
| `business_object_type` | 业务对象类型 | `RULE` | - | 多态关联 |
| `business_object_id` | 业务对象 ID | `FK` | 多态引用 | 必填 |
| `document_no` | 文件/单据号 | `EVIDENCE` | - | 可选 |
| `file_url` | 文件地址 | `EVIDENCE` | - | 必填 |
| `issued_at` | 出具日期 | `TIME` | - | 可选 |
| `valid_until` | 有效期至 | `TIME` | - | 到期提醒 |
| `uploaded_by` | 上传人 | `FK` | `employee` | 必填 |

### 12.3 `risk_event` / `reminder_task` 风险与提醒

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 风险/提醒 ID | `PK` | - | 风险或任务 |
| `business_object_type` | 业务对象类型 | `RULE` | - | 多态 |
| `business_object_id` | 业务对象 ID | `FK` | 多态引用 | 必填 |
| `risk_type_id` | 风险类型 | `FK/RULE` | `risk_type_definition` | 可定义 |
| `risk_level` | 风险等级 | `RISK` | - | 高/中/低 |
| `reason` | 原因 | `TEXT/RISK` | - | 必填 |
| `responsible_employee_id` | 责任人 | `FK` | `employee` | 必填 |
| `due_date` | 截止日期 | `TIME` | - | 超期提醒 |
| `status` | 状态 | `STATUS` | - | 待处理、处理中、完成、关闭 |

### 12.4 `data_quality_issue` 数据质量问题

| 字段 | 中文名 | 角色 | 关联对象 | 规则/校验 |
|---|---|---|---|---|
| `id` | 问题 ID | `PK` | - | 数据治理对象 |
| `source_system` | 来源系统 | `SNAPSHOT` | - | Excel、钉钉、系统 |
| `source_table_name` | 来源表 | `SNAPSHOT` | - | 追溯 |
| `source_row_no` | 来源行 | `EVIDENCE` | - | 追溯 |
| `business_object_type` | 对象类型 | `RULE` | - | 多态 |
| `business_object_id` | 对象 ID | `FK` | 多态引用 | 可选 |
| `issue_type_id` | 问题类型 | `FK/RULE` | `data_issue_type_definition` | 客户空、待核销、重复主档等 |
| `risk_level` | 风险等级 | `RISK` | - | 高/中/低 |
| `owner_employee_id` | 处理人 | `FK` | `employee` | 必填 |
| `due_date` | 截止日期 | `TIME` | - | 超期提醒 |
| `status` | 状态 | `STATUS` | - | 待处理、已修正、关闭 |

---

## 13. 全域智能体检查规则样例

| 编号 | 域 | 检查规则 | 风险提示 |
|---|---|---|---|
| `CRM-001` | 客商 | 合同、采购、开票中的客户/供应商无法匹配 `customer` | 外部组织主档断链 |
| `CRM-002` | 客商 | 相同税号存在多个 `customer` | 组织重复建档 |
| `BID-001` | 招投标 | 正式投标缺少预投标、客户、责任人或证据 | 投标链不完整 |
| `BID-002` | 招投标 | 中标服务费无付款证据或成本归属 | 中标成本断链 |
| `PRJ-001` | 项目 | 项目无归属部门或项目经理 | 责任归属缺失 |
| `PRJ-002` | 项目 | 项目验收状态完成但无验收事件/证据 | 履约证据不足 |
| `CTR-001` | 合同 | 框架协议下有结算/开票/资源入项但无执行单 | 执行边界缺失 |
| `CTR-002` | 合同 | 合同编号未按规则生成 | 编号治理缺失 |
| `SET-001` | 结算 | 结算明细无法追溯资源入项和结算规则 | 结算不可解释 |
| `HR-001` | 人事 | 招聘需求为离职补缺但无离职员工 | 缺口来源缺失 |
| `HR-002` | 人事 | 招聘性质影响用工/结算/发薪但未确认 | 用工规则缺失 |
| `PAY-001` | 发薪 | 发薪批次缺少任一周期字段 | 薪资周期口径不完整 |
| `COST-001` | 成本 | 成本无项目、部门或归属对象 | 成本无法归集 |
| `PUR-001` | 采购 | 未收票先付款且无审批备注 | 例外付款不合规 |
| `PUR-002` | 采购 | 设备采购无固定资产或入库记录 | 资产追溯断点 |
| `PUR-003` | 采购 | 专利/论文/软著采购无 IP 申请或资产 | 知识产权链断点 |
| `AR-001` | 回款 | 开票客户为空或 `#N/A` | 客户主档质量问题 |
| `AR-002` | 回款 | 回款未分配到发票或合同 | 待核销异常 |
| `AR-003` | 回款 | 半年以上未回款 | 中高风险应收 |
| `IP-001` | 知识产权 | IP 资产无申请、作者、权利人或证据 | IP 资产链不完整 |
| `AST-001` | 固定资产 | 资产盘点差异未确认 | 资产风险未闭环 |

---

## 14. 后续需要单独讨论的设计专题

### 14.1 框架协议、执行单、合同范围

需要具体讨论：

1. `contract_execution_order` 的命名：合同执行单、订单、执行协议、范围单是否统一。
2. 执行单与 `contract_sub` 的边界。
3. 执行单与 `contract_labor_scope` 的边界。
4. 执行单是否作为资源入项、结算、开票、回款的优先挂接对象。
5. 框架协议的结算规则如何被执行单继承或覆盖。

### 14.2 合同编号规则

需要具体讨论：

1. 公司段：南大尚诚、尚诚能源等如何编码。
2. 年度段：按签署年度、立项年度还是合同归属年度。
3. 客户段：客户编码、简称还是客户分类。
4. 业务类型段：劳务、科技、采购、框架、执行单等。
5. 协议类型段：合同、框架、订单、执行协议、补充协议、变更协议。
6. 流水号重置规则：按公司/年度/业务类型/客户组合，还是全局年度流水。

### 14.3 可定义主数据体系

全平台都应遵循“不做死枚举”的原则。

优先建设的定义表：

1. 客户角色、供应商类别、风险类型。
2. 商机来源、商机阶段、跟进方式。
3. 投标角色、投标事件类型、投标关系类型。
4. 项目类型、项目阶段、项目角色。
5. 协议类型、执行类型、结算周期、结算规则类型。
6. 招聘需求原因、招聘性质、用工类型、薪资项目。
7. 采购标的类型、交付类型、资产类别。
8. 知识产权分类、进度类型、法律状态。
9. 未回款原因、催收升级规则、数据质量问题类型。
