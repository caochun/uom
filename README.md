# UOM Domains

本项目提供 UOM（Unified Ontology Modeling）运行时，以及基于它实现的高速联网收费、融资租赁和企业日常运营领域。

UOM 的持久化图只有两个固定元概念：

```text
Object   可独立识别和追溯的业务对象
Relation 两个 Object 之间有方向、可携带事实的业务关系
```

领域 `model.yaml` 是面向业务建模者和 LLM 维护场景的 UOM 源模型（`uom.domain.v1`）。UOM 在领域加载时
将它编译为符合 OAG `Ontology` schema（`oag.ontology.v1`）的运行时本体，统一补齐稳定 ID、对象/关系
基础属性、Repository binding、可变性和 Action 副作用契约。OAG 只接收编译结果，不解释
UOM DSL。Action 不是第三种图记录，而是创建或改变 Object/Relation 的有副作用业务操作。

项目按职责分为三层：

```text
oag-agent/  本体元模型、Agent、Tool、逻辑 Repository、SourceManager 和 ActionRuntime 协议
uom/        领域源模型 schema、编译器、Source adapter、UomChangeStore、Action、审计和模型编辑
highway/    高速领域模型、数据、函数、空间能力和 Web 应用
leasing/    融资租赁模型、数据、Action、确定性函数、领域资料和 Web 应用
foxoms/     企业日常运营模型、Mock 数据、Agent 和 Web 应用
```

每个领域只维护一个 UOM 源模型，例如 [`highway/model.yaml`](highway/model.yaml)，其中定义具体对象、关系、
只读 Function、业务 Action、命名 Repository 和 Agent 策略。编译后的 OAG Ontology 只存在于运行时，供
LLM、Prompt、Tool 和 Repository 使用。Action 的公开契约包含输入、适用上下文、前置条件和副作用摘要；
具体 ChangeSet 模板放在领域私有的 `action_plans.yaml`，不会进入 LLM 本体或浏览器 bootstrap。

```text
domain/model.yaml (uom.domain.v1)
        |
        | UOM compiler
        v
OAG Ontology (oag.ontology.v1, runtime)
        |
        +--> Prompt / Tool / Agent
        +--> OntologyRepository
                    |
                    v
              SourceManager
               /        \
 OntologyRepository      UomChangeStore
               \        /
            UOM Source --> SQLite / 外部业务系统
```

`OntologyRepository` 是 OAG 的逻辑业务数据访问边界，按本体中声明的具体 Object/Relation 类型访问数据。
`SourceManager` 创建并复用命名 source 实例；UOM Workspace 从同一实例建立 `UomChangeStore`，执行物理图
ChangeSet、revision、退役、审计和历史操作，因此不会自行打开另一条 SQLite 访问通道，也不会把这些
UOM 专有语义放入 OAG Repository。

OAG 的 `load_domain(provider)` 只返回 `Ontology`、`OntologyRepository` 和 `RuntimeBindings`。
`RuntimeBindings` 只绑定本体中已声明的 Function 实现和唯一的 `ActionRuntime`，不作为任意领域服务容器。
UOM 的 `load_domain(domain_dir)` 在此基础上返回 `UomDomainRuntime`，显式提供 `workspace`、
`change_store` 和 `actions`。地图投影等仅属于具体应用的能力由应用直接创建，例如 Highway 的
`SpatialViewService`，不会注册进 OAG。

对象或关系可在源模型中通过 `repository`、`selector`、`mapping` 映射到不同的 ERP、CRM 或 API；
当前三个领域的默认实现是 UOM SQLite 属性图。
可选的 `provider.py` 只负责绑定数据 Source、Python Function 实现和 ActionRuntime；领域或应用服务
由 UOM runtime 或具体应用显式持有。当前高速模型基于
[`highway/docs/高速联网收费领域本体模型 V3.1.md`](highway/docs/高速联网收费领域本体模型%20V3.1.md) 做了面向 LLM 的抽象，
没有把设备、名单和运行参数逐表展开。

