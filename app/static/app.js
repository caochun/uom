const state = {
  data: null,
  view: "objects",
  objectFilter: "all",
  relationFilter: "all",
  modelKind: "object",
  search: "",
  selected: null,
  pendingOperations: [],
  preview: null,
  sessionId: `oms-${crypto.randomUUID()}`,
  agentBusy: false,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const icons = () => window.lucide?.createIcons({ attrs: { "aria-hidden": "true" } });

const typeNames = () => state.data?.model?.object_types || {};
const relationNames = () => state.data?.model?.relation_types || {};
const propertyDefinitions = () => state.data?.model?.property_definitions || {};
const objectIndex = () => Object.fromEntries((state.data?.objects || []).map((item) => [item.id, item]));
const relationCount = (id) => (state.data?.relations || []).filter((rel) => rel.from === id || rel.to === id).length;
const propertyTypeOptions = [
  ["string", "文本"], ["number", "数值"], ["money", "金额"], ["date", "日期"],
  ["period", "期间"], ["boolean", "是 / 否"], ["json", "JSON"],
];

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  icons();
  await Promise.all([loadData(), loadAgentStatus()]);
});

function bindEvents() {
  $$(".nav-item[data-view]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  $$('[data-open-form]').forEach((button) => button.addEventListener("click", () => openEditor(button.dataset.openForm)));
  $("#objectFilters").addEventListener("click", segmentedHandler("objectFilter", renderObjects));
  $("#relationFilters").addEventListener("click", segmentedHandler("relationFilter", renderRelations));
  $("#modelKindTabs").addEventListener("click", segmentedHandler("modelKind", renderModel, "kind"));
  $("#globalSearch").addEventListener("input", (event) => { state.search = event.target.value.trim().toLowerCase(); renderCurrentView(); });
  $("#refreshBtn").addEventListener("click", loadData);
  $("#agentToggle").addEventListener("click", openAgent);
  $("#closeAgentBtn").addEventListener("click", closeAgent);
  $("#scrim").addEventListener("click", closeOverlays);
  $$('[data-close-drawer]').forEach((button) => button.addEventListener("click", closeDetail));
  $$('[data-close-changes]').forEach((button) => button.addEventListener("click", () => $("#changeDialog").close()));
  $("#editorForm").addEventListener("submit", submitEditor);
  $("#editorDialog").addEventListener("click", handleEditorClick);
  $("#editorDialog").addEventListener("input", handleEditorInput);
  $("#applyChangesBtn").addEventListener("click", applyPendingChanges);
  $("#openChangesBtn").addEventListener("click", () => state.pendingOperations.length ? previewOperations(state.pendingOperations) : toast("当前没有待应用的变更"));
  $("#askAboutBtn").addEventListener("click", askAboutSelection);
  $("#clearContextBtn").addEventListener("click", clearAgentContext);
  $("#agentForm").addEventListener("submit", sendAgentMessage);
  $("#agentInput").addEventListener("input", autoGrowTextarea);
  $("#agentInput").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("#agentForm").requestSubmit(); } });
  $("#agentMessages").addEventListener("click", handleAgentClick);
  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) { event.preventDefault(); $("#globalSearch").focus(); }
    if (event.key === "Escape") closeOverlays();
  });
}

