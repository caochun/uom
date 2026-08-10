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
  previewMode: "changeset",
  actionContextId: "",
  availableActions: [],
  currentAction: null,
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
  $$('[data-open-actions]').forEach((button) => button.addEventListener("click", () => openActionLauncher("")));
  $("#objectFilters").addEventListener("click", (event) => handleTypeFilterClick(event, "object"));
  $("#relationFilters").addEventListener("click", (event) => handleTypeFilterClick(event, "relation"));
  $("#modelKindTabs").addEventListener("click", segmentedHandler("modelKind", renderModel, "kind"));
  $("#globalSearch").addEventListener("input", (event) => { state.search = event.target.value.trim().toLowerCase(); renderCurrentView(); });
  $("#refreshBtn").addEventListener("click", loadData);
  $("#agentToggle").addEventListener("click", openAgent);
  $("#closeAgentBtn").addEventListener("click", closeAgent);
  $("#scrim").addEventListener("click", closeOverlays);
  $$('[data-close-drawer]').forEach((button) => button.addEventListener("click", closeDetail));
  $$('[data-close-changes]').forEach((button) => button.addEventListener("click", () => $("#changeDialog").close()));
  $("#returnFromChanges").addEventListener("click", returnFromChanges);
  $("#editorForm").addEventListener("submit", submitEditor);
  $("#editorDialog").addEventListener("click", handleEditorClick);
  $("#editorDialog").addEventListener("input", handleEditorInput);
  $("#applyChangesBtn").addEventListener("click", applyPendingChanges);
  $("#contextActionBtn").addEventListener("click", () => {
    const contextId = state.selected?.kind === "object" ? state.selected.id : "";
    closeDetail();
    openActionLauncher(contextId);
  });
  $$('[data-close-actions]').forEach((button) => button.addEventListener("click", closeActionDialog));
  $("#backToActions").addEventListener("click", renderActionCatalog);
  $("#actionCatalog").addEventListener("click", handleActionCatalogClick);
  $("#actionForm").addEventListener("submit", submitAction);
  $("#openChangesBtn").addEventListener("click", () => {
    if (!state.pendingOperations.length) return toast("当前没有待应用的变更");
    if (state.preview) {
      renderChangePreview();
      $("#changeDialog").showModal();
      return;
    }
    previewOperations(state.pendingOperations);
  });
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

function typeCatalog(kind) {
  const definitions = kind === "object" ? typeNames() : relationNames();
  const records = kind === "object" ? state.data.objects : state.data.relations;
  const counts = records.reduce((result, item) => {
    result[item.type] = (result[item.type] || 0) + 1;
    return result;
  }, {});
  const catalog = Object.entries(definitions).map(([id, definition]) => ({
    id,
    name: definition.name || id,
    count: counts[id] || 0,
  }));
  Object.keys(counts).filter((id) => !definitions[id]).sort().forEach((id) => catalog.push({
    id,
    name: `${id}（未定义）`,
    count: counts[id],
  }));
  return catalog;
}

function renderTypeFilters() {
  const objectTypes = typeCatalog("object");
  const relationTypes = typeCatalog("relation");
  if (state.objectFilter !== "all" && !objectTypes.some((item) => item.id === state.objectFilter)) state.objectFilter = "all";
  if (state.relationFilter !== "all" && !relationTypes.some((item) => item.id === state.relationFilter)) state.relationFilter = "all";

  $("#objectFilters").innerHTML = [
    filterButton("all", "全部", state.data.objects.length, state.objectFilter),
    ...objectTypes.map((item) => filterButton(item.id, item.name, item.count, state.objectFilter)),
  ].join("");

  $("#relationFilters").innerHTML = [
    filterButton("all", "全部", state.data.relations.length, state.relationFilter),
    ...relationTypes.map((item) => filterButton(item.id, item.name, item.count, state.relationFilter)),
  ].join("");
}