融资租赁领域位于 [`leasing`](leasing)，它围绕授信、方案、合同、放款、应收、收款、核销、结清和凭证
建立经营与资金追溯主链。详细设计见 [`leasing/README.md`](leasing/README.md)，原始 PlantUML 资料位于
[`leasing/docs`](leasing/docs)。

## 运行

项目使用 SQLite 保存实例数据，OAG Agent 作为 Git 子模块提供 Agent 运行时。安装依赖后：

```bash
git submodule update --init --recursive
uv sync --project oag-agent
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent --env-file .env -- python -m highway.app.server
```

打开 <http://127.0.0.1:8765>。LLM 配置写在根目录 `.env` 中；没有 LLM 配置时，图数据、模型和表单仍可使用。

融资租赁工作台使用独立领域入口和端口：

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent --env-file .env -- python -m leasing.app.server
```

打开 <http://127.0.0.1:8766>。

FoxOMS 企业运营工作台使用独立领域入口和端口：

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent --env-file .env -- python -m foxoms.app.server
```

打开 <http://127.0.0.1:8768>。

## 用户级 systemd 服务

部署目录为 `~/Develop/highway-oms` 时，可安装仓库中的用户服务：

```bash
install -Dm644 highway/deploy/highway-oms.service ~/.config/systemd/user/highway-oms.service
systemctl --user daemon-reload
systemctl --user enable --now highway-oms.service
systemctl --user status highway-oms.service
journalctl --user -u highway-oms.service -f
```

服务监听 `0.0.0.0:5678`。要在用户未登录时随系统启动，还需确保 `loginctl show-user "$USER" -p Linger`
返回 `Linger=yes`。

详细的对象分组、关系方向、Action 和校验规则见 [`highway/README.md`](highway/README.md)。

## 数据写入

业务表单和 Agent 都使用模型驱动 Action。Action 会先编译成 ChangeSet，经过校验并得到用户确认后，再在
SQLite 事务中同时写入对象、关系和操作审计。模型扩展使用相同的预览/提交机制。

```text
业务意图 -> Action 表单 -> preview_action -> 用户确认 -> execute_action -> data/graph.db
```

OAG 中 `Function` 专指无领域副作用的查询、计算或校验能力；它始终按只读工具注册。
UOM 内部的 Workspace 负责模型维护和 ChangeSet，ActionRuntime 负责业务 Action 生命周期，
两者都不通过伪装成 Function 的方式向 LLM 暴露写操作。

### 对象和关系的变化

UOM 使用“当前状态图 + 不可变 Action 历史”处理业务变化。对象和关系的 `lifecycle`
由存储层统一维护，包含 `revision`、`created_at`、`updated_at` 和 `retired_at`；
领域 Action 不得自行填写这些字段。

- 同一业务身份的事实变化使用更新，产生新业务事实时创建新对象。
- `id` 和 `type` 是稳定身份；关系的 `from` / `to` 也不可原地修改。
- 关联对象变化时，应退役旧关系并创建新关系。
- `delete_object` / `delete_relation` 在日常 ChangeSet 中表示退役，数据仍保留在 SQLite，
  但不再出现于当前图。退役后的稳定 ID 不能复用。
- 每次数据变更都记录操作、操作人、渠道、原因以及每条记录的 `before` / `after`。
- 提交时校验 `revision`；如果预览后数据已被修改，本次提交失效，必须刷新后重试。

`model.yaml` 的演化与业务数据历史分开管理。`aliases` 用于记录同一概念的其他业务名称。
已被数据使用的属性不能原地修改值类型，应新建属性并执行显式数据迁移。
`model.yaml` 的完整版本历史仍由 Git 管理。

## 校验

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m uom.validation --root highway
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m unittest discover -s highway/tests -v
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m uom.validation --root leasing
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m unittest discover -s leasing/tests -v
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m uom.validation --root foxoms
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m unittest discover -s foxoms/tests -v
node --check foxoms/app/static/app.js
node --check highway/app/static/app.js
node --check leasing/app/static/app.js
```
