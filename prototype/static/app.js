const state = {
  objectType: "PayrollRun",
  objectId: "PAYROLL_202604",
  selectedEmployee: "EMP074",
  context: null,
};

const money = (value) => {
  const num = Number(value || 0);
  return num.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function loadDomain() {
  const data = await getJson("/api/domain");
  document.querySelector("#domainDescription").textContent = data.domain.description;
  renderHealth(data.health);
  renderFlows(data.flows);
  if (data.spotlight) {
    await selectObject(data.spotlight.object_type, data.spotlight.object_id);
  }
}

function renderHealth(items) {
  const grid = document.querySelector("#healthGrid");
  grid.innerHTML = "";
  items.forEach((item) => {
    const button = document.createElement("button");
    button.className = "health-card";
    button.innerHTML = `
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <p>${escapeHtml(item.detail)}</p>
    `;
    button.addEventListener("click", () => selectObject(item.object_type, item.object_id));
    grid.appendChild(button);
  });
}

function renderFlows(flows) {
  const grid = document.querySelector("#flowGrid");
  grid.innerHTML = "";
  flows.forEach((flow) => {
    const node = document.createElement("button");
    node.className = "flow-card";
    const objectHtml = flow.objects.map((item) => `
      <span>${escapeHtml(item.summary)} <b>${escapeHtml(item.count)}</b></span>
    `).join("");
    const functionHtml = flow.functions.map((item) => `
      <em>${escapeHtml(item.summary)}</em>
    `).join("");
    node.innerHTML = `
      <strong>${escapeHtml(flow.title)}</strong>
      <div class="flow-objects">${objectHtml}</div>
      <div class="flow-functions">${functionHtml}</div>
    `;
    node.addEventListener("click", () => selectObject(flow.object_type, flow.object_id));
    grid.appendChild(node);
  });
}

async function selectObject(objectType, objectId = "") {
  state.objectType = objectType;
  state.objectId = objectId || "";
  if (objectType === "Employee" && objectId) state.selectedEmployee = objectId;
  const [context, detail] = await Promise.all([
    getJson(`/api/context?object_type=${encodeURIComponent(objectType)}&object_id=${encodeURIComponent(objectId || "")}`),
    getJson(`/api/object?object_type=${encodeURIComponent(objectType)}&object_id=${encodeURIComponent(objectId || "")}`),
  ]);
  state.context = context;
  renderContext(context);
  renderObjectDetail(detail, context);
}

function renderContext(context) {
  const current = context.current;
  document.querySelector("#currentTitle").textContent = current.display;
  document.querySelector("#currentSubtitle").textContent =
    `${current.summary} · ${current.object_type} · 共 ${current.count} 条`;
  document.querySelector("#contextNarrative").textContent = context.narrative;
  document.querySelector("#explanation").textContent = context.narrative;

  const related = document.querySelector("#relatedEntries");
  related.innerHTML = "";
  context.related.slice(0, 10).forEach((item) => {
    const node = document.createElement("div");
    node.className = "entry";
    const samples = item.samples.map((sample) => `
      <button class="text-link" data-object-type="${escapeHtml(item.target_type)}" data-object-id="${escapeHtml(sample.id)}">${escapeHtml(sample.label)}</button>
    `).join("");
    node.innerHTML = `
      <div>
        <strong>${escapeHtml(item.target_summary)}</strong>
        <p>${escapeHtml(item.description)}</p>
      </div>
      <span>${escapeHtml(item.count)}</span>
      <div class="sample-row">${samples || "<small>暂无样例</small>"}</div>
    `;
    related.appendChild(node);
  });
  related.querySelectorAll("[data-object-type]").forEach((button) => {
    button.addEventListener("click", () => selectObject(button.dataset.objectType, button.dataset.objectId));
  });

  const capabilities = document.querySelector("#capabilityEntries");
  capabilities.innerHTML = "";
  context.capabilities.slice(0, 12).forEach((item) => {
    const button = document.createElement("button");
    button.className = `capability ${item.runnable ? "runnable" : ""}`;
    button.innerHTML = `
      <span>${escapeHtml(item.group)}</span>
      <strong>${escapeHtml(item.summary)}</strong>
      <p>${escapeHtml(item.description)}</p>
    `;
    button.addEventListener("click", () => runCapability(item));
    capabilities.appendChild(button);
  });
}

function renderObjectDetail(detail, context) {
  const target = document.querySelector("#objectDetail");
  target.innerHTML = "";
  if (detail.type === "payroll_run") {
    renderPayrollRun(target, detail.data);
    return;
  }
  if (detail.type === "employee") {
    renderEmployee(target, detail.data);
    return;
  }
  if (detail.type === "employee_collection") {
    renderEmployeeCollection(target, detail);
    return;
  }
  renderTableDetail(target, detail, context.current);
}

function renderPayrollRun(target, data) {
  target.innerHTML = `
    <div class="metrics">
      <div><span>计算人数</span><strong>${escapeHtml(data.counts.calculated)}</strong></div>
      <div><span>扣前应发</span><strong>${money(data.totals.gross)}</strong></div>
      <div><span>个税</span><strong>${money(data.totals.tax)}</strong></div>
      <div class="accent"><span>实发</span><strong>${money(data.totals.net)}</strong></div>
    </div>
    <div class="insight-band">
      <div class="insight-icon">i</div>
      <div>
        <h3>批次智能摘要</h3>
        <p>${escapeHtml(data.agent_brief)}</p>
      </div>
    </div>
    <div class="inline-actions">
      <button data-action="review_diffs">复核剩余差异</button>
      <button data-action="confirm_deductions">确认扣款台账</button>
      <button data-action="approval_summary">生成审批摘要</button>
    </div>
  `;
  target.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => runAction(button.dataset.action));
  });
}

