const state = {
  app: null,
  module: "home",
  selectedEmployee: "EMP074",
};

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function init() {
  state.app = await getJson("/api/app");
  renderNav(state.app.modules);
  renderHome(state.app);
}

function renderNav(modules) {
  const nav = document.querySelector("#moduleNav");
  nav.innerHTML = modules.map((module) => `
    <button data-module="${escapeHtml(module.id)}">${escapeHtml(module.label)}</button>
  `).join("");
  nav.querySelectorAll("[data-module]").forEach((button) => {
    button.addEventListener("click", () => openModule(button.dataset.module));
  });
  markActiveNav();
}

async function openModule(moduleId) {
  state.module = moduleId;
  markActiveNav();
  if (moduleId === "home") return renderHome(state.app || await getJson("/api/app"));
  if (moduleId === "people") return renderPeople();
  if (moduleId === "payroll") return renderPayroll();
  if (moduleId === "ontology") return renderOntology();
}

function markActiveNav() {
  document.querySelectorAll("#moduleNav button").forEach((button) => {
    button.classList.toggle("active", button.dataset.module === state.module);
  });
}

function setTitle(title, subtitle) {
  document.querySelector("#pageTitle").textContent = title;
  document.querySelector("#pageSubtitle").textContent = subtitle || "";
}

function setAgent(agent) {
  document.querySelector("#agentTitle").textContent = agent.title || "智能层";
  document.querySelector("#agentSummary").innerHTML = renderMarkdown(agent.summary || "");
  document.querySelector("#agentActions").innerHTML = (agent.next_actions || [])
    .map((item) => {
      const action = normalizeAgentAction(item);
      if (!action.enabled || !action.kind) {
        return `<li><span class="agent-action disabled" title="${escapeHtml(action.disabled_reason || "")}">${escapeHtml(action.label)}</span></li>`;
      }
      return `<li><button class="agent-action" title="${escapeHtml(action.kind)}" data-action="${escapeHtml(JSON.stringify(action))}">${escapeHtml(action.label)}</button></li>`;
    })
    .join("");
  document.querySelectorAll(".agent-action").forEach((button) => {
    button.addEventListener("click", () => runAgentAction(parseAction(button.dataset.action)));
  });
  document.querySelector("#agentEvidence").innerHTML = (agent.evidence || [])
    .map((item) => `<span>${escapeHtml(item)}</span>`)
    .join("");
}

function normalizeAgentAction(item) {
  if (item && typeof item === "object") {
    return {
      label: item.label || item.title || "打开",
      kind: item.kind || "",
      target: item.target || {},
      params: item.params || {},
      enabled: item.enabled !== false,
      requires_confirmation: item.requires_confirmation === true,
      disabled_reason: item.disabled_reason || "",
      id: item.id || "",
      side_effect: item.side_effect || "",
    };
  }
  return { label: String(item || ""), kind: "", target: {}, enabled: false };
}

function runAgentAction(action) {
  if (!action || action.enabled === false) return;
  if (action.requires_confirmation && !window.confirm(`确认执行：${action.label}？`)) return;
  if (action.kind === "navigate") {
    navigateAction(action.target || {});
  } else if (action.kind === "api_call") {
    apiAction(action.target || {});
  } else if (action.kind === "focus") {
    focusAction(action.target || {});
  } else if (action.kind === "ontology_function") {
    ontologyFunctionAction(action);
  }
}

function parseAction(raw) {
  try {
    const action = JSON.parse(raw || "{}");
    return action && typeof action === "object" ? action : {};
  } catch {
    return {};
  }
}

function navigateAction(target) {
  if (target.module === "home") return openModule("home");
  if (target.module === "people") return openModule("people");
  if (target.module === "payroll") return openModule("payroll");
  if (target.module === "ontology") return renderObject(target.object_type || "Employee", target.filters || {});
  if (target.module === "employee") return renderEmployee(target.employee_id || state.selectedEmployee);
}

function apiAction(target) {
  if (target.endpoint === "/api/explain/payroll") {
    const button = document.querySelector("#explainPayrollBtn");
    if (button) explainPayroll(state.selectedEmployee, button);
    else renderEmployee(state.selectedEmployee).then(() => {
      const nextButton = document.querySelector("#explainPayrollBtn");
      if (nextButton) explainPayroll(state.selectedEmployee, nextButton);
    });
  }
}

