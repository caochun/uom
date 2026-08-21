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

`approval`（审批申请）是一次针对业务对象的审批决策事实，不拆成流程、阶段或任务对象。审批采用的流程快照、
历史记录和最终结果保存在 `approval.details`；被审批对象、提交主体和决策主体通过关系连接，决策关系的
`sequence` 表示顺序，相同序号可表达并行或会签。

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

模型提供登记客户、授信、创建方案、发起审批、记录审批决定、签约、放款、建立租金版本、生成应收、登记收款、
核销、结清和生成凭证等 Action。审批仍是一个 `approval` 对象：阶段决定追加到 `details.history`，只有最终决定
才更新 `details.result` 和审批状态；签约 Action 会拒绝没有通过审批的方案。核销目标可以是应收或逾期罚息，
登记收款时还可以记录可选的合同意向关系，真正的资金归属仍由核销路径确定。

所有依赖已有业务对象的 Action 都用必填对象输入显式表达参与者，例如发起审批中的 `reviewed_object`、
核销中的 `payment_id` 和生成应收中的 `schedule_version_id`。`context_input` 只声明详情页当前对象应预填到哪个输入；
它不会把 UI 上下文当作隐含的业务事实。因此 Agent 无需依赖详情页也能准确指定操作对象，而 UI 仍可自动预填。

Action 的业务顺序由公开 `model.yaml` 中的 `preconditions` 声明，而不是统一线性流程。当前支持 `object_status` 和
`related_object` 两种条件：例如签约前方案必须有已通过的审批，核销前收款必须处于未核销或部分核销状态。
前置条件在操作目录、预览和最终提交时都会评估；前端会锁定当前不可执行的操作并显示原因。

状态是业务操作的结果，不由用户在表单中任意指定。审批推进方案状态，签约关闭方案，计划新版本显式替代
旧版本，核销根据累计金额更新收款和应收/罚息状态；最终结清会检查未结债权、关闭合同和生效计划，并用
`reverse_occupy` 流水释放合同占用授信。具体执行模板位于私有 `action_plans.yaml`；Action 编译为
Object/Relation ChangeSet，经过预览和用户确认后写入 SQLite。

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
- 收款、应收和罚息的状态必须与累计核销进度一致；
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
当前 Seed 包含济南、青岛、潍坊、烟台、淄博和临沂多组业务状态，用于验证审批、额度预占/释放、
合同履约、多对多核销、罚息和结清语义；写入前会同时执行模型校验与资金一致性审计。

原始领域资料保存在 `docs/融资租赁数据模型.puml` 和 `docs/_实体定义.iuml`，用于对照而不作为运行时模型直接加载。