function renderEmployee(target, data) {
  const line = data.line || {};
  target.innerHTML = `
    <div class="employee-layout">
      <section>
        <div class="section-head compact">
          <div>
            <h3>${escapeHtml(line.employee_id || state.selectedEmployee)} · ${escapeHtml(line.employee_name_snapshot || "")}</h3>
            <p>${escapeHtml(line.payroll_company_name_snapshot || "")} · ${escapeHtml(line.position || "")}</p>
          </div>
          <button id="agentExplainEmployee" class="primary-button">生成薪资说明</button>
        </div>
        <div class="metrics compact-metrics">
          <div><span>应发</span><strong>${money(line.gross_pay_before_deduction)}</strong></div>
          <div><span>社保</span><strong>${money(line.personal_social_security)}</strong></div>
          <div><span>公积金</span><strong>${money(line.personal_housing_fund)}</strong></div>
          <div><span>个税</span><strong>${money(line.personal_income_tax)}</strong></div>
          <div class="accent"><span>实发</span><strong>${money(line.net_pay)}</strong></div>
        </div>
        <div class="inline-actions">
          <button data-action="review_diffs">复核该员工差异</button>
          <button data-action="confirm_deductions">确认该员工扣款</button>
          <button data-action="approval_summary">生成该员工审批说明</button>
        </div>
      </section>
      <section class="warning-list">
        ${data.warnings.map((warning) => `
          <div class="warning"><strong>${escapeHtml(warning.rule_code)}</strong><p>${escapeHtml(warning.message)}</p></div>
        `).join("")}
      </section>
    </div>
  `;
  target.querySelector("#agentExplainEmployee").addEventListener("click", explainEmployeePayroll);
  target.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => runAction(button.dataset.action, state.selectedEmployee));
  });
}

function renderEmployeeCollection(target, detail) {
  const rows = detail.rows || [];
  target.innerHTML = `
    <div class="collection-head">
      <div>
        <h3>员工主数据</h3>
        <p>共 ${escapeHtml(detail.total)} 名员工。这里是集合入口，选择员工后才进入单人薪资上下文。</p>
      </div>
    </div>
    <div class="employee-grid">
      ${rows.map((employee) => `
        <button class="employee-card" data-employee-id="${escapeHtml(employee.employee_id)}">
          <strong>${escapeHtml(employee.employee_id)} · ${escapeHtml(employee.name)}</strong>
          <span>${escapeHtml(employee.company)}</span>
          <em>${escapeHtml(employee.position || "员工")} · 月薪 ${money(employee.monthly_salary_total)}</em>
        </button>
      `).join("")}
    </div>
  `;
  target.querySelectorAll("[data-employee-id]").forEach((button) => {
    button.addEventListener("click", () => selectObject("Employee", button.dataset.employeeId));
  });
}

