# OMS Action Contract 设计草案

## 定位

OMS Action Contract 是企业资源管理系统里的统一业务动作协议。

它不是普通按钮配置，也不是前端路由表。它用于把页面按钮、智能层建议、本体函数、审批工作流、权限校验和审计追踪连接起来。

一句话：

> Action Contract 把“下一步建议”变成可执行、可解释、可治理的业务动作。

## 与 ontology functions 的关系

`ontology.yaml.functions` 定义系统具备的底层业务能力，例如：

- `calculate_payroll`
- `calculate_contributions`
- `build_payroll_snapshot`
- `generate_payroll_lines`

这些函数描述的是系统能做什么、涉及哪些对象、依赖什么、写入什么对象。

Action Contract 定义用户在某个业务上下文中能看到和执行什么动作。

两者关系：

```text
ontology.functions = system capabilities
OMS actions        = user-facing business commands
```

一个 function 可以对应多个 action。

例如 `calculate_payroll` 可以被这些 action 使用：

- 复核整批工资
- 查看单个员工工资
- 生成审批前试算摘要

一个 action 也可以不调用 function，例如：

- `navigate`：打开薪资模块
- `api_call`：生成工资说明
- `workflow`：提交审批
- `export`：导出工资表

Agent 推荐的应该是 action，而不是直接裸调 function。

## 基础结构

建议的 action 结构：

```json
{
  "id": "payroll.review_diffs",
  "label": "复核工资行差异",
  "kind": "navigate",
  "target": {
    "module": "payroll",
    "focus": "diffs",
    "object_type": "PayrollRun",
    "object_id": "PAYROLL_202604"
  },
  "reason": "当前批次存在 12 个工资行差异",
  "enabled": true,
  "disabled_reason": "",
  "requires_confirmation": false,
  "side_effect": "read_only",
  "agent_autorun": "safe",
  "evidence": [
    "calculate_payroll.diff_count",
    "PayrollLine benchmark diff"
  ]
}
```

## 字段说明

### id

动作的稳定标识。

示例：

```text
payroll.review_diffs
payroll.calculate_preview
employee.explain_payroll
payroll.submit_approval
```

### label

给用户看的按钮文案。

### kind

动作类型。

当前原型支持：

```text
navigate
api_call
focus
```

后续建议扩展：

```text
ontology_function
workflow
mutation
export
```

### target

动作目标。

不同 `kind` 使用不同 target。

导航动作：

```json
{
  "kind": "navigate",
  "target": {
    "module": "payroll",
    "focus": "diffs"
  }
}
```

API 调用：

```json
{
  "kind": "api_call",
  "target": {
    "endpoint": "/api/explain/payroll"
  }
}
```

本体函数调用：

```json
{
  "kind": "ontology_function",
  "target": {
    "function": "calculate_payroll"
  }
}
```

工作流动作：

```json
{
  "kind": "workflow",
  "target": {
    "workflow": "payroll_approval",
    "transition": "submit"
  }
}
```

### enabled 与 disabled_reason

`enabled` 表示动作当前是否可执行。

如果不可执行，必须提供 `disabled_reason`。

示例：

```json
{
  "enabled": false,
  "disabled_reason": "当前批次仍有 12 个工资行差异，不能提交审批。"
}
```

### requires_confirmation

是否需要用户确认。

只读或导航动作通常不需要确认。写入、审批、锁定、导出等动作需要确认。

### side_effect

动作副作用等级。

建议取值：

```text
read_only       只读
preview         试算或预览，不写入业务事实
write           写入业务数据
workflow        改变流程状态
export          生成外部文件
irreversible    锁定、归档、发放等不可轻易撤销动作
```

### agent_autorun

Agent 是否可以自动执行。

建议取值：

```text
safe   可以自动执行，例如导航、只读查询
ask    需要用户确认
never  只能由用户手动触发
```

## 参数来源

如果 action 调用 API、本体函数、工作流或写操作，就必须明确参数来源。

参数不应该由 Agent 临时随意填写，而应该由 Action Runtime 从上下文、选择、用户输入、默认值和对象关系中解析。

### 参数来源类型

```text
context       当前业务上下文
selection     当前选中对象
input         用户输入
current_user  当前登录用户
literal       action 定义里的固定值
derived       通过对象关系派生
agent_suggested Agent 建议值
```

### 参数绑定示例

```yaml
params:
  payroll_run_id:
    source: context
    path: object_id
  employee_id:
    source: context
    path: employee_id
  include_result_set:
    source: literal
    value: true
```

也可以使用短模板：

```yaml
params:
  payroll_run_id: "{context.object_id}"
  employee_id: "{context.employee_id}"
  include_result_set: true
```

### 参数 provenance

执行时应记录每个参数的来源。

示例：