function segmentedHandler(stateKey, render, dataKey = "filter") {
  return (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    $$("button", event.currentTarget).forEach((item) => item.classList.toggle("active", item === button));
    state[stateKey] = button.dataset[dataKey];
    render();
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error((payload.errors || [payload.error || response.statusText]).join("\n"));
  return payload;
}

async function loadData() {
  try {
    state.data = await api("/api/bootstrap");
    renderShell();
    toast("数据已刷新");
  } catch (error) {
    toast(error.message, true);
  }
}

function renderShell() {
  const { stats, model } = state.data;
  $("#objectNavCount").textContent = stats.object_count;
  $("#relationNavCount").textContent = stats.relation_count;
  $("#modelNavCount").textContent = Object.keys(model.object_types || {}).length + Object.keys(model.relation_types || {}).length;
  $("#sidebarModelName").textContent = model.model.name;
  $("#sidebarModelVersion").textContent = `v${model.model.version}`;
  $("#modelVersion").textContent = `v${model.model.version}`;
  renderMetrics();
  renderObjects();
  renderRelations();
  renderModel();
  icons();
}

function renderMetrics() {
  const objects = state.data.objects;
  const relations = state.data.relations;
  const revenue = sumObjectMoney(objects.filter((item) => item.type === "revenue"));
  const attributed = relations.filter((item) => item.type === "cost_attribution" && item.properties?.status === "confirmed").reduce((sum, item) => sum + Number(item.properties?.amount?.amount || 0), 0);
  const disposed = relations.filter((item) => ["cost_attribution", "enterprise_absorption"].includes(item.type) && item.properties?.status === "confirmed").reduce((map, item) => map.set(item.from, (map.get(item.from) || 0) + Number(item.properties?.amount?.amount || 0)), new Map());
  const pending = objects.filter((item) => item.type === "cost").reduce((sum, item) => sum + Math.max(0, Number(item.properties?.amount?.amount || 0) - (disposed.get(item.id) || 0)), 0);
  const currency = revenue.currency || "CNY";
  $("#metricRevenue").textContent = money(revenue.amount, currency);
  $("#metricCost").textContent = money(attributed, currency);
  $("#metricContribution").textContent = money(revenue.amount - attributed, currency);
  $("#metricPending").textContent = money(pending, currency);
  const pendingCount = objects.filter((item) => item.type === "cost" && Number(item.properties?.amount?.amount || 0) > (disposed.get(item.id) || 0)).length;
  $("#metricPendingHint").textContent = `${pendingCount} 项需要经营判断`;
  $("#initialAgentMessage").textContent = `当前确认收入 ${money(revenue.amount, currency)}，已归因成本 ${money(attributed, currency)}，收入贡献 ${money(revenue.amount - attributed, currency)}。仍有 ${money(pending, currency)} 成本等待经营判断。`;
}

function sumObjectMoney(items) {
  return items.reduce((result, item) => {
    result.amount += Number(item.properties?.amount?.amount || 0);
    result.currency ||= item.properties?.amount?.currency;
    return result;
  }, { amount: 0, currency: null });
}

function switchView(view) {
  state.view = view;
  $$(".nav-item[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$(".view").forEach((section) => section.classList.toggle("active", section.id === `${view}View`));
  renderCurrentView();
}

function renderCurrentView() {
  ({ objects: renderObjects, relations: renderRelations, model: renderModel }[state.view] || renderObjects)();
}

function matchesSearch(item) {
  if (!state.search) return true;
  return JSON.stringify(item).toLowerCase().includes(state.search);
}

function renderObjects() {
  if (!state.data) return;
  const groups = {
    all: () => true,
    revenue: (item) => ["revenue", "receivable", "cash_receipt"].includes(item.type),
    cost: (item) => ["cost", "payable", "cash_payment", "purchase_order", "asset"].includes(item.type),
    cash: (item) => ["cash_receipt", "cash_payment", "receivable", "payable"].includes(item.type),
    context: (item) => !["revenue", "receivable", "cash_receipt", "cost", "payable", "cash_payment"].includes(item.type),
  };
  const items = state.data.objects.filter(groups[state.objectFilter] || groups.all).filter(matchesSearch);
  $("#objectResultCount").textContent = `${items.length} 项`;
  $("#objectsEmpty").classList.toggle("hidden", items.length > 0);
  $("#objectsTable").innerHTML = items.map((item) => {
    const props = item.properties || {};
    const amount = props.amount ? money(props.amount.amount, props.amount.currency) : "-";
    const period = props.period || props.occurred_on || props.details?.due_date || "-";
    const label = typeNames()[item.type]?.name || item.type;
    return `<tr data-object-id="${escapeAttr(item.id)}">
      <td><div class="object-cell"><div class="type-icon ${escapeAttr(item.type)}"><i data-lucide="${typeIcon(item.type)}"></i></div><div class="object-main"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.id)}</span></div></div></td>
      <td><span class="type-code" title="${escapeAttr(item.type)}">${escapeHtml(label)}</span></td>
      <td class="money">${escapeHtml(amount)}</td><td>${escapeHtml(period)}</td>
      <td>${statusPill(props.status)}</td><td>${relationCount(item.id)}</td>
      <td><button class="row-more" aria-label="查看详情"><i data-lucide="chevron-right"></i></button></td>
    </tr>`;
  }).join("");
  $$("#objectsTable tr").forEach((row) => row.addEventListener("click", () => showDetail("object", row.dataset.objectId)));
  icons();
}

function renderRelations() {
  if (!state.data) return;
  const economic = ["cost_attribution", "enterprise_absorption", "settles_receivable", "settles_payable"];
  const trace = ["derived_from"];
  const groups = { all: () => true, economic: (item) => economic.includes(item.type), trace: (item) => trace.includes(item.type), context: (item) => !economic.includes(item.type) && !trace.includes(item.type) };
  const items = state.data.relations.filter(groups[state.relationFilter] || groups.all).filter(matchesSearch);
  const index = objectIndex();
  $("#relationResultCount").textContent = `${items.length} 项`;
  $("#relationsEmpty").classList.toggle("hidden", items.length > 0);
  $("#relationsTable").innerHTML = items.map((item) => {
    const source = index[item.from] || { id: item.from, name: "未知对象", type: "unknown" };
    const target = index[item.to] || { id: item.to, name: "未知对象", type: "unknown" };
    const definition = relationNames()[item.type];
    const props = item.properties || {};
    const fact = props.amount ? money(props.amount.amount, props.amount.currency) : (props.status || "-");
    return `<tr data-relation-id="${escapeAttr(item.id)}">
      <td><div class="object-main"><strong>${escapeHtml(definition?.name || item.type)}</strong><span>${escapeHtml(item.type)}</span></div></td>
      <td>${endpoint(source)}</td><td class="direction-arrow"><i data-lucide="arrow-right"></i></td><td>${endpoint(target)}</td>
      <td>${escapeHtml(fact)}</td><td><button class="row-more" aria-label="查看详情"><i data-lucide="chevron-right"></i></button></td>
    </tr>`;
  }).join("");
  $$("#relationsTable tr").forEach((row) => row.addEventListener("click", () => showDetail("relation", row.dataset.relationId)));
  const summary = [
    ["circle-dollar-sign", state.data.relations.filter((item) => economic.includes(item.type)).length, "经营核算关系"],
    ["waypoints", state.data.relations.filter((item) => trace.includes(item.type)).length, "来源追溯关系"],
    ["link-2", new Set(state.data.relations.flatMap((item) => [item.from, item.to])).size, "已连接对象"],
  ];
  $("#relationSummary").innerHTML = summary.map(([icon, count, label]) => `<article><div class="summary-icon"><i data-lucide="${icon}"></i></div><div><strong>${count}</strong><span>${label}</span></div></article>`).join("");
  icons();
}

function renderModel() {
  if (!state.data) return;
  const definitions = state.modelKind === "object" ? state.data.model.object_types : state.data.model.relation_types;
  const usage = state.data.model_usage[state.modelKind] || {};
  const entries = Object.entries(definitions || {}).filter(([id, definition]) => matchesSearch({ id, ...definition }));
  $("#typeGrid").innerHTML = entries.map(([id, definition]) => {
    const props = Object.entries(definition.properties || {});
    const endpoints = state.modelKind === "relation" && (definition.from_types?.length || definition.to_types?.length) ? `${(definition.from_types || ["*"]).join(", ")} → ${(definition.to_types || ["*"]).join(", ")}` : "";
    return `<article class="type-card" data-type-id="${escapeAttr(id)}">
      <div class="type-card-header"><div><span class="type-id">${escapeHtml(id)}</span><h3>${escapeHtml(definition.name)}</h3></div><span class="usage-badge">${usage[id]?.count || 0} 条数据</span></div>
      <p>${escapeHtml(definition.description)}</p>
      ${endpoints ? `<div class="property-list endpoint-types"><span>${escapeHtml(endpoints)}</span></div>` : ""}
      <div class="property-list">${props.slice(0, 5).map(([id, usage]) => `<span>${escapeHtml(id)}${usage?.required ? " *" : ""}</span>`).join("")}</div>
    </article>`;
  }).join("");
  $$(".type-card").forEach((card) => card.addEventListener("click", () => showDetail("model", card.dataset.typeId)));
}

function showDetail(kind, id) {
  let item;
  if (kind === "object") item = state.data.objects.find((entry) => entry.id === id);
  if (kind === "relation") item = state.data.relations.find((entry) => entry.id === id);
  if (kind === "model") item = (state.modelKind === "object" ? state.data.model.object_types : state.data.model.relation_types)[id];
  if (!item) return;
  state.selected = { kind, id, item };
  const title = item.name || item.id || id;
  $("#detailEyebrow").textContent = kind === "model" ? `${state.modelKind === "object" ? "对象" : "关系"}类型` : `${kind === "object" ? "对象" : "关系"}详情`;
  $("#detailTitle").textContent = title;
  $("#detailBody").innerHTML = detailMarkup(kind, id, item);
  $("#detailDrawer").classList.add("open");
  $("#scrim").classList.remove("hidden");
  updateAgentContext();
  icons();
}

function detailMarkup(kind, id, item) {
  if (kind === "model") {
    return detailSection("类型定义", { type: id, ...item }) + `<div class="detail-section"><h3>设计边界</h3><p class="muted-text">该定义是用户业务词汇，不会增加新的本体概念。Object / Relation 的结构保持不变。</p></div>`;
  }
  const links = state.data.relations.filter((rel) => rel.from === id || rel.to === id);
  const index = objectIndex();
  const linkMarkup = links.length ? links.map((rel) => {
    const outbound = rel.from === id;
    const other = index[outbound ? rel.to : rel.from];
    return `<div class="relation-link"><i data-lucide="${outbound ? "arrow-right" : "arrow-left"}"></i><div><strong>${escapeHtml(relationNames()[rel.type]?.name || rel.type)} · ${escapeHtml(other?.name || (outbound ? rel.to : rel.from))}</strong><span>${escapeHtml(rel.id)}</span></div></div>`;
  }).join("") : `<span class="muted-text">暂无关系</span>`;
  return detailSection("基本信息", Object.fromEntries(Object.entries(item).filter(([key]) => !["properties", "tags", "source_refs"].includes(key))))
    + detailSection("Properties", item.properties || {})
    + (item.tags?.length ? detailSection("Tags", { tags: item.tags }) : "")
    + (item.source_refs?.length ? detailSection("来源引用", { source_refs: item.source_refs }) : "")
    + `<div class="detail-section"><h3>相邻关系 · ${links.length}</h3><div>${linkMarkup}</div></div>`;
}

function detailSection(title, values) {
  const rows = Object.entries(values).map(([key, value]) => `<div class="detail-row"><span>${escapeHtml(key)}</span><code>${escapeHtml(formatValue(value))}</code></div>`).join("");
  return `<div class="detail-section"><h3>${escapeHtml(title)}</h3><div class="detail-list">${rows || '<div class="detail-row"><span>-</span><code>无</code></div>'}</div></div>`;
}

function closeDetail() { $("#detailDrawer").classList.remove("open"); $("#scrim").classList.add("hidden"); }
function closeOverlays() { closeDetail(); closeAgent(); }
function openAgent() { $(".app-shell").classList.remove("agent-collapsed"); $("#agentPanel").classList.add("open"); if (window.innerWidth <= 1180) $("#scrim").classList.remove("hidden"); }
function closeAgent() { $("#agentPanel").classList.remove("open"); if (window.innerWidth > 1180) $(".app-shell").classList.add("agent-collapsed"); if (!$("#detailDrawer").classList.contains("open")) $("#scrim").classList.add("hidden"); }

function openEditor(kind) {
  const definitions = kind === "object" ? objectTypeOptions() : relationTypeOptions();
  $("#formEyebrow").textContent = kind === "model" ? "业务词汇" : "经营数据";
  $("#formTitle").textContent = { object: "新增业务对象", relation: "新增业务关系", model: "扩展用户模型" }[kind];
  $("#editorForm").dataset.kind = kind;
  $("#formError").classList.add("hidden");
  if (kind === "object") $("#formBody").innerHTML = objectForm(definitions);
  if (kind === "relation") $("#formBody").innerHTML = relationForm(definitions);
  if (kind === "model") $("#formBody").innerHTML = modelForm();
  $("#editorDialog").showModal();
  if (kind === "relation") updateRelationEndpoints();
  if (["object", "relation"].includes(kind)) updateInstancePropertyFields();
  if (kind === "model") addModelPropertyRow();
  icons();
}

function objectForm(definitions) {
  return `
    ${field("对象 ID", "id", "text", "例如 revenue:customer-a-2026-08", true)}
    ${selectField("对象类型", "type", Object.entries(definitions).map(([id, def]) => [id, def.name]), true)}
    ${field("名称", "name", "text", "面向业务人员的清晰名称", true, "full")}
    ${instancePropertiesContainer()}
    ${field("Tags", "tags", "text", "多个标签用逗号分隔", false, "full")}
    ${field("其他 Properties", "extra_properties", "textarea", '{\n  "key": "value"\n}', false, "full", "填写 JSON 对象；会与上方属性合并。")}`;
}

function relationForm(definitions) {
  const objectOptions = state.data.objects.map((item) => [item.id, `${item.name} · ${typeNames()[item.type]?.name || item.type}`]);
  return `
    ${field("关系 ID", "id", "text", "例如 rel:cost-revenue-002", true)}
    ${selectField("关系类型", "type", Object.entries(definitions).map(([id, def]) => [id, def.name]), true)}
    ${selectField("From", "from", objectOptions, true, "full")}
    ${selectField("To", "to", objectOptions, true, "full")}
    ${instancePropertiesContainer()}
    ${field("Tags", "tags", "text", "多个标签用逗号分隔", false, "full")}
    ${field("其他 Properties", "extra_properties", "textarea", '{\n  "key": "value"\n}', false, "full", "填写 JSON 对象；会与上方属性合并。")}`;
}

function modelForm() {
  const objectOptions = Object.entries(typeNames()).map(([id, def]) => [id, def.name]);
  return `
    ${selectField("类型种类", "model_kind", [["object", "对象类型"], ["relation", "关系类型"]], true)}
    ${field("Type ID", "type_id", "text", "例如 channel_commission", true)}
    ${field("显示名称", "display_name", "text", "渠道返佣", true, "full")}
    ${field("业务定义", "description", "textarea", "说明它在企业经营中的含义", true, "full")}
    <div class="field model-relation-fields hidden">${selectInner("From 类型", "from_type", [["", "不限"], ...objectOptions], false)}</div>
    <div class="field model-relation-fields hidden">${selectInner("To 类型", "to_type", [["", "不限"], ...objectOptions], false)}</div>
    <div class="field full property-editor">
      <div class="property-editor-header"><div><label>Properties</label><small>选择已有属性，或定义带值类型的新属性。</small></div><button type="button" class="secondary-button compact" data-add-property><i data-lucide="plus"></i>添加属性</button></div>
      <datalist id="propertyDefinitionOptions">${Object.entries(propertyDefinitions()).map(([id, definition]) => `<option value="${escapeAttr(id)}">${escapeHtml(definition.name)} · ${escapeHtml(definition.type)}</option>`).join("")}</datalist>
      <div class="model-property-rows" id="modelPropertyRows"></div>
    </div>`;
}

function instancePropertiesContainer() {
  return `<div class="field full instance-properties"><div class="property-editor-header"><div><label>Properties</label><small>字段由所选业务类型生成。</small></div></div><div class="instance-property-grid" id="instancePropertyFields"></div></div>`;
}

function modelPropertyRow() {
  return `<div class="model-property-row">
    <div class="mini-field property-key"><label>Property ID</label><input name="property_id" list="propertyDefinitionOptions" placeholder="例如 amount" required></div>
    <div class="mini-field"><label>显示名称</label><input name="property_name" placeholder="金额" required></div>
    <div class="mini-field"><label>值类型</label><select name="property_type">${propertyTypeOptions.map(([value, text]) => `<option value="${value}">${text} · ${value}</option>`).join("")}</select></div>
    <label class="required-toggle"><input name="property_required" type="checkbox"><span>必填</span></label>
    <button type="button" class="icon-button remove-property" data-remove-property title="删除属性" aria-label="删除属性"><i data-lucide="trash-2"></i></button>
    <div class="mini-field property-description"><label>属性说明</label><input name="property_description" placeholder="说明属性在经营语境中的含义"></div>
    <small class="property-definition-status">新属性将写入用户模型</small>
  </div>`;
}

function field(label, name, type, placeholder, required = false, className = "", hint = "") { return `<div class="field ${className}">${fieldInner(label, name, type, placeholder, required, hint)}</div>`; }
function fieldInner(label, name, type, placeholder, required = false, hint = "") { const input = type === "textarea" ? `<textarea name="${name}" placeholder="${escapeAttr(placeholder)}" ${required ? "required" : ""}></textarea>` : `<input name="${name}" type="${type}" placeholder="${escapeAttr(placeholder)}" ${required ? "required" : ""}>`; return `<label>${escapeHtml(label)}${required ? " <em>*</em>" : ""}</label>${input}${hint ? `<small>${escapeHtml(hint)}</small>` : ""}`; }
function selectField(label, name, options, required = false, className = "") { return `<div class="field ${className}">${selectInner(label, name, options, required)}</div>`; }
function selectInner(label, name, options, required = false) { return `<label>${escapeHtml(label)}${required ? " <em>*</em>" : ""}</label><select name="${name}" ${required ? "required" : ""}>${options.map(([value, text]) => `<option value="${escapeAttr(value)}">${escapeHtml(text)} · ${escapeHtml(value)}</option>`).join("")}</select>`; }

function handleEditorClick(event) {
  if (event.target.closest("[data-add-property]")) addModelPropertyRow();
  const remove = event.target.closest("[data-remove-property]");
  if (remove) remove.closest(".model-property-row")?.remove();
}

function handleEditorInput(event) {
  if (event.target.name === "property_id") syncModelPropertyRow(event.target.closest(".model-property-row"));
}

function addModelPropertyRow() {
  const rows = $("#modelPropertyRows");
  if (!rows) return;
  rows.insertAdjacentHTML("beforeend", modelPropertyRow());
  icons();
}

function syncModelPropertyRow(row) {
  if (!row) return;
  const id = $('[name="property_id"]', row).value.trim();
  const definition = propertyDefinitions()[id];
  const name = $('[name="property_name"]', row);
  const type = $('[name="property_type"]', row);
  const description = $('[name="property_description"]', row);
  const status = $(".property-definition-status", row);
  const wasExisting = row.dataset.existing === "true";
  if (definition) {
    name.value = definition.name || "";
    type.value = definition.type || "string";
    description.value = definition.description || "";
    name.readOnly = true;
    type.disabled = true;
    description.readOnly = true;
    status.textContent = `已有属性定义 · ${definition.type}`;
    row.dataset.existing = "true";
    return;
  }
  if (wasExisting) {
    name.value = "";
    type.value = "string";
    description.value = "";
  }
  name.readOnly = false;
  type.disabled = false;
  description.readOnly = false;
  status.textContent = "新属性将写入用户模型";
  row.dataset.existing = "false";
}

function updateInstancePropertyFields() {
  const form = $("#editorForm");
  const kind = form.dataset.kind;
  const container = $("#instancePropertyFields");
  if (!container || !["object", "relation"].includes(kind)) return;
  const typeId = $('select[name="type"]', form)?.value;
  const definition = (kind === "object" ? typeNames() : relationNames())[typeId] || {};
  const usages = Object.entries(definition.properties || {});
  container.innerHTML = usages.length
    ? usages.map(([propertyId, usage]) => instancePropertyField(propertyId, usage)).join("")
    : '<span class="muted-text empty-properties">该类型尚未声明属性，可在“其他 Properties”中补充。</span>';
}

function instancePropertyField(propertyId, usage) {
  const definition = propertyDefinitions()[propertyId] || { name: propertyId, type: "json" };
  const required = usage?.required === true;
  const requiredAttr = required ? "required" : "";
  const label = `${escapeHtml(definition.name || propertyId)}${required ? " <em>*</em>" : ""}`;
  const hint = definition.description ? `<small>${escapeHtml(definition.description)}</small>` : "";
  const attrs = `data-property-id="${escapeAttr(propertyId)}" data-property-type="${escapeAttr(definition.type)}"`;
  if (definition.type === "money") {
    return `<div class="field full instance-property" ${attrs}><label>${label}</label><div class="money-property-grid"><input data-property-value type="number" step="any" placeholder="0" ${requiredAttr}><input data-property-currency type="text" value="CNY" maxlength="3" pattern="[A-Z]{3}" aria-label="币种"></div>${hint}</div>`;
  }
  if (definition.type === "boolean") {
    return `<div class="field instance-property" ${attrs}><label>${label}</label><select data-property-value ${requiredAttr}><option value="">未设置</option><option value="true">是</option><option value="false">否</option></select>${hint}</div>`;
  }
  const inputType = { number: "number", date: "date", period: "month" }[definition.type] || "text";
  const control = definition.type === "json"
    ? `<textarea data-property-value placeholder='{\n  "key": "value"\n}' ${requiredAttr}></textarea>`
    : `<input data-property-value type="${inputType}" ${definition.type === "number" ? 'step="any"' : ""} ${requiredAttr}>`;
  return `<div class="field instance-property ${definition.type === "json" ? "full" : ""}" ${attrs}><label>${label}</label>${control}${hint}</div>`;
}

$("#editorDialog").addEventListener("change", (event) => {
  if (event.target.name === "model_kind") {
    const relation = event.target.value === "relation";
    $$(".model-object-fields").forEach((field) => field.classList.toggle("hidden", relation));
    $$(".model-relation-fields").forEach((field) => field.classList.toggle("hidden", !relation));
  }
  if (event.target.name === "type" && $("#editorForm").dataset.kind === "relation") {
    updateRelationEndpoints();
  }
  if (event.target.name === "type" && ["object", "relation"].includes($("#editorForm").dataset.kind)) {
    updateInstancePropertyFields();
  }
});

async function submitEditor(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") {
    $("#editorDialog").close();
    return;
  }
  const form = event.currentTarget;
  if (!form.reportValidity()) return;
  try {
    const values = Object.fromEntries(new FormData(form).entries());
    const operations = buildOperations(form.dataset.kind, values, form);
    $("#editorDialog").close();
    await previewOperations(operations);
  } catch (error) {
    $("#formError").textContent = error.message;
    $("#formError").classList.remove("hidden");
  }
}

function objectTypeOptions() {
  const result = { ...typeNames() };
  state.data.objects.forEach((item) => { result[item.type] ||= { name: item.type }; });
  return result;
}

function relationTypeOptions() {
  const result = { ...relationNames() };
  state.data.relations.forEach((item) => { result[item.type] ||= { name: item.type }; });
  return result;
}

function updateRelationEndpoints() {
  const typeId = $('#editorForm select[name="type"]')?.value;
  const definition = relationNames()[typeId] || {};
  const update = (name, allowed) => {
    const select = $(`#editorForm select[name="${name}"]`);
    if (!select) return;
    const current = select.value;
    const objects = state.data.objects.filter((item) => !allowed?.length || allowed.includes(item.type));
    select.innerHTML = objects.map((item) => `<option value="${escapeAttr(item.id)}">${escapeHtml(item.name)} · ${escapeHtml(typeNames()[item.type]?.name || item.type)}</option>`).join("");
    if (objects.some((item) => item.id === current)) select.value = current;
  };
  update("from", definition.from_types);
  update("to", definition.to_types);
}

function buildOperations(kind, values, form) {
  if (kind === "model") return buildModelOperations(values, form);
  return [buildOperation(kind, values, form)];
}

function buildOperation(kind, values, form) {
  if (kind === "object") {
    const properties = buildInstanceProperties(form, values.extra_properties);
    const record = { id: values.id, type: values.type, name: values.name };
    if (Object.keys(properties).length) record.properties = properties;
    const tags = splitList(values.tags); if (tags.length) record.tags = tags;
    return { action: "create_object", record };
  }
  if (kind === "relation") {
    const properties = buildInstanceProperties(form, values.extra_properties);
    const record = { id: values.id, type: values.type, from: values.from, to: values.to };
    if (Object.keys(properties).length) record.properties = properties;
    const tags = splitList(values.tags); if (tags.length) record.tags = tags;
    return { action: "create_relation", record };
  }
  throw new Error(`不支持的编辑类型：${kind}`);
}

function buildInstanceProperties(form, extraProperties) {
  const properties = parseExtraProperties(extraProperties);
  $$(".instance-property", form).forEach((row) => {
    const propertyId = row.dataset.propertyId;
    const valueType = row.dataset.propertyType;
    const input = $("[data-property-value]", row);
    if (!input || input.value === "") return;
    if (valueType === "money") {
      const currency = $("[data-property-currency]", row)?.value.trim().toUpperCase() || "CNY";
      properties[propertyId] = { amount: Number(input.value), currency };
    } else if (valueType === "number") {
      properties[propertyId] = Number(input.value);
    } else if (valueType === "boolean") {
      properties[propertyId] = input.value === "true";
    } else if (valueType === "json") {
      try { properties[propertyId] = JSON.parse(input.value); }
      catch { throw new Error(`${propertyId} 必须是有效的 JSON`); }
    } else {
      properties[propertyId] = input.value;
    }
  });
  return properties;
}

function buildModelOperations(values, form) {
  const relation = values.model_kind === "relation";
  const definition = { name: values.display_name, description: values.description, properties: {} };
  const operations = [];
  const seen = new Set();
  $$(".model-property-row", form).forEach((row) => {
    const propertyId = $('[name="property_id"]', row).value.trim();
    if (!propertyId) return;
    if (seen.has(propertyId)) throw new Error(`Property ${propertyId} 重复`);
    seen.add(propertyId);
    definition.properties[propertyId] = { required: $('[name="property_required"]', row).checked };
    if (propertyDefinitions()[propertyId]) return;
    const propertyDefinition = {
      name: $('[name="property_name"]', row).value.trim(),
      type: $('[name="property_type"]', row).value,
    };
    const description = $('[name="property_description"]', row).value.trim();
    if (description) propertyDefinition.description = description;
    operations.push({ action: "upsert_property_definition", property_id: propertyId, definition: propertyDefinition });
  });
  if (relation) {
    const from = splitList(values.from_type); const to = splitList(values.to_type);
    if (from.length) definition.from_types = from;
    if (to.length) definition.to_types = to;
  }
  operations.push({ action: relation ? "upsert_relation_type" : "upsert_object_type", type_id: values.type_id, definition });
  return operations;
}

async function previewOperations(operations) {
  state.pendingOperations = operations;
  $("#changeCount").textContent = operations.length;
  try {
    state.preview = await api("/api/changes/preview", { method: "POST", body: JSON.stringify({ operations }) });
    renderChangePreview();
    $("#changeDialog").showModal();
  } catch (error) { toast(error.message, true); }
}

function renderChangePreview() {
  const preview = state.preview;
  $("#changeSummary").innerHTML = (preview.changes || []).map((text) => `<div><i data-lucide="plus-circle"></i><span>${escapeHtml(text)}</span></div>`).join("");
  $("#changeCode").textContent = JSON.stringify(state.pendingOperations, null, 2);
  const box = $("#validationBox");
  box.classList.toggle("invalid", !preview.valid);
  box.innerHTML = preview.valid ? `<i data-lucide="shield-check"></i><span>结构与经营约束校验通过，将更新 ${preview.changed_files.join("、")}。</span>` : `<i data-lucide="circle-x"></i><span>${escapeHtml(preview.errors.join("\n"))}</span>`;
  $("#applyChangesBtn").disabled = !preview.valid;
  icons();
}

async function applyPendingChanges() {
  if (!state.pendingOperations.length || !state.preview?.valid) return;
  const button = $("#applyChangesBtn"); button.disabled = true;
  try {
    const result = await api("/api/changes/apply", { method: "POST", body: JSON.stringify({ operations: state.pendingOperations }) });
    $("#changeDialog").close();
    state.pendingOperations = []; state.preview = null; $("#changeCount").textContent = "0";
    toast(result.changes.join("；"));
    await loadData();
  } catch (error) { toast(error.message, true); button.disabled = false; }
}

async function loadAgentStatus() {
  try {
    const status = await api("/api/agent/status");
    const element = $("#agentStatus");
    element.className = `agent-status ${status.available ? "ready" : "error"}`;
    element.title = status.message || "";
    element.innerHTML = `<span class="status-dot"></span><span>${escapeHtml(status.available ? "oag-agent 已连接" : "模型服务未配置")}</span>`;
    $("#agentRuntimeLabel").textContent = status.available ? "oag-agent · 在线" : "oag-agent · 未配置";
  } catch (error) { $("#agentStatus").classList.add("error"); $("#agentStatus").lastElementChild.textContent = error.message; }
}

async function sendAgentMessage(event) {
  event.preventDefault();
  if (state.agentBusy) return;
  const input = $("#agentInput"); const message = input.value.trim();
  if (!message) return;
  input.value = ""; autoGrowTextarea({ target: input });
  appendMessage("user", message);
  await streamAgent("/api/agent/chat", { message: contextualMessage(message), session_id: state.sessionId });
}

function contextualMessage(message) {
  if (!state.selected) return message;
  return `${message}\n\n[当前 UI 上下文：${state.selected.kind} ${state.selected.id}]`;
}

async function streamAgent(path, payload) {
  state.agentBusy = true; $(".send-button").disabled = true;
  let assistantBody = null;
  try {
    const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!response.ok) throw new Error(await response.text());
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n"); buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "text") {
          if (!assistantBody) assistantBody = appendMessage("assistant", "");
          assistantBody.querySelector("p").textContent += event.content || "";
          scrollAgent();
        } else if (event.type === "confirmation_required" || event.type === "question") {
          appendConfirmation(event);
        } else if (event.type === "tool_call" || event.type === "tool_result") {
          appendToolEvent(event);
        } else if (event.type === "error") {
          appendMessage("assistant", event.message || "Agent 暂不可用。");
        }
      }
      if (done) break;
    }
    if (path.includes("confirm") && payload.approved) await loadData();
  } catch (error) { appendMessage("assistant", `无法完成请求：${error.message}`); }
  finally { state.agentBusy = false; $(".send-button").disabled = false; }
}