function renderTableDetail(target, detail, current) {
  const rows = detail.rows || [];
  const fields = detail.fields || [];
  if (!rows.length) {
    target.innerHTML = `
      <div class="empty-state">
        <strong>${escapeHtml(current.summary)}</strong>
        <p>当前没有可展示记录，但本体仍会提供相关对象和能力入口。</p>
      </div>
    `;
    return;
  }
  target.innerHTML = `
    <table class="data-table">
      <thead><tr>${fields.map((field) => `<th>${escapeHtml(field)}</th>`).join("")}</tr></thead>
      <tbody>
        ${rows.map((row) => `
          <tr>${fields.map((field) => `<td>${escapeHtml(row[field])}</td>`).join("")}</tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

async function runCapability(item) {
  const target = document.querySelector("#actionResult");
  if (!item.runnable) {
    target.innerHTML = renderMarkdown(`### ${item.summary}\n\n该能力来自本体函数 \`${item.name}\`。当前原型只展示入口，真实系统可在这里进入业务表单、审批流或工具执行。\n\n涉及对象：${(item.writes_to || []).join(", ") || "只读查询"}`);
    return;
  }
  if (item.action) {
    await runAction(item.action, state.objectType === "Employee" ? state.objectId : "");
    return;
  }
  target.innerHTML = renderMarkdown(`### ${item.summary}\n\n运行时已识别当前上下文参数：\`${JSON.stringify(item.params)}\``);
}

async function runAction(action, employeeId = "") {
  const target = document.querySelector("#actionResult");
  target.textContent = "正在执行业务动作...";
  const data = await getJson(
    `/api/action?action=${encodeURIComponent(action)}&employee_id=${encodeURIComponent(employeeId || "")}`,
  );
  target.innerHTML = `<h4>${escapeHtml(data.title)}</h4>${renderMarkdown(data.markdown)}`;
  document.querySelector("#explanation").innerHTML = renderMarkdown(data.markdown);
  if (data.focus_employee_id) {
    await selectObject("Employee", data.focus_employee_id);
  }
}

function explainContext() {
  const box = document.querySelector("#explanation");
  box.innerHTML = renderMarkdown(buildContextExplanation(state.context));
}

async function explainEmployeePayroll() {
  const box = document.querySelector("#explanation");
  if (state.objectType !== "Employee" || !state.objectId) {
    explainContext();
    return;
  }
  box.textContent = "Agent 正在读取本体和工具结果生成说明...";
  const data = await getJson(`/api/agent/explain?employee_id=${encodeURIComponent(state.objectId)}`);
  box.innerHTML = renderMarkdown(data.text);
}

function buildContextExplanation(context) {
  if (!context) return "当前业务对象正在加载。";
  const current = context.current || {};
  const related = (context.related || []).filter((item) => item.count > 0).slice(0, 4);
  const capabilities = (context.capabilities || []).slice(0, 4);
  const relatedLines = related.length
    ? related.map((item) => `- ${item.target_summary}：${item.count} 条，${item.description}`).join("\n")
    : "- 当前对象暂时没有已落表的直接关联记录，但本体关系仍可作为进入业务流程的导航。";
  const capabilityLines = capabilities.length
    ? capabilities.map((item) => `- ${item.summary}：${item.group}`).join("\n")
    : "- 当前对象暂无可展示能力入口。";
  return [
    `### ${current.display || current.summary || "当前对象"} 业务说明`,
    "",
    current.description || context.narrative || "",
    "",
    "**相关业务入口**",
    relatedLines,
    "",
    "**当前可用能力**",
    capabilityLines,
  ].join("\n");
}

function renderMarkdown(text) {
  const source = String(text || "");
  const lines = source.split(/\r?\n/);
  let html = "";
  let inTable = false;
  let inUnorderedList = false;
  let inOrderedList = false;
  let tableRowIndex = 0;

  const closeBlocks = () => {
    if (inTable) {
      html += "</tbody></table>";
      inTable = false;
      tableRowIndex = 0;
    }
    if (inUnorderedList) {
      html += "</ul>";
      inUnorderedList = false;
    }
    if (inOrderedList) {
      html += "</ol>";
      inOrderedList = false;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeBlocks();
      continue;
    }
    if (line.startsWith("|") && line.endsWith("|")) {
      const cells = line.split("|").slice(1, -1).map((cell) => cell.trim());
      if (cells.every((cell) => /^:?-{3,}:?$/.test(cell))) continue;
      if (!inTable) {
        closeBlocks();
        html += "<table><tbody>";
        inTable = true;
      }
      const tag = tableRowIndex === 0 ? "th" : "td";
      html += `<tr>${cells.map((cell) => `<${tag}>${inlineMarkdown(cell)}</${tag}>`).join("")}</tr>`;
      tableRowIndex += 1;
      continue;
    }
    if (line.startsWith("- ")) {
      if (!inUnorderedList) {
        closeBlocks();
        html += "<ul>";
        inUnorderedList = true;
      }
      html += `<li>${inlineMarkdown(line.slice(2))}</li>`;
      continue;
    }
    const orderedMatch = line.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      if (!inOrderedList) {
        closeBlocks();
        html += "<ol>";
        inOrderedList = true;
      }
      html += `<li>${inlineMarkdown(orderedMatch[1])}</li>`;
      continue;
    }
    closeBlocks();
    if (line.startsWith("### ")) {
      html += `<h4>${inlineMarkdown(line.slice(4))}</h4>`;
    } else {
      html += `<p>${inlineMarkdown(line)}</p>`;
    }
  }
  closeBlocks();
  return html;
}

function inlineMarkdown(text) {
  return escapeHtml(text).replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
}

function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

document.querySelector("#refreshBtn").addEventListener("click", loadDomain);
document.querySelector("#explainBtn").addEventListener("click", explainContext);

loadDomain();
