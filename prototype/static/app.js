const state = {
  atlas: [],
  context: null,
  selectedType: "PayrollRun",
  selectedId: "PAYROLL_202604",
  watchedTasks: new Set(),
  typedTextByTask: new Map(),
  typewriterTargets: new Map(),
  typewriterTimers: new Map(),
};

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function init() {
  const data = await getJson("/api/shell");
  state.atlas = data.atlas || [];
  state.context = data.context;
  state.selectedType = data.context.resource.type;
  state.selectedId = data.context.id;
  renderAtlas();
  renderContext(data.context);
}

function renderAtlas() {
  const root = document.querySelector("#atlas");
  root.innerHTML = state.atlas.map((group) => `
    <section class="atlas-group">
      <h2>${escapeHtml(group.name)}</h2>
      <div class="resource-list">
        ${(group.resources || []).map((resource) => resourceButton(resource)).join("")}
      </div>
    </section>
  `).join("");
  root.querySelectorAll("[data-resource-type]").forEach((button) => {
    button.addEventListener("click", () => openResource(button.dataset.resourceType, button.dataset.resourceId || ""));
  });
}

function resourceButton(resource) {
  const active = resource.type === state.selectedType ? " active" : "";
  return `
    <button class="resource-button${active}" data-resource-type="${escapeHtml(resource.type)}" data-resource-id="${escapeHtml(resource.sample_id || "")}">
      <span>${escapeHtml(resource.name)}</span>
      <strong>${formatCount(resource.count)}</strong>
    </button>
  `;
}

async function openResource(type, id) {
  state.selectedType = type;
  state.selectedId = id || "";
  renderAtlas();
  setLoading("正在切换资源...");
  const params = new URLSearchParams({ type, id: id || "" });
  const context = await getJson(`/api/context?${params.toString()}`);
  state.context = context;
  state.selectedId = context.id;
  renderContext(context);
  renderAtlas();
}

function renderContext(context) {
  document.querySelector("#contextKind").textContent = `${context.resource.name} / ${context.resource.source} / ${context.resource.mutability}`;
  document.querySelector("#contextTitle").textContent = context.resource.name;
  document.querySelector("#contextSubtitle").textContent = context.resource.description || context.subtitle || "";
  renderMetrics(context.metrics || []);
  renderResourceTable(context);
  renderDetail(context);
  renderConversation(context.conversation || {});
  watchConversationTask(context.conversation || {});
}

function renderMetrics(metrics) {
  document.querySelector("#contextMetrics").innerHTML = metrics.map((item) => `
    <div class="summary-item ${escapeHtml(item.tone || "normal")}">
      <span>${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
    </div>
  `).join("");
}

function renderResourceTable(context) {
  const browser = context.browser || { columns: [], rows: [] };
  document.querySelector("#listTitle").textContent = context.resource.name;
  document.querySelector("#listMeta").textContent = `共 ${formatCount(browser.total || 0)} 条记录`;
  const columns = browser.columns || [];
  const rows = browser.rows || [];
  document.querySelector("#resourceTable").innerHTML = `
    <div class="table-head" style="--cols:${columns.length || 1}">
      ${columns.map((column) => `<span>${escapeHtml(column.label)}</span>`).join("")}
    </div>
    <div class="table-body">
      ${rows.map((row) => `
        <button class="table-row ${row.selected ? "selected" : ""}" style="--cols:${columns.length || 1}" data-resource-type="${escapeHtml(context.resource.type)}" data-resource-id="${escapeHtml(row.id)}">
          ${(row.cells || []).map((cell) => `<span>${escapeHtml(cell.value || "-")}</span>`).join("")}
        </button>
      `).join("")}
    </div>
  `;
  document.querySelectorAll("#resourceTable [data-resource-type]").forEach((button) => {
    button.addEventListener("click", () => openResource(button.dataset.resourceType, button.dataset.resourceId || ""));
  });
}