function focusAction(target) {
  if (target.id === "search") {
    openModule("people");
    setTimeout(() => document.querySelector("#searchInput").focus(), 0);
  }
}

async function ontologyFunctionAction(action) {
  const functionName = (action.target || {}).function || action.id || "ontology_function";
  setAgent({
    title: `执行中 · ${action.label}`,
    summary: `正在调用本体函数 \`${functionName}\`。\n\n参数：\`${JSON.stringify(action.params || {})}\``,
    next_actions: [{ label: "等待执行完成", kind: "", enabled: false }],
    evidence: ["oms.actions.yaml", functionName],
  });
  const params = new URLSearchParams({
    action_id: action.id || "",
    employee_id: state.selectedEmployee || "",
    object_type: state.module === "payroll" ? "PayrollRun" : "Employee",
  });
  try {
    const data = await getJson(`/api/action/execute?${params.toString()}`);
    const result = data.result || {};
    const presentation = data.presentation || {};
    setAgent({
      title: `${data.status === "success" ? "执行完成" : "执行结果"} · ${action.label}`,
      summary: formatActionPresentation(presentation, result, data.message || ""),
      next_actions: (presentation.next_actions && presentation.next_actions.length) ? presentation.next_actions : [
        { label: "查看本体能力", kind: "navigate", target: { module: "ontology", object_type: inferObjectType(action) }, enabled: true },
        { label: "返回薪资批次", kind: "navigate", target: { module: "payroll" }, enabled: true },
      ],
      evidence: ["oms.actions.yaml", functionName],
    });
  } catch (error) {
    setAgent({
      title: `执行失败 · ${action.label}`,
      summary: `调用本体函数时遇到错误：${error.message}`,
      next_actions: [
        { label: "查看本体能力", kind: "navigate", target: { module: "ontology", object_type: inferObjectType(action) }, enabled: true },
      ],
      evidence: ["api/action/execute"],
    });
  }
}

function formatActionPresentation(presentation, result, fallbackMessage) {
  if (!presentation || !presentation.summary) {
    return `${fallbackMessage}\n\n${formatActionResult(result)}`;
  }
  const lines = [presentation.summary];
  if (presentation.highlights && presentation.highlights.length) {
    lines.push("");
    lines.push(...presentation.highlights.map((item) => `- **${item.label}**: ${formatActionValue(item.value)}`));
  }
  if (presentation.warnings && presentation.warnings.length) {
    lines.push("");
    lines.push("### 需要注意");
    lines.push(...presentation.warnings.map((item) => `- ${item}`));
  }
  return lines.join("\n");
}

function inferObjectType(action) {
  const functionName = (action.target || {}).function || "";
  if (functionName.includes("rule")) return "Company";
  if (functionName.includes("employee")) return "Employee";
  return "PayrollRun";
}

function formatActionResult(result) {
  if (!result || typeof result !== "object") return String(result || "");
  const lines = [];
  const preferredKeys = [
    "status",
    "payroll_run_id",
    "employee_id",
    "employee_name",
    "payroll_company_name",
    "snapshot_id",
    "employee_snapshot_count",
    "generated_line_count",
    "calculated_line_count",
    "diff_count",
    "warning_count",
    "net_pay_total",
    "social_count",
    "housing_count",
    "deduction_count",
  ];
  for (const key of preferredKeys) {
    if (result[key] !== undefined && result[key] !== "") {
      lines.push(`- **${key}**: ${formatActionValue(result[key])}`);
    }
  }
  if (!lines.length) {
    return `\`${JSON.stringify(result).slice(0, 1200)}\``;
  }
  return lines.join("\n");
}

function formatActionValue(value) {
  if (Array.isArray(value)) return `${value.length} 条`;
  if (value && typeof value === "object") return `\`${JSON.stringify(value).slice(0, 240)}\``;
  return escapeHtml(value);
}

