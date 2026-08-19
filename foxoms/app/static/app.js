function createSessionId() {
  if (globalThis.crypto?.randomUUID) return `oms-${globalThis.crypto.randomUUID()}`;
  if (globalThis.crypto?.getRandomValues) {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
    return `oms-${[...bytes].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
  }
  return `oms-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

const state = {
  data: null,
  view: "operations",
  operationView: "overview",
  managedPartyId: "all",
  dataKind: "object",
  objectFilter: "all",
  relationFilter: "all",
  modelKind: "object",
  search: "",
  selected: null,
  pendingOperations: [],
  preview: null,
  previewMode: "changeset",
  actionContextId: "",
  actionContextType: "",
  actionContextCandidates: [],
  availableActions: [],
  currentAction: null,
  sessionId: createSessionId(),
  agentBusy: false,
  agentPending: false,
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
  ["string", "文本"], ["number", "数值"], ["money", "金额"], ["date", "日期"], ["datetime", "日期时间"],
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
  $$('[data-open-actions]').forEach((button) => button.addEventListener("click", openActionsForCurrentView));
  $("#objectFilters").addEventListener("click", (event) => handleTypeFilterClick(event, "object"));
  $("#relationFilters").addEventListener("click", (event) => handleTypeFilterClick(event, "relation"));
  $("#operationTabs").addEventListener("click", handleOperationTabClick);
  $("#managedPartyList").addEventListener("click", handleManagedPartyClick);
  $("#operationContent").addEventListener("click", handleOperationContentClick);
  $("#dataKindTabs").addEventListener("click", handleDataKindClick);
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
  $("#detailBody").addEventListener("click", (event) => {
    const link = event.target.closest("[data-related-object]");
    if (link) showDetail("object", link.dataset.relatedObject);
  });
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
  const summaryCounts = kind === "object" ? state.data.stats?.object_types : state.data.stats?.relation_types;
  const counts = records.length ? records.reduce((result, item) => {
    result[item.type] = (result[item.type] || 0) + 1;
    return result;
  }, {}) : (summaryCounts || {});
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
    filterButton("all", "全部", state.data.stats.object_count, state.objectFilter),
    ...objectTypes.map((item) => filterButton(item.id, item.name, item.count, state.objectFilter)),
  ].join("");

  $("#relationFilters").innerHTML = [
    filterButton("all", "全部", state.data.stats.relation_count, state.relationFilter),
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
    state.data = { ...(await api("/api/bootstrap")), objects: [], relations: [] };
    renderShell();
    const [objects, relations] = await Promise.all([
      loadRecordPages("object"),
      loadRecordPages("relation"),
    ]);
    state.data.objects = objects;
    state.data.relations = relations;
    state.data.graph_loaded = true;
    renderShell();
    toast("数据已刷新");
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadRecordPages(kind) {
  const records = [];
  const path = kind === "object" ? "/api/objects/query" : "/api/relations/query";
  let offset = 0;
  while (true) {
    const page = await api(path, {
      method: "POST",
      body: JSON.stringify({ limit: 500, offset }),
    });
    records.push(...page.records);
    if (!page.has_more) return records;
    offset += page.records.length;
  }
}

function renderShell() {
  const { stats, model } = state.data;
  const hasActions = Object.keys(model.actions || {}).length > 0;
  $("#operationsNavCount").textContent = state.data.objects.filter((item) => item.type === "opportunity").length;
  $("#dataNavCount").textContent = stats.object_count + stats.relation_count;
  $("#objectNavCount").textContent = stats.object_count;
  $("#relationNavCount").textContent = stats.relation_count;
  $("#modelNavCount").textContent = Object.keys(model.object_types || {}).length + Object.keys(model.relation_types || {}).length + Object.keys(model.actions || {}).length;
  $("#sidebarModelName").textContent = model.model.name;
  $("#sidebarModelVersion").textContent = `v${model.model.version}`;
  $("#modelVersion").textContent = `v${model.model.version}`;
  $$('[data-open-actions]').forEach((button) => button.classList.toggle("hidden", !hasActions));
  renderTypeFilters();
  renderManagedPartyList();
  renderOperations();
  renderObjects();
  renderRelations();
  renderModel();
  icons();
}

function renderMetrics() {
  const objects = scopedObjects();
  const opportunities = objects.filter((item) => item.type === "opportunity");
  const bids = objects.filter((item) => item.type === "bid");
  const invoices = objects.filter((item) => item.type === "invoice");
  const receipts = objects.filter((item) => item.type === "receipt");
  const invoiced = sumObjectMoney(invoices);
  const received = sumObjectMoney(receipts);
  const objectIds = new Set(objects.map((item) => item.id));
  const settledAmount = state.data.relations
    .filter((item) => item.type === "settles" && objectIds.has(item.from) && objectIds.has(item.to))
    .reduce((total, item) => total + Number(item.properties?.settled_amount?.amount || 0), 0);
  const outstanding = Math.max(0, invoiced.amount - settledAmount);
  const unallocated = Math.max(0, received.amount - settledAmount);
  const currency = invoiced.currency || received.currency || "CNY";

  $("#metricOpportunities").textContent = opportunities.length;
  $("#metricOpportunityHint").textContent = `${opportunities.filter((item) => !businessChildren(item.id, "contains", "tender").length).length} 项暂无后续`;
  $("#metricPendingBids").textContent = bids.filter((item) => !item.properties?.bid_result).length;
  $("#metricAwards").textContent = bids.filter((item) => item.properties?.bid_result === "awarded").length;
  $("#metricDeliveries").textContent = objects.filter((item) => ["order", "work_item"].includes(item.type)).length;
  $("#metricOutstanding").textContent = money(outstanding, currency);
  $("#metricOutstandingHint").textContent = `${money(invoiced.amount, currency)} 已开票${unallocated ? ` · ${money(unallocated, currency)} 待核销` : ""}`;
  const partyName = selectedManagedParty()?.name || `${managedParties().length} 家受管企业`;
  $("#initialAgentMessage").textContent = `${partyName}当前有 ${opportunities.length} 项商机、${bids.filter((item) => item.properties?.bid_result === "awarded").length} 项中标记录和 ${money(outstanding, currency)} 待回款。`;
}

function renderBusinessPipelineLegacy() {
  const stages = [
    ["opportunity", "商机"], ["tender", "招标"], ["bid", "投标"],
    ["framework_agreement", "框架协议"], ["contract", "项目合同"],
    ["order", "订单"], ["work_item", "项目/任务"], ["invoice", "发票"], ["receipt", "回款"],
  ];
  const pipeline = $("#businessPipeline");
  if (!pipeline) return;
  pipeline.innerHTML = stages.map(([type, label], index) => {
    const count = state.data.objects.filter((item) => item.type === type).length;
    return `${index ? '<i data-lucide="chevron-right"></i>' : ""}<button type="button" data-pipeline-type="${type}"><span>${escapeHtml(label)}</span><strong>${count}</strong></button>`;
  }).join("");
  $$("[data-pipeline-type]", pipeline).forEach((button) => button.addEventListener("click", () => {
    state.objectFilter = button.dataset.pipelineType;
    renderTypeFilters();
    renderObjects();
  }));
}

function sumObjectMoney(items) {
  return items.reduce((result, item) => {
    const value = item.properties?.paid_amount || item.properties?.amount;
    result.amount += Number(value?.amount || 0);
    result.currency ||= value?.currency;
    return result;
  }, { amount: 0, currency: null });
}

function managedParties() {
  return (state.data?.objects || []).filter((item) => item.type === "party" && item.properties?.is_managed === true);
}

function selectedManagedParty() {
  return state.managedPartyId === "all"
    ? null
    : managedParties().find((item) => item.id === state.managedPartyId) || null;
}

function renderManagedPartyList() {
  const parties = managedParties();
  if (state.managedPartyId !== "all" && !parties.some((item) => item.id === state.managedPartyId)) state.managedPartyId = "all";
  $("#managedPartyList").innerHTML = [
    `<button class="${state.managedPartyId === "all" ? "active" : ""}" data-managed-party="all"><i data-lucide="building-2"></i><span><strong>全部受管企业</strong><small>${parties.length} 家经营主体</small></span></button>`,
    ...parties.map((party) => `<button class="${state.managedPartyId === party.id ? "active" : ""}" data-managed-party="${escapeAttr(party.id)}"><i data-lucide="building"></i><span><strong>${escapeHtml(party.name)}</strong><small>${escapeHtml(party.id)}</small></span></button>`),
  ].join("");
  icons();
}

function handleManagedPartyClick(event) {
  const button = event.target.closest("[data-managed-party]");
  if (!button) return;
  state.managedPartyId = button.dataset.managedParty;
  renderManagedPartyList();
  renderOperations();
}

function handleOperationTabClick(event) {
  const button = event.target.closest("[data-operation]");
  if (!button) return;
  state.operationView = button.dataset.operation;
  $$('[data-operation]', $("#operationTabs")).forEach((item) => item.classList.toggle("active", item === button));
  renderOperations();
}

function handleDataKindClick(event) {
  const button = event.target.closest("[data-kind]");
  if (!button) return;
  state.dataKind = button.dataset.kind;
  $$('[data-kind]', $("#dataKindTabs")).forEach((item) => item.classList.toggle("active", item === button));
  renderDataView();
}

function renderDataView() {
  const objectsVisible = state.dataKind === "object";
  $("#dataObjectsPanel").classList.toggle("hidden", !objectsVisible);
  $("#dataRelationsPanel").classList.toggle("hidden", objectsVisible);
  (objectsVisible ? renderObjects : renderRelations)();
}

function businessChildren(id, relationType, childType = "") {
  const index = objectIndex();
  return (state.data?.relations || [])
    .filter((relation) => relation.type === relationType && relation.from === id)
    .map((relation) => index[relation.to])
    .filter((item) => item && (!childType || item.type === childType));
}

function businessParents(id, relationType, parentType = "") {
  const index = objectIndex();
  return (state.data?.relations || [])
    .filter((relation) => relation.type === relationType && relation.to === id)
    .map((relation) => index[relation.from])
    .filter((item) => item && (!parentType || item.type === parentType));
}

function scopedObjectIds() {
  const allObjects = state.data?.objects || [];
  if (state.managedPartyId === "all") return new Set(allObjects.map((item) => item.id));
  const index = objectIndex();
  const ids = new Set([state.managedPartyId]);
  const structural = new Set(["contains", "derives"]);
  const relations = state.data?.relations || [];

  relations.filter((item) => item.type === "participates_in" && item.from === state.managedPartyId)
    .forEach((item) => ids.add(item.to));

  let changed = true;
  while (changed) {
    changed = false;
    relations.forEach((relation) => {
      if (!structural.has(relation.type)) return;
      if (ids.has(relation.from) && !ids.has(relation.to)) {
        ids.add(relation.to);
        changed = true;
      }
      if (ids.has(relation.to) && !ids.has(relation.from)) {
        ids.add(relation.from);
        changed = true;
      }
    });
  }

  relations.forEach((relation) => {
    if (relation.type === "participates_in" && ids.has(relation.to)) ids.add(relation.from);
    if (relation.type === "allocated_to" && ids.has(relation.to)) ids.add(relation.from);
    if (relation.type === "involves_ip" && ids.has(relation.from)) ids.add(relation.to);
    if (relation.type === "settles" && ids.has(relation.to)) ids.add(relation.from);
  });

  // A split receipt may introduce another invoice from the same customer/provider chain.
  relations.filter((relation) => relation.type === "settles" && ids.has(relation.from))
    .forEach((relation) => ids.add(relation.to));
  relations.filter((relation) => relation.type === "contains" && ids.has(relation.to))
    .forEach((relation) => ids.add(relation.from));
  return new Set([...ids].filter((id) => index[id]));
}

function scopedObjects() {
  const ids = scopedObjectIds();
  return (state.data?.objects || []).filter((item) => ids.has(item.id));
}

function renderOperations() {
  if (!state.data) return;
  const party = selectedManagedParty();
  $("#operationsTitle").textContent = party ? party.name : "经营工作台";
  $("#operationsSubtitle").textContent = party
    ? "从该企业经营的商机出发，追踪签约、履约投入和资金回收。"
    : "跨受管企业查看商务、履约和资金链；选择企业可收窄经营范围。";
  renderMetrics();
  const renderers = {
    overview: renderOperationsOverview,
    commercial: renderCommercialView,
    delivery: renderDeliveryView,
    finance: renderFinanceView,
    resources: renderResourceView,
  };
  $("#operationContent").innerHTML = (renderers[state.operationView] || renderOperationsOverview)();
  icons();
}

function handleOperationContentClick(event) {
  const objectButton = event.target.closest("[data-business-object]");
  if (objectButton) {
    showDetail("object", objectButton.dataset.businessObject);
    return;
  }
  const viewButton = event.target.closest("[data-go-operation]");
  if (viewButton) {
    state.operationView = viewButton.dataset.goOperation;
    $$('[data-operation]', $("#operationTabs")).forEach((item) => item.classList.toggle("active", item.dataset.operation === state.operationView));
    renderOperations();
  }
}

function renderOperationsOverview() {
  const objects = scopedObjects().filter(matchesSearch);
  const opportunities = objects.filter((item) => item.type === "opportunity");
  const agreements = objects.filter((item) => ["framework_agreement", "contract"].includes(item.type));
  const invoices = objects.filter((item) => item.type === "invoice");
  const invoiceIds = new Set(invoices.map((item) => item.id));
  const settled = (state.data.relations || []).filter((item) => item.type === "settles" && invoiceIds.has(item.to))
    .reduce((total, item) => total + Number(item.properties?.settled_amount?.amount || 0), 0);
  const invoiced = sumObjectMoney(invoices);
  const outstanding = Math.max(0, invoiced.amount - settled);
  const currency = invoiced.currency || "CNY";
  const openOpportunities = opportunities.filter((item) => !businessChildren(item.id, "contains", "tender").length);
  const activeDeliveries = objects.filter((item) => ["order", "work_item"].includes(item.type));
  const allocations = (state.data.relations || []).filter((item) => item.type === "allocated_to" && activeDeliveries.some((target) => target.id === item.to));

  return `<div class="overview-grid">
    <section class="business-band span-two">
      <div class="band-heading"><div><span class="eyebrow">商务状态</span><h2>从机会到商务约定</h2></div><button class="text-command" data-go-operation="commercial">查看完整脉络<i data-lucide="arrow-right"></i></button></div>
      <div class="stage-track">
        ${overviewStage("lightbulb", "商机", opportunities.length, `${openOpportunities.length} 项暂无后续`)}
        <i data-lucide="chevron-right"></i>
        ${overviewStage("landmark", "进入招投标", opportunities.length - openOpportunities.length, "按商机统计")}
        <i data-lucide="chevron-right"></i>
        ${overviewStage("badge-check", "中标", objects.filter((item) => item.type === "bid" && item.properties?.bid_result === "awarded").length, "已确认结果")}
        <i data-lucide="chevron-right"></i>
        ${overviewStage("file-signature", "商务约定", agreements.length, "框架协议或项目合同")}
      </div>
    </section>
    <section class="business-band">
      <div class="band-heading"><div><span class="eyebrow">资金回收</span><h2>${money(outstanding, currency)} 待回款</h2></div><button class="icon-command" data-go-operation="finance" title="查看开票回款"><i data-lucide="arrow-up-right"></i></button></div>
      <div class="finance-meter"><span style="width:${invoiced.amount ? Math.min(100, settled / invoiced.amount * 100) : 0}%"></span></div>
      <div class="band-stat-row"><span>已开票 <strong>${money(invoiced.amount, currency)}</strong></span><span>已核销 <strong>${money(settled, currency)}</strong></span></div>
    </section>
    <section class="business-band">
      <div class="band-heading"><div><span class="eyebrow">履约投入</span><h2>${activeDeliveries.length} 项订单/任务</h2></div><button class="icon-command" data-go-operation="delivery" title="查看履约交付"><i data-lucide="arrow-up-right"></i></button></div>
      <div class="band-stat-row compact"><span>资源投入 <strong>${allocations.length}</strong></span><span>知识资产 <strong>${objects.filter((item) => item.type === "intellectual_asset").length}</strong></span></div>
    </section>
    <section class="business-band span-two">
      <div class="band-heading"><div><span class="eyebrow">需要关注</span><h2>经营事项</h2></div></div>
      <div class="attention-list">
        ${openOpportunities.length ? attentionRow("clock-3", `${openOpportunities.length} 项商机尚未进入招投标`, "商机可以停留于此，不视为数据异常", "commercial") : attentionRow("circle-check", "商机均已有后续记录", "当前不存在停留在机会阶段的商机", "commercial")}
        ${outstanding ? attentionRow("circle-dollar-sign", `${money(outstanding, currency)} 已开票未回款`, "按发票核销金额计算", "finance") : attentionRow("circle-check", "已开票金额全部回款", "当前没有发票余额", "finance")}
      </div>
    </section>
  </div>`;
}

function overviewStage(icon, label, count, hint) {
  return `<div class="stage-item"><span><i data-lucide="${icon}"></i></span><div><strong>${count}</strong><b>${escapeHtml(label)}</b><small>${escapeHtml(hint)}</small></div></div>`;
}

function attentionRow(icon, title, hint, view) {
  return `<button data-go-operation="${view}"><i data-lucide="${icon}"></i><span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(hint)}</small></span><i data-lucide="chevron-right"></i></button>`;
}

function renderCommercialView() {
  const scopedIds = scopedObjectIds();
  let opportunities = (state.data.objects || []).filter((item) => item.type === "opportunity" && scopedIds.has(item.id));
  if (state.search) opportunities = opportunities.filter((item) => commercialThreadIds(item).some((id) => matchesSearch(objectIndex()[id] || { id })));
  const content = opportunities.map(renderCommercialThread).join("");
  return operationSectionHeader("商务拓展", "以商机为入口查看招标、投标结果及中标后的商务路径", `${opportunities.length} 项商机`)
    + `<div class="commercial-thread-list">${content || operationEmpty("没有匹配的商机")}</div>`;
}

function commercialThreadIds(opportunity) {
  const ids = [opportunity.id];
  businessChildren(opportunity.id, "contains", "tender").forEach((tender) => {
    ids.push(tender.id);
    businessChildren(tender.id, "contains", "bid").forEach((bid) => {
      ids.push(bid.id);
      businessChildren(bid.id, "derives").forEach((agreement) => {
        ids.push(agreement.id);
        businessChildren(agreement.id, "contains").forEach((item) => ids.push(item.id));
      });
    });
  });
  return ids;
}

function renderCommercialThread(opportunity) {
  const tenders = businessChildren(opportunity.id, "contains", "tender");
  return `<article class="commercial-thread">
    <button class="thread-root" data-business-object="${escapeAttr(opportunity.id)}"><span class="type-icon opportunity"><i data-lucide="lightbulb"></i></span><span><strong>${escapeHtml(opportunity.name)}</strong><small>${escapeHtml(partyNamesFor(opportunity.id, "potential_customer").join("、") || "未记录潜在客户")}</small></span><i data-lucide="chevron-right"></i></button>
    <div class="thread-body">${tenders.length ? tenders.map(renderTenderBranch).join("") : `<div class="thread-empty"><i data-lucide="pause"></i><span><strong>暂未进入招投标</strong><small>商机可以停留在当前阶段，不视为流程异常</small></span></div>`}</div>
  </article>`;
}

function renderTenderBranch(tender) {
  const bids = businessChildren(tender.id, "contains", "bid");
  return `<div class="thread-branch">
    ${businessNode(tender, "landmark", `${partyNamesFor(tender.id, "tenderer").join("、") || "未记录招标方"} · ${bids.length} 份投标`)}
    <div class="thread-children">${bids.length ? bids.map(renderBidBranch).join("") : `<div class="thread-empty compact"><span>尚未登记投标</span></div>`}</div>
  </div>`;
}

function renderBidBranch(bid) {
  const result = bid.properties?.bid_result;
  const downstream = businessChildren(bid.id, "derives");
  const label = result === "awarded" ? "中标" : result === "not_awarded" ? "未中标" : "待结果";
  return `<div class="thread-branch bid-branch">
    ${businessNode(bid, "file-check-2", `${partyNamesFor(bid.id, "lead_bidder").join("、") || "未记录投标方"}`, statusPill(result || "pending", label))}
    ${downstream.length ? `<div class="thread-children">${downstream.map((item) => {
      const children = businessChildren(item.id, "contains").filter((child) => ["order", "work_item"].includes(child.type));
      return `<div class="thread-branch">${businessNode(item, "file-signature", typeNames()[item.type]?.name || item.type)}${children.length ? `<div class="thread-children">${children.map((child) => businessNode(child, typeIcon(child.type), typeNames()[child.type]?.name || child.type)).join("")}</div>` : ""}</div>`;
    }).join("")}</div>` : ""}
  </div>`;
}

function businessNode(item, icon, hint, trailing = "") {
  return `<button class="business-node" data-business-object="${escapeAttr(item.id)}"><span class="node-icon"><i data-lucide="${icon}"></i></span><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(hint)}</small></span>${trailing || '<i data-lucide="chevron-right"></i>'}</button>`;
}

function partyNamesFor(targetId, role) {
  const index = objectIndex();
  return (state.data.relations || [])
    .filter((item) => item.type === "participates_in" && item.to === targetId && item.properties?.participation_role === role)
    .map((item) => index[item.from]?.name)
    .filter(Boolean);
}

function renderDeliveryView() {
  const scopedIds = scopedObjectIds();
  let commitments = (state.data.objects || []).filter((item) => scopedIds.has(item.id) && ["framework_agreement", "contract"].includes(item.type));
  if (state.search) commitments = commitments.filter((item) => [item, ...businessChildren(item.id, "contains")].some(matchesSearch));
  return operationSectionHeader("履约交付", "从框架协议或项目合同进入订单和项目/任务，查看实际资源与知识资产", `${commitments.length} 项商务约定`)
    + `<div class="delivery-list">${commitments.map(renderDeliveryCommitment).join("") || operationEmpty("暂无履约事项")}</div>`;
}

function renderDeliveryCommitment(commitment) {
  const targetType = commitment.type === "framework_agreement" ? "order" : "work_item";
  const items = businessChildren(commitment.id, "contains", targetType);
  return `<article class="delivery-group">
    <button class="delivery-heading" data-business-object="${escapeAttr(commitment.id)}"><span class="type-icon ${escapeAttr(commitment.type)}"><i data-lucide="file-signature"></i></span><span><strong>${escapeHtml(commitment.name)}</strong><small>${escapeHtml(typeNames()[commitment.type]?.name || commitment.type)} · ${escapeHtml(partyNamesFor(commitment.id, "customer").join("、"))}</small></span><b>${items.length} 项履约</b><i data-lucide="chevron-right"></i></button>
    <div class="delivery-items">${items.map(renderDeliveryItem).join("") || `<div class="thread-empty"><i data-lucide="inbox"></i><span><strong>尚未建立履约事项</strong><small>${commitment.type === "framework_agreement" ? "可在协议下下达订单" : "可在合同下建立项目/任务"}</small></span></div>`}</div>
  </article>`;
}

function renderDeliveryItem(item) {
  const allocations = (state.data.relations || []).filter((relation) => relation.type === "allocated_to" && relation.to === item.id);
  const intellectualAssets = businessChildren(item.id, "involves_ip");
  const index = objectIndex();
  const resourceTypes = ["personnel", "software_resource", "hardware_resource"].map((type) => ({ type, count: allocations.filter((relation) => index[relation.from]?.type === type).length }));
  return `<div class="delivery-item">
    <button data-business-object="${escapeAttr(item.id)}"><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(typeNames()[item.type]?.name || item.type)}</small></span><i data-lucide="chevron-right"></i></button>
    <div class="delivery-facts">${resourceTypes.map(({ type, count }) => `<span><i data-lucide="${typeIcon(type)}"></i>${escapeHtml(typeNames()[type]?.name || type)} <b>${count}</b></span>`).join("")}<span><i data-lucide="badge-check"></i>知识资产 <b>${intellectualAssets.length}</b></span></div>
    ${allocations.length || intellectualAssets.length ? `<div class="allocation-list">${allocations.map((relation) => allocationChip(index[relation.from], relation)).join("")}${intellectualAssets.map((asset) => `<button data-business-object="${escapeAttr(asset.id)}"><i data-lucide="badge-check"></i>${escapeHtml(asset.name)}</button>`).join("")}</div>` : ""}
  </div>`;
}

function allocationChip(resource, relation) {
  if (!resource) return "";
  return `<button data-business-object="${escapeAttr(resource.id)}"><i data-lucide="${typeIcon(resource.type)}"></i>${escapeHtml(resource.name)}<small>${escapeHtml(relationFact(relation))}</small></button>`;
}

function renderFinanceView() {
  const scopedIds = scopedObjectIds();
  let parents = (state.data.objects || []).filter((item) => scopedIds.has(item.id) && ["contract", "order"].includes(item.type) && businessChildren(item.id, "contains", "invoice").length);
  if (state.search) parents = parents.filter((item) => [item, ...businessChildren(item.id, "contains", "invoice")].some(matchesSearch));
  return operationSectionHeader("开票回款", "按合同或订单汇总发票、回款核销和待回款余额", `${parents.length} 项开票业务`)
    + `<div class="finance-list">${parents.map(renderFinanceGroup).join("") || operationEmpty("暂无开票数据")}</div>`;
}

function renderFinanceGroup(parent) {
  const invoices = businessChildren(parent.id, "contains", "invoice");
  const total = sumObjectMoney(invoices);
  const settled = invoices.reduce((sum, invoice) => sum + settledForInvoice(invoice.id), 0);
  const outstanding = Math.max(0, total.amount - settled);
  const progress = total.amount ? Math.min(100, settled / total.amount * 100) : 0;
  return `<article class="finance-group">
    <button class="finance-heading" data-business-object="${escapeAttr(parent.id)}"><span><strong>${escapeHtml(parent.name)}</strong><small>${escapeHtml(typeNames()[parent.type]?.name || parent.type)} · ${invoices.length} 张发票</small></span><span class="finance-total"><b>${money(outstanding, total.currency || "CNY")}</b><small>待回款</small></span><i data-lucide="chevron-right"></i></button>
    <div class="finance-progress"><span style="width:${progress}%"></span></div>
    <div class="finance-columns"><span>发票</span><span>开票金额</span><span>已核销</span><span>余额</span></div>
    <div class="invoice-list">${invoices.map(renderInvoiceRow).join("")}</div>
  </article>`;
}

function settledForInvoice(invoiceId) {
  return (state.data.relations || []).filter((item) => item.type === "settles" && item.to === invoiceId)
    .reduce((total, item) => total + Number(item.properties?.settled_amount?.amount || 0), 0);
}

function renderInvoiceRow(invoice) {
  const value = invoice.properties?.amount || { amount: 0, currency: "CNY" };
  const allocations = (state.data.relations || []).filter((item) => item.type === "settles" && item.to === invoice.id);
  const settled = settledForInvoice(invoice.id);
  const balance = Math.max(0, Number(value.amount || 0) - settled);
  const index = objectIndex();
  return `<div class="invoice-row">
    <button data-business-object="${escapeAttr(invoice.id)}"><span><strong>${escapeHtml(invoice.name)}</strong><small>${escapeHtml(invoice.properties?.issued_date || "未记录日期")}</small></span><span>${money(value.amount, value.currency)}</span><span>${money(settled, value.currency)}</span><span class="${balance ? "amount-due" : "amount-clear"}">${money(balance, value.currency)}</span><i data-lucide="chevron-right"></i></button>
    ${allocations.length ? `<div class="receipt-allocations">${allocations.map((relation) => `<button data-business-object="${escapeAttr(relation.from)}"><i data-lucide="corner-down-right"></i><span>${escapeHtml(index[relation.from]?.name || relation.from)}</span><small>核销 ${escapeHtml(relationFact(relation))}</small></button>`).join("")}</div>` : `<div class="receipt-allocations empty">尚无回款核销</div>`}
  </div>`;
}

function renderResourceView() {
  const objects = scopedObjects();
  const resources = objects.filter((item) => ["personnel", "software_resource", "hardware_resource"].includes(item.type));
  const intellectualAssets = objects.filter((item) => item.type === "intellectual_asset");
  const filteredResources = state.search ? resources.filter(matchesSearch) : resources;
  return operationSectionHeader("资源资产", "人员、软件和硬件分别管理，以投入关系展示实际去向；知识资产显示所需或产出角色", `${resources.length + intellectualAssets.length} 项资产`)
    + `<div class="resource-sections">
      ${["personnel", "software_resource", "hardware_resource"].map((type) => renderResourceSection(type, filteredResources.filter((item) => item.type === type))).join("")}
      ${renderIntellectualAssetSection(state.search ? intellectualAssets.filter(matchesSearch) : intellectualAssets)}
    </div>`;
}

function renderResourceSection(type, resources) {
  return `<section class="resource-section"><div class="resource-section-heading"><span class="type-icon ${escapeAttr(type)}"><i data-lucide="${typeIcon(type)}"></i></span><div><h3>${escapeHtml(typeNames()[type]?.name || type)}</h3><span>${resources.length} 项</span></div></div><div class="resource-list">${resources.map(renderResourceRow).join("") || `<span class="muted-text">当前范围没有此类资源投入</span>`}</div></section>`;
}

function renderResourceRow(resource) {
  const allocations = (state.data.relations || []).filter((item) => item.type === "allocated_to" && item.from === resource.id);
  const index = objectIndex();
  return `<div class="resource-row"><button data-business-object="${escapeAttr(resource.id)}"><strong>${escapeHtml(resource.name)}</strong><small>${allocations.length} 个投入去向</small></button><div>${allocations.map((relation) => `<button data-business-object="${escapeAttr(relation.to)}"><span>${escapeHtml(index[relation.to]?.name || relation.to)}</span><small>${escapeHtml(relationFact(relation))}</small></button>`).join("") || '<span class="muted-text">暂无投入记录</span>'}</div></div>`;
}

function renderIntellectualAssetSection(assets) {
  const index = objectIndex();
  return `<section class="resource-section ip-section"><div class="resource-section-heading"><span class="type-icon intellectual_asset"><i data-lucide="badge-check"></i></span><div><h3>知识资产</h3><span>${assets.length} 项</span></div></div><div class="resource-list">${assets.map((asset) => {
    const link = (state.data.relations || []).find((item) => item.type === "involves_ip" && item.to === asset.id);
    return `<div class="resource-row"><button data-business-object="${escapeAttr(asset.id)}"><strong>${escapeHtml(asset.name)}</strong><small>${link?.properties?.ip_role === "required" ? "履约所需" : "履约产出"}</small></button><div><button data-business-object="${escapeAttr(link?.from || "")}"><span>${escapeHtml(index[link?.from]?.name || "未关联")}</span><small>${escapeHtml(typeNames()[index[link?.from]?.type]?.name || "履约对象")}</small></button></div></div>`;
  }).join("") || '<span class="muted-text">当前范围没有知识资产</span>'}</div></section>`;
}

function operationSectionHeader(title, description, count) {
  return `<div class="operation-section-heading"><div><span class="eyebrow">经营视图</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div><span>${escapeHtml(count)}</span></div>`;
}

function operationEmpty(message) {
  return `<div class="operation-empty"><i data-lucide="inbox"></i><strong>${escapeHtml(message)}</strong><span>调整经营主体或搜索条件后再试。</span></div>`;
}

function switchView(view) {
  state.view = view;
  $$(".nav-item[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$(".view").forEach((section) => section.classList.toggle("active", section.id === `${view}View`));
  renderCurrentView();
}

function renderCurrentView() {
  ({ operations: renderOperations, data: renderDataView, model: renderModel }[state.view] || renderOperations)();
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
    const period = props.issued_date || props.received_date || props.start_date || props.end_date || "-";
    const label = typeNames()[item.type]?.name || item.type;
    return `<tr data-object-id="${escapeAttr(item.id)}">
      <td><div class="object-cell"><div class="type-icon ${escapeAttr(item.type)}"><i data-lucide="${typeIcon(item.type)}"></i></div><div class="object-main"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.id)}</span></div></div></td>
      <td><span class="type-code" title="${escapeAttr(item.type)}">${escapeHtml(label)}</span></td>
      <td class="money">${escapeHtml(amount)}</td><td>${escapeHtml(period)}</td>
      <td>${objectMarker(item)}</td><td>${relationCount(item.id)}</td>
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
    const fact = relationFact(item);
    return `<tr data-relation-id="${escapeAttr(item.id)}">
      <td><div class="object-main"><strong>${escapeHtml(definition?.name || item.type)}</strong><span>${escapeHtml(item.type)}</span></div></td>
      <td>${endpoint(source)}</td><td class="direction-arrow"><i data-lucide="arrow-right"></i></td><td>${endpoint(target)}</td>
      <td>${escapeHtml(fact)}</td><td><button class="row-more" aria-label="查看详情"><i data-lucide="chevron-right"></i></button></td>
    </tr>`;
  }).join("");
  $$("#relationsTable tr").forEach((row) => row.addEventListener("click", () => showDetail("relation", row.dataset.relationId)));
  const summary = [
    ["users", state.data.relations.filter((item) => item.type === "participates_in").length, "主体参与"],
    ["waypoints", state.data.relations.filter((item) => ["contains", "derives"].includes(item.type)).length, "业务链路"],
    ["package-open", state.data.relations.filter((item) => ["allocated_to", "involves_ip"].includes(item.type)).length, "资源与知识资产"],
    ["badge-dollar-sign", state.data.relations.filter((item) => item.type === "settles").length, "回款核销"],
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
  const hasContextActions = kind === "object" && Object.values(state.data?.model?.actions || {})
    .some((action) => action.available_on?.some((type) => type === "*" || type === item.type));
  $("#contextActionBtn").classList.toggle("hidden", !hasContextActions);
  $("#detailDrawer").classList.add("open");
  $("#scrim").classList.remove("hidden");
  updateAgentContext();
  icons();
  if (kind !== "model") loadDetailHistory(kind, id);
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
    const fact = relationFact(rel);
    const role = fact !== "-" ? ` · ${fact}` : "";
    return `<button class="relation-link" type="button" data-related-object="${escapeAttr(other?.id || (outbound ? rel.to : rel.from))}"><i data-lucide="${outbound ? "arrow-right" : "arrow-left"}"></i><div><strong>${escapeHtml(relationNames()[rel.type]?.name || rel.type)}${escapeHtml(role)} · ${escapeHtml(other?.name || (outbound ? rel.to : rel.from))}</strong><span>${escapeHtml(typeNames()[other?.type]?.name || other?.type || "未知类型")} · ${escapeHtml(rel.id)}</span></div><i data-lucide="chevron-right"></i></button>`;
  }).join("") : `<span class="muted-text">暂无关系</span>`;
  return (kind === "object" ? businessPositionMarkup(item) : "")
    + detailSection("基本信息", Object.fromEntries(Object.entries(item).filter(([key]) => !["properties", "tags", "source_refs", "lifecycle"].includes(key))))
    + detailSection("Properties", item.properties || {})
    + (item.tags?.length ? detailSection("Tags", { tags: item.tags }) : "")
    + (item.source_refs?.length ? detailSection("来源引用", { source_refs: item.source_refs }) : "")
    + lifecycleMarkup(item.lifecycle)
    + `<div class="detail-section"><h3>相邻关系 · ${links.length}</h3><div>${linkMarkup}</div></div>`
    + `<div class="detail-section"><h3>变更历史</h3><div class="record-history" id="recordHistory"><div class="history-empty"><i data-lucide="loader-circle"></i><span>正在读取</span></div></div></div>`;
}

function lifecycleMarkup(lifecycle) {
  if (!lifecycle) return "";
  const values = {
    版本: `r${lifecycle.revision || 1}`,
    创建时间: formatTimestamp(lifecycle.created_at),
    最后变更: formatTimestamp(lifecycle.updated_at),
  };
  if (lifecycle.retired_at) values.退役时间 = formatTimestamp(lifecycle.retired_at);
  return detailSection("生命周期", values);
}

async function loadDetailHistory(kind, id) {
  const container = $("#recordHistory");
  if (!container) return;
  try {
    const result = await api("/api/records/history", {
      method: "POST",
      body: JSON.stringify({ kind, record_id: id, limit: 100 }),
    });
    if (state.selected?.kind !== kind || state.selected?.id !== id) return;
    container.innerHTML = historyMarkup(result.history || []);
    icons();
  } catch (error) {
    container.innerHTML = `<div class="history-empty"><i data-lucide="circle-alert"></i><span>${escapeHtml(error.message)}</span></div>`;
    icons();
  }
}

function historyMarkup(history) {
  if (!history.length) return `<div class="history-empty"><i data-lucide="history"></i><span>暂无可追溯的业务操作</span></div>`;
  return history.map((entry) => {
    const change = entry.change || {};
    const operation = {
      create_object: "创建对象", update_object: "更新对象", delete_object: "退役对象",
      create_relation: "建立关系", update_relation: "更新关系", delete_relation: "终止关系",
    }[change.operation] || change.operation || "变更";
    const differences = historyDifferences(change.before, change.after);
    return `<article class="history-item">
      <span class="history-marker"><i data-lucide="git-commit-horizontal"></i></span>
      <div class="history-main"><div><strong>${escapeHtml(entry.action_name || operation)}</strong><span>${escapeHtml(operation)}</span></div>
      <time>${escapeHtml(formatTimestamp(entry.created_at))} · ${escapeHtml(entry.actor || "-")} · ${escapeHtml(entry.channel || "-")}</time>
      ${entry.reason ? `<p>${escapeHtml(entry.reason)}</p>` : ""}
      ${differences.length ? `<details><summary>${differences.length} 项变化</summary><div class="history-differences">${differences.map((item) => `<div><code>${escapeHtml(item.path)}</code><span>${escapeHtml(item.before)} → ${escapeHtml(item.after)}</span></div>`).join("")}</div></details>` : ""}</div>
    </article>`;
  }).join("");
}

function historyDifferences(before, after) {
  const left = flattenRecord(before || {});
  const right = flattenRecord(after || {});
  return [...new Set([...Object.keys(left), ...Object.keys(right)])]
    .filter((key) => !key.startsWith("lifecycle.") && formatValue(left[key]) !== formatValue(right[key]))
    .map((key) => ({ path: key, before: formatValue(left[key]), after: formatValue(right[key]) }));
}

function flattenRecord(value, prefix = "", output = {}) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    Object.entries(value).forEach(([key, child]) => flattenRecord(child, prefix ? `${prefix}.${key}` : key, output));
  } else if (prefix) output[prefix] = value;
  return output;
}

function businessPositionMarkup(item) {
  const upstream = (state.data.relations || [])
    .filter((relation) => ["contains", "derives"].includes(relation.type) && relation.to === item.id)
    .map((relation) => objectIndex()[relation.from])
    .filter(Boolean);
  const downstream = (state.data.relations || [])
    .filter((relation) => ["contains", "derives"].includes(relation.type) && relation.from === item.id)
    .map((relation) => objectIndex()[relation.to])
    .filter(Boolean);
  const roles = (state.data.relations || [])
    .filter((relation) => relation.type === "participates_in" && relation.to === item.id)
    .map((relation) => `${objectIndex()[relation.from]?.name || relation.from} · ${relation.properties?.participation_role || "参与"}`);
  const facts = [];
  if (upstream.length) facts.push(["业务来源", upstream.map((parent) => parent.name).join("、")]);
  if (downstream.length) facts.push(["后续结果", downstream.map((child) => child.name).join("、")]);
  if (roles.length) facts.push(["参与主体", roles.join("；")]);
  if (item.type === "opportunity" && !businessChildren(item.id, "contains", "tender").length) facts.push(["当前阶段", "暂未进入招投标（合法状态）"]);
  if (item.type === "bid") facts.push(["投标结果", { awarded: "中标", not_awarded: "未中标" }[item.properties?.bid_result] || "待结果"]);
  if (item.type === "invoice") {
    const amount = item.properties?.amount || { amount: 0, currency: "CNY" };
    const settled = settledForInvoice(item.id);
    facts.push(["核销进度", `${money(settled, amount.currency)} / ${money(amount.amount, amount.currency)}`]);
    facts.push(["待回款", money(Math.max(0, Number(amount.amount || 0) - settled), amount.currency)]);
  }
  if (item.type === "receipt") {
    const value = item.properties?.amount || { amount: 0, currency: "CNY" };
    const settled = (state.data.relations || []).filter((relation) => relation.type === "settles" && relation.from === item.id)
      .reduce((total, relation) => total + Number(relation.properties?.settled_amount?.amount || 0), 0);
    facts.push(["核销进度", `${money(settled, value.currency)} / ${money(value.amount, value.currency)}`]);
  }
  if (!facts.length) return "";
  return `<div class="detail-section business-position"><h3>业务位置</h3><div class="detail-list">${facts.map(([label, value]) => `<div class="detail-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div></div>`;
}

function detailSection(title, values) {
  const rows = Object.entries(values).map(([key, value]) => `<div class="detail-row"><span>${escapeHtml(key)}</span><code>${escapeHtml(formatValue(value))}</code></div>`).join("");
  return `<div class="detail-section"><h3>${escapeHtml(title)}</h3><div class="detail-list">${rows || '<div class="detail-row"><span>-</span><code>无</code></div>'}</div></div>`;
}

function closeDetail() {
  $("#detailDrawer").classList.remove("open");
  $("#scrim").classList.add("hidden");
}
function closeOverlays() { closeDetail(); closeAgent(); }
function openAgent() { $(".app-shell").classList.remove("agent-collapsed"); $("#agentPanel").classList.add("open"); if (window.innerWidth <= 1180) $("#scrim").classList.remove("hidden"); }
function closeAgent() { $("#agentPanel").classList.remove("open"); if (window.innerWidth > 1180) $(".app-shell").classList.add("agent-collapsed"); if (!$("#detailDrawer").classList.contains("open")) $("#scrim").classList.add("hidden"); }

async function openActionLauncher(contextId = "") {
  state.actionContextType = "";
  state.actionContextCandidates = [];
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
    state.availableActions = contextId
      ? (result.actions || []).filter((action) => action.available_on?.length)
      : result.actions || [];
    const context = result.context;
    renderActionContext(context);
    renderActionCatalog();
  } catch (error) {
    $("#actionCatalog").innerHTML = `<div class="action-empty"><i data-lucide="circle-x"></i><span>${escapeHtml(error.message)}</span></div>`;
    icons();
  }
}

function openActionsForCurrentView() {
  if (state.view === "data" && state.dataKind === "object" && state.objectFilter !== "all") {
    openActionLauncherForType(state.objectFilter);
    return;
  }
  openActionLauncher("");
}

function openActionLauncherForType(contextType) {
  const candidates = (state.data?.objects || []).filter((item) => item.type === contextType);
  state.actionContextType = contextType;
  state.actionContextCandidates = candidates;
  state.actionContextId = candidates.length === 1 ? candidates[0].id : "";
  state.currentAction = null;
  state.availableActions = Object.entries(state.data?.model?.actions || {})
    .filter(([, action]) => action.available_on?.some((type) => type === "*" || type === contextType))
    .map(([id, action]) => ({ id, ...action }));
  $("#actionDialogTitle").textContent = "选择业务操作";
  $("#actionForm").classList.add("hidden");
  renderActionContext(candidates.length === 1 ? candidates[0] : {
    kind: "object_type",
    type: contextType,
    count: candidates.length,
  });
  renderActionCatalog();
  $("#actionDialog").showModal();
  icons();
}

function renderActionCatalog() {
  state.currentAction = null;
  $("#actionDialogTitle").textContent = "选择业务操作";
  $("#actionForm").classList.add("hidden");
  const catalog = $("#actionCatalog");
  catalog.classList.remove("hidden");
  catalog.innerHTML = state.availableActions.length
    ? state.availableActions.map((action) => {
      const blocked = action.executable === false;
      const reasons = (action.blocked_reasons || []).join("；");
      return `<button class="action-card ${blocked ? "blocked" : ""}" type="button" data-action-id="${escapeAttr(action.id)}" ${blocked ? "disabled" : ""} ${reasons ? `title="${escapeAttr(reasons)}"` : ""}>
        <span class="action-card-icon"><i data-lucide="${actionIcon(action.icon)}"></i></span>
        <span><strong>${escapeHtml(action.name)}</strong><small>${escapeHtml(blocked ? reasons : action.description)}</small></span>
        <i data-lucide="${blocked ? "lock-keyhole" : "chevron-right"}"></i>
      </button>`;
    }).join("")
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
  const preparedInputs = { ...initialInputs };
  if (action.context_input && state.actionContextId && preparedInputs[action.context_input] === undefined) {
    preparedInputs[action.context_input] = state.actionContextId;
  }
  $("#actionDialogTitle").textContent = action.name;
  $("#actionCatalog").classList.add("hidden");
  $("#actionForm").classList.remove("hidden");
  $("#actionFormError").classList.add("hidden");
  $("#actionFormBody").innerHTML = actionContextField(action) + Object.entries(action.inputs || {})
    .map(([inputId, definition]) => actionInputField(
      inputId,
      definition,
      Object.prototype.hasOwnProperty.call(preparedInputs, inputId) ? preparedInputs[inputId] : undefined,
    ))
    .join("");
  icons();
}

function actionContextField(action) {
  if (action.context_input) return "";
  if (!state.actionContextType || state.actionContextId) return "";
  const choices = state.actionContextCandidates.map((item) => `<label class="object-choice"><input type="radio" name="action_context_id" value="${escapeAttr(item.id)}" required><span><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(typeNames()[item.type]?.name || item.type)} · ${escapeHtml(item.id)}</small></span><i data-lucide="check"></i></label>`).join("");
  return `<div class="field action-input full" data-action-context><label>操作对象 <em>*</em></label><div class="object-choice-list">${choices || '<span class="muted-text">当前类型还没有可操作的对象</span>'}</div></div>`;
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
  const inputType = { number: "number", date: "date", datetime: "datetime-local", period: "month" }[valueType] || "text";
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
    const selectedContext = $('input[name="action_context_id"]:checked', form);
    const contextId = state.currentAction.context_input
      ? inputs[state.currentAction.context_input] || ""
      : selectedContext?.value || state.actionContextId;
    if (state.actionContextType && !contextId) throw new Error("请选择要执行操作的对象");
    const preview = await api("/api/actions/preview", {
      method: "POST",
      body: JSON.stringify({
        action_id: state.currentAction.id,
        inputs,
        context_id: contextId,
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
    ? context.kind === "object_type"
      ? `<i data-lucide="list-filter"></i><span>${escapeHtml(typeNames()[context.type]?.name || context.type)} · ${context.count} 个可选对象</span>`
      : `<i data-lucide="focus"></i><span>${escapeHtml(context.name)} · ${escapeHtml(typeNames()[context.type]?.name || context.type)}</span>`
    : "";
}

function openPresentedActionForm(payload) {
  if (payload?.kind !== "action_form" || !payload.action?.id) return;
  state.actionContextType = "";
  state.actionContextCandidates = [];
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
    ${field("对象 ID", "id", "text", "例如 opportunity:energy-002", true)}
    ${selectField("对象类型", "type", Object.entries(definitions).map(([id, def]) => [id, def.name]), true)}
    ${field("名称", "name", "text", "面向业务人员的清晰名称", true, "full")}
    ${instancePropertiesContainer()}
    ${field("Tags", "tags", "text", "多个标签用逗号分隔", false, "full")}
    ${field("其他 Properties", "extra_properties", "textarea", '{\n  "key": "value"\n}', false, "full", "填写 JSON 对象；会与上方属性合并。")}`;
}

function relationForm(definitions) {
  const objectOptions = state.data.objects.map((item) => [item.id, `${item.name} · ${typeNames()[item.type]?.name || item.type}`]);
  return `
    ${field("关系 ID", "id", "text", "例如 rel:opportunity-party-002", true)}
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
    ${field("Type ID", "type_id", "text", "例如 service_acceptance", true)}
    ${field("显示名称", "display_name", "text", "服务验收", true, "full")}
    ${field("业务定义", "description", "textarea", "说明它在企业运营中的含义", true, "full")}
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
  const inputType = { number: "number", date: "date", datetime: "datetime-local", period: "month" }[definition.type] || "text";
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
  const result = Object.fromEntries(Object.entries(typeNames()).filter(([, definition]) => definition.deprecated !== true));
  state.data.objects.forEach((item) => {
    if (!typeNames()[item.type]) result[item.type] ||= { name: item.type };
  });
  return result;
}

function relationTypeOptions() {
  const result = Object.fromEntries(Object.entries(relationNames()).filter(([, definition]) => definition.deprecated !== true));
  state.data.relations.forEach((item) => {
    if (!relationNames()[item.type]) result[item.type] ||= { name: item.type };
  });
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
  $("#actionReasonLabel").textContent = isAction ? "执行说明" : "变更说明";
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
      : await api("/api/changes/apply", {
          method: "POST",
          body: JSON.stringify({
            operations: state.pendingOperations,
            reason: $("#actionReason").value.trim(),
            actor: "web_user",
          }),
        });
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
  if (state.agentBusy || state.agentPending) return;
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
          setAgentPending(true);
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
    $(".send-button").disabled = state.agentPending;
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
  if (event.type === "question") {
    const options = Array.isArray(event.options) ? event.options.filter((option) => option?.label) : [];
    const inputType = event.multi_select ? "checkbox" : "radio";
    const choices = options.map((option) => `<label class="agent-question-option"><input type="${inputType}" name="agent_question_${state.sessionId}" value="${escapeAttr(option.label)}"><span><strong>${escapeHtml(option.label)}</strong>${option.description ? `<small>${escapeHtml(option.description)}</small>` : ""}</span><i data-lucide="check"></i></label>`).join("");
    const answerControl = choices || '<input class="agent-question-text" data-agent-answer-text type="text" aria-label="回答" autocomplete="off">';
    wrapper.innerHTML = `<div class="message-avatar"><i data-lucide="message-circle-question"></i></div><div class="message-body question-card" data-agent-question data-multi-select="${event.multi_select === true}"><strong>${escapeHtml(event.question || "请选择")}</strong><div class="agent-question-options">${answerControl}</div><div class="question-error hidden">请选择后再继续</div><div class="confirmation-actions"><button class="confirm-deny" data-agent-confirm="false">取消</button><button class="confirm-approve" data-agent-answer>继续</button></div></div>`;
  } else {
    const question = `Agent 请求执行 ${event.tool_name}`;
    wrapper.innerHTML = `<div class="message-avatar"><i data-lucide="shield-check"></i></div><div class="message-body confirmation-card"><strong>${escapeHtml(question)}</strong><pre>${escapeHtml(JSON.stringify(event.args || {}, null, 2))}</pre><div class="confirmation-actions"><button class="confirm-deny" data-agent-confirm="false">取消</button><button class="confirm-approve" data-agent-confirm="true">确认执行</button></div></div>`;
  }
  $("#agentMessages").append(wrapper); icons(); scrollAgent(true);
}

async function handleAgentClick(event) {
  const suggestion = event.target.closest(".suggestions button");
  if (suggestion) { $("#agentInput").value = suggestion.textContent; $("#agentForm").requestSubmit(); return; }
  const answerButton = event.target.closest("[data-agent-answer]");
  if (answerButton) {
    const card = answerButton.closest("[data-agent-question]");
    const textAnswer = $("[data-agent-answer-text]", card)?.value.trim();
    const selected = $$('input[type="radio"]:checked, input[type="checkbox"]:checked', card).map((input) => input.value);
    const answer = textAnswer || (card.dataset.multiSelect === "true" ? JSON.stringify(selected) : selected[0]);
    const error = $(".question-error", card);
    if (!answer || answer === "[]") { error.classList.remove("hidden"); return; }
    error.classList.add("hidden");
    $(".confirmation-actions", card).remove();
    $(".agent-question-options", card).insertAdjacentHTML("afterend", `<div class="question-answer"><i data-lucide="check"></i><span>${escapeHtml(card.dataset.multiSelect === "true" ? selected.join("、") : answer)}</span></div>`);
    setAgentPending(false);
    icons();
    await streamAgent("/api/agent/confirm", { session_id: state.sessionId, approved: true, answer });
    return;
  }
  const confirm = event.target.closest("[data-agent-confirm]");
  if (confirm) { confirm.closest(".confirmation-actions").remove(); setAgentPending(false); await streamAgent("/api/agent/confirm", { session_id: state.sessionId, approved: confirm.dataset.agentConfirm === "true" }); }
}

function setAgentPending(pending) {
  state.agentPending = pending;
  $("#agentInput").disabled = pending;
  $(".send-button").disabled = pending || state.agentBusy;
}

function askAboutSelection() { if (!state.selected) return; closeDetail(); openAgent(); $("#agentInput").value = `解释这个${state.selected.kind === "relation" ? "关系" : "对象"}及其业务含义：${state.selected.id}`; $("#agentInput").focus(); }
function clearAgentContext() { state.selected = null; updateAgentContext(); }
function updateAgentContext() { $("#agentContext span").textContent = state.selected ? `当前上下文：${state.selected.id}` : "当前上下文：全部业务对象"; }
function autoGrowTextarea(event) { const input = event.target; input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 160)}px`; }
function isAgentNearBottom() { const messages = $("#agentMessages"); return messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80; }
function scrollAgent(force = false) { const messages = $("#agentMessages"); if (force || isAgentNearBottom()) messages.scrollTop = messages.scrollHeight; }

function endpoint(item) { return `<div class="endpoint"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.id)} · ${escapeHtml(typeNames()[item.type]?.name || item.type)}</span></div>`; }
function actionIcon(icon) { return String(icon || "play").replaceAll("_", "-"); }
function relationFact(relation) {
  const props = relation.properties || {};
  if (props.settled_amount) return money(props.settled_amount.amount, props.settled_amount.currency);
  if (props.quantity !== undefined) {
    const period = props.start_date || props.end_date
      ? ` · ${props.start_date || "?"} 至 ${props.end_date || "?"}`
      : "";
    return `${props.quantity} ${props.unit || ""}${period}`.trim();
  }
  return props.participation_role || props.ip_role || props.status || "-";
}
function objectMarker(item) {
  const props = item.properties || {};
  if (item.type === "party") return props.is_managed
    ? statusPill("managed", "受管")
    : statusPill("external", "外部");
  if (item.type === "bid" && props.bid_result) {
    return statusPill(
      props.bid_result,
      { awarded: "中标", not_awarded: "未中标" }[props.bid_result] || props.bid_result,
    );
  }
  return statusPill(props.status);
}
function typeIcon(type) {
  if (type === "party") return "building-2";
  if (type === "opportunity") return "lightbulb";
  if (type === "tender") return "landmark";
  if (type === "bid") return "file-check-2";
  if (["framework_agreement", "contract"].includes(type)) return "file-signature";
  if (type === "order") return "clipboard-list";
  if (type === "work_item") return "briefcase-business";
  if (type === "personnel") return "users";
  if (type === "software_resource") return "app-window";
  if (type === "hardware_resource") return "server";
  if (type === "intellectual_asset") return "badge-check";
  if (type === "invoice") return "receipt-text";
  if (type === "receipt") return "circle-dollar-sign";
  return "box";
}
function statusPill(status, label = status) { return status ? `<span class="status-pill ${escapeAttr(status)}">${escapeHtml(label)}</span>` : '<span class="muted-text">-</span>'; }
function money(amount, currency = "CNY") { if (amount === null || amount === undefined || Number.isNaN(Number(amount))) return "-"; return new Intl.NumberFormat("zh-CN", { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(amount)); }
function formatValue(value) { return typeof value === "object" ? JSON.stringify(value, null, 2) : String(value ?? "-"); }
function formatTimestamp(value) { if (!value) return "-"; const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(date); }
function parseExtraProperties(value) { if (!value?.trim()) return {}; const parsed = JSON.parse(value); if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("其他 Properties 必须是 JSON 对象"); return parsed; }
function splitList(value) { return String(value || "").split(",").map((item) => item.trim()).filter(Boolean); }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]); }
function escapeAttr(value) { return escapeHtml(value); }
function toast(message, error = false) { const item = document.createElement("div"); item.className = `toast ${error ? "error" : ""}`; item.textContent = message; $("#toastRegion").append(item); setTimeout(() => item.remove(), 3200); }
