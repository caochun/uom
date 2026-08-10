# OMS Domain

本目录是 OMS 的 OAG domain，负责定义企业经营对象关系语义、用户业务词汇、实例数据和确定性经营函数。

## 设计边界

OMS 只有两个本体概念：

- `Object`：企业经营中具有稳定 ID 的主体、意图、承诺、工作、事件、资源或结果。
- `Relation`：两个 Object 之间具有方向、类型和可选事实的业务联系。

`revenue`、`cost`、`contract`、`cash_receipt` 等是 Object 的开放 `type`；`derived_from`、
`cost_attribution`、`settles_receivable` 等是 Relation 的开放 `type`。项目、合同、部门和人员都只是普通
Object，不是所有经营链路必须经过的中心。

Graph、Node 和 Edge 属于存储及查询视图，不是业务本体概念，因此不设置 `metamodel.yaml`。

## 文件职责

```text
ontology.yaml         固定的 Object / Relation 契约、函数和交互策略
model.yaml            用户维护的 Property、对象类型和关系类型
data/oms.db           对象与关系实例的唯一业务数据源
functions/__init__.py OAG resolver 和领域函数注册入口
store.py              SQLite、ChangeSet 和确定性经营计算
scripts/              模型与数据校验
tests/                模型、存储和 OAG 集成测试
```

`ontology.yaml` 是标准 OAG domain，由 `oag.ontology.loader.load_domain()` 直接加载。运行时代码只注册 resolver
和函数实现，不重复构造本体。

## Object

```yaml
id: revenue:a-2026-07
type: revenue
name: 客户 A 2026 年 7 月收入
properties:
  status: recognized
  amount: {amount: 1000000, currency: CNY}
  period: "2026-07"
tags: [management_view]
source_refs: [erp:revenue-1]
```

- `id` 是稳定标识，更新操作不能修改。
- `type` 直接表达主要业务语义。
- `name` 提供面向人和 LLM 的名称。
- `properties` 保存可计算或可判断的事实。
- `tags` 只用于非排他检索，不参与金额计算或关系推理。
- `source_refs` 保存可选的来源系统引用。

不使用 `type: business_object` 加 `object_type: revenue` 的双重表达。

## Relation

```yaml
id: rel:people-cost-revenue
type: cost_attribution
from: cost:people-a
to: revenue:a-2026-07
properties:
  amount: {amount: 300000, currency: CNY}
  basis: resource_assignment
  status: confirmed
  period: "2026-07"
```

`from` 和 `to` 是有方向的 Object ID。Relation 的 `properties` 描述联系自身的金额、依据、状态或时间，
不应改写到任一端点对象上。

## 用户模型

`model.yaml` 不是元模型，而是企业认可的业务词汇表：

```yaml
schema: oms.business_model.v2

property_definitions:
  amount:
    name: 金额
    type: money
    description: 由数值和 ISO 币种组成的金额。

object_types:
  cost:
    name: 成本
    description: 已消耗并需要解释承担去向的经济资源。
    properties:
      amount: {required: false}
      period: {required: false}

relation_types:
  cost_attribution:
    name: 成本归因
    description: 将成本的一部分或全部金额归因到收入。
    from_types: [cost]
    to_types: [revenue]
    properties:
      amount: {required: true}
      basis: {required: true}
```

Property 定义一次值类型，各业务类型只引用 Property 并声明是否必填。支持的值类型为：

- `string`
- `number`
- `money`，结构为 `{amount, currency}`
- `date`，格式为 `YYYY-MM-DD`
- `period`，格式为 `YYYY-MM`
- `boolean`
- `json`

未知业务 `type` 可以先作为开放词汇进入数据。未知 Property 作为 JSON 兼容值保存；一旦同名 Property 在
`property_definitions` 中登记，所有数据中的该字段都必须满足定义类型。

## 经营关系

模型不把收入和支出强制塞进同一条流程，而是分别记录事实，再按业务证据建立关系：

```text
收入 -> derived_from -> 结算结果 -> derived_from -> 合同 -> derived_from -> 商机
成本 -> cost_attribution -> 收入
成本 -> enterprise_absorption -> 企业
收款 -> settles_receivable -> 应收 -> derived_from -> 收入
付款 -> settles_payable -> 应付 -> derived_from -> 采购订单
```

关键规则：

- `derived_from` 的方向是结果指向来源，且不能形成循环。
- `cost_attribution` 从成本指向收入，可按金额拆分并延后建立。
- `enterprise_absorption` 表示成本不再归因到具体收入，由企业整体承担。
- `settles_receivable` 和 `settles_payable` 分别表达收款核销应收、付款核销应付。
- 已确认归因或核销金额不能超过对应对象金额。
- 原始成本不因后续归因结论而改写，认识变化通过 Relation 表达。

示例中，100 万收入关联 30 万人员成本和 15 万采购成本，收入贡献为 55 万。5 万前置成本可以保持待归因；
失败商机的 2 万成本通过 `enterprise_absorption` 由企业承担。

## 存储与变更

`data/oms.db` 使用 SQLite 保存属性图：

- `objects` 保存 Object。
- `relations` 保存 Relation，并用外键约束端点。
- `metadata` 保存 schema 版本和数据修订号。

完整记录保存在 JSON payload 中，ID、type、name、source 和 target 同时保存为索引列。SQLite 是唯一实例数据源，
不存在 YAML 数据副本。

所有变更使用结构化 ChangeSet：

```text
preview_changes -> 用户确认 -> apply_changes
```

支持创建、更新和删除 Object/Relation，以及更新 Property、对象类型和关系类型。预览不会写入数据；应用操作
必须与当前快照上已通过的预览完全一致。业务数据在 SQLite 事务中提交，用户模型通过原子文件替换更新。

## OAG 函数

- `get_business_overview`：汇总收入、成本、收付款和待归因成本。
- `calculate_revenue_contribution`：计算指定收入的确认归因成本和贡献。
- `find_unattributed_costs`：查找尚未完全归因的成本余额。
- `trace_object`：按深度双向追溯对象及关系。
- `get_model_vocabulary`：读取 Property、对象类型和关系类型。
- `preview_changes` / `apply_changes`：校验并应用用户确认的变更。

## 验证

从仓库根目录执行：

```bash
python3 oms/scripts/validate_model.py
python3 -m unittest discover -s oms/tests -v
```

校验覆盖记录契约、Property 类型、必填属性、端点类型、重复 ID、循环关系、金额上限和 JSON 兼容性。