function appendMessage(role, text) {
  const wrapper = document.createElement("div"); wrapper.className = `message ${role}`;
  wrapper.innerHTML = role === "assistant" ? `<div class="message-avatar"><i data-lucide="sparkles"></i></div><div class="message-body"><p>${escapeHtml(text)}</p></div>` : `<div class="message-body"><p>${escapeHtml(text)}</p></div>`;
  $("#agentMessages").append(wrapper); icons(); scrollAgent(); return wrapper.querySelector(".message-body");
}

function appendToolEvent(event) {
  const element = document.createElement("div"); element.className = "tool-event";
  element.textContent = event.type === "tool_call" ? `调用 ${event.name}` : `${event.name} 已返回${event.blocked ? "（已阻止）" : ""}`;
  $("#agentMessages").append(element); scrollAgent();
}

function appendConfirmation(event) {
  const wrapper = document.createElement("div"); wrapper.className = "message assistant";
  const question = event.type === "question" ? event.question : `Agent 请求执行 ${event.tool_name}`;
  wrapper.innerHTML = `<div class="message-avatar"><i data-lucide="shield-check"></i></div><div class="message-body confirmation-card"><strong>${escapeHtml(question)}</strong><pre>${escapeHtml(JSON.stringify(event.args || event.options || {}, null, 2))}</pre><div class="confirmation-actions"><button class="confirm-deny" data-agent-confirm="false">取消</button><button class="confirm-approve" data-agent-confirm="true">确认执行</button></div></div>`;
  $("#agentMessages").append(wrapper); icons(); scrollAgent();
}

