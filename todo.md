# TODO: Ontology-Native OMS Shell

## Product Principle

Build an OMS shell where the ontology is not shown as a database schema, but disappears into ordinary work views.

Users should see primary business resources, current context, related evidence, available actions, and proactive guidance. The ontology should quietly determine what fields, relationships, actions, constraints, explanations, and next steps appear.

The shell should not become a chat box waiting for questions. When a user opens a primary resource, the system should understand the current context and actively guide the user toward the next meaningful step.

## Core Model

- only primary resources are directly visible to users
- non-primary ontology objects support primary resource pages instead of becoming top-level navigation entries
- runtime builds a resource context from ontology, data, workflow, links, actions, and current status
- LLM uses that context to proactively explain, guide, and suggest next steps
- deterministic code owns capability boundaries, permissions, side effects, and execution

## Primary Resource Model

Not every ontology object should be a user-facing resource.

Each object should have a presentation role:

```yaml
ui:
  visibility: primary | embedded | history | evidence | admin_config | internal
  display_name: "员工"
  nav_group: "人员与组织"
  list_fields: [...]
  detail_sections: [...]
```

Meaning:

- `primary`: appears in navigation and resource browser.
- `embedded`: appears as a section inside a primary resource page. Example: salary profile versions on an employee page.
- `history`: appears as timeline or previous records under a primary resource. Example: employment relationship changes under an employee page.
- `evidence`: explains why a state, number, warning, validation result, or recommendation exists. Example: payroll snapshots explaining which employee state was used by a payroll run.
- `admin_config`: appears only in configuration/admin views. Example: tax rate rules and social insurance rules.
- `internal`: hidden from normal users; available only for debug, audit, or trace inspection.

Example classification for current OMS ontology:

- Primary: 员工、公司主体、月度薪资批次、员工月度工资明细、工资条、顾问服务关系、顾问劳务费结算、人力成本归集、审批记录、导出记录。
- Embedded/History: 自然人、员工任职关系、薪资档案版本、考勤汇总、绩效记录、工资补扣调整、社保缴费记录、公积金缴费记录、个税累计台账。
- Evidence/Internal: 薪资输入快照、员工薪资输入快照、工资项明细、社保公积金扣款台账、薪资校验结果。
- Admin Config: 薪资拆分规则、绩效系数规则、社保规则、公积金规则、个税税率规则。

The exact classification should be metadata-driven, not hardcoded in Python.

## Resource Context

When a user opens a primary resource, the shell should build a deterministic `resource_context`.

Example:

```yaml
resource_context:
  resource_type: PayrollRun
  resource_label: "月度薪资批次"
  resource_id: "PAYROLL_202604"
  status: "draft"
  key_facts:
    - "批次已创建"
    - "尚未构建薪资输入快照"
    - "已有考勤和绩效输入候选"
  related_context:
    - label: "员工范围"
      source: Employee
      role: embedded
    - label: "薪资档案版本"
      source: SalaryProfile
      role: evidence
  available_actions:
    - build_payroll_snapshot
    - generate_payroll_lines
  blocked_actions:
    - action: calculate_payroll
      reason: "需要先生成工资明细"
```

This context should come from:

- current primary resource record
- ontology object metadata
- links and relationship graph
- workflow step order
- function schemas, `depends_on`, `preconditions`, `writes_to`, `involves_objects`
- presentation metadata
- existing runtime data and execution results

It should not require hardcoded payroll concepts in the shell.

## Proactive Guidance

The system should actively guide the user when a primary resource is opened.

Guidance should answer:

- What is this resource's current state?
- What matters most right now?
- What evidence explains that state?
- What action can the user take next?
- Which actions are unavailable, and why?
- What should the user review before proceeding?

LLM can generate the human-facing guidance, but only from deterministic context.

Example output:

> 这个薪资批次还处在准备阶段。现在最重要的是确认输入是否完整，然后构建薪资快照。快照生成后，本批次会固定员工归属、薪资档案和规则，后续主数据变化不会影响本次核算。

The UI should show this as an assistant-style proactive message, not as ontology jargon.

## Action Candidates

The runtime should derive candidate actions for the current primary resource from ontology and presentation metadata:

- workflow actions
- read-only lookup actions
- preview actions
- mutation actions
- export actions
- navigation actions

Actions need deterministic metadata:

