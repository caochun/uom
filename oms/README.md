# 企业收支 OMS 本体

本目录定义面向 LLM 的企业经营 MVP 语义层。它参考
[`TwinCore企业运营管理平台全域对象关系图_v1.md`](../docs/TwinCore企业运营管理平台全域对象关系图_v1.md)，
但不复制项目、合同、工资和采购等来源系统对象。

模型不设置统一的项目或经营核算中心。收入、支出和现金事实可以分别产生，成本与收入通过可延后建立的
归因关系连接。

## 三层结构

```text
metamodel.yaml       建模语言：Concept / Relation / Property / Function
ontology.yaml        企业收支概念、关系和分析函数
data/
  objects.yaml       具体经济事实
  relations.yaml     核销、拆分和归因关系
```

元模型不包含 Graph、Node 或 Edge。对象和关系可以使用图存储，也可以使用关系数据库或其他实现。

## 核心结构

```text
收入链：
revenue -> receivable <- cash_receipt

支出链：
expenditure -> cost_expense
            -> asset -> cost_expense
            -> payable <- cash_payment

经营关联：
cost_expense --allocated_amount--> revenue
cost_expense --absorbed_amount----> enterprise
```

本体只有 10 个概念：

- `enterprise`、`counterparty`：事实归属企业和相关交易方。
- `revenue`：已经确认的收入。
- `expenditure`：取得或使用资源的支出事项，不等同于付款。
- `cost_expense`、`asset`：支出形成的当期消耗或未来价值。
- `receivable`、`payable`：收款权利和付款义务。
- `cash_receipt`、`cash_payment`：实际现金流入和流出。

合同、结算、项目、商机、人员入项、工资单、采购单和发票通过 `source_refs` 保留为事实来源。
它们可以帮助判断成本归因，但不是收入和成本之间的必经节点。

## 成本归因

`cost_attributed_to_revenue` 是模型的核心关系，保存归因金额、依据、状态和期间。成本与收入是多对多关系：
一项成本可以拆给多项收入，一项收入也可以承担多项成本。

成本金额存在三种去向：

```text
已归因金额    已通过 confirmed 关系归因到具体收入
企业承担金额  已明确作为企业整体期间消耗
待归因金额    成本金额 - 已归因金额 - 企业承担金额
```

待归因不代表成本尚未发生。它表示成本已经进入企业经营结果，但尚未确定由哪项收入承担。未来收入出现后，
可以新增归因关系；如果投入无法转化，则新增企业承担关系。原始成本事实不需要被改写。

## 示例数据

示例企业在 2026 年 7 月有：

```text
收入                         1,000,000
已归因人员成本                 300,000
已归因采购服务成本             150,000
等待未来收入归因的前置成本       50,000
失败商机、由企业承担的费用         20,000
采购形成的资产                   50,000
```

因此：

```text
该项收入贡献 = 1,000,000 - 300,000 - 150,000 = 550,000
企业经营结果 = 1,000,000 - 300,000 - 150,000 - 50,000 - 20,000 = 480,000
```

收入贡献和企业经营结果不同，是因为前置成本和公共/失败投入不能在没有依据时强行归到某项收入。

采购支出 20 万元被拆为 15 万元成本和 5 万元资产；付款 20 万元只核销应付，不能整体作为成本。

## Function

- `analyze_revenue_contribution`：解释某项收入承担的成本、贡献、应收和实收。
- `analyze_expenditure`：解释支出形成了成本、资产、应付和付款中的哪些事实。
- `analyze_enterprise_result`：按期间计算企业全部收入减全部成本。
- `find_unattributed_costs`：找出仍等待收入归因的成本余额及来源线索。

## 校验

```bash
python3 oms/scripts/validate_model.py
python3 -m unittest discover -s oms/tests -v
```

校验器会拒绝未知概念、错误关系端点、未声明属性、无效金额类型，以及超过原始收入、支出、成本、
应收、应付或现金事实金额的拆分、归因和核销。