function filterButton(id, name, count, selected) {
  return `<button class="${selected === id ? "active" : ""}" data-filter="${escapeAttr(id)}" title="${escapeAttr(id)}">${escapeHtml(name)} <span class="filter-count">${count}</span></button>`;
}

function handleTypeFilterClick(event, kind) {
  const button = event.target.closest("button[data-filter]");
  if (!button) return;
  state[`${kind}Filter`] = button.dataset.filter;
  renderTypeFilters();
  (kind === "object" ? renderObjects : renderRelations)();
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
  $("#modelNavCount").textContent = Object.keys(model.object_types || {}).length + Object.keys(model.relation_types || {}).length + Object.keys(model.actions || {}).length;
  $("#sidebarModelName").textContent = model.model.name;
  $("#sidebarModelVersion").textContent = `v${model.model.version}`;
  $("#modelVersion").textContent = `v${model.model.version}`;
  renderTypeFilters();
  renderMetrics();
  renderObjects();
  renderRelations();
  renderModel();
  icons();
}

function renderMetrics() {
  const objects = state.data.objects;
  const relations = state.data.relations;
  const index = objectIndex();
  const passages = objects.filter((item) => item.type === "passage");
  const transactions = sumObjectMoney(objects.filter((item) => item.type === "toll_transaction"));
  const clearing = sumObjectMoney(objects.filter((item) => item.type === "clearing_result"));
  const incomplete = passages.filter((passage) => {
    const outbound = relations.filter((item) => item.from === passage.id);
    const stages = new Set(outbound
      .filter((item) => item.type === "references" && index[item.to]?.type === "toll_transaction")
      .map((item) => index[item.to]?.properties?.stage));
    const hasSplit = outbound.some((item) => item.type === "derives" && index[item.to]?.type === "split_record");
    return !stages.has("entry") || !stages.has("exit") || !hasSplit;
  });
  $("#metricPassages").textContent = passages.length;
  $("#metricTransactions").textContent = money(transactions.amount, transactions.currency || "CNY");
  $("#metricClearing").textContent = money(clearing.amount, clearing.currency || "CNY");
  $("#metricIncomplete").textContent = incomplete.length;
  $("#metricIncompleteHint").textContent = incomplete.length ? "需要补充入口、出口或拆分" : "通行主链完整";
  $("#initialAgentMessage").textContent = `当前有 ${passages.length} 条通行记录，交易金额 ${money(transactions.amount, transactions.currency || "CNY")}，清分金额 ${money(clearing.amount, clearing.currency || "CNY")}；${incomplete.length ? `仍有 ${incomplete.length} 条通行待完善。` : "通行主链暂未发现缺口。"}`;
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
  const items = state.data.objects
    .filter((item) => state.objectFilter === "all" || item.type === state.objectFilter)
    .filter(matchesSearch);
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
  const items = state.data.relations
    .filter((item) => state.relationFilter === "all" || item.type === state.relationFilter)
    .filter(matchesSearch);
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
    ["boxes", state.data.relations.filter((item) => item.type === "contains").length, "结构关系"],
    ["waypoints", state.data.relations.filter((item) => item.type === "derives").length, "派生追溯关系"],
    ["link-2", state.data.relations.filter((item) => ["references", "associates"].includes(item.type)).length, "引用与关联"],
  ];
  $("#relationSummary").innerHTML = summary.map(([icon, count, label]) => `<article><div class="summary-icon"><i data-lucide="${icon}"></i></div><div><strong>${count}</strong><span>${label}</span></div></article>`).join("");
  icons();
}