function renderDetail(context) {
  const detail = context.detail || { facts: [], related: [], actions: [] };
  document.querySelector("#detailTitle").textContent = context.title;
  document.querySelector("#detailMeta").textContent = context.subtitle || "";
  document.querySelector("#detailView").innerHTML = `
    <section class="detail-section primary-section">
      <div class="section-title">
        <h3>字段详情</h3>
        <span>${escapeHtml(context.resource.id_label)}：${escapeHtml(context.id || "-")}</span>
      </div>
      <div class="fact-groups">
        ${(detail.facts || []).map(renderFactGroup).join("") || emptyBlock("当前记录暂无可展示字段")}
      </div>
    </section>

    <section class="detail-section">
      <div class="section-title">
        <h3>相关资源</h3>
        <span>由当前记录自动带出</span>
      </div>
      <div class="related-grid">
        ${(detail.related || []).map(renderRelatedGroup).join("") || emptyBlock("当前资源暂无相关记录")}
      </div>
    </section>
  `;
  document.querySelectorAll("#detailView [data-resource-type]").forEach((button) => {
    button.addEventListener("click", () => openResource(button.dataset.resourceType, button.dataset.resourceId || ""));
  });
}

function renderFactGroup(group) {
  return `
    <div class="fact-group">
      <h4>${escapeHtml(group.title)}</h4>
      <dl>
        ${(group.rows || []).map((row) => `<div><dt>${escapeHtml(row.label)}</dt><dd>${escapeHtml(row.value)}</dd></div>`).join("")}
      </dl>
    </div>
  `;
}

function renderRelatedGroup(group) {
  return `
    <article class="related-card">
      <div class="related-head">
        <strong>${escapeHtml(group.title)}</strong>
        <span>${formatCount(group.count)} 条</span>
      </div>
      <p>${escapeHtml(group.description || "")}</p>
      <div class="related-rows">
        ${(group.rows || []).map((row) => `
          <button data-resource-type="${escapeHtml(group.type)}" data-resource-id="${escapeHtml(row.id || "")}" ${row.id ? "" : "disabled"}>
            <strong>${escapeHtml(row.title || row.id || "-")}</strong>
            <span>${escapeHtml(row.description || "")}</span>
          </button>
        `).join("") || `<span class="empty-inline">暂无样本记录</span>`}
      </div>
    </article>
  `;
}

