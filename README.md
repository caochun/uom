# UOM Domains

本项目提供 UOM（Unified Ontology Modeling）运行时，以及基于它实现的高速联网收费、融资租赁和企业日常运营领域。

UOM 只有两个固定本体概念：

```text
Object   可独立识别和追溯的业务对象
Relation 两个 Object 之间有方向、可携带事实的业务关系
```

项目按职责分为三层：

```text
oag-agent/  通用 Agent 运行时和 DomainProvider 协议
uom/        Object / Relation、Action、ChangeSet、SQLite 和模型校验运行时
highway/    高速领域模型、数据、函数、空间能力和 Web 应用
leasing/    融资租赁模型、数据、Action、确定性函数、领域资料和 Web 应用
foxoms/     企业日常运营模型、Mock 数据、Agent 和 Web 应用
```

核心图语义由 [`uom/ontology.yaml`](uom/ontology.yaml) 定义。具体高速业务语义由
[`highway/model.yaml`](highway/model.yaml) 中的 `type`、`properties`、关系、Action 和领域函数表达。
`highway/provider.py` 复用 UOM provider 形成最终运行时 Ontology，并通过 `oag-agent` 的
`DomainProvider` 协议加载。OAG 不关心本体是否经过组合。当前模型基于
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
业务意图 -> Action 表单 -> preview -> 用户确认 -> apply -> highway/data/graph.db
```

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

`model.yaml` 的演化与业务数据历史分开管理。类型或属性可使用 `deprecated: true`
停止新增，使用 `aliases` 保留旧名称。已被数据使用的属性不能原地修改值类型，应新建属性并执行
显式数据迁移。`model.yaml` 的完整版本历史仍由 Git 管理。

## 校验

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python highway/scripts/validate_model.py --root highway
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m unittest discover -s highway/tests -v
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python leasing/scripts/validate_model.py --root leasing
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m unittest discover -s leasing/tests -v
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python foxoms/scripts/validate_model.py --root foxoms
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m unittest discover -s foxoms/tests -v
node --check foxoms/app/static/app.js
node --check highway/app/static/app.js
node --check leasing/app/static/app.js
```