function renderModel() {
  if (!state.data) return;
  const definitions = state.modelKind === "object"
    ? state.data.model.object_types
    : state.modelKind === "relation"
      ? state.data.model.relation_types
      : state.data.model.actions;
  const usage = state.data.model_usage[state.modelKind] || {};
  const entries = Object.entries(definitions || {}).filter(([id, definition]) => matchesSearch({ id, ...definition }));
  $("#typeGrid").innerHTML = entries.map(([id, definition]) => {
    const props = state.modelKind === "action"
      ? Object.keys(definition.inputs || {}).map((id) => [id, {}])
      : Object.entries(definition.properties || {});
    const endpoints = state.modelKind === "relation" && (definition.from_types?.length || definition.to_types?.length) ? `${(definition.from_types || ["*"]).join(", ")} → ${(definition.to_types || ["*"]).join(", ")}` : "";
    const availability = state.modelKind === "action"
      ? (definition.available_on?.length ? `适用于 ${definition.available_on.join(", ")}` : "全局操作")
      : "";
    return `<article class="type-card" data-type-id="${escapeAttr(id)}">
      <div class="type-card-header"><div><span class="type-id">${escapeHtml(id)}</span><h3>${escapeHtml(definition.name)}</h3></div>${state.modelKind === "action" ? `<span class="action-card-icon"><i data-lucide="${actionIcon(definition.icon)}"></i></span>` : `<span class="usage-badge">${usage[id]?.count || 0} 条数据</span>`}</div>
      <p>${escapeHtml(definition.description)}</p>
      ${endpoints ? `<div class="property-list endpoint-types"><span>${escapeHtml(endpoints)}</span></div>` : ""}
      ${availability ? `<div class="property-list endpoint-types"><span>${escapeHtml(availability)}</span></div>` : ""}
      <div class="property-list">${props.slice(0, 5).map(([id, usage]) => `<span>${escapeHtml(id)}${usage?.required ? " *" : ""}</span>`).join("")}</div>
    </article>`;
  }).join("");
  $$(".type-card").forEach((card) => card.addEventListener("click", () => showDetail("model", card.dataset.typeId)));
  icons();
}

function showDetail(kind, id) {
  let item;
  if (kind === "object") item = state.data.objects.find((entry) => entry.id === id);
  if (kind === "relation") item = state.data.relations.find((entry) => entry.id === id);
  if (kind === "model") item = (state.modelKind === "object" ? state.data.model.object_types : state.modelKind === "relation" ? state.data.model.relation_types : state.data.model.actions)[id];
  if (!item) return;
  state.selected = { kind, id, item };
  const title = item.name || item.id || id;
  $("#detailEyebrow").textContent = kind === "model" ? ({ object: "对象类型", relation: "关系类型", action: "业务操作" }[state.modelKind]) : `${kind === "object" ? "对象" : "关系"}详情`;
  $("#detailTitle").textContent = title;
  $("#detailBody").innerHTML = detailMarkup(kind, id, item);
  $("#contextActionBtn").classList.toggle("hidden", kind !== "object");
  $("#detailDrawer").classList.add("open");
  $("#scrim").classList.remove("hidden");
  updateAgentContext();
  icons();
}

