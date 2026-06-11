# TODO: Make Prototype Truly Ontology-Native

## Goal

Refactor `prototype/oms_app.py` from an OMS payroll-specific shell into a generic ontology-driven resource shell.

The shell should not know about `Person`, `Employee`, `PayrollRun`, payroll diffs, contribution deductions, or any other domain-specific concept in Python code. It should render resources, fields, relationships, capabilities, diagnostics, and guidance from ontology metadata, domain configuration, function schemas, runtime results, and optional LLM interpretation.

The target product principle:

> Ontology disappears into everywhere: users see normal resource lists, detail views, related records, actions, evidence, and business guidance; the ontology quietly determines what appears.

## Current Problems

- `prototype/oms_app.py` still contains hardcoded OMS concepts:
  - `RESOURCE_GROUPS`
  - `DISPLAY_OVERRIDES`
  - `PAYROLL_SIGNAL_TYPES`
  - `CAPABILITY_ORDER`
  - object-specific table columns in `browser_columns()`
  - function-specific presenters such as `present_payroll_result()`
  - payroll-specific `runtime_signals()`
  - function-specific summaries in `result_summary()`
  - function-specific evidence in `capability_evidence()`
- The prototype product direction is ontology-native, but implementation is still domain-specific.
- Adding a new domain would require editing Python code instead of updating ontology/domain metadata.

## Desired Architecture

### 1. Resource Display Metadata Comes From Ontology

Use ontology metadata as the default source for UI labels:

- object display name from `summary`
- object description from `description`
- field label from `properties.*.description`
- id field from required property or explicit source metadata

Add optional UI metadata only where inference is not enough:

```yaml
ui:
  display_name: "员工身份"
  list_fields: [employee_id, department, position, status]
  detail_groups:
    - title: "基本信息"
      fields: [employee_id, person_id, employee_number]
```

### 2. Resource Groups Are Configuration, Not Code

Move resource grouping out of Python:

```yaml
ui:
  groups:
    - name: "人员资源"
      objects: [Person, Employee, EmploymentRelationship, SalaryProfile]
    - name: "薪资结算"
      objects: [PayrollRun, PayrollLine, PayrollItem]
```

Fallback if no config exists:

- group by `kind`
- then by `data_source`
- then alphabetically by object name

### 3. Table Columns Are Derived

Remove object-specific column maps from `browser_columns()`.

Default column inference:

- required/id field first
- fields containing or describing name/status/type/date/period/company/employee
- numeric money/base/amount/tax/cost fields
- max 4-6 columns

Allow override through ontology UI metadata:

```yaml
ui:
  list_fields: [...]
```

### 4. Detail Layout Is Generic

Replace object-specific detail grouping with general field grouping:

- identity fields
- status/type fields
- date/period fields
- amount/base/cost/tax fields
- source/trace/rule/note fields
- remaining fields

Allow override through:

```yaml
ui:
  detail_groups:
    - title: "关系定位"
      fields: [...]
```

### 5. Runtime Signals Are Declared By Resource

Remove hardcoded `PAYROLL_SIGNAL_TYPES` and payroll calls from generic runtime code.

Declare signal functions in ontology/domain metadata:

```yaml
objects:
  PayrollRun:
    ui:
      signal_functions:
        - calculate_payroll
```

The shell should:

- run declared signal functions asynchronously or on demand
- display generic signal cards from returned counts, warnings, diffs, and result sets
- avoid showing payroll-specific metrics on unrelated resources

### 6. Capabilities Are Ordered From Ontology

Remove `CAPABILITY_ORDER`.

Order capabilities by:

- workflows and workflow step order
- `depends_on`
- function group
- function type
- current preconditions/status availability
- enabled actions before disabled actions

### 7. Result Presentation Is Generic

Remove function-specific presenter methods where possible:

- `present_employee_state_result`
- `present_rules_result`
- `present_snapshot_result`
- `present_generate_lines_result`
- `present_contributions_result`
- `present_payroll_result`

Generic result presentation should inspect:

- scalar count fields
- `status`
- `warnings` / `sample_warnings`
- `diffs` / `sample_diffs`
- `result_set`
- `sample_*` rows
- function `writes_to`
- function `involves_objects`

Domain-specific wording should be handled by:

- ontology metadata
- optional presentation config
- LLM explanation grounded in result JSON

### 8. Evidence Is Derived

Remove hardcoded `capability_evidence()`.

Evidence should come from:

- current resource type
- function `involves_objects`
- function `writes_to`
- related ontology links
- rules applying to involved objects
- runtime result sections

### 9. LLM Role Remains Non-Blocking

Keep LLM non-blocking:

- resource view loads with deterministic fallback
- `/api/llm/task` returns async enhancements
- result explanations stream through `partial`
- frontend shows typewriter effect for result explanations

LLM should only:

- explain
- summarize
- guide
- diagnose warnings/diffs
- translate ontology metadata into business language

LLM should not:

- calculate business results
- decide approvals
- mutate data
- bypass preconditions or status constraints

## Proposed File Structure

Possible end state:

```text
prototype/
  oms_app.py                 # thin HTTP server
  shell/
    runtime.py               # generic shell orchestration
    resources.py             # generic resource browsing/detail
    capabilities.py          # generic capability discovery/order
    presentation.py          # generic result presentation
    llm.py                   # async non-blocking LLM tasks
  static/
    index.html
    app.js
    styles.css

oms/
  ontology.yaml              # business ontology
  presentation.yaml          # optional UI/presentation metadata
```

## Migration Plan

1. Add optional `ui` metadata support without changing existing behavior.
2. Move `DISPLAY_OVERRIDES` into ontology summaries or UI metadata.
3. Move `RESOURCE_GROUPS` into ontology/presentation config.
4. Replace object-specific `browser_columns()` with inferred columns plus optional overrides.
5. Replace hardcoded detail grouping with generic field grouping plus optional overrides.
6. Move payroll signal behavior into object-level `ui.signal_functions`.
7. Replace `CAPABILITY_ORDER` with workflow/dependency-based ordering.
8. Introduce generic result presenter.
9. Keep only minimal domain-specific configuration outside Python.
10. Split `oms_app.py` into generic shell modules after behavior stabilizes.

## Definition Of Done

- `prototype/oms_app.py` contains no hardcoded OMS object names except default demo context.
- Adding a new ontology object requires no Python code change.
- Adding a new function requires no Python code change for basic display and execution preview.
- Resource list, detail, related records, actions, evidence, and guidance are generated from ontology/config.
- Payroll-specific metrics only appear because payroll resources/functions declare them.
- LLM remains optional, async, and grounded in deterministic runtime output.