```json
{
  "name": "payroll_run_id",
  "value": "PAYROLL_202604",
  "source": "context.object_id",
  "trusted": true
}
```

这样审计时可以回答：

```text
这个参数是谁提供的？
来自当前对象、用户输入、系统派生，还是 Agent 建议？
```

Agent 建议值应该进入 `suggested_params`，不能直接覆盖关键参数。

## 用户输入

有些动作需要用户输入。

例如审批动作：

```yaml
input_schema:
  decision:
    type: enum
    options: ["通过", "驳回"]
    required: true
  comment:
    type: string
    required: false
```

前端根据 `input_schema` 生成确认表单，用户提交后再执行。

## 权限

企业管理系统中的 action 必须绑定权限。

示例：

```yaml
permission: payroll.run.approve
required_roles:
  - payroll_admin
  - finance_reviewer
```

前端禁用只是体验。后端 Action Runtime 必须再次校验权限。

## 状态机约束

Action 需要接入 ontology 中的状态机和约束。

例如 `PayrollRun` 中已有：

- `status_transitions`
- `constraints`
- `excluded_functions`

Action Runtime 执行前应该检查：

- 当前状态是否允许此动作
- 目标 function 是否被当前状态排除
- 依赖函数是否满足
- 是否违反 paid、locked 等状态约束

## 幂等性

Action 需要说明重复执行的行为。

建议结构：

```yaml
idempotency:
  mode: prevent_duplicate
  key: "{action_id}:{object_type}:{object_id}:{snapshot_id}"
```

建议取值：

```text
allow              允许重复执行
prevent_duplicate  防止重复
create_version     每次执行生成新版本
```

## 异步执行

批量计算、导出、生成工资条、批量说明等动作可能需要异步执行。

Action Runtime 可以返回：

```json
{
  "status": "accepted",
  "job_id": "JOB_001"
}
```

然后通过 job 状态轮询：

```text
pending
running
succeeded
failed
cancelled
```

## 执行结果协议

Action 执行后应返回标准结果：

```json
{
  "status": "success",
  "action_id": "payroll.calculate_preview",
  "result": {},
  "message": "薪资试算完成。",
  "refresh": {
    "modules": ["payroll"],
    "objects": [
      {
        "type": "PayrollRun",
        "id": "PAYROLL_202604"
      }
    ]
  },
  "next_actions": []
}
```

这样前端知道执行后刷新哪里，智能层知道下一步应该推荐什么。

## 审计

Action 是审计天然入口。

写操作、流程动作、导出动作必须记录：

```text
actor
action_id
object_type
object_id
params
param_sources
before_state
after_state
result
timestamp
trace_id
evidence
```

即使 prototype 没有用户体系，也应该在结构上预留这些字段。

## 版本与快照

薪资系统尤其需要版本约束。

Action 执行时应带 expected state：

```json
{
  "expected_state": {
    "payroll_run_id": "PAYROLL_202604",
    "status": "draft",
    "snapshot_id": "SNAPSHOT_202604",
    "diff_count": 12
  }
}
```

后端执行前检查状态是否仍一致。

如果用户看到 A 状态，执行时已经变成 B 状态，系统应提示刷新，而不是继续执行。

## 批量动作

Action 需要支持多对象。

示例：

```json
{
  "selection": {
    "object_type": "Employee",
    "ids": ["EMP001", "EMP002"]
  }
}
```

批量动作需要声明失败策略：

```text
all_or_nothing
partial_success
preview_first
```

## Action Runtime

后续应建设 Action Runtime，负责统一执行 action。

推荐流程：

```text
用户点击 action
  -> 前端提交 action_id + context + input
  -> Action Runtime 读取 action 定义
  -> 解析参数
  -> 校验权限
  -> 校验状态机
  -> 校验确认与输入
  -> 执行 navigate / api_call / ontology_function / workflow / export
  -> 写审计
  -> 返回结果、刷新建议和 next_actions
```

建议接口：

```text
GET  /api/actions?object_type=PayrollRun&object_id=PAYROLL_202604
POST /api/action/execute
```

## Agent 的角色

Agent 不应该直接做事。

Agent 应该：

- 推荐 action
- 解释为什么推荐 action
- 生成 action 的候选参数
- 发现策略缺口
- 总结执行结果

Agent 不应该绕过：

- 权限
- 状态机
- 参数校验
- 用户确认
- 审计

## 当前 prototype 状态

当前 prototype 已经实现简化版 Action Contract：

```json
{
  "label": "先进入薪资批次复核差异",
  "kind": "navigate",
  "target": {
    "module": "payroll",
    "focus": "diffs"
  },
  "enabled": true,
  "requires_confirmation": false
}
```

前端当前支持：

- `navigate`
- `api_call`
- `focus`

后续应扩展到：

- action registry
- 参数绑定
- ontology_function 执行
- confirmation/input_schema
- audit
- permission
- async jobs