function detailMarkup(kind, id, item) {
  if (kind === "model") {
    const title = state.modelKind === "action" ? "操作定义" : "类型定义";
    return detailSection(title, { id, ...item }) + `<div class="detail-section"><h3>设计边界</h3><p class="muted-text">${state.modelKind === "action" ? "业务操作生成 Object / Relation 变更，但自身不进入业务关系图。" : "该定义是用户业务词汇，不会增加新的本体概念。Object / Relation 的结构保持不变。"}</p></div>`;
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

async function openActionLauncher(contextId = "") {
  state.actionContextId = contextId;
  state.currentAction = null;
  $("#actionDialogTitle").textContent = "选择业务操作";
  $("#actionForm").classList.add("hidden");
  $("#actionCatalog").classList.remove("hidden");
  $("#actionCatalog").innerHTML = '<div class="action-loading"><i data-lucide="loader-circle"></i><span>正在读取业务操作</span></div>';
  $("#actionDialog").showModal();
  icons();
  try {
    const result = await api("/api/actions/available", {
      method: "POST",
      body: JSON.stringify({ context_id: contextId }),
    });
    state.availableActions = result.actions || [];
    const context = result.context;
    renderActionContext(context);
    renderActionCatalog();
  } catch (error) {
    $("#actionCatalog").innerHTML = `<div class="action-empty"><i data-lucide="circle-x"></i><span>${escapeHtml(error.message)}</span></div>`;
    icons();
  }
}

function renderActionCatalog() {
  state.currentAction = null;
  $("#actionDialogTitle").textContent = "选择业务操作";
  $("#actionForm").classList.add("hidden");
  const catalog = $("#actionCatalog");
  catalog.classList.remove("hidden");
  catalog.innerHTML = state.availableActions.length
    ? state.availableActions.map((action) => `<button class="action-card" type="button" data-action-id="${escapeAttr(action.id)}">
        <span class="action-card-icon"><i data-lucide="${actionIcon(action.icon)}"></i></span>
        <span><strong>${escapeHtml(action.name)}</strong><small>${escapeHtml(action.description)}</small></span>
        <i data-lucide="chevron-right"></i>
      </button>`).join("")
    : '<div class="action-empty"><i data-lucide="circle-slash"></i><span>当前上下文没有可用操作</span></div>';
  icons();
}

function handleActionCatalogClick(event) {
  const button = event.target.closest("[data-action-id]");
  if (!button) return;
  const action = state.availableActions.find((item) => item.id === button.dataset.actionId);
  if (action) openActionForm(action);
}

function openActionForm(action, initialInputs = {}) {
  state.currentAction = action;
  $("#actionDialogTitle").textContent = action.name;
  $("#actionCatalog").classList.add("hidden");
  $("#actionForm").classList.remove("hidden");
  $("#actionFormError").classList.add("hidden");
  $("#actionFormBody").innerHTML = Object.entries(action.inputs || {})
    .map(([inputId, definition]) => actionInputField(
      inputId,
      definition,
      Object.prototype.hasOwnProperty.call(initialInputs, inputId) ? initialInputs[inputId] : undefined,
    ))
    .join("");
  icons();
}

function actionInputField(inputId, definition, initialValue = undefined) {
  const property = definition.property ? propertyDefinitions()[definition.property] : null;
  const valueType = property?.type || definition.type || (definition.object_types ? "object" : "string");
  const value = initialValue === undefined ? definition.default : initialValue;
  const label = definition.name || property?.name || inputId;
  const required = definition.required === true;
  const requiredLabel = required ? " <em>*</em>" : "";
  const requiredAttr = required ? "required" : "";
  const hint = property?.description ? `<small>${escapeHtml(property.description)}</small>` : "";
  const attrs = `class="field action-input ${valueType === "money" || valueType === "json" || valueType === "object" ? "full" : ""}" data-action-input="${escapeAttr(inputId)}" data-value-type="${escapeAttr(valueType)}"`;
  if (valueType === "object") {
    const options = (state.data?.objects || []).filter((item) => definition.object_types.includes(item.type));
    const choices = options.map((item, index) => `<label class="object-choice"><input type="radio" name="action_${escapeAttr(inputId)}" value="${escapeAttr(item.id)}" ${required && index === 0 ? "required" : ""} ${value === item.id ? "checked" : ""}><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(typeNames()[item.type]?.name || item.type)} · ${escapeHtml(item.id)}</small></span><i data-lucide="check"></i></label>`).join("");
    return `<div ${attrs}><label>${escapeHtml(label)}${requiredLabel}</label><div class="object-choice-list">${choices || '<span class="muted-text">没有符合类型的对象</span>'}</div></div>`;
  }
  if (valueType === "money") {
    const amount = value?.amount ?? "";
    const currency = value?.currency || "CNY";
    return `<div ${attrs}><label>${escapeHtml(label)}${requiredLabel}</label><div class="money-property-grid"><input data-action-value type="number" step="any" value="${escapeAttr(amount)}" placeholder="0" ${requiredAttr}><input data-action-currency type="text" value="${escapeAttr(currency)}" maxlength="3" pattern="[A-Z]{3}" aria-label="币种"></div>${hint}</div>`;
  }
  if (valueType === "boolean") {
    return `<div ${attrs}><label class="boolean-action-input"><input data-action-value type="checkbox" ${value === true ? "checked" : ""}><span>${escapeHtml(label)}${requiredLabel}</span></label>${hint}</div>`;
  }
  const defaultValue = value ?? "";
  const inputType = { number: "number", date: "date", period: "month" }[valueType] || "text";
  const control = valueType === "json"
    ? `<textarea data-action-value placeholder='["customer"]' ${requiredAttr}>${defaultValue === "" ? "" : escapeHtml(JSON.stringify(defaultValue, null, 2))}</textarea>`
    : `<input data-action-value type="${inputType}" value="${escapeAttr(defaultValue)}" ${valueType === "number" ? 'step="any"' : ""} ${requiredAttr}>`;
  return `<div ${attrs}><label>${escapeHtml(label)}${requiredLabel}</label>${control}${hint}</div>`;
}

async function submitAction(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity() || !state.currentAction) return;
  try {
    const inputs = buildActionInputs(state.currentAction, form);
    const preview = await api("/api/actions/preview", {
      method: "POST",
      body: JSON.stringify({
        action_id: state.currentAction.id,
        inputs,
        context_id: state.actionContextId,
      }),
    });
    state.previewMode = "action";
    state.preview = preview;
    state.pendingOperations = preview.operations || [];
    $("#changeCount").textContent = state.pendingOperations.length;
    closeActionDialog();
    renderChangePreview();
    $("#changeDialog").showModal();
  } catch (error) {
    $("#actionFormError").textContent = error.message;
    $("#actionFormError").classList.remove("hidden");
  }
}

function buildActionInputs(action, form) {
  const result = {};
  Object.entries(action.inputs || {}).forEach(([inputId]) => {
    const row = $(`[data-action-input="${CSS.escape(inputId)}"]`, form);
    const valueType = row.dataset.valueType;
    if (valueType === "object") {
      const selected = $('input[type="radio"]:checked', row);
      if (selected) result[inputId] = selected.value;
      return;
    }
    const input = $("[data-action-value]", row);
    if (valueType === "boolean") {
      result[inputId] = input.checked;
      return;
    }
    if (!input || input.value === "") return;
    if (valueType === "money") {
      result[inputId] = {
        amount: Number(input.value),
        currency: $("[data-action-currency]", row).value.trim().toUpperCase(),
      };
    } else if (valueType === "number") {
      result[inputId] = Number(input.value);
    } else if (valueType === "json") {
      try { result[inputId] = JSON.parse(input.value); }
      catch { throw new Error(`${inputId} 必须是有效的 JSON`); }
    } else {
      result[inputId] = input.value;
    }
  });
  return result;
}

function renderActionContext(context) {
  const contextElement = $("#actionContext");
  contextElement.classList.toggle("hidden", !context);
  contextElement.innerHTML = context
    ? `<i data-lucide="focus"></i><span>${escapeHtml(context.name)} · ${escapeHtml(typeNames()[context.type]?.name || context.type)}</span>`
    : "";
}

function openPresentedActionForm(payload) {
  if (payload?.kind !== "action_form" || !payload.action?.id) return;
  state.actionContextId = payload.context_id || "";
  state.availableActions = [payload.action];
  renderActionContext(payload.context || null);
  const dialog = $("#actionDialog");
  if (!dialog.open) dialog.showModal();
  openActionForm(payload.action, payload.initial_inputs || {});
}

function closeActionDialog() {
  if ($("#actionDialog").open) $("#actionDialog").close();
}

function openEditor(kind) {
  const definitions = kind === "object" ? objectTypeOptions() : relationTypeOptions();
  $("#formEyebrow").textContent = kind === "model" ? "业务词汇" : "业务数据";
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
    ${field("对象 ID", "id", "text", "例如 passage:customer-a-2026-08", true)}
    ${selectField("对象类型", "type", Object.entries(definitions).map(([id, def]) => [id, def.name]), true)}
    ${field("名称", "name", "text", "面向业务人员的清晰名称", true, "full")}
    ${instancePropertiesContainer()}
    ${field("Tags", "tags", "text", "多个标签用逗号分隔", false, "full")}
    ${field("其他 Properties", "extra_properties", "textarea", '{\n  "key": "value"\n}', false, "full", "填写 JSON 对象；会与上方属性合并。")}`;
}

function relationForm(definitions) {
  const objectOptions = state.data.objects.map((item) => [item.id, `${item.name} · ${typeNames()[item.type]?.name || item.type}`]);
  return `
    ${field("关系 ID", "id", "text", "例如 rel:passage-split-002", true)}
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
    ${field("业务定义", "description", "textarea", "说明它在联网收费中的含义", true, "full")}
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
    <div class="mini-field property-description"><label>属性说明</label><input name="property_description" placeholder="说明属性在业务语境中的含义"></div>
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
  state.previewMode = "changeset";
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
  const isAction = state.previewMode === "action";
  $("#changeEyebrow").textContent = isAction ? "业务操作" : "ChangeSet";
  $("#changeTitle").textContent = isAction ? `确认${preview.action?.name || "业务操作"}` : "确认本次变更";
  const outcome = $("#businessOutcome");
  outcome.classList.toggle("hidden", !isAction);
  outcome.innerHTML = isAction
    ? `<i data-lucide="${actionIcon(preview.action?.icon)}"></i><div><strong>${escapeHtml(preview.summary || preview.action?.name)}</strong>${preview.context ? `<span>当前对象：${escapeHtml(preview.context.name)} · ${escapeHtml(preview.context.id)}</span>` : ""}</div>`
    : "";
  $("#changeSummary").innerHTML = (preview.changes || []).map((text) => `<div><i data-lucide="plus-circle"></i><span>${escapeHtml(text)}</span></div>`).join("");
  $("#changeCode").textContent = JSON.stringify(state.pendingOperations, null, 2);
  const box = $("#validationBox");
  box.classList.toggle("invalid", !preview.valid);
  box.innerHTML = preview.valid ? `<i data-lucide="shield-check"></i><span>结构与业务约束校验通过，将更新 ${preview.changed_files.join("、")}。</span>` : `<i data-lucide="circle-x"></i><span>${escapeHtml(preview.errors.join("\n"))}</span>`;
  $("#actionReasonField").classList.toggle("hidden", !isAction);
  if (!isAction) $("#actionReason").value = "";
  $("#applyChangesBtn").disabled = !preview.valid;
  $("#applyChangesBtn").innerHTML = isAction ? '<i data-lucide="check"></i>确认执行' : '<i data-lucide="check"></i>应用变更';
  icons();
}

function returnFromChanges() {
  $("#changeDialog").close();
  if (state.previewMode === "action" && state.currentAction) {
    $("#actionDialog").showModal();
    openActionForm(state.currentAction);
  }
}

async function applyPendingChanges() {
  if (!state.pendingOperations.length || !state.preview?.valid) return;
  const button = $("#applyChangesBtn"); button.disabled = true;
  try {
    const isAction = state.previewMode === "action";
    const result = isAction
      ? await api("/api/actions/apply", {
          method: "POST",
          body: JSON.stringify({
            preview_token: state.preview.preview_token,
            reason: $("#actionReason").value.trim(),
            actor: "web_user",
          }),
        })
      : await api("/api/changes/apply", { method: "POST", body: JSON.stringify({ operations: state.pendingOperations }) });
    $("#changeDialog").close();
    state.pendingOperations = []; state.preview = null; state.previewMode = "changeset"; $("#changeCount").textContent = "0";
    toast(result.summary || result.changes.join("；"));
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
  let assistantBody = null; let assistantMarkdown = ""; let toolGroup = null; let waitingForConfirmation = false;
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
          const shouldFollow = isAgentNearBottom();
          if (!assistantBody) assistantBody = appendMessage("assistant", "");
          assistantMarkdown += event.content || "";
          renderAssistantMarkdown(assistantBody, assistantMarkdown);
          scrollAgent(shouldFollow);
        } else if (event.type === "confirmation_required" || event.type === "question") {
          waitingForConfirmation = true;
          appendConfirmation(event);
        } else if (event.type === "tool_call" || event.type === "tool_result") {
          toolGroup = appendToolEvent(event, toolGroup);
        } else if (event.type === "presentation" && event.name === "ui_open_action_form") {
          if (assistantBody) {
            assistantBody.closest(".message")?.remove();
            assistantBody = null;
            assistantMarkdown = "";
          }
          openPresentedActionForm(event.payload);
        } else if (event.type === "error") {
          appendMessage("assistant", event.message || "Agent 暂不可用。");
        }
      }
      if (done) break;
    }
    if (path.includes("confirm") && payload.approved) await loadData();
  } catch (error) { appendMessage("assistant", `无法完成请求：${error.message}`); }
  finally {
    if (!waitingForConfirmation) collapseToolEvents();
    state.agentBusy = false;
    $(".send-button").disabled = false;
  }
}