async function handleAgentClick(event) {
  const suggestion = event.target.closest(".suggestions button");
  if (suggestion) { $("#agentInput").value = suggestion.textContent; $("#agentForm").requestSubmit(); return; }
  const confirm = event.target.closest("[data-agent-confirm]");
  if (confirm) { confirm.closest(".confirmation-actions").remove(); await streamAgent("/api/agent/confirm", { session_id: state.sessionId, approved: confirm.dataset.agentConfirm === "true" }); }
}

function askAboutSelection() { if (!state.selected) return; closeDetail(); openAgent(); $("#agentInput").value = `解释这个${state.selected.kind === "relation" ? "关系" : "对象"}及其经营含义：${state.selected.id}`; $("#agentInput").focus(); }
function clearAgentContext() { state.selected = null; updateAgentContext(); }
function updateAgentContext() { $("#agentContext span").textContent = state.selected ? `当前上下文：${state.selected.id}` : "当前上下文：全部经营对象"; }
function autoGrowTextarea(event) { const input = event.target; input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 160)}px`; }
function scrollAgent() { const messages = $("#agentMessages"); messages.scrollTop = messages.scrollHeight; }

function endpoint(item) { return `<div class="endpoint"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.id)} · ${escapeHtml(typeNames()[item.type]?.name || item.type)}</span></div>`; }
function typeIcon(type) { if (["revenue", "cash_receipt"].includes(type)) return "trending-up"; if (["cost", "cash_payment"].includes(type)) return "trending-down"; if (["contract", "receivable", "payable"].includes(type)) return "file-text"; if (type === "enterprise") return "building-2"; if (["customer", "supplier", "employee"].includes(type)) return "user-round"; if (type === "project") return "briefcase-business"; return "box"; }
function statusPill(status) { return status ? `<span class="status-pill ${escapeAttr(status)}">${escapeHtml(status)}</span>` : '<span class="muted-text">-</span>'; }
function money(amount, currency = "CNY") { if (amount === null || amount === undefined || Number.isNaN(Number(amount))) return "-"; return new Intl.NumberFormat("zh-CN", { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(amount)); }
function formatValue(value) { return typeof value === "object" ? JSON.stringify(value, null, 2) : String(value ?? "-"); }
function parseExtraProperties(value) { if (!value?.trim()) return {}; const parsed = JSON.parse(value); if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("其他 Properties 必须是 JSON 对象"); return parsed; }
function splitList(value) { return String(value || "").split(",").map((item) => item.trim()).filter(Boolean); }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]); }
function escapeAttr(value) { return escapeHtml(value); }
function toast(message, error = false) { const item = document.createElement("div"); item.className = `toast ${error ? "error" : ""}`; item.textContent = message; $("#toastRegion").append(item); setTimeout(() => item.remove(), 3200); }