function renderHome(data) {
  state.module = "home";
  markActiveNav();
  setTitle("企业资源总览", data.product.description);
  setAgent(data.agent);
  const dashboard = data.dashboard;
  document.querySelector("#content").innerHTML = `
    <div class="metric-grid">
      ${dashboard.metrics.map(metricCard).join("")}
    </div>
    <section class="block">
      <div class="section-head">
        <h2>需要关注</h2>
        <p>稳定管理系统首页，智能层只负责排序和解释。</p>
      </div>
      <div class="attention-list">
        ${dashboard.attention.map((item) => `
          <button class="attention ${escapeHtml(item.severity)}" data-module="${escapeHtml(item.module)}">
            <strong>${escapeHtml(item.title)}</strong>
            <span>${escapeHtml(item.detail)}</span>
          </button>
        `).join("")}
      </div>
    </section>
    <section class="block">
      <div class="section-head">
        <h2>企业资源地图</h2>
        <p>资源对象来自 ontology，本体提供关系和能力。</p>
      </div>
      <div class="resource-map">
        ${dashboard.resource_map.map((group) => `
          <div class="resource-group">
            <h3>${escapeHtml(group.label)}</h3>
            ${group.objects.map((object) => `
              <button class="resource-chip" data-object-type="${escapeHtml(object.type)}">
                <strong>${escapeHtml(object.summary)}</strong>
                <span>${escapeHtml(object.type)} · ${escapeHtml(object.count)}</span>
              </button>
            `).join("")}
          </div>
        `).join("")}
      </div>
    </section>
  `;
  document.querySelectorAll("[data-module]").forEach((button) => {
    button.addEventListener("click", () => openModule(button.dataset.module));
  });
  document.querySelectorAll("[data-object-type]").forEach((button) => {
    button.addEventListener("click", () => renderObject(button.dataset.objectType));
  });
}

async function renderPeople(query = "") {
  state.module = "people";
  markActiveNav();
  const data = await getJson(`/api/employees?q=${encodeURIComponent(query)}`);
  setTitle("人员资源", `共 ${data.total} 个当前薪资快照员工`);
  setAgent(data.agent);
  document.querySelector("#content").innerHTML = `
    <section class="block">
      <div class="section-head">
        <h2>员工</h2>
        <p>选择员工查看自然人、任职、薪资档案和本批次薪资上下文。</p>
      </div>
      <div class="employee-grid">
        ${data.rows.map((row) => `
          <button class="employee-card" data-employee-id="${escapeHtml(row.employee_id)}">
            <strong>${escapeHtml(row.employee_id)} · ${escapeHtml(row.name)}</strong>
            <span>${escapeHtml(row.company)}</span>
            <em>${escapeHtml(row.position)} · 月薪 ${money(row.monthly_salary_total)}</em>
          </button>
        `).join("")}
      </div>
    </section>
  `;
  document.querySelectorAll("[data-employee-id]").forEach((button) => {
    button.addEventListener("click", () => renderEmployee(button.dataset.employeeId));
  });
}

async function renderEmployee(employeeId) {
  state.selectedEmployee = employeeId;
  const data = await getJson(`/api/employee?employee_id=${encodeURIComponent(employeeId)}`);
  const payroll = data.payroll || {};
  const line = payroll.line || {};
  setTitle(`${employeeId} · ${(data.person && data.person.name) || ""}`, `${line.payroll_company_name_snapshot || ""} · ${line.position || ""}`);
  setAgent(data.agent);
  document.querySelector("#content").innerHTML = `
    <div class="metric-grid compact">
      ${metricCard({ label: "扣前应发", value: money(line.gross_pay_before_deduction), detail: "gross" })}
      ${metricCard({ label: "个人社保", value: money(line.personal_social_security), detail: "deduction" })}
      ${metricCard({ label: "个人公积金", value: money(line.personal_housing_fund), detail: "deduction" })}
      ${metricCard({ label: "个税", value: money(line.personal_income_tax), detail: "tax" })}
      ${metricCard({ label: "实发", value: money(line.net_pay), detail: "net", tone: "strong" })}
    </div>
    <section class="block">
      <div class="section-head">
        <h2>工资项</h2>
        <button id="explainPayrollBtn">生成工资说明</button>
      </div>
      ${table(data.payroll.items || [], [
        ["item_name", "工资项"],
        ["item_category", "类型"],
        ["amount", "金额", "money"],
        ["source_object_type", "来源"],
      ])}
    </section>
    <section class="block">
      <div class="section-head">
        <h2>资源关系</h2>
        <p>人员主数据和薪资上下文并列呈现。</p>
      </div>
      <div class="two-col">
        ${recordBox("自然人", data.person)}
        ${recordBox("员工身份", data.employee)}
      </div>
    </section>
  `;
  document.querySelector("#explainPayrollBtn").addEventListener("click", (event) => explainPayroll(employeeId, event.currentTarget));
}