function appendMessage(role, text) {
  const wrapper = document.createElement("div"); wrapper.className = `message ${role}`;
  wrapper.innerHTML = role === "assistant" ? '<div class="message-avatar"><i data-lucide="sparkles"></i></div><div class="message-body markdown-content"></div>' : `<div class="message-body"><p>${escapeHtml(text)}</p></div>`;
  const body = wrapper.querySelector(".message-body");
  if (role === "assistant") renderAssistantMarkdown(body, text);
  $("#agentMessages").append(wrapper); icons(); scrollAgent(true); return body;
}

function renderAssistantMarkdown(container, markdown) {
  if (!window.marked || !window.DOMPurify) {
    container.innerHTML = `<p>${escapeHtml(markdown).replace(/\n/g, "<br>")}</p>`;
    return;
  }
  const parsed = window.marked.parse(markdown, { gfm: true, breaks: true });
  container.innerHTML = window.DOMPurify.sanitize(parsed, { USE_PROFILES: { html: true } });
  container.querySelectorAll("a[href]").forEach((link) => {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  });
}

function appendToolEvent(event, group = null) {
  if (!group || !group.isConnected) {
    group = document.createElement("details");
    group.className = "tool-events";
    group.open = true;
    group.innerHTML = '<summary><i data-lucide="wrench"></i><span class="tool-event-summary-label">正在调用工具</span><b class="tool-event-count">0</b></summary><div class="tool-event-list"></div>';
    $("#agentMessages").append(group);
  }
  const name = event.name || event.tool_name || "工具";
  const element = document.createElement("div");
  element.className = `tool-event ${event.type === "tool_result" ? "result" : "call"}`;
  element.innerHTML = event.type === "tool_call"
    ? `<i data-lucide="play"></i><span>调用 ${escapeHtml(name)}</span>`
    : `<i data-lucide="${event.blocked ? "circle-x" : "check"}"></i><span>${escapeHtml(name)} 已返回${event.blocked ? "（已阻止）" : ""}</span>`;
  $(".tool-event-list", group).append(element);
  const count = $$(".tool-event", group).length;
  $(".tool-event-count", group).textContent = count;
  $(".tool-event-summary-label", group).textContent = "正在调用工具";
  icons();
  scrollAgent(true);
  return group;
}

