# OMS Domain

本目录是 OMS 的 OAG domain，负责定义企业经营对象关系语义、用户业务词汇、实例数据和确定性经营函数。

## 设计边界

OMS 只有两个本体概念：

- `Object`：企业经营中具有稳定 ID 的主体、意图、承诺、工作、事件、资源或结果。
- `Relation`：两个 Object 之间具有方向、类型和可选事实的业务联系。

`revenue`、`cost`、`contract`、`cash_receipt` 等是 Object 的开放 `type`；`derived_from`、
`allocated_to` 等是 Relation 的开放 `type`。项目、合同、部门和资源都只是普通
Object，不是所有经营链路必须经过的中心。

Graph、Node 和 Edge 属于存储及查询视图，不是业务本体概念，因此不设置 `metamodel.yaml`。

## 文件职责

```text
ontology.yaml         固定的 Object / Relation 契约、函数和交互策略
model.yaml            用户维护的 Property、对象类型、关系类型和业务操作
data/oms.db           对象与关系实例的唯一业务数据源
functions/__init__.py OAG adapter 和领域函数注册入口
sqlite_adapter.py     Object / Relation 的 SQLite ObjectAdapter
business.py           基于 ObjectRepository 的确定性经营计算
actions.py            将模型化业务操作编译为 ChangeSet
store.py              用户模型和 ChangeSet 应用服务
scripts/              模型与数据校验
tests/                模型、存储和 OAG 集成测试
```

`ontology.yaml` 是标准 OAG domain，由 `oag.ontology.loader.load_domain()` 直接加载。运行时代码注册
`oms_sqlite` adapter 和函数实现，不重复构造本体，也不创建第二套 Repository。

```text
OAG query / mutate / 领域函数
              |
              v
      ObjectRepository
         |          |
         v          v
      Object      Relation
         \          /
          OmsSqliteAdapter
                 |
              oms.db
```

确定性经营函数只使用加载器注入的 `ObjectRepository` 查询 Object/Relation。`store.py` 只负责用户业务词汇和
ChangeSet 的预览、校验与提交；数据快照也经由 Repository 读取，批量写入由 Repository 选中的 adapter 在一个
SQLite 事务内完成。

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
id: rel:delivery-cost-revenue
type: allocated_to
from: cost:delivery-a
to: revenue:a
properties:
      amount: {amount: 300000, currency: CNY}
      status: confirmed
      occurred_on: "2026-08-10"
```

`from` 和 `to` 是有方向的 Object ID。Relation 的 `properties` 描述联系自身的金额、依据、状态或时间，
不应改写到任一端点对象上。

## 用户模型

`model.yaml` 不是元模型，而是企业认可的业务词汇和操作定义：

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
  allocated_to:
    name: 金额对应
    description: 用于成本对应收入、收款核销应收和付款核销应付。
    from_types: [cost, cash_receipt, cash_payment]
    to_types: [revenue, receivable, payable]
    properties:
      amount: {required: true}
      status: {required: true}

actions:
  allocate_cost:
    name: 分配成本
    handler: changeset
    available_on: [cost]
    inputs:
      revenue_id: {name: 对应收入, object_types: [revenue], required: true}
      amount: {name: 对应金额, property: amount, required: true}
      occurred_on: {name: 确认日期, property: occurred_on, required: true}
    effects:
      - create_relation:
          type: allocated_to
          from: $context
          to: $input.revenue_id
          properties:
            amount: $input.amount
            status: confirmed
            occurred_on: $input.occurred_on
```

Property 定义一次值类型，各业务类型只引用 Property 并声明是否必填。支持的值类型为：

- `string`
- `number`
- `money`，结构为 `{amount, currency}`
- `date`，格式为 `YYYY-MM-DD`
- `period`，格式为 `YYYY-MM`
- `boolean`
- `json`

Action 不是第三个本体概念，也不写入业务图。它只描述用户可执行的业务行为，并把输入、当前对象和本次创建的
对象解析为 `create_object` / `create_relation` ChangeSet。MVP 不支持条件、分支或通用工作流 DSL。