async function renderPayroll() {
  state.module = "payroll";
  markActiveNav();
  const data = await getJson("/api/payroll");
  const run = data.run || {};
  setTitle(`${run.payroll_run_id} · 薪资批次`, `${run.payroll_period} 工资归属月 · 状态 ${run.status}`);
  setAgent(data.agent);
  document.querySelector("#content").innerHTML = `
    <div class="metric-grid">
      ${metricCard({ label: "计算人数", value: data.counts.employees, detail: "PayrollLine" })}
      ${metricCard({ label: "差异", value: data.counts.diffs, detail: "benchmark", tone: data.counts.diffs ? "danger" : "" })}
      ${metricCard({ label: "扣款待确认", value: data.counts.deduction_warning_employees, detail: "ContributionDeduction", tone: "warn" })}
      ${metricCard({ label: "实发合计", value: money(data.totals.net), detail: "net", tone: "strong" })}
    </div>
    <section class="block">
      <div class="section-head">
        <h2>工资行预览</h2>
        <p>结果由本体函数实时试算，空 CSV 不是阻断。</p>
      </div>
      ${table(data.sample_lines || [], [
        ["employee_id", "员工"],
        ["employee_name_snapshot", "姓名"],
        ["gross_pay_before_deduction", "扣前应发", "money"],
        ["personal_income_tax", "个税", "money"],
        ["net_pay", "实发", "money"],
      ])}
    </section>
    <section class="block">
      <div class="section-head">
        <h2>差异样例</h2>
        <p>差异优先进入复核，而不是直接审批。</p>
      </div>
      ${diffList(data.sample_diffs || [])}
    </section>
  `;
}

async function renderOntology() {
  state.module = "ontology";
  markActiveNav();
  await renderObject("Employee");
}

async function renderObject(objectType, filters = {}) {
  state.module = "ontology";
  markActiveNav();
  const params = new URLSearchParams({ object_type: objectType });
  Object.entries(filters || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(`filter_${key}`, value);
  });
  const data = await getJson(`/api/object?${params.toString()}`);
  setTitle(`${objectType} · ${data.object.summary}`, data.object.description);
  setAgent(data.agent);
  const filterText = Object.entries(data.object.filters || {})
    .map(([key, value]) => `${key}=${value}`)
    .join("，");
  document.querySelector("#content").innerHTML = `
    <section class="block">
      <div class="section-head">
        <h2>记录</h2>
        <p>共 ${data.object.count} 条${filterText ? `，已按 ${escapeHtml(filterText)} 过滤` : ""}，展示前 20 条。</p>
      </div>
      ${objectRows(data.rows || [])}
    </section>
    <section class="block">
      <div class="section-head">
        <h2>本体关系与能力</h2>
      </div>
      <div class="two-col">
        ${listBox("关系", data.related.map((item) => `${item.source} → ${item.target}`))}
        ${listBox("能力", data.functions.map((item) => `${item.group} / ${item.summary}`))}
      </div>
    </section>
  `;
}

