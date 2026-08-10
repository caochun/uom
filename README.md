# OMS

OMS 是一个面向企业经营分析的对象关系工作台。它以收入、成本、应收、应付、收款和付款等经营事实为中心，
用可追溯关系解释事实之间的来源、核销和成本归因，而不要求所有数据经过项目或统一核算中心。

项目使用两个稳定的本体概念：

```text
Object   企业经营中可识别、可追溯的事物
Relation 两个 Object 之间有方向、可携带事实的业务联系
```

具体业务含义由用户模型中的 `type`、`properties` 和可选 `tags` 表达。`revenue`、`cost`、
`cost_attribution` 等都是开放业务词汇，不是新的本体概念。

## 当前能力

- 浏览和搜索经营对象、关系及相邻关系。
- 通过表单创建对象、关系，并通过 ChangeSet 预览后写入。
- 扩展对象类型、关系类型和带值类型的 Property 定义。
- 根据用户模型动态生成金额、日期、期间、布尔值和 JSON 等表单控件。
- 计算收入贡献、查找待归因成本并追溯对象关系。
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
  model.yaml            用户维护的 Property、对象类型和关系类型
  data/oms.db           对象与关系实例的唯一业务数据源
  functions/            OAG resolver 和领域函数注册入口
  store.py              SQLite、经营计算和 ChangeSet 服务
  scripts/              模型校验器
  tests/                模型、存储和 OAG 集成测试

oag-agent/              Git 子模块，提供 OAG Agent 运行时
docs/                   原始业务资料
```

`ontology.yaml` 只定义稳定的 Object/Relation 记录契约和 Agent 能力。属性类型、业务类型、关系端点与必填规则
属于用户语义，统一放在 `model.yaml`。对象和关系在存储层形成属性图，但 Graph、Node、Edge 不进入业务本体。

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
    name: 收入
    description: 企业因履约等经营活动确认的经济利益。
    properties:
      amount: {required: false}

relation_types:
  cost_attribution:
    name: 成本归因
    description: 将成本的一部分或全部金额归因到收入。
    from_types: [cost]
    to_types: [revenue]
    properties:
      amount: {required: true}
```

MVP 支持 `string`、`number`、`money`、`date`、`period`、`boolean` 和 `json`。业务数据允许使用尚未登记的
开放 `type` 和 Property；一旦 Property 已在用户模型中定义，其值就必须满足相应类型。

更完整的模型约定见 [oms/README.md](oms/README.md)。

## 数据与写入

`oms/data/oms.db` 是唯一业务数据源。SQLite 中使用 `objects`、`relations` 和 `metadata` 三张表；完整记录保存在
JSON payload 中，常用 ID、type 和关系端点同时建立独立列与索引。

表单和 Agent 使用同一条写入路径：

```text
表单 / OAG Agent
        |
        v
preview_changes  ->  结构、类型、端点和经营约束校验
        |
        v
用户明确确认
        |
        v
apply_changes    ->  SQLite 事务或 model.yaml 原子更新
```

`apply_changes` 只接受在当前数据快照上预览过的同一组操作。对象仍被关系引用时不能删除，也不会发生隐式级联。

## 经营口径

- 收入、应收和收款分别表示价值确认、收款权利和现金流入。
- 成本、应付和付款分别表示价值消耗、付款义务和现金流出。
- 成本可以晚于发生时间归因到收入，也可以拆分给多项收入。
- 暂未形成收入的投入可以先保持待归因，失败投入可以由企业承担。
- 单项收入贡献只扣除确认归因到该收入的成本；企业经营结果统计企业全部收入和成本。

示例数据中，100 万收入关联 45 万已确认成本，因此收入贡献为 55 万。

## 验证

```bash
python3 oms/scripts/validate_model.py
python3 -m unittest discover -s oms/tests -v
node --check app/static/app.js
```

测试覆盖模型结构、Property 类型、关系端点、金额上限、SQLite 事务、ChangeSet 预览确认和 OAG resolver 集成。