会形成对外权利、义务或承诺的操作必须同时记录必要往来方：商机和合同明确客户，采购订单明确供应商，应收和
应付明确债务人或债权人。销售发票与采购发票使用同一个 `invoice` 对象类型，但由不同 Action 固定业务方向，
避免依赖用户手工填写类别来决定后续语义。

未知业务 `type` 可以先作为开放词汇进入数据。未知 Property 作为 JSON 兼容值保存；一旦同名 Property 在
`property_definitions` 中登记，所有数据中的该字段都必须满足定义类型。

## 经营关系

模型不把收入和支出强制塞进同一条流程，而是分别记录事实，再按业务证据建立关系：

```text
收入 -> derived_from -> 结算结果 -> derived_from -> 合同 -> derived_from -> 商机
成本 -> allocated_to -> 收入
收款 -> allocated_to -> 应收 -> derived_from -> 收入
付款 -> allocated_to -> 应付 -> derived_from -> 采购订单
成本 -> associated_with -> 商机/项目/部门
```

关键规则：

- `derived_from` 的方向是结果指向来源，且不能形成循环。
- `allocated_to` 统一表达成本与收入、收款与应收、付款与应付之间的金额对应。
- `associated_with` 记录没有直接因果的业务上下文，`involves` 记录参与者及其角色。
- `evidenced_by` 把经营事实连接到发票、验收记录或银行回单等凭据。
- 已确认的金额对应不能超过来源金额；收付款核销也不能超过应收或应付金额。
- 原始成本不因后续归因结论而改写，认识变化通过 Relation 表达。

尚未形成收入的前置成本可以先通过 `associated_with` 关联商机、项目或部门。收入形成后再建立
`allocated_to`；最终没有收入覆盖的成本仍作为企业真实支出保留。

## 存储与变更

`data/oms.db` 使用 SQLite 保存属性图：

- `objects` 保存 Object。
- `relations` 保存 Relation，并用外键约束端点。
- `metadata` 保存 schema 版本和数据修订号。
- `action_log` 保存业务操作、操作者、渠道和变更前后值，不作为业务图节点。

完整记录保存在 JSON payload 中，ID、type、name、source 和 target 同时保存为索引列。SQLite 是唯一实例数据源，
不存在 YAML 数据副本。

当前 `data/oms.db` 不包含业务实例，待模型确认后再重新 seed。

业务数据优先通过模型化 Action 写入：

```text
get_available_actions
        -> preview_action
        -> ChangeSet 校验
        -> 用户确认
        -> apply_action
        -> SQLite 图数据 + action_log 原子提交
```

原始 ChangeSet 仍支持创建、更新和删除 Object/Relation，以及更新 Property、对象类型和关系类型，供模型扩展和
高级数据维护使用。预览不会写入数据；应用操作
必须与当前快照上已通过的预览完全一致。业务数据在 SQLite 事务中提交，用户模型通过原子文件替换更新。

## OAG 函数

- `get_business_overview`：汇总收入、成本、收付款和待归因成本。
- `calculate_revenue_contribution`：计算指定收入的确认归因成本和贡献。
- `find_unattributed_costs`：查找尚未完全归因的成本余额。
- `trace_object`：按深度双向追溯对象及关系。
- `get_model_vocabulary`：读取 Property、对象类型和关系类型。
- `get_available_actions`：读取全局或当前对象可执行的业务操作。
- `preview_action` / `apply_action`：预览并原子执行模型化业务操作。
- `preview_changes` / `apply_changes`：校验并应用用户确认的变更。

## 验证

从仓库根目录执行：

```bash
python3 oms/scripts/validate_model.py
python3 -m unittest discover -s oms/tests -v
```

校验覆盖记录契约、Property 类型、必填属性、端点类型、重复 ID、循环关系、金额上限和 JSON 兼容性。