async function explainPayroll(employeeId, button) {
  const originalText = button.textContent;
  button.disabled = true;
  button.classList.add("loading");
  button.textContent = "正在生成...";
  setAgent({
    title: "工资说明生成中",
    summary: "正在读取薪资计算结果、工资项、扣款提示和个税上下文，请稍候。",
    next_actions: [{ label: "等待说明生成完成", kind: "", enabled: false }],
    evidence: ["calculate_payroll", "PayrollItem", "TaxLedger"],
  });
  try {
    const data = await getJson(`/api/explain/payroll?employee_id=${encodeURIComponent(employeeId)}`);
    setAgent({
      title: `工资说明 · ${data.mode}`,
      summary: data.text,
      next_actions: [
        { label: "复核扣款台账", kind: "navigate", target: { module: "payroll", focus: "deductions" }, enabled: true },
        { label: "查看工资项", kind: "navigate", target: { module: "employee", employee_id: state.selectedEmployee }, enabled: true },
        { label: "生成审批说明", kind: "navigate", target: { module: "payroll", focus: "approval" }, enabled: true },
      ],
      evidence: ["calculate_payroll", "PayrollItem", "TaxLedger"],
    });
  } catch (error) {
    setAgent({
      title: "工资说明生成失败",
      summary: `生成过程中遇到错误：${error.message}`,
      next_actions: [
        { label: "稍后重试", kind: "api_call", target: { endpoint: "/api/explain/payroll" }, enabled: true },
        { label: "检查本体与接口", kind: "navigate", target: { module: "ontology", object_type: "Employee" }, enabled: true },
        { label: "查看确定性薪资结果", kind: "navigate", target: { module: "employee", employee_id: state.selectedEmployee }, enabled: true },
      ],
      evidence: ["api/explain/payroll"],
    });
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
    button.textContent = originalText;
  }
}

function metricCard(metric) {
  return `
    <div class="metric ${escapeHtml(metric.tone || "")}">
      <span>${escapeHtml(metric.label)}</span>
      <strong>${escapeHtml(metric.value)}</strong>
      <em>${escapeHtml(metric.detail || "")}</em>
    </div>
  `;
}

function table(rows, columns) {
  if (!rows.length) return `<div class="empty">暂无记录</div>`;
  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${columns.map(([, label]) => `<th>${escapeHtml(label)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows.map((row) => `
            <tr>${columns.map(([key, , format]) => `<td>${format === "money" ? money(row[key]) : escapeHtml(row[key])}</td>`).join("")}</tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function diffList(diffs) {
  if (!diffs.length) return `<div class="empty">暂无差异</div>`;
  return `<div class="diff-list">${diffs.map((diff) => `
    <button class="diff-card" data-employee-id="${escapeHtml(diff.employee_id)}">
      <strong>${escapeHtml(diff.employee_id)}</strong>
      <span>${escapeHtml(Object.keys(diff.fields || {}).join(", "))}</span>
    </button>
  `).join("")}</div>`;
}

function recordBox(title, record) {
  const entries = Object.entries(record || {}).slice(0, 8);
  return `
    <div class="record-box">
      <h3>${escapeHtml(title)}</h3>
      ${entries.map(([key, value]) => `<p><span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong></p>`).join("")}
    </div>
  `;
}

function listBox(title, rows) {
  return `
    <div class="record-box">
      <h3>${escapeHtml(title)}</h3>
      ${(rows || []).map((row) => `<p>${escapeHtml(row)}</p>`).join("") || "<p>暂无</p>"}
    </div>
  `;
}

function objectRows(rows) {
  if (!rows.length) return `<div class="empty">暂无记录</div>`;
  const keys = Object.keys(rows[0]).slice(0, 8);
  return table(rows, keys.map((key) => [key, key]));
}

function money(value) {
  const num = Number(value || 0);
  return num.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function renderMarkdown(text) {
  const lines = String(text || "").split(/\r?\n/);
  let html = "";
  let inList = false;
  const closeList = () => {
    if (inList) {
      html += "</ul>";
      inList = false;
    }
  };
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeList();
      continue;
    }
    if (line.startsWith("- ")) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${inlineMarkdown(line.slice(2))}</li>`;
      continue;
    }
    closeList();
    if (line.startsWith("### ")) {
      html += `<h3>${inlineMarkdown(line.slice(4))}</h3>`;
    } else if (line.startsWith("## ")) {
      html += `<h3>${inlineMarkdown(line.slice(3))}</h3>`;
    } else {
      html += `<p>${inlineMarkdown(line)}</p>`;
    }
  }
  closeList();
  return html;
}

function inlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

document.querySelector("#searchBtn").addEventListener("click", () => {
  renderPeople(document.querySelector("#searchInput").value.trim());
});
document.querySelector("#searchInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter") renderPeople(event.currentTarget.value.trim());
});

init();