```yaml
side_effect: read_only | preview | mutation | workflow | export
requires_confirmation: true | false
enabled: true | false
disabled_reason: "..."
```

Runtime responsibilities:

- bind parameters from current context
- filter by preconditions and status
- separate enabled and blocked actions
- sort by workflow order, dependency order, and relevance
- never let LLM invent executable capabilities

LLM responsibilities:

- rank or highlight deterministic candidates
- explain why an action is recommended
- explain why an action is blocked
- phrase action choices in business language

## Display Rules

The shell should render normal business views:

- resource list
- resource detail
- related records
- evidence and trace
- action panel
- proactive guidance

It should not render ontology objects as a flat table browser.

Default labels should come from ontology:

- object display name from `summary`
- object description from `description`
- field label from `properties.*.description`
- id field from required property or explicit metadata

Optional UI metadata can refine:

```yaml
ui:
  display_name: "员工"
  list_fields: [employee_id, employee_number, department, position, status]
  detail_sections:
    - title: "基本信息"
      fields: [employee_id, employee_number, department, position, status]
    - title: "薪资上下文"
      related: [SalaryProfile, EmploymentRelationship]
```

## LLM Role

LLM should be used at runtime for proactive interaction, not for business authority.

LLM can:

- explain the current resource state
- summarize related evidence
- guide the user to the next step
- translate ontology/runtime metadata into business language
- diagnose warnings, blockers, and unusual states
- ask the user focused follow-up questions when context is incomplete

LLM must not:

- calculate business results
- mutate data
- approve workflow steps
- bypass status constraints
- choose functions outside deterministic candidates
- invent fields, records, or permissions

LLM must remain non-blocking:

- resource view loads with deterministic fallback
- guidance is requested asynchronously
- streamed/partial responses can be displayed with typewriter effect
- failure should not block normal resource operation

## Current Implementation Focus

The prototype should evolve toward a thin shell:

- primary resource visibility comes from presentation metadata
- resource lists and detail sections are generated from ontology and presentation metadata
- `resource_context` is built dynamically at runtime
- action candidates are derived from ontology functions, workflows, preconditions, and presentation metadata
- proactive guidance is generated from `resource_context`
- result presentation should become generic instead of function-specific
- domain-specific wording should move into ontology and presentation metadata

## Target Architecture

Possible end state:

```text
prototype/
  oms_app.py                 # thin HTTP server
  shell/
    ontology.py              # ontology loading and metadata helpers
    resources.py             # primary resource browsing and detail context
    actions.py               # action candidate discovery and binding from ontology
    workflows.py             # workflow/dependency/precondition ordering
    presentation.py          # generic field/detail/result presentation
    guidance.py              # resource_context construction
    llm.py                   # async non-blocking LLM guidance
  static/
    index.html
    app.js
    styles.css

oms/
  ontology.yaml              # domain ontology
  presentation.yaml          # optional UI visibility/layout metadata
```

## Migration Plan

1. Add object visibility metadata: `primary`, `embedded`, `evidence`, `internal`, `admin_config`.
2. Change resource browser to show only primary resources by default.
3. Render embedded/evidence objects inside primary resource details through links and configured sections.
4. Build deterministic `resource_context` for every primary resource detail view.
5. Derive action candidates from ontology functions, workflows, preconditions, and presentation metadata.
6. Use LLM only to explain and prioritize deterministic context/actions.
7. Move resource labels, groups, list fields, and detail sections out of Python.
8. Replace object-specific column/detail logic with generic inference plus optional UI metadata.
9. Replace hardcoded capability ordering with workflow/dependency-based ordering.
10. Replace function-specific result presenters with generic result inspection and optional presentation metadata.
11. Split `prototype/oms_app.py` into shell modules after behavior stabilizes.

## Definition Of Done

- Users only see primary business resources by default.
- Secondary/internal ontology objects appear as context, evidence, or drill-downs, not as top-level resources.
- Opening a primary resource produces deterministic `resource_context`.
- The system proactively guides the user based on current context.
- LLM guidance is async, non-blocking, and grounded in deterministic context.
- LLM never invents executable actions or bypasses constraints.
- Adding a new ontology object does not require Python code changes for basic display.
- Adding a new function/action does not require Python code changes for basic candidate discovery and preview.
- `prototype/oms_app.py` contains no hardcoded OMS object names except demo defaults.
