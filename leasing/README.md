# 融资租赁领域

`leasing` 是基于 UOM 的融资租赁经营与资金追溯领域。原始资料包含 35 个实体和约 65 条关系；本模型不复刻
数据库表，而是保留可独立追溯的业务事实、少量稳定关系和用户可执行的业务操作。

## 核心链路

```text
客户 -> 授信 -> 项目方案 -> 合同 -> 放款
                                  |
                                  v
租金计划版本 -> 应收 <- 核销明细 <- 收款

合同 -> 结清 -> 会计凭证 -> 凭证分录
```

`allocation`（核销明细）是独立 Object，不是一条普通关系。它承载核销金额、日期、顺序和冲销状态，并分别
连接收款与应收或罚息，因此可以表达一笔收款核销多笔应收、一笔应收分次收款。

## 模型边界

首版定义 21 个对象类型：

```text
主体：party / customer
租前：credit / credit_entry / lease_plan
合同：contract / contract_participation / loan / schedule_version / change_order
资金：receivable / payment / allocation / penalty / settlement
保障：subject_matter / guarantee
结果：invoice / voucher / voucher_line / approval
```

关系词汇收敛为五种：

| 关系 | 含义 |
| --- | --- |
| `contains` | 整体包含依附的组成或明细事实 |
| `references` | 业务事实引用来源、依据或业务对象 |
| `associates` | 两个独立对象之间存在业务联系 |
| `derives` | 来源业务事实生成处理或核算结果 |
| `supersedes` | 新版本替代旧版本，历史事实仍保留 |

数据库中的 `客户id`、`合同id`、`归属类型 + 归属id`、`来源单据类型 + 来源单据id` 不作为重复属性保存，
而由关系表达。字段明细只保留 LLM 推理和业务判断需要的金额、日期、状态、版本和分类。

## 业务操作

模型提供登记客户、授信、创建方案、签约、放款、建立租金版本、生成应收、登记收款、核销、结清和生成凭证
等 Action。Action 编译为 Object/Relation ChangeSet，经过预览和用户确认后写入 SQLite。

## Web 工作台

`app/` 是融资租赁领域自己的 Web 应用，不进入 UOM 核心。页面直接使用当前 `model.yaml` 生成对象和关系
筛选、Action 目录及输入表单，并提供：

- 合同金额、收款和待核销资金概览；
- 授信到结清的可点击经营主链；
- 对象、关系及相邻事实追溯；
- 模型词汇浏览和扩展；
- Action 预览、业务校验、确认执行；
- 基于 oag-agent 的对话和 UI Action 表单调用。

启动服务：

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent --env-file .env -- python -m leasing.app.server
```

默认打开 <http://127.0.0.1:8766>。没有 LLM 配置时，图数据、模型和业务表单仍可使用。

部署到 `~/Develop/leasing-oms` 时，可安装用户级 systemd 服务：

```bash
install -Dm644 leasing/deploy/leasing-oms.service ~/.config/systemd/user/leasing-oms.service
systemctl --user daemon-reload
systemctl --user enable --now leasing-oms.service
```

部署服务监听 `0.0.0.0:8767`，并与 `highway-oms.service` 共享 UOM、oag-agent 和根目录 `.env`，但使用独立的
`leasing/data/graph.db` 和 Agent 会话。

## 确定性约束

`audit_finance_consistency` 在 LLM 之外检查：

- 每条核销必须来源于一笔收款，并指向一笔应收或罚息；
- 同一收款的累计核销不得超过到账金额；
- 同一应收或罚息的累计核销不得超过业务金额；
- 核销两端币种必须一致；
- 授信预占和已用金额由额度流水汇总，余额不得为负且合计不得超过授信金额；
- 凭证借方与贷方合计必须平衡。

`LeasingActionService` 会在业务 Action 预览阶段把 ChangeSet 投影到当前图上并执行同一审计；审计失败时
不会生成提交令牌，因此非法资金变更无法进入确认和写入阶段。

## 验证

```bash
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python leasing/scripts/validate_model.py --root leasing
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python -m unittest discover -s leasing/tests -v
PYTHONPATH="$PWD/oag-agent:$PWD" uv run --project oag-agent -- python leasing/scripts/seed.py
node --check leasing/app/static/app.js
```

`seed.py` 默认只校验；使用 `--confirm-clear` 才会替换 `leasing/data/graph.db`。

原始领域资料保存在 `docs/融资租赁数据模型.puml` 和 `docs/_实体定义.iuml`，用于对照而不作为运行时模型直接加载。