function renderSurfaceSection(section) {
  if (section.kind === "metrics") {
    return `
      <section class="detail-section soft-section">
        <div class="section-title"><h3>${escapeHtml(section.title)}</h3></div>
        <div class="mini-metrics">
          ${(section.rows || []).map((row) => `<div><span>${escapeHtml(row.label)}</span><strong>${escapeHtml(row.value)}</strong></div>`).join("")}
        </div>
      </section>
    `;
  }
  if (section.kind === "facts") {
    return `
      <section class="detail-section soft-section">
        <div class="section-title"><h3>${escapeHtml(section.title)}</h3></div>
        <div class="fact-group flat"><dl>
          ${(section.rows || []).map((row) => `<div><dt>${escapeHtml(row.label)}</dt><dd>${escapeHtml(row.value)}</dd></div>`).join("")}
        </dl></div>
      </section>
    `;
  }
  return `
    <section class="detail-section soft-section">
      <div class="section-title"><h3>${escapeHtml(section.title)}</h3></div>
      <div class="issue-list">
        ${(section.rows || []).map((row) => `
          <div class="issue-row">
            <strong>${escapeHtml(row.title || row.message || JSON.stringify(row))}</strong>
            <span>${escapeHtml(row.meta || row.employee_id || row.rule_code || "")}</span>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderConversation(conversation) {
  document.querySelector("#railTitle").textContent = conversation.title || "当前可以这样推进";
  document.querySelector("#railJudgment").textContent = conversation.judgment || "";
  const pending = conversation.llm_status === "pending";
  document.querySelector(".guidance-head span").textContent = conversation.mode === "llm" ? "智能引导" : (pending ? "业务引导 · 智能生成中" : "业务引导");
  document.querySelector("#railPrompts").innerHTML = (conversation.prompts || []).map((prompt) => `
    <button class="prompt-button" data-prompt="${escapeHtml(prompt.text || prompt.label)}">
      <strong>${escapeHtml(prompt.label)}</strong>
      <span>${escapeHtml(prompt.text || "")}</span>
    </button>
  `).join("");
  document.querySelector("#railActions").innerHTML = (conversation.actions || []).map((action) => `
    <button class="action-button" data-function="${escapeHtml(action.function || "")}">
      <strong>${escapeHtml(action.label)}</strong>
      <span>${escapeHtml(action.description || action.mode || "")}</span>
    </button>
  `).join("") || `<div class="empty-note">当前更适合先查看资源详情。</div>`;
  document.querySelector("#railEvidence").innerHTML = (conversation.evidence || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("");
  document.querySelectorAll("#railActions [data-function]").forEach((button) => {
    button.addEventListener("click", () => executeCapability(button.dataset.function));
  });
  document.querySelectorAll("#railPrompts [data-prompt]").forEach((button) => {
    button.addEventListener("click", () => showPromptResponse(button.dataset.prompt));
  });
}

function showPromptResponse(text) {
  const context = state.context;
  const evidence = (context.conversation.evidence || []).join("、");
  showRailResult({
    title: "建议查看",
    summary: text,
    sections: evidence ? [{ title: "依据", kind: "list", rows: [{ title: evidence, meta: "" }] }] : [],
  });
}

async function executeCapability(functionName) {
  if (!functionName) return;
  setRailBusy(functionName);
  const params = new URLSearchParams({
    function: functionName,
    type: state.selectedType,
    id: state.selectedId || "",
  });
  const data = await getJson(`/api/execute?${params.toString()}`);
  renderExecutionResult(data);
}

function renderExecutionResult(data) {
  const result = data.result || {};
  const functionLabel = (data.function || {}).label || data.function || "业务操作";
  showRailResult({
    title: `${functionLabel}结果`,
    summary: result.summary || data.message || "执行完成",
    explanation: result.llm_explanation || "",
    mode: result.mode || "rules",
    llmTask: result.llm_task || "",
    highlights: result.highlights || [],
    sections: result.sections || [],
  });
  watchResultTask(result.llm_task || "");
  renderConversation(data.conversation || state.context.conversation || {});
  watchConversationTask(data.conversation || state.context.conversation || {});
}

function showRailResult(result) {
  const section = document.querySelector("#railResultSection");
  const root = document.querySelector("#railResult");
  section.classList.remove("hidden");
  root.innerHTML = `
    <article class="result-card">
      <h3>${escapeHtml(result.title || "预览结果")}</h3>
      <p>${escapeHtml(result.summary || "")}</p>
      ${result.llmTask && !result.explanation ? `<div class="result-explanation pending"><span>智能解释生成中</span><p>▍</p></div>` : ""}
      ${result.explanation ? `<div class="result-explanation"><span>${result.mode === "llm" ? "智能解释" : "结果说明"}</span><p>${escapeHtml(result.explanation)}</p></div>` : ""}
      ${result.highlights && result.highlights.length ? `
        <div class="result-highlights">
          ${result.highlights.slice(0, 6).map((item) => `<div><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong></div>`).join("")}
        </div>
      ` : ""}
      ${(result.sections || []).slice(0, 4).map(renderRailResultSection).join("")}
    </article>
  `;
}

async function watchConversationTask(conversation) {
  const taskId = conversation.llm_task || "";
  if (!taskId) return;
  if (state.watchedTasks.has(taskId)) return;
  state.watchedTasks.add(taskId);
  const result = await pollTask(taskId);
  if (result && result.kind === "conversation" && result.result) {
    renderConversation(result.result);
  }
}

async function watchResultTask(taskId) {
  if (!taskId) return;
  if (state.watchedTasks.has(taskId)) return;
  state.watchedTasks.add(taskId);
  state.typedTextByTask.set(taskId, "");
  state.typewriterTargets.delete(taskId);
  for (let i = 0; i < 60; i += 1) {
    await delay(i < 4 ? 250 : 500);
    const data = await getJson(`/api/llm/task?id=${encodeURIComponent(taskId)}`);
    if (data.kind !== "result") continue;
    if (data.partial) {
      typeResultText(taskId, data.partial, data.status === "done");
    }
    if (data.status === "done" || data.status === "error" || data.status === "missing") {
      if (data.result && data.result.text) typeResultText(taskId, data.result.text, true);
      return;
    }
  }
}

function typeResultText(taskId, text, done) {
  const card = document.querySelector("#railResult .result-card");
  if (!card) return;
  let box = card.querySelector(".result-explanation");
  if (!box) {
    box = document.createElement("div");
    box.className = "result-explanation";
    box.innerHTML = `<span>智能解释</span><p></p>`;
    const firstParagraph = card.querySelector("p");
    firstParagraph.insertAdjacentElement("afterend", box);
  }
  box.classList.remove("pending");
  const label = box.querySelector("span");
  label.textContent = done ? "智能解释" : "智能解释生成中";
  state.typewriterTargets.set(taskId, { text, done });
  if (!state.typewriterTimers.has(taskId)) {
    state.typewriterTimers.set(taskId, setInterval(() => tickTypewriter(taskId), 55));
  }
}

function tickTypewriter(taskId) {
  const target = state.typewriterTargets.get(taskId);
  if (!target) return stopTypewriter(taskId);
  const box = document.querySelector("#railResult .result-explanation");
  if (!box) return stopTypewriter(taskId);
  const paragraph = box.querySelector("p");
  const current = state.typedTextByTask.get(taskId) || "";
  if (current.length < target.text.length) {
    const next = target.text.slice(0, current.length + 1);
    state.typedTextByTask.set(taskId, next);
    paragraph.textContent = next + "▍";
    return;
  }
  paragraph.textContent = current + (target.done ? "" : "▍");
  if (target.done) stopTypewriter(taskId);
}

function stopTypewriter(taskId) {
  const timer = state.typewriterTimers.get(taskId);
  if (timer) clearInterval(timer);
  state.typewriterTimers.delete(taskId);
}

async function pollTask(taskId) {
  for (let i = 0; i < 20; i += 1) {
    await delay(i < 3 ? 500 : 1000);
    const data = await getJson(`/api/llm/task?id=${encodeURIComponent(taskId)}`);
    if (data.status === "done" || data.status === "error" || data.status === "missing") {
      return data;
    }
  }
  return null;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function renderRailResultSection(section) {
  const rows = normalizeSectionRows(section).slice(0, 5);
  if (section.kind === "facts" || section.kind === "metrics") {
    return `
      <div class="result-subsection">
        <h4>${escapeHtml(section.title)}</h4>
        <div class="result-facts">
          ${rows.map((row) => `<div><span>${escapeHtml(row.label)}</span><strong>${escapeHtml(row.value)}</strong></div>`).join("")}
        </div>
      </div>
    `;
  }
  return `
    <div class="result-subsection">
      <h4>${escapeHtml(section.title)}</h4>
      <div class="result-list">
        ${rows.map((row) => `<div><strong>${escapeHtml(row.title || summarizeRow(row))}</strong><span>${escapeHtml(row.meta || "")}</span></div>`).join("")}
      </div>
    </div>
  `;
}

function normalizeSectionRows(section) {
  const rows = section.rows || [];
  if (section.kind === "facts" || section.kind === "metrics") return rows;
  return rows.map((row) => ({
    title: row.title || summarizeRow(row),
    meta: row.meta || row.employee_id || row.rule_code || row.status || "",
  }));
}

function summarizeRow(row) {
  if (!row || typeof row !== "object") return String(row || "");
  if (row.message) return row.message;
  if (row.employee_name) return `${row.employee_name}：实发 ${row.net_pay || ""}`;
  if (row.employee_id && row.net_pay !== undefined) return `${row.employee_id}：实发 ${row.net_pay}`;
  if (row.field) return `${row.field}：当前 ${row.calculated} / 基准 ${row.expected}`;
  return JSON.stringify(row).slice(0, 160);
}

function emptyBlock(text) {
  return `<div class="empty-note">${escapeHtml(text)}</div>`;
}

function setLoading(text) {
  document.querySelector("#contextKind").textContent = text;
}

function setRailBusy(functionName) {
  document.querySelector("#railTitle").textContent = "正在执行预览";
  document.querySelector("#railJudgment").textContent = `正在调用：${functionName}`;
}

function formatCount(value) {
  const num = Number(value || 0);
  return Number.isFinite(num) ? num.toLocaleString("zh-CN") : String(value || 0);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

init().catch((error) => {
  document.body.innerHTML = `<main class="fatal"><h1>原型启动失败</h1><p>${escapeHtml(error.message)}</p></main>`;
});