function collapseToolEvents() {
  $$(".tool-events[open]", $("#agentMessages")).forEach((group) => {
    group.open = false;
    $(".tool-event-summary-label", group).textContent = "工具调用已完成";
  });
}

function appendConfirmation(event) {
  const wrapper = document.createElement("div"); wrapper.className = "message assistant";
  const question = event.type === "question" ? event.question : `Agent 请求执行 ${event.tool_name}`;
  wrapper.innerHTML = `<div class="message-avatar"><i data-lucide="shield-check"></i></div><div class="message-body confirmation-card"><strong>${escapeHtml(question)}</strong><pre>${escapeHtml(JSON.stringify(event.args || event.options || {}, null, 2))}</pre><div class="confirmation-actions"><button class="confirm-deny" data-agent-confirm="false">取消</button><button class="confirm-approve" data-agent-confirm="true">确认执行</button></div></div>`;
  $("#agentMessages").append(wrapper); icons(); scrollAgent(true);
}

async function handleAgentClick(event) {
  const suggestion = event.target.closest(".suggestions button");
  if (suggestion) { $("#agentInput").value = suggestion.textContent; $("#agentForm").requestSubmit(); return; }
  const confirm = event.target.closest("[data-agent-confirm]");
  if (confirm) { confirm.closest(".confirmation-actions").remove(); await streamAgent("/api/agent/confirm", { session_id: state.sessionId, approved: confirm.dataset.agentConfirm === "true" }); }
}

