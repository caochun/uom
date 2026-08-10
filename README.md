# OMS

本分支将 OMS 用于高速公路经营分析。它把路网、车辆通行、收费清分、收入、养护成本和实际资金放在同一张
对象关系网络中，用可追溯关系解释事实来源、收付款核销和成本归因。

系统使用两个稳定的本体概念：

```text
Object   企业经营中可识别、可追溯的事物
Relation 两个 Object 之间有方向、可携带事实的业务联系
```

具体业务含义由用户模型中的 `type`、`properties` 和可选 `tags` 表达。`revenue`、`cost`、
`allocated_to` 等都是开放业务词汇，不是新的本体概念。

## 当前能力

- 浏览和搜索经营对象、关系及相邻关系。
- 通过模型定义的业务操作登记经营事实，确认业务结果后写入。
- 在对象上下文中执行确认收入、核销收付款、分配成本和添加凭据等操作。
- 扩展对象类型、关系类型和带值类型的 Property 定义。
- 根据用户模型动态生成金额、日期、期间、布尔值和 JSON 等表单控件。
- 计算收入贡献、查找待归因成本并追溯对象关系。
- 支持高速公路经营主链路：收费公路、路段、收费站、车辆通行、通行费交易、清分、养护和路况事件。
- 通过 `oag-agent` 使用自然语言查询数据或发起需要确认的变更。
- 使用 SQLite 保存对象关系数据，不依赖外部数据库服务。

## 架构

```text
app/
  server.py             HTTP API 和静态资源服务
  agent_runtime.py      oag-agent 会话适配
  static/               对象、关系、模型和 Agent 工作台

oms/
  ontology.yaml         Object / Relation 本体、函数和交互策略
  model.yaml            用户维护的 Property、对象类型、关系类型和业务操作
  data/oms.db           对象与关系实例的唯一业务数据源
  functions/            OAG adapter 和领域函数注册入口
  sqlite_adapter.py     Object / Relation 的 SQLite 数据源适配器
  business.py           基于 ObjectRepository 的确定性经营计算
  actions.py            业务操作解析和 ChangeSet 生成
  store.py              用户模型和 ChangeSet 应用服务
  scripts/              模型校验器
  tests/                模型、存储和 OAG 集成测试

oag-agent/              Git 子模块，提供 OAG Agent 运行时
docs/                   原始业务资料
```

`ontology.yaml` 只定义稳定的 Object/Relation 记录契约和 Agent 能力。属性类型、业务类型、关系端点与必填规则
属于用户语义，统一放在 `model.yaml`。对象和关系在存储层形成属性图，但 Graph、Node、Edge 不进入业务本体。

OAG Agent 的 `query`、`count`、`search`、领域函数和数据变更统一以 `ObjectRepository` 为实例访问边界。
Repository 根据 `ontology.yaml` 中的 `source.type: oms_sqlite` 将 Object/Relation 路由到 SQLite adapter；领域函数
不会自行创建另一套 store 读取数据库。

## 快速开始

环境要求：Git、Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
git submodule update --init --recursive
uv sync --project oag-agent
cp .env.example .env
PYTHONPATH="$PWD/oag-agent:$PWD" \
  uv run --project oag-agent --env-file .env -- python -m app.server
```

打开 <http://127.0.0.1:8765>。

`.env.example` 默认不配置 LLM，此时对象、关系、用户模型和 ChangeSet 仍可正常使用。启用 Agent 时，在
根目录 `.env` 中配置一组 OpenAI 兼容参数：

```dotenv
LLM_API_KEY=your-api-key
LLM_API_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL=your-model
LLM_DISABLE_REASONING=true
```

也支持 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `OAG_MODEL`。本地 OpenAI 兼容服务配置了 URL 后可以省略
真实 API Key，运行时会使用本地占位值。

## 用户模型

Property 在 `model.yaml` 中独立定义值类型，Object/Relation 类型只声明使用哪些 Property 以及是否必填：

```yaml
property_definitions:
  amount:
    name: 金额
    type: money
    description: 由数值和 ISO 币种组成的金额。

object_types:
  revenue:
    name: 通行费收入
    description: 根据通行费交易或清分结果确认的经济利益。
    properties:
      amount: {required: true}

relation_types:
  allocated_to:
    name: 金额对应
    description: 用于成本对应收入、收款核销应收和付款核销应付。
    from_types: [cost, cash_receipt, cash_payment]
    to_types: [revenue, receivable, payable]
    properties:
      amount: {required: true}
      status: {required: true}
```

高速公路业务复用同一套 `Object` / `Relation` 设计，不引入 Highway 专用本体。模型中的高速公路对象和关系表达为：

```text
收费公路 -contains-> 路段 -contains-> 收费站
车辆通行 -occurred_at(entry_station)-> 入口收费站
车辆通行 -occurred_at(exit_station)-> 出口收费站
通行费交易 -derived_from-> 车辆通行
清分批次 -derived_from-> 通行费交易
收入 -derived_from-> 清分批次
养护作业 -affects-> 路段/收费站
成本 -derived_from-> 养护作业
成本 -allocated_to-> 通行费收入
```

对应的业务操作由 `model.yaml` 动态渲染，例如登记收费公路、登记路段、登记收费站、登记车辆通行、记录通行费交易、
登记收费清分、确认通行费收入、登记养护作业、登记高速公路成本和登记路况事件。收费金额进入 `toll_transaction`、
`settlement_batch` 或 `revenue`，实际回款仍使用通用的 `receivable` / `cash_receipt` 及 `allocated_to` 表达。

MVP 支持 `string`、`number`、`money`、`date`、`period`、`boolean` 和 `json`。业务数据允许使用尚未登记的
开放 `type` 和 Property；一旦 Property 已在用户模型中定义，其值就必须满足相应类型。

更完整的模型约定见 [oms/README.md](oms/README.md)。

## 数据与写入

`oms/data/oms.db` 是唯一业务数据源。SQLite 中使用 `objects`、`relations`、`metadata` 和 `action_log`；完整记录保存在
JSON payload 中，常用 ID、type 和关系端点同时建立独立列与索引。

表单和 Agent 使用同一条业务写入路径：

```text
业务表单 / OAG Agent
        |
        v
model.yaml Action  ->  生成 Object / Relation ChangeSet
        |
        v
preview_action    ->  结构、类型、端点和经营约束校验
        |
        v
用户明确确认
        |
        v
apply_action      ->  图数据与操作审计在同一 SQLite 事务提交
```

Action 不是本体概念，也不进入对象关系图。通用 `preview_changes` / `apply_changes` 保留给模型扩展、修复和高级数据
维护；所有提交只接受基于当前快照生成的预览。对象仍被关系引用时不能删除，也不会发生隐式级联。

## 经营口径

- 收入、应收和收款分别表示价值确认、收款权利和现金流入。
- 成本、应付和付款分别表示价值消耗、付款义务和现金流出。
- 成本可以晚于发生时间归因到收入，也可以拆分给多项收入。
- 养护成本先追溯到养护作业；收入形成后再决定是否以及如何对应。
- 单项收入贡献只扣除确认归因到该收入的成本；企业经营结果统计企业全部收入和成本。

本分支不自动覆盖已有实例数据；高速公路对象可通过模型化业务操作逐步登记。

## 验证

```bash
python3 oms/scripts/validate_model.py
python3 -m unittest discover -s oms/tests -v
node --check app/static/app.js
```

测试覆盖模型结构、Property 类型、Action 编译、关系端点、金额上限、SQLite 原子审计、ChangeSet 预览确认和
OAG Repository 集成。
