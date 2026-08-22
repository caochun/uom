# FoxOMS Domain

FoxOMS 是一个逐步定义中的 UOM 领域。目前定义了业务主体、商机、招标事项和投标记录，
可以表达业务主体以特定角色参与业务，以及商机、招标事项和投标记录之间的包含结构。
中标投标可以形成框架协议或项目合同：框架协议包含后续订单，项目合同定义项目或任务。
人员、软件和硬件作为独立资源类型管理，并通过统一的投入关系配置到订单或项目/任务。
知识资产通过一条带角色的关系表达为订单或项目/任务所需的条件或产生的成果。
合同或订单可以包含多张发票，回款通过带金额的核销关系分配到发票；发票和回款主体
从合同或订单参与方推导，不重复保存。
模型同时定义了 20 个业务操作。操作不是通用的“新增对象”，而是一次形成完整业务事实：
例如建立商机会同时记录经营方与潜在客户，登记招标和投标会建立所属关系，签约只允许从
中标记录进入框架协议或项目合同两条路径之一，登记回款则必须同时完成首笔发票核销。

商机可以进入招投标链，也可以长期停留在商机阶段；模型不提供从商机直接签协议或合同的
捷径。Action 服务还会校验受管经营方、中标结果、唯一签约路径、资源投入日期和数量、
知识资产角色、金额币种及累计核销上限。实例数据与线上操作共用同一套业务一致性审计。

领域语义统一定义在 [`model.yaml`](model.yaml)。

## 运行

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent --env-file .env -- python -m foxoms.app.server
```

默认打开 <http://127.0.0.1:8768>。未配置 LLM 时，对象、关系、模型和高级数据维护仍可使用。

部署到 `~/Develop/fox-oms` 时，可安装用户级 systemd 服务：

```bash
install -Dm644 foxoms/deploy/foxoms-oms.service ~/.config/systemd/user/foxoms-oms.service
systemctl --user daemon-reload
systemctl --user enable --now foxoms-oms.service
```

部署服务监听 `0.0.0.0:8768`，使用独立的 `foxoms/data/graph.db` 和 Agent 会话。

## 经营工作台

前端默认以经营脉络而非对象表格组织数据，并可按受管业务主体收窄范围：

- 总览汇总商机、投标、中标、履约事项和待回款；
- 商务拓展沿商机、招标、投标、商务约定展开，并将“暂无后续”显示为合法状态；
- 履约交付从框架协议或项目合同进入订单、项目/任务和资源投入；
- 开票回款按合同或订单汇总发票余额，并展开一笔回款核销多张发票的事实；
- 资源资产分别展示人员、软件、硬件和知识资产的实际投入去向。

底层对象和关系表格保留在“全部数据”，用于高级检查和维护。对象详情抽屉显示其业务来源、
后续结果、参与主体、投标结果或资金核销进度，并继续使用 `model.yaml` 中适用的 Action。

## 校验

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m uom.validation --root foxoms
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m unittest discover -s foxoms/tests -v
node --check foxoms/app/static/app.js
```

## Mock 数据

先校验数据，再显式确认替换本地数据库：

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python foxoms/scripts/seed.py
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python foxoms/scripts/seed.py --confirm-clear
```