function askAboutSelection() { if (!state.selected) return; closeDetail(); openAgent(); $("#agentInput").value = `解释这个${state.selected.kind === "relation" ? "关系" : "对象"}及其业务含义：${state.selected.id}`; $("#agentInput").focus(); }
function clearAgentContext() { state.selected = null; updateAgentContext(); }
function updateAgentContext() { $("#agentContext span").textContent = state.selected ? `当前上下文：${state.selected.id}` : "当前上下文：全部业务对象"; }
function autoGrowTextarea(event) { const input = event.target; input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 160)}px`; }
function isAgentNearBottom() { const messages = $("#agentMessages"); return messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80; }
function scrollAgent(force = false) { const messages = $("#agentMessages"); if (force || isAgentNearBottom()) messages.scrollTop = messages.scrollHeight; }

function endpoint(item) { return `<div class="endpoint"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.id)} · ${escapeHtml(typeNames()[item.type]?.name || item.type)}</span></div>`; }
function actionIcon(icon) { return String(icon || "play").replaceAll("_", "-"); }
function typeIcon(type) {
  if (["toll_road", "section", "toll_interval", "toll_station", "toll_plaza", "toll_lane", "toll_gantry"].includes(type)) return "route";
  if (["vehicle", "passage"].includes(type)) return "car-front";
  if (type === "passage_medium") return "credit-card";
  if (["toll_transaction", "vehicle_id_record", "consumption_detail"].includes(type)) return "scan-line";
  if (["split_record", "clearing_result", "invoice_basis_data"].includes(type)) return "waypoints";
  if (["account", "account_transaction", "bill", "bill_settlement"].includes(type)) return "wallet-cards";
  if (type === "party") return "building-2";
  if (["fee_module", "fee_rule", "control_entry"].includes(type)) return "shield-check";
  return "box";
}
function statusPill(status) { return status ? `<span class="status-pill ${escapeAttr(status)}">${escapeHtml(status)}</span>` : '<span class="muted-text">-</span>'; }
function money(amount, currency = "CNY") { if (amount === null || amount === undefined || Number.isNaN(Number(amount))) return "-"; return new Intl.NumberFormat("zh-CN", { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(amount)); }
function formatValue(value) { return typeof value === "object" ? JSON.stringify(value, null, 2) : String(value ?? "-"); }
function parseExtraProperties(value) { if (!value?.trim()) return {}; const parsed = JSON.parse(value); if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("其他 Properties 必须是 JSON 对象"); return parsed; }
function splitList(value) { return String(value || "").split(",").map((item) => item.trim()).filter(Boolean); }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]); }
function escapeAttr(value) { return escapeHtml(value); }
function toast(message, error = false) { const item = document.createElement("div"); item.className = `toast ${error ? "error" : ""}`; item.textContent = message; $("#toastRegion").append(item); setTimeout(() => item.remove(), 3200); }
