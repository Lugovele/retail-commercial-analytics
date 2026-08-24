const state = {
  runtime: null,
  catalog: [],
  options: { periods: [], entities: {} },
  summaryResponse: null,
  chartResponse: null,
  tableResponse: null,
  contributionResponse: null,
  activeView: "overview",
  periodMode: "COMPARE",
  comparisonMode: "YOY",
  currentGrain: "network",
  chartMetric: "revenue",
  previewGrain: "category",
  tablePageSize: 40,
  overviewPreviewRowLimit: 8,
  sortColumn: "Оборот",
  sortDirection: "desc",
  activeProvenanceConcept: "revenue"
};

const primaryKpis = ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct"];
const additiveContributionMetrics = ["revenue_vat", "revenue", "units", "retailer_margin_abs"];
const chartMetrics = ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct", "weighted_shelf_price_vat"];
const secondaryContextByGrain = {
  network: ["selling_store_count", "weighted_shelf_price_vat", "sku_count"],
  category: ["selling_store_count", "weighted_shelf_price_vat", "velocity"],
  manufacturer: ["selling_store_count", "weighted_shelf_price_vat", "category_revenue_share"],
  brand: ["category_revenue_share", "selling_store_count", "velocity"],
  sku: ["selling_store_count", "weighted_shelf_price_vat", "velocity"],
  store: ["sku_count", "revenue", "units"]
};
const driverBucketsByGrain = {
  network: [
    { title: "Объём", concepts: ["units"] },
    { title: "Цена", concepts: ["weighted_shelf_price_vat"] },
    { title: "Присутствие", concepts: ["selling_store_count", "distribution"] },
    { title: "Скорость", concepts: ["velocity", "revenue_velocity"] },
    { title: "Экономика", concepts: ["retailer_margin_pct", "retailer_margin_abs"] },
    { title: "Структура", concepts: ["sku_count", "brand_count", "category_count"] }
  ],
  category: [
    { title: "Объём", concepts: ["units"] },
    { title: "Цена", concepts: ["weighted_shelf_price_vat"] },
    { title: "Присутствие", concepts: ["distribution", "selling_store_count"] },
    { title: "Скорость", concepts: ["velocity", "revenue_velocity"] },
    { title: "Экономика", concepts: ["retailer_margin_pct", "retailer_margin_abs"] },
    { title: "Структура", concepts: ["sku_count", "brand_count"] }
  ],
  manufacturer: [
    { title: "Объём", concepts: ["units"] },
    { title: "Цена", concepts: ["weighted_shelf_price_vat"] },
    { title: "Присутствие", concepts: ["distribution", "selling_store_count"] },
    { title: "Скорость", concepts: ["velocity", "revenue_velocity"] },
    { title: "Экономика", concepts: ["retailer_margin_pct", "retailer_margin_abs"] },
    { title: "Структура", concepts: ["category_revenue_share", "sku_count"] }
  ],
  brand: [
    { title: "Объём", concepts: ["units"] },
    { title: "Цена", concepts: ["weighted_shelf_price_vat"] },
    { title: "Присутствие", concepts: ["distribution", "selling_store_count"] },
    { title: "Скорость", concepts: ["velocity", "revenue_velocity"] },
    { title: "Экономика", concepts: ["retailer_margin_pct", "retailer_margin_abs"] },
    { title: "Структура", concepts: ["category_revenue_share", "sku_count"] }
  ],
  sku: [
    { title: "Объём", concepts: ["units"] },
    { title: "Цена", concepts: ["weighted_shelf_price_vat"] },
    { title: "Присутствие", concepts: ["selling_store_count", "distribution"] },
    { title: "Скорость", concepts: ["velocity", "revenue_velocity"] },
    { title: "Экономика", concepts: ["retailer_margin_pct", "retailer_margin_abs"] },
    { title: "Структура", concepts: ["selling_store_count"] }
  ],
  store: [
    { title: "Объём", concepts: ["units"] },
    { title: "Цена", concepts: ["weighted_shelf_price_vat"] },
    { title: "Присутствие", concepts: ["sku_count"] },
    { title: "Скорость", concepts: [] },
    { title: "Экономика", concepts: ["retailer_margin_pct", "retailer_margin_abs"] },
    { title: "Структура", concepts: ["sku_count", "brand_count"] }
  ]
};
const previewColumns = {
  category: ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct", "sku_count", "selling_store_count"],
  manufacturer: ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct"],
  brand: ["revenue", "units", "retailer_margin_abs", "category_revenue_share"],
  sku: ["revenue", "units", "retailer_margin_abs", "weighted_shelf_price_vat", "selling_store_count"],
  store: ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct", "sku_count"]
};
const grainLabels = {
  network: "Все данные",
  category: "Категория",
  manufacturer: "Производитель",
  brand: "Бренд",
  sku: "SKU",
  store: "ТТ"
};
const previewByGrain = {
  network: "category",
  category: "manufacturer",
  manufacturer: "brand",
  brand: "sku",
  sku: "store"
};
const comparisonLabels = {
  YOY: "Год к году",
  MOM: "Месяц к месяцу",
  PREVIOUS_AVAILABLE: "Предыдущий доступный период",
  NONE: "Без сравнения"
};
const filterConfig = {
  category: { label: "Все категории", childFilters: ["manufacturer", "brand", "sku"] },
  manufacturer: { label: "Все производители", childFilters: ["brand", "sku"] },
  brand: { label: "Все бренды", childFilters: ["sku"] },
  sku: { label: "Все SKU", childFilters: [] },
  store: { label: "Все ТТ", childFilters: [] }
};
const searchFilterIds = ["manufacturer", "brand", "sku", "store"];

document.addEventListener("DOMContentLoaded", async () => {
  bindStaticControls();
  await initializeDashboard();
});

function bindStaticControls() {
  document.querySelectorAll("[data-period-mode]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.periodMode = button.dataset.periodMode;
      document.querySelectorAll("[data-period-mode]").forEach((item) => {
        item.classList.toggle("is-active", item === button);
      });
      updatePeriodPanels();
      await runOverviewQuery();
    });
  });

  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      setActiveView(button.dataset.view);
    });
  });
  document.querySelectorAll("[data-header-action]").forEach((button) => {
    if (button.disabled) return;
    button.addEventListener("click", () => {
      if (button.dataset.headerAction === "reports") openReportsPanel();
    });
  });

  document.querySelectorAll("[data-drill-grain]").forEach((button) => {
    button.addEventListener("click", async () => {
      const targetGrain = button.dataset.drillGrain;
      if (!canActivateSummaryGrain(targetGrain)) {
        showToast(`Сначала выберите объект уровня «${grainLabels[targetGrain]}».`);
        return;
      }
      state.currentGrain = targetGrain;
      updateBreadcrumb();
      updatePreviewGrain();
      await runOverviewQuery();
    });
  });

  document.querySelectorAll("[data-open-provenance]").forEach((button) => {
    button.addEventListener("click", () => openProvenance(state.activeProvenanceConcept));
  });
  document.getElementById("close-drawer").addEventListener("click", closeProvenance);
  document.getElementById("scrim").addEventListener("click", closeProvenance);
  document.getElementById("close-reports-panel").addEventListener("click", closeReportsPanel);
  document.getElementById("scrim").addEventListener("click", closeReportsPanel);
  document.getElementById("reset-filters").addEventListener("click", async () => {
    resetAllEntityFilters();
    await refreshRuntimeOptions();
    updatePreviewGrain();
    await runOverviewQuery();
  });
  const filterDrawer = document.querySelector(".filter-drawer");
  filterDrawer?.querySelector("summary")?.setAttribute("aria-expanded", filterDrawer.open ? "true" : "false");
  filterDrawer?.addEventListener("toggle", () => {
    filterDrawer.querySelector("summary")?.setAttribute("aria-expanded", filterDrawer.open ? "true" : "false");
  });
}

async function initializeDashboard() {
  try {
    setLoading(true, "Загрузка данных");
    state.runtime = await getJson("/api/dashboard/runtime");
    setupRetailerControl();
    await loadCatalog();
    await refreshRuntimeOptions({ resetPeriods: true, resetEntities: true });
    bindDynamicControls();
    updatePeriodPanels();
    updatePrivateLabelTerminology();
    updatePreviewGrain();
    setActiveView(state.activeView);
    renderChartMetricOptions();
    await runOverviewQuery();
  } catch (error) {
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

function setActiveView(view) {
  const target = view || "overview";
  state.activeView = target;
  document.querySelectorAll("[data-view]").forEach((button) => {
    const isActive = button.dataset.view === target;
    button.classList.toggle("is-active", isActive);
    if (isActive) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    const isActive = panel.dataset.viewPanel === target;
    panel.classList.toggle("is-hidden", !isActive);
  });
}

function setupRetailerControl() {
  const retailerSelect = document.getElementById("retailer-select");
  retailerSelect.replaceChildren(
    ...state.runtime.retailers.map((retailer) => option(retailer.retailer_id, retailer.display_label))
  );
  retailerSelect.value = state.runtime.default_retailer_id;
  retailerSelect.addEventListener("change", async () => {
    resetAllEntityFilters();
    await loadCatalog();
    await refreshRuntimeOptions({ resetPeriods: true, resetEntities: true });
    updatePrivateLabelTerminology();
    updatePreviewGrain();
    await runOverviewQuery();
  });
}

function bindDynamicControls() {
  document.getElementById("comparison-mode").addEventListener("change", async (event) => {
    state.comparisonMode = event.target.value;
    await runOverviewQuery();
  });
  document.getElementById("private-label-toggle").addEventListener("change", async (event) => {
    document.getElementById("private-label-scope").value = event.target.checked ? "INCLUDE" : "EXCLUDE";
    await refreshRuntimeOptions({ resetEntities: true });
    await runOverviewQuery();
  });
  document.getElementById("private-label-scope").addEventListener("change", async (event) => {
    document.getElementById("private-label-toggle").checked = event.target.value === "INCLUDE";
    await refreshRuntimeOptions({ resetEntities: true });
    await runOverviewQuery();
  });
  document.getElementById("chart-metric").addEventListener("change", async (event) => {
    state.chartMetric = event.target.value;
    state.activeProvenanceConcept = event.target.value;
    await runOverviewQuery();
  });
  document.getElementById("preview-grain").addEventListener("change", async (event) => {
    state.previewGrain = event.target.value;
    await runOverviewQuery();
  });

  for (const id of Object.keys(filterConfig)) {
    const select = document.getElementById(`${id}-filter`);
    select.addEventListener("change", async () => {
      resetChildFilters(id);
      applyFilterDrilldown(id);
      await refreshRuntimeOptions();
      updatePreviewGrain();
      await runOverviewQuery();
    });
  }

  searchFilterIds.forEach((id) => {
    const input = document.getElementById(`${id}-search`);
    input.addEventListener("input", () => populateEntityFilter(id));
    input.addEventListener("focus", () => populateEntityFilter(id));
    input.addEventListener("keydown", (event) => handleComboboxKeydown(event, id));
    document.querySelector(`[data-combobox="${id}"]`)?.addEventListener("focusout", () => {
      setTimeout(() => {
        const control = document.querySelector(`[data-combobox="${id}"]`);
        if (!control?.contains(document.activeElement)) closeCombobox(id);
      }, 0);
    });
  });

  document.querySelectorAll("[data-clear-filter]").forEach((button) => {
    button.addEventListener("click", async () => {
      clearEntityFilter(button.dataset.clearFilter);
      await refreshRuntimeOptions();
      updatePreviewGrain();
      await runOverviewQuery();
    });
  });

  ["period-single", "period-a", "date-from", "date-to"].forEach((id) => {
    document.getElementById(id).addEventListener("change", async () => {
      await refreshRuntimeOptions({ resetEntities: true });
      await runOverviewQuery();
    });
  });
}

async function loadCatalog() {
  const retailer = selectedRetailer();
  const payload = await getJson(
    `/api/dashboard/catalog?retailer_id=${encodeURIComponent(retailer.retailer_id)}&source_id=${encodeURIComponent(retailer.source_id)}`
  );
  state.catalog = payload.metrics;
}

async function loadOptions() {
  const retailer = selectedRetailer();
  const params = new URLSearchParams({
    retailer_id: retailer.retailer_id,
    source_id: retailer.source_id,
    private_label_scope: document.getElementById("private-label-scope").value
  });
  const dateFrom = selectedDateFrom();
  const dateTo = selectedDateTo();
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  Object.entries(selectedFilterValues()).forEach(([key, value]) => params.set(key, value));
  state.options = await getJson(`/api/dashboard/options?${params.toString()}`);
}

async function refreshRuntimeOptions({ resetPeriods = false, resetEntities = false } = {}) {
  if (resetEntities) resetAllEntityFilters();
  await loadOptions();
  populatePeriodSelects(resetPeriods);
  populateEntityFilters();
}

function populatePeriodSelects(resetPeriods) {
  const periods = state.options.periods.map((period) => period.value);
  const latest = periods[periods.length - 1];
  const earliest = periods[0];
  setupPeriodSelect("period-single", latest, resetPeriods);
  setupPeriodSelect("period-a", latest, resetPeriods);
  setupPeriodSelect("date-from", earliest, resetPeriods);
  setupPeriodSelect("date-to", latest, resetPeriods);
}

function setupPeriodSelect(id, selected, resetSelection) {
  const select = document.getElementById(id);
  const previous = select.value;
  select.replaceChildren(...state.options.periods.map((period) => option(period.value, formatPeriod(period.value))));
  select.value = !resetSelection && previous && state.options.periods.some((period) => period.value === previous)
    ? previous
    : selected;
}

async function runOverviewQuery() {
  setLoading(true, "Запрос к витрине");
  renderSkeletons();
  try {
    const summaryPayload = buildQueryPayload(state.currentGrain, entityIdsForSummary(), overviewConcepts());
    const chartPayload = buildChartQueryPayload();
    const previewPayload = buildQueryPayload(state.previewGrain, entityIdsForPreview(), tableConcepts());
    state.summaryResponse = await postJson("/api/dashboard/query", summaryPayload);
    state.chartResponse = await postJson("/api/dashboard/query", chartPayload);
    state.contributionResponse = await loadContributionRows();
    state.tableResponse = await postJson("/api/dashboard/query", previewPayload);
    renderOverview();
    setLoading(false, "Данные обновлены");
  } catch (error) {
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

async function loadContributionRows() {
  const payload = buildContributionPayload();
  if (!payload) return null;
  return postJson("/api/dashboard/contribution", payload);
}

function buildQueryPayload(grain, entityIds, metricConcepts) {
  const retailer = selectedRetailer();
  const periodMode = backendPeriodMode();
  return {
    retailer_id: retailer.retailer_id,
    source_id: retailer.source_id,
    date_from: selectedDateFrom(),
    date_to: selectedDateTo(),
    period_mode: periodMode,
    period_grain: "month",
    grain_id: grain,
    entity_ids: entityIds,
    entity_filters: selectedParentFiltersForGrain(grain),
    metric_concepts: metricConcepts,
    comparison_mode: periodMode === "SINGLE_PERIOD" ? selectedComparisonMode() : "NONE",
    include_lineage: true,
    mart_build_id: retailer.default_mart_build_id,
    private_label_scope: document.getElementById("private-label-scope").value
  };
}

function buildChartQueryPayload() {
  const periods = state.options.periods.map((period) => period.value);
  const dateFrom = state.periodMode === "DATE_RANGE" ? selectedDateFrom() : periods[0] || selectedDateFrom();
  const dateTo = state.periodMode === "DATE_RANGE" ? selectedDateTo() : periods[periods.length - 1] || selectedDateTo();
  return {
    ...buildQueryPayload(state.currentGrain, entityIdsForSummary(), [state.chartMetric]),
    date_from: dateFrom,
    date_to: dateTo,
    period_mode: "DATE_RANGE",
    comparison_mode: "NONE"
  };
}

function buildContributionPayload() {
  if (state.periodMode !== "COMPARE") return null;
  const metricConcept = contributionMetricForOverview();
  if (!metricConcept) return null;
  const comparison = state.summaryResponse?.comparisons?.[0];
  if (!comparison?.comparison_period_start) return null;
  const parentEntityIds = entityIdsForSummary();
  const parentEntityId = parentEntityIds[0] || null;
  const retailer = selectedRetailer();
  return {
    retailer_id: retailer.retailer_id,
    source_id: retailer.source_id,
    current_period: selectedDateFrom(),
    reference_period: comparison.comparison_period_start,
    period_grain: "month",
    parent_grain_id: state.currentGrain,
    parent_entity_id: parentEntityId,
    child_grain_id: state.previewGrain,
    metric_concept: metricConcept,
    comparison_mode: selectedComparisonMode(),
    private_label_scope: document.getElementById("private-label-scope").value,
    mart_build_id: retailer.default_mart_build_id,
    limit: state.overviewPreviewRowLimit
  };
}

function backendPeriodMode() {
  return state.periodMode === "DATE_RANGE" ? "DATE_RANGE" : "SINGLE_PERIOD";
}

function overviewConcepts() {
  return [...new Set([
    ...primaryKpis,
    ...chartMetrics,
    ...Object.values(secondaryContextByGrain).flat(),
    ...Object.values(driverBucketsByGrain).flatMap((groups) => groups.flatMap((group) => group.concepts))
  ])]
    .filter((concept) => catalogEntry(concept));
}

function tableConcepts() {
  return previewColumns[state.previewGrain].filter((concept) => catalogEntry(concept));
}

function renderOverview() {
  renderContextStrip();
  renderBreadcrumb();
  renderChartMetricOptions();
  renderKpis();
  renderKpiSecondaryContext();
  renderChart();
  renderDiagnosis();
  renderAttention();
  renderOverviewTable();
}

function renderKpis() {
  const grid = document.getElementById("kpi-grid");
  grid.replaceChildren(...primaryKpis.map((concept) => {
    const result = summaryResultFor(concept);
    const entry = catalogEntry(concept);
    const card = document.createElement("article");
    card.className = "kpi-card";
    if (!result || !entry) {
      card.classList.add("is-unavailable");
      appendText(card, "small", entry?.display_label || concept);
      appendText(card, "strong", "Недоступно");
      appendText(card, "span", "Показатель недоступен для выбранного среза.");
      return card;
    }
    const comparison = comparisonFor(state.summaryResponse, result);
    appendText(card, "small", displayLabel(concept));
    appendText(card, "strong", formatValue(result.value, entry.format));
    const meta = document.createElement("span");
    meta.className = "kpi-meta";
    meta.textContent = kpiContextText(comparison, entry);
    card.appendChild(meta);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "inline-link";
    button.textContent = "Откуда?";
    button.addEventListener("click", () => openProvenance(concept));
    card.appendChild(button);
    return card;
  }));
}

function renderKpiSecondaryContext() {
  const container = document.getElementById("kpi-secondary");
  const concepts = (secondaryContextByGrain[state.currentGrain] || [])
    .filter((concept) => visibleSummaryResult(concept))
    .slice(0, 3);
  if (!concepts.length) {
    container.replaceChildren();
    return;
  }
  container.replaceChildren(...concepts.map((concept) => {
    const result = summaryResultFor(concept);
    const entry = catalogEntry(concept);
    const item = document.createElement("article");
    item.className = "secondary-metric";
    appendText(item, "span", displayLabel(concept));
    appendText(item, "strong", compactMetricText(result, entry));
    const button = document.createElement("button");
    button.type = "button";
    button.className = "inline-link";
    button.textContent = "Откуда?";
    button.addEventListener("click", () => openProvenance(concept));
    item.appendChild(button);
    return item;
  }));
}

function renderChart() {
  const chartResult = chartResultFor(state.chartMetric);
  const result = chartResult || summaryResultFor(state.chartMetric);
  const coverage = chartResult ? state.chartResponse : state.summaryResponse;
  const entry = catalogEntry(state.chartMetric);
  const box = document.getElementById("chart-box");
  const footnote = document.getElementById("chart-footnote");
  if (!result || !entry) {
    replaceWithMessage(box, "empty-state", "Показатель недоступен для выбранного среза.");
    footnote.textContent = "";
    return;
  }
  const points = result.period_values
    .map((item) => ({ period: item.period_start, value: item.value }))
    .filter((item) => item.value !== null && item.value !== undefined);
  if (!points.length) {
    replaceWithMessage(box, "empty-state", "За выбранный период данных нет.");
    footnote.textContent = limitationText(result);
    return;
  }
  box.replaceChildren(buildSvgChart(points, entry));
  const missing = (coverage?.missing_periods || []).map(formatPeriod).join(", ");
  const limitation = limitationText(result);
  footnote.textContent = [
    missing ? `Пропущены периоды: ${missing}` : "Все запрошенные периоды с данными показаны.",
    limitation
  ].filter(Boolean).join(" ");
}

function buildSvgChart(points, entry) {
  const width = 860;
  const height = 336;
  const pad = { left: 72, right: 28, top: 22, bottom: 58 };
  const svg = svgEl("svg", { class: "chart-svg", viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `${entry.display_label}: динамика` });
  const values = points.map((point) => point.value);
  const max = Math.max(...values, 1);
  const min = Math.min(0, ...values);
  const range = max - min || 1;
  const x = (index) => pad.left + (index * (width - pad.left - pad.right)) / Math.max(points.length - 1, 1);
  const y = (value) => pad.top + (max - value) * (height - pad.top - pad.bottom) / range;

  for (let tick = 0; tick <= 4; tick += 1) {
    const value = min + (range * tick) / 4;
    const yy = y(value);
    svg.appendChild(svgEl("line", { class: "grid-line", x1: pad.left, y1: yy, x2: width - pad.right, y2: yy }));
    svg.appendChild(svgText(pad.left - 10, yy + 4, formatValue(value, entry.format), "end", "axis-label"));
  }
  svg.appendChild(svgEl("line", { class: "axis-line", x1: pad.left, y1: height - pad.bottom, x2: width - pad.right, y2: height - pad.bottom }));
  svg.appendChild(svgEl("line", { class: "axis-line", x1: pad.left, y1: pad.top, x2: pad.left, y2: height - pad.bottom }));
  svg.appendChild(svgText(pad.left, 14, unitLabel(entry.format), "start", "axis-unit"));

  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${x(index)} ${y(point.value)}`).join(" ");
  svg.appendChild(svgEl("path", { class: "chart-line", d: path }));
  points.forEach((point, index) => {
    svg.appendChild(svgText(x(index), height - 30, formatPeriod(point.period), "middle", "axis-label"));
    const circle = svgEl("circle", { class: "chart-point", cx: x(index), cy: y(point.value), r: 5, tabindex: 0 });
    const tooltip = `${formatPeriod(point.period)} · ${entry.display_label}: ${formatValue(point.value, entry.format)}`;
    circle.addEventListener("mousemove", (event) => showTooltip(event, tooltip));
    circle.addEventListener("focus", (event) => showTooltip(event, tooltip));
    circle.addEventListener("mouseleave", hideTooltip);
    circle.addEventListener("blur", hideTooltip);
    circle.addEventListener("click", () => openProvenance(entry.metric_concept));
    svg.appendChild(circle);
  });
  comparisonMarkerPeriods().forEach((period) => {
    const index = points.findIndex((point) => point.period === period);
    if (index >= 0) {
      svg.appendChild(svgEl("line", { class: "comparison-marker", x1: x(index), y1: pad.top, x2: x(index), y2: height - pad.bottom }));
      svg.appendChild(svgText(x(index), pad.top + 14, period === selectedDateFrom() ? "A" : "B", "middle", "marker-label"));
    }
  });
  return svg;
}

function renderDiagnosis() {
  const grid = document.getElementById("diagnosis-grid");
  const usedConcepts = new Set();
  const cards = [];
  (driverBucketsByGrain[state.currentGrain] || driverBucketsByGrain.network).forEach((group) => {
    const concept = representativeConcept(group.concepts, usedConcepts);
    if (!concept) return;
    usedConcepts.add(concept);
    const card = document.createElement("article");
    card.className = "diagnosis-card";
    appendText(card, "h3", group.title);
    const result = summaryResultFor(concept);
    const entry = catalogEntry(concept);
    appendText(card, "span", displayLabel(concept));
    appendText(card, "strong", compactMetricText(result, entry));
    appendText(card, "p", movementText(result, entry));
    if (result?.provenance) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "inline-link";
      button.textContent = "Откуда?";
      button.addEventListener("click", () => openProvenance(concept));
      card.appendChild(button);
    }
    cards.push(card);
  });
  if (!cards.length) {
    replaceWithMessage(grid, "empty-state", "Для выбранного среза нет поддержанных показателей.");
    return;
  }
  grid.replaceChildren(...cards);
}

function renderAttention() {
  const list = document.getElementById("attention-list");
  const items = attentionItems();
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state compact";
    empty.textContent = "Для выбранного среза нет подтверждённых сигналов.";
    list.replaceChildren(empty);
    return;
  }
  list.replaceChildren(...items.slice(0, 3).map((item) => {
    const node = document.createElement("article");
    node.className = `attention-item ${item.kind || ""}`;
    appendText(node, "strong", item.title);
    appendText(node, "span", item.text);
    if (item.concept) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "inline-link";
      button.textContent = "Проверить";
      button.addEventListener("click", () => openProvenance(item.concept));
      node.appendChild(button);
    }
    return node;
  }));
}

function renderOverviewTable() {
  const table = document.getElementById("overview-table");
  if (hasContributionRows()) {
    renderContributionTable(table);
    return;
  }
  const concepts = tableConcepts();
  const headers = [grainLabels[state.previewGrain], ...concepts.map(displayLabel)];
  if (!state.tableResponse?.metric_results?.length) {
    renderMessageRow(table, "За выбранный период данных нет.");
    document.getElementById("table-title").textContent = "Объекты в выбранном срезе";
    document.getElementById("table-context").textContent = tableContextText(0, contributionFallbackReason());
    return;
  }
  const entities = [...new Set(state.tableResponse.metric_results.map((result) => result.entity_id))];
  const rows = entities.map((entityId) => {
    const cells = concepts.map((concept) => {
      const result = tableResultFor(concept, entityId);
      const entry = catalogEntry(concept);
      return result && entry ? metricCellText(result, entry, state.tableResponse) : "Недоступно";
    });
    return [entityId, ...cells];
  });
  renderRows(table, headers, rows, {
    onFirstCellClick: (entityId) => drillIntoEntity(String(entityId)),
    rowLimit: state.overviewPreviewRowLimit
  });
  const caption = table.createCaption();
  caption.textContent = `Показаны первые ${Math.min(rows.length, state.overviewPreviewRowLimit)} из ${entities.length}`;
  document.getElementById("table-title").textContent = "Объекты в выбранном срезе";
  document.getElementById("table-context").textContent = tableContextText(entities.length, contributionFallbackReason());
}

function hasContributionRows() {
  return ["READY", "TOTAL_DELTA_ZERO"].includes(state.contributionResponse?.status)
    && Boolean(state.contributionResponse?.rows?.length);
}

function renderContributionTable(table) {
  const metric = catalogEntry(state.contributionResponse.metric_concept);
  document.getElementById("table-title").textContent = "Где произошло изменение?";
  const headers = [
    grainLabels[state.previewGrain],
    "Текущий период",
    "Период сравнения",
    "Изменение",
    "Вклад в изменение",
    "Доказательство"
  ];
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach((header) => {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = header;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  const tbody = document.createElement("tbody");
  state.contributionResponse.rows.slice(0, state.overviewPreviewRowLimit).forEach((row) => {
    const tr = document.createElement("tr");
    const entityCell = document.createElement("td");
    const entityButton = document.createElement("button");
    entityButton.type = "button";
    entityButton.className = "table-link";
    entityButton.textContent = entityDisplayLabel(state.previewGrain, row.child_entity_id);
    entityButton.addEventListener("click", () => drillIntoEntity(String(row.child_entity_id)));
    entityCell.appendChild(entityButton);
    tr.appendChild(entityCell);
    [
      formatValue(row.current_value, metric?.format || "decimal"),
      formatValue(row.reference_value, metric?.format || "decimal"),
      formatDeltaValue(row.delta, metric?.format || "decimal"),
      row.contribution_share === null ? "н/д" : formatValue(row.contribution_share, "percent")
    ].forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    });
    const actionCell = document.createElement("td");
    const provenanceButton = document.createElement("button");
    provenanceButton.type = "button";
    provenanceButton.className = "text-button";
    provenanceButton.textContent = "Откуда?";
    provenanceButton.addEventListener("click", () => openContributionProvenance(row));
    actionCell.appendChild(provenanceButton);
    tr.appendChild(actionCell);
    tbody.appendChild(tr);
  });
  table.replaceChildren(thead, tbody);
  const caption = table.createCaption();
  caption.textContent = `Показаны первые ${Math.min(state.contributionResponse.rows.length, state.overviewPreviewRowLimit)} · сортировка по абсолютному изменению`;
  const zeroNote = state.contributionResponse.status === "TOTAL_DELTA_ZERO"
    ? " Вклад в общее изменение не рассчитывается: итоговое изменение равно нулю."
    : "";
  document.getElementById("table-context").textContent =
    `Объекты с наибольшим вкладом в изменение. Ранжирование по изменению: ${displayLabel(state.contributionResponse.metric_concept)}. ${contributionMixedSignNote()}${zeroNote}`.trim();
}

function renderContextStrip() {
  const response = state.summaryResponse;
  if (!response) return;
  updateComparisonPeriodDisplay(response);
  updateFilterCount();
  document.getElementById("context-strip").textContent = contextFilterText();
  document.getElementById("context-coverage-note").textContent = coverageNoteText(response);
}

function renderBreadcrumb() {
  document.querySelectorAll("[data-drill-grain]").forEach((button) => {
    updateBreadcrumbButton(button);
  });
}

function renderChartMetricOptions() {
  const select = document.getElementById("chart-metric");
  const metrics = chartMetrics.filter((concept) => catalogEntry(concept));
  select.replaceChildren(...metrics.map((concept) => option(concept, displayLabel(concept))));
  if (!metrics.includes(state.chartMetric)) state.chartMetric = metrics[0] || "revenue";
  select.value = state.chartMetric;
}

function renderSkeletons() {
  document.getElementById("kpi-grid").replaceChildren(...primaryKpis.map(() => {
    const card = document.createElement("article");
    card.className = "kpi-card is-loading";
    return card;
  }));
  document.getElementById("kpi-secondary").replaceChildren();
  replaceWithMessage(document.getElementById("chart-box"), "loading-state", "Загрузка динамики...");
}

function attentionItems() {
  const items = [];
  if (state.summaryResponse.coverage_status === "PARTIAL" && state.summaryResponse.missing_periods.length) {
    items.push({
      title: "Неполное покрытие данных",
      text: `${state.summaryResponse.available_periods.length} периодов с данными · ${state.summaryResponse.missing_periods.length} пропущено`,
      kind: "warning"
    });
  }
  const comparisonMissing = state.summaryResponse.limitations.find((item) => item.issue_code === "comparison_period_missing");
  if (comparisonMissing) {
    items.push({
      title: "Нет периода сравнения",
      text: "Для выбранного периода нет подходящего референса.",
      kind: "warning"
    });
  }
  return items;
}

function updatePeriodPanels() {
  document.getElementById("single-fields").classList.toggle("is-hidden", state.periodMode !== "SINGLE_PERIOD");
  document.getElementById("compare-fields").classList.toggle("is-hidden", state.periodMode !== "COMPARE");
  document.getElementById("range-fields").classList.toggle("is-hidden", state.periodMode !== "DATE_RANGE");
}

function updateBreadcrumb() {
  document.querySelectorAll("[data-drill-grain]").forEach((button) => {
    updateBreadcrumbButton(button);
  });
}

function updateBreadcrumbButton(button) {
  const grain = button.dataset.drillGrain;
  const canActivate = canActivateSummaryGrain(grain);
  button.classList.toggle("is-active", grain === state.currentGrain);
  button.disabled = !canActivate;
  button.title = canActivate ? "Перейти к выбранному уровню" : `Сначала выберите объект уровня «${grainLabels[grain]}».`;
}

function canActivateSummaryGrain(grain) {
  if (grain === "network") return true;
  return Boolean(document.getElementById(`${grain}-filter`)?.value);
}

function updateComparisonPeriodDisplay(response) {
  const target = document.getElementById("period-b-derived");
  if (!target) return;
  if (state.periodMode !== "COMPARE") {
    target.textContent = "Не используется";
    return;
  }
  const comparison = response?.comparisons?.[0];
  target.textContent = comparison?.comparison_period_start
    ? formatPeriod(comparison.comparison_period_start)
    : "Нет подходящего периода";
}

function updatePreviewGrain() {
  const defaultPreview = previewByGrain[state.currentGrain] || "store";
  state.previewGrain = defaultPreview;
  const select = document.getElementById("preview-grain");
  select.value = defaultPreview;
}

function populateEntityFilters() {
  Object.keys(filterConfig).forEach(populateEntityFilter);
}

function populateEntityFilter(id) {
  const config = filterConfig[id];
  const select = document.getElementById(`${id}-filter`);
  const previous = select.value;
  const input = document.getElementById(`${id}-search`);
  const query = input?.value?.toLocaleLowerCase("ru-RU") || "";
  const allValues = state.options.entities?.[id] || [];
  const values = allValues.filter((item) => {
    if (!query) return true;
    return `${item.label} ${item.value}`.toLocaleLowerCase("ru-RU").includes(query);
  });
  if (!input) {
    select.replaceChildren(option("", config.label), ...values.map((item) => option(item.value, item.label)));
    select.value = values.some((item) => item.value === previous) ? previous : "";
    updateFilterCount();
    return;
  }
  const selected = allValues.find((item) => item.value === previous);
  select.replaceChildren(option("", config.label), ...(selected ? [option(selected.value, selected.label)] : []));
  select.value = selected ? selected.value : "";
  if (input && selected && document.activeElement !== input) input.value = selected.label;
  renderComboboxOptions(id, values);
  select.title = values.length > 20 ? "Уточните поиск, чтобы быстрее найти нужное значение." : "Выбор меняет аналитический срез.";
  updateFilterCount();
}

function renderComboboxOptions(id, values) {
  const input = document.getElementById(`${id}-search`);
  const list = document.getElementById(`${id}-options`);
  if (!input || !list) return;
  const visibleValues = values.slice(0, 20);
  list.replaceChildren();
  if (!visibleValues.length) {
    const empty = document.createElement("div");
    empty.className = "combo-empty";
    empty.textContent = "Ничего не найдено";
    list.appendChild(empty);
  } else {
    visibleValues.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "combo-option";
      button.setAttribute("role", "option");
      button.dataset.value = item.value;
      button.id = `${id}-option-${index}`;
      button.textContent = item.label;
      button.addEventListener("mousedown", (event) => event.preventDefault());
      button.addEventListener("click", async () => {
        await selectComboboxValue(id, item);
      });
      button.addEventListener("keydown", async (event) => {
        await handleComboboxOptionKeydown(event, id, index, item);
      });
      button.addEventListener("focus", () => setActiveComboboxOption(id, button));
      list.appendChild(button);
    });
  }
  const shouldOpen = document.activeElement === input || list.contains(document.activeElement);
  list.classList.toggle("is-open", shouldOpen);
  input.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

async function selectComboboxValue(id, item) {
  const select = document.getElementById(`${id}-filter`);
  select.replaceChildren(option("", filterConfig[id].label), option(item.value, item.label));
  select.value = item.value;
  document.getElementById(`${id}-search`).value = item.label;
  closeCombobox(id);
  resetChildFilters(id);
  applyFilterDrilldown(id);
  await refreshRuntimeOptions();
  updatePreviewGrain();
  await runOverviewQuery();
}

function handleComboboxKeydown(event, id) {
  const list = document.getElementById(`${id}-options`);
  const options = Array.from(list?.querySelectorAll(".combo-option") || []);
  if (event.key === "Escape") {
    closeCombobox(id);
    return;
  }
  if (!options.length) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    openCombobox(id);
    options[0].focus();
  }
  if (event.key === "Enter") {
    event.preventDefault();
    options[0].click();
  }
}

async function handleComboboxOptionKeydown(event, id, index, item) {
  const list = document.getElementById(`${id}-options`);
  const options = Array.from(list?.querySelectorAll(".combo-option") || []);
  if (!options.length) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    options[Math.min(index + 1, options.length - 1)].focus();
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    if (index === 0) {
      document.getElementById(`${id}-search`).focus();
    } else {
      options[Math.max(index - 1, 0)].focus();
    }
  } else if (event.key === "Home") {
    event.preventDefault();
    options[0].focus();
  } else if (event.key === "End") {
    event.preventDefault();
    options[options.length - 1].focus();
  } else if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    await selectComboboxValue(id, item);
  } else if (event.key === "Escape") {
    event.preventDefault();
    closeCombobox(id);
    document.getElementById(`${id}-search`).focus();
  }
}

function setActiveComboboxOption(id, activeOption) {
  const list = document.getElementById(`${id}-options`);
  const input = document.getElementById(`${id}-search`);
  Array.from(list?.querySelectorAll(".combo-option") || []).forEach((optionNode) => {
    optionNode.setAttribute("aria-selected", optionNode === activeOption ? "true" : "false");
  });
  input?.setAttribute("aria-activedescendant", activeOption.id);
}

function openCombobox(id) {
  const input = document.getElementById(`${id}-search`);
  const list = document.getElementById(`${id}-options`);
  if (!input || !list) return;
  list.classList.add("is-open");
  input.setAttribute("aria-expanded", "true");
}

function closeCombobox(id) {
  const input = document.getElementById(`${id}-search`);
  const list = document.getElementById(`${id}-options`);
  if (!input || !list) return;
  list.classList.remove("is-open");
  input.setAttribute("aria-expanded", "false");
  input.removeAttribute("aria-activedescendant");
}

function clearEntityFilter(id) {
  document.getElementById(`${id}-filter`).value = "";
  document.getElementById(`${id}-search`).value = "";
  resetChildFilters(id);
  if (state.currentGrain === id) state.currentGrain = "network";
  updateBreadcrumb();
}

function resetChildFilters(filterId) {
  (filterConfig[filterId]?.childFilters || []).forEach((id) => {
    document.getElementById(`${id}-filter`).value = "";
    const search = document.getElementById(`${id}-search`);
    if (search) search.value = "";
    closeCombobox(id);
  });
}

function resetAllEntityFilters() {
  Object.keys(filterConfig).forEach((id) => {
    const select = document.getElementById(`${id}-filter`);
    if (select) select.value = "";
    const search = document.getElementById(`${id}-search`);
    if (search) search.value = "";
    closeCombobox(id);
  });
  state.currentGrain = "network";
  updateBreadcrumb();
  updatePreviewGrain();
  updateFilterCount();
}

function applyFilterDrilldown(filterId) {
  const select = document.getElementById(`${filterId}-filter`);
  if (select.value) state.currentGrain = filterId;
  updateBreadcrumb();
  updateFilterCount();
}

function drillIntoEntity(entityId) {
  const targetGrain = state.previewGrain;
  const select = document.getElementById(`${targetGrain}-filter`);
  if (!select) return;
  select.value = entityId;
  state.currentGrain = targetGrain;
  resetChildFilters(targetGrain);
  updateBreadcrumb();
  updatePreviewGrain();
  runOverviewQuery();
}

function selectedRetailer() {
  const selectedId = document.getElementById("retailer-select")?.value || state.runtime.default_retailer_id;
  return state.runtime.retailers.find((retailer) => retailer.retailer_id === selectedId) || state.runtime.retailers[0];
}

function selectedDateFrom() {
  if (state.periodMode === "DATE_RANGE") return document.getElementById("date-from")?.value || "";
  if (state.periodMode === "SINGLE_PERIOD") return document.getElementById("period-single")?.value || "";
  return document.getElementById("period-a")?.value || "";
}

function selectedDateTo() {
  if (state.periodMode === "DATE_RANGE") return document.getElementById("date-to")?.value || "";
  if (state.periodMode === "SINGLE_PERIOD") return document.getElementById("period-single")?.value || "";
  return document.getElementById("period-a")?.value || "";
}

function selectedComparisonMode() {
  return state.periodMode === "COMPARE" ? state.comparisonMode : "NONE";
}

function selectedFilterValues() {
  return Object.fromEntries(
    Object.keys(filterConfig)
      .map((id) => [id, document.getElementById(`${id}-filter`)?.value || ""])
      .filter(([, value]) => value)
  );
}

function selectedParentFiltersForGrain(grain) {
  const selected = selectedFilterValues();
  const parentMap = {
    network: [],
    category: [],
    manufacturer: ["category"],
    brand: ["category", "manufacturer"],
    sku: ["category", "manufacturer", "brand"],
    store: ["category", "manufacturer", "brand", "sku"]
  };
  return Object.fromEntries(
    (parentMap[grain] || [])
      .filter((key) => selected[key])
      .map((key) => [key, [selected[key]]])
  );
}

function entityIdsForSummary() {
  if (state.currentGrain === "network") return firstEntityIds("network", 1);
  const selected = document.getElementById(`${state.currentGrain}-filter`)?.value;
  if (selected) return [selected];
  state.currentGrain = "network";
  updateBreadcrumb();
  updatePreviewGrain();
  return firstEntityIds("network", 1);
}

function entityIdsForPreview() {
  return firstEntityIds(state.previewGrain, state.overviewPreviewRowLimit);
}

function firstEntityIds(grain, limit) {
  return (state.options.entities?.[grain] || []).slice(0, limit).map((item) => item.value);
}

function catalogEntry(concept) {
  return state.catalog.find((entry) => entry.metric_concept === concept);
}

function displayLabel(concept) {
  return catalogEntry(concept)?.display_label || concept;
}

function contributionMetricForOverview() {
  if (additiveContributionMetrics.includes(state.chartMetric)) return state.chartMetric;
  return catalogEntry("revenue") ? "revenue" : null;
}

function summaryResultFor(concept) {
  return state.summaryResponse?.metric_results.find((result) => result.metric_concept === concept);
}

function chartResultFor(concept) {
  return state.chartResponse?.metric_results.find((result) => result.metric_concept === concept);
}

function visibleSummaryResult(concept) {
  const result = summaryResultFor(concept);
  if (!result || !catalogEntry(concept)) return null;
  if (state.periodMode === "DATE_RANGE" && result.limitations?.includes("range_aggregation_period_only")) return null;
  return result;
}

function representativeConcept(concepts, excludedConcepts = new Set()) {
  return concepts.find((concept) => !excludedConcepts.has(concept) && visibleSummaryResult(concept)) || null;
}

function tableResultFor(concept, entityId) {
  return state.tableResponse?.metric_results.find((result) => result.metric_concept === concept && result.entity_id === entityId);
}

function comparisonFor(response, result) {
  if (!response || !result) return null;
  return response.comparisons.find((item) => item.entity_id === result.entity_id && item.metric_definition_id === result.lineage?.metric_definition_id);
}

function resultForProvenance(concept) {
  return summaryResultFor(concept) || state.summaryResponse?.metric_results[0] || state.tableResponse?.metric_results[0];
}

function comparisonMarkerPeriods() {
  if (state.periodMode !== "COMPARE") return [];
  const comparison = state.summaryResponse?.comparisons?.[0];
  return [selectedDateFrom(), comparison?.comparison_period_start].filter(Boolean);
}

function kpiContextText(comparison, entry) {
  if (state.periodMode === "COMPARE" && comparison) {
    const deltaFormat = entry.format === "percent" ? "percentage_points" : entry.format;
    return `${formatDeltaValue(comparison.delta, deltaFormat)} · ${formatValue(comparison.pct_delta, "percent")}`;
  }
  if (state.periodMode === "DATE_RANGE") return "За доступные периоды диапазона";
  return "За выбранный период";
}

function compactMetricText(result, entry) {
  if (!result || !entry) return "Недоступно";
  const comparison = comparisonFor(state.summaryResponse, result);
  if (state.periodMode === "COMPARE" && comparison) {
    const deltaFormat = entry.format === "percent" ? "percentage_points" : entry.format;
    return `${formatValue(result.value, entry.format)} · ${formatDeltaValue(comparison.delta, deltaFormat)}`;
  }
  if (result.limitations?.includes("range_aggregation_period_only")) return "только по периодам";
  return formatValue(result.value, entry.format);
}

function movementText(result, entry) {
  if (!result || !entry) return "Показатель недоступен для выбранного среза.";
  if (state.periodMode === "DATE_RANGE") return "Показано за доступные периоды диапазона.";
  if (state.periodMode === "SINGLE_PERIOD") return "Состояние за выбранный период.";
  const comparison = comparisonFor(state.summaryResponse, result);
  if (!comparison) return "Нет подходящего периода сравнения.";
  const threshold = entry.format === "percent" ? 0.0001 : 0;
  if (comparison.delta > threshold) return "Растёт относительно периода сравнения.";
  if (comparison.delta < -threshold) return "Снижается относительно периода сравнения.";
  return "Без изменения относительно периода сравнения.";
}

function metricCellText(result, entry, response) {
  const comparison = comparisonFor(response, result);
  if (state.periodMode === "COMPARE" && comparison) {
    const deltaFormat = entry.format === "percent" ? "percentage_points" : entry.format;
    return `${formatValue(result.value, entry.format)} (${formatDeltaValue(comparison.delta, deltaFormat)})`;
  }
  if (result.limitations?.includes("range_aggregation_period_only")) return "только по периодам";
  return formatValue(result.value, entry.format);
}

function limitationText(result) {
  if (!result?.limitations?.length) return "";
  if (result.limitations.includes("range_aggregation_period_only")) return "Показатель доступен только по отдельным периодам.";
  return "Есть ограничения для выбранного среза.";
}

function periodContextText() {
  if (state.periodMode === "DATE_RANGE") {
    return `${formatPeriod(selectedDateFrom())} — ${formatPeriod(selectedDateTo())}`;
  }
  if (state.periodMode === "SINGLE_PERIOD") return formatPeriod(selectedDateFrom());
  const comparison = state.summaryResponse?.comparisons?.[0];
  const ref = comparison?.comparison_period_start ? formatPeriod(comparison.comparison_period_start) : "нет периода";
  return `${formatPeriod(selectedDateFrom())} vs ${ref} · ${comparisonLabels[state.comparisonMode]}`;
}

function contextFilterText() {
  const selected = selectedFilterValues();
  const parts = Object.entries(selected).map(([key, value]) => `${grainLabels[key]}: ${entityDisplayLabel(key, value)}`);
  return parts.length ? parts.join(" · ") : "";
}

function privateLabelScopeText(scope) {
  const scopeName = selectedRetailer().private_label_display_name;
  return {
    INCLUDE: `${scopeName} включена`,
    EXCLUDE: `${scopeName} исключена`,
    ONLY: `только ${scopeName}`
  }[scope] || scope;
}

function coverageNoteText(response) {
  if (!response?.missing_periods?.length) return "";
  const available = response.available_periods.length;
  const requested = available + response.missing_periods.length;
  return `Покрытие: ${available} из ${requested} периодов. Пропущены: ${response.missing_periods.map(formatPeriod).join(", ")}`;
}

function updateFilterCount() {
  const count = Object.keys(selectedFilterValues()).length;
  const target = document.getElementById("filter-count");
  if (!target) return;
  target.textContent = count ? `${count} выбрано` : "0 выбрано";
  document.getElementById("reset-filters")?.classList.toggle("is-hidden", count === 0);
}

function entityDisplayLabel(grain, entityId) {
  if (!entityId) return "";
  if (grain === "network") return "Все данные";
  const optionItem = (state.options.entities?.[grain] || []).find((item) => item.value === entityId);
  return optionItem?.label || entityId;
}

function tableContextText(count, reason = "") {
  const current = grainLabels[state.currentGrain];
  const next = grainLabels[state.previewGrain];
  if (!count) return `Нет объектов уровня «${next}» для текущего среза.`;
  if (reason) return `${next}: объекты в выбранном срезе. ${reason}`;
  return `${next}: первые ${Math.min(count, state.tablePageSize)} объектов для среза «${current}».`;
}

function contributionFallbackReason() {
  const status = state.contributionResponse?.status;
  if (state.periodMode !== "COMPARE") return "Вклад в изменение доступен только в режиме сравнения.";
  if (!additiveContributionMetrics.includes(state.chartMetric)) return "Для выбранного показателя вклад в изменение не рассчитывается.";
  if (status === "NOT_APPLICABLE_PARENT_CHILD_SCOPE") return "Для этой пары уровней вклад пока недоступен.";
  if (status === "NOT_APPLICABLE") return "Для выбранного показателя вклад не применим.";
  if (status === "INSUFFICIENT_COMPARISON") return "Нет полного периода сравнения для расчёта вклада.";
  if (status === "AMBIGUOUS_METRIC_DEFINITION") return "Требуется уточнить определение показателя.";
  if (status === "NO_DATA") return "Нет данных для расчёта вклада.";
  return "";
}

function contributionMixedSignNote() {
  const rows = state.contributionResponse?.rows || [];
  const hasPositive = rows.some((row) => row.delta > 0);
  const hasNegative = rows.some((row) => row.delta < 0);
  if (!hasPositive || !hasNegative) return "";
  return "Вклад может быть выше 100% или отрицательным, если объекты компенсируют изменение.";
}

function updatePrivateLabelTerminology() {
  const scopeName = selectedRetailer().private_label_display_name;
  document.getElementById("private-label-label").textContent = `Учёт ${scopeName}`;
  const options = {
    INCLUDE: `${scopeName}: включить`,
    EXCLUDE: `${scopeName}: исключить`,
    ONLY: `${scopeName}: только`
  };
  Array.from(document.getElementById("private-label-scope").options).forEach((item) => {
    item.textContent = options[item.value] || item.value;
  });
}

function openProvenance(concept) {
  const result = resultForProvenance(concept);
  state.activeProvenanceConcept = concept;
  const content = document.getElementById("provenance-content");
  content.replaceChildren();
  if (!result?.provenance) {
    const empty = document.createElement("section");
    empty.className = "provenance-section";
    appendText(empty, "h3", "Что это за показатель");
    appendText(empty, "p", "Происхождение из витрины недоступно для этого значения.");
    content.appendChild(empty);
  } else {
    provenanceSections(result.provenance, result).forEach((section) => content.appendChild(section));
  }
  document.getElementById("provenance-drawer").classList.add("is-open");
  document.getElementById("provenance-drawer").setAttribute("aria-hidden", "false");
  document.getElementById("scrim").classList.add("is-open");
}

function openContributionProvenance(row) {
  const content = document.getElementById("provenance-content");
  content.replaceChildren();
  contributionProvenanceSections(row.provenance || {}, row).forEach((section) => content.appendChild(section));
  document.getElementById("provenance-drawer").classList.add("is-open");
  document.getElementById("provenance-drawer").setAttribute("aria-hidden", "false");
  document.getElementById("scrim").classList.add("is-open");
}

function contributionProvenanceSections(provenance, row) {
  const scope = provenance.scope || {};
  const parent = provenance.parent || {};
  const child = provenance.child || {};
  const metric = provenance.metric || {};
  const calculation = provenance.calculation || {};
  const run = provenance.run_lineage || {};
  const source = provenance.source_evidence || {};
  const parentDefinition = metric.parent_definition || {};
  const childDefinition = metric.child_definition || {};
  const sections = [
    section("Что это за показатель", [
      ["Показатель", "Вклад в изменение"],
      ["Базовый показатель", displayLabel(metric.metric_concept || state.contributionResponse?.metric_concept)],
      ["Вклад", row.contribution_share === null ? "н/д" : formatValue(row.contribution_share, "percent")]
    ]),
    section("Срез", [
      ["Родительский уровень", [grainLabels[parent.grain_id] || parent.grain_id, entityDisplayLabel(parent.grain_id, parent.entity_id)].filter(Boolean).join(" / ") || "н/д"],
      ["Дочерний объект", [grainLabels[child.grain_id] || child.grain_id, entityDisplayLabel(child.grain_id, child.entity_id)].filter(Boolean).join(" / ") || "н/д"],
      ["Периоды", [formatPeriod(scope.current_period), formatPeriod(scope.reference_period)].filter(Boolean).join(" vs ") || "н/д"],
      ["Учёт ассортимента", privateLabelScopeText(scope.private_label_scope)]
    ]),
    section("Расчёт", [
      ["Текущий период", formatValue(calculation.current_value, catalogEntry(metric.metric_concept)?.format || "decimal")],
      ["Период сравнения", formatValue(calculation.reference_value, catalogEntry(metric.metric_concept)?.format || "decimal")],
      ["Изменение объекта", formatDeltaValue(calculation.child_delta, catalogEntry(metric.metric_concept)?.format || "decimal")],
      ["Изменение родителя", formatDeltaValue(calculation.parent_delta, catalogEntry(metric.metric_concept)?.format || "decimal")],
      ["Формула", calculation.formula || "н/д"]
    ]),
    section("Сравнение", [
      ["Тип", comparisonLabels[scope.comparison_mode] || scope.comparison_mode || "н/д"],
      ["Статус", calculation.status || "н/д"]
    ]),
    section("Покрытие данных", [
      ["Доказательство по источнику", source.status || "н/д"]
    ]),
    section("Бизнес-правило", [
      ["Правило", [childDefinition.rule_version, parentDefinition.rule_version].filter(Boolean).join(" / ") || "н/д"]
    ]),
    section("Качество", [
      ["Ограничения", compactList(provenance.missing_fields)]
    ])
  ];
  const technical = document.createElement("details");
  technical.className = "provenance-technical";
  const summary = document.createElement("summary");
  summary.textContent = "Технические детали";
  technical.appendChild(summary);
  technical.appendChild(section(null, [
    ["Определение родителя", [parentDefinition.metric_definition_id, parentDefinition.metric_definition_version, parentDefinition.metric_config_hash].filter(Boolean).join(" / ") || "н/д"],
    ["Определение дочернего объекта", [childDefinition.metric_definition_id, childDefinition.metric_definition_version, childDefinition.metric_config_hash].filter(Boolean).join(" / ") || "н/д"],
    ["Технический срез", [scope.retailer_id, scope.source_id, scope.parent_grain_id, scope.parent_entity_id, scope.child_grain_id, scope.private_label_scope].filter(Boolean).join(" / ") || "н/д"],
    ["Запуск анализа", compactList(run.analysis_run_ids)],
    ["Версия аналитической витрины", run.mart_build_id || "н/д"],
    ["Ревизия источника", compactList(run.source_revision_ids)],
    ["Недостающие поля", compactList(provenance.missing_fields)]
  ]));
  sections.push(technical);
  return sections;
}

function provenanceSections(provenance, result) {
  const scope = provenance.current_analytical_scope || {};
  const metric = provenance.metric || {};
  const value = provenance.value || {};
  const comparison = provenance.comparison || {};
  const rule = provenance.business_rule || {};
  const run = provenance.run_lineage || {};
  const source = provenance.source_evidence || {};
  const quality = provenance.quality || {};
  const sections = [
    section("Что это за показатель", [
      ["Показатель", displayLabel(metric.metric_concept || result.metric_concept)],
      ["Значение", formatValue(value.value, catalogEntry(result.metric_concept)?.format || "decimal")]
    ]),
    section("Срез", [
      ["Сеть / источник", [selectedRetailer().display_label, selectedRetailer().source_label].filter(Boolean).join(" / ") || "н/д"],
      ["Периоды", compactList((scope.requested_periods || []).map(formatPeriod))],
      ["Объект", [grainLabels[scope.grain_id] || scope.grain_id, entityDisplayLabel(scope.grain_id, scope.entity_id)].filter(Boolean).join(" / ") || "н/д"],
      ["Учёт ассортимента", privateLabelScopeText(scope.private_label_scope)]
    ]),
    section("Расчёт", [
      ["Числитель", value.numerator_value ?? "н/д"],
      ["Знаменатель", value.denominator_value ?? "н/д"],
      ["Стратегия диапазона", rangeStrategyLabel(value.range_aggregation_strategy)]
    ]),
    section("Сравнение", [
      ["Тип", comparisonLabels[comparison.comparison_mode] || comparison.comparison_mode || "н/д"],
      ["Периоды", compactList((comparison.periods || []).map((item) => `${item.current_period_start} vs ${item.comparison_period_start}`))],
      ["Качество", compactList(comparison.quality_statuses)]
    ]),
    section("Покрытие данных", [
      ["Доступные периоды", compactList(scope.available_periods)],
      ["Пропущенные периоды", compactList(scope.missing_periods)]
    ]),
    section("Бизнес-правило", [
      ["Правило", [rule.business_rule_id, rule.business_rule_version].filter(Boolean).join(" / ") || "н/д"]
    ]),
    section("Качество", [
      ["Статусы", compactList(quality.quality_statuses)],
      ["Ограничения", compactList(quality.result_limitations)]
    ])
  ];
  const technical = document.createElement("details");
  technical.className = "provenance-technical";
  const summary = document.createElement("summary");
  summary.textContent = "Технические детали";
  technical.appendChild(summary);
  technical.appendChild(section(null, [
    ["Определение показателя", [metric.metric_definition_id, metric.metric_definition_version, metric.metric_config_hash].filter(Boolean).join(" / ") || "н/д"],
    ["Технический срез", [scope.retailer_id, scope.source_id, scope.grain_id, scope.entity_id, scope.private_label_scope].filter(Boolean).join(" / ") || "н/д"],
    ["Запуск анализа", compactList(run.analysis_run_ids)],
    ["Версия аналитической витрины", run.mart_build_id || "н/д"],
    ["Ревизия источника", compactList(run.source_revision_ids)],
    ["Доказательство по источнику", source.status || "н/д"],
    ["Недостающие поля", compactList(provenance.missing_fields)]
  ]));
  sections.push(technical);
  return sections;
}

function section(title, rows) {
  const node = document.createElement("section");
  node.className = "provenance-section";
  if (title) appendText(node, "h3", title);
  const dl = document.createElement("dl");
  rows.forEach(([key, value]) => {
    appendText(dl, "dt", key);
    appendText(dl, "dd", String(value));
  });
  node.appendChild(dl);
  return node;
}

function closeProvenance() {
  document.getElementById("provenance-drawer").classList.remove("is-open");
  document.getElementById("provenance-drawer").setAttribute("aria-hidden", "true");
  document.getElementById("scrim").classList.remove("is-open");
}

function openReportsPanel() {
  const retailer = selectedRetailer();
  const content = document.getElementById("reports-content");
  content.replaceChildren(
    section("Текущий отчёт", [
      ["Сеть", retailer.display_label],
      ["Источник", retailer.source_label],
      ["Доступные периоды", state.options.periods.length ? `${state.options.periods.length} · ${formatPeriod(state.options.periods[0].value)} — ${formatPeriod(state.options.periods[state.options.periods.length - 1].value)}` : "н/д"],
      ["Категории", String((state.options.entities?.category || []).length)],
      ["Производители", String((state.options.entities?.manufacturer || []).length)],
      ["Бренды", String((state.options.entities?.brand || []).length)],
      ["SKU", String((state.options.entities?.sku || []).length)],
      ["ТТ", String((state.options.entities?.store || []).length)]
    ]),
    section("Текущий режим", [
      ["Период", periodContextText()],
      ["Учёт ассортимента", privateLabelScopeText(document.getElementById("private-label-scope").value)]
    ])
  );
  document.getElementById("reports-panel").classList.add("is-open");
  document.getElementById("reports-panel").setAttribute("aria-hidden", "false");
  document.getElementById("scrim").classList.add("is-open");
}

function closeReportsPanel() {
  document.getElementById("reports-panel").classList.remove("is-open");
  document.getElementById("reports-panel").setAttribute("aria-hidden", "true");
  document.getElementById("scrim").classList.remove("is-open");
}

function renderRows(table, headers, rows, options = {}) {
  const renderedRows = sortedRows(headers, rows).slice(0, options.rowLimit || rows.length);
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach((header) => {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = header;
    th.addEventListener("click", () => {
      state.sortColumn = header;
      state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
      renderOverviewTable();
    });
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  const tbody = document.createElement("tbody");
  renderedRows.forEach((row) => {
    const tr = document.createElement("tr");
    row.forEach((cell, index) => {
      const td = document.createElement("td");
      if (index === 0 && options.onFirstCellClick) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "table-link";
        button.textContent = cell;
        button.addEventListener("click", () => options.onFirstCellClick(cell));
        td.appendChild(button);
      } else {
        td.textContent = cell;
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.replaceChildren(thead, tbody);
}

function renderMessageRow(table, message) {
  const tbody = document.createElement("tbody");
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.className = "empty-state";
  td.textContent = message;
  tr.appendChild(td);
  tbody.appendChild(tr);
  table.replaceChildren(tbody);
}

function sortedRows(headers, rows) {
  const index = headers.indexOf(state.sortColumn);
  if (index < 0) return rows;
  return [...rows].sort((left, right) => {
    const direction = state.sortDirection === "asc" ? 1 : -1;
    return String(left[index]).localeCompare(String(right[index]), "ru-RU", { numeric: true }) * direction;
  });
}

function formatValue(value, format) {
  if (value === null || value === undefined || Number.isNaN(value)) return "н/д";
  if (format === "currency") return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value);
  if (format === "percent") return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value * 100)}%`;
  if (format === "percentage_points") return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value * 100)} п.п.`;
  if (format === "integer") return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value);
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value);
}

function formatDeltaValue(value, format) {
  if (value === null || value === undefined || Number.isNaN(value)) return "н/д";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatValue(value, format)}`;
}

function formatPeriod(value) {
  if (!value) return "н/д";
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("ru-RU", { month: "short", year: "numeric" }).format(date);
}

function compactList(value) {
  if (!value || !value.length) return "нет";
  return value.join(", ");
}

function rangeStrategyLabel(strategy) {
  return {
    sum_available_periods: "сумма доступных периодов",
    ratio_of_sums: "отношение сумм",
    weighted_ratio_of_sums: "взвешенное отношение",
    recompute_share_scope: "пересчёт доли в срезе",
    period_only: "только по периодам",
    projection_defined: "определено проекцией"
  }[strategy] || strategy || "н/д";
}

function unitLabel(format) {
  return {
    currency: "руб.",
    percent: "%",
    decimal: "значение",
    integer: "кол-во"
  }[format] || "";
}

function option(value, label) {
  const node = document.createElement("option");
  node.value = value;
  node.textContent = label;
  return node;
}

function appendText(parent, tagName, value) {
  const node = document.createElement(tagName);
  node.textContent = value;
  parent.appendChild(node);
  return node;
}

function replaceWithMessage(parent, className, message) {
  const node = document.createElement("div");
  node.className = className;
  node.textContent = message;
  parent.replaceChildren(node);
}

function setLoading(isLoading, message) {
  document.body.classList.toggle("is-loading", isLoading);
  document.getElementById("system-state").textContent = message || (isLoading ? "Загрузка данных" : "Данные обновлены");
}

function showPageError(error) {
  replaceWithMessage(document.getElementById("chart-box"), "error-state", "Не удалось загрузить данные. Повторите попытку.");
  showToast(error?.message ? "Не удалось загрузить данные. Детали доступны в журнале браузера." : "Не удалось загрузить данные.");
}

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.setTimeout(() => toast.classList.remove("is-visible"), 3200);
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function svgEl(name, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
  return node;
}

function svgText(x, y, value, anchor, className) {
  const text = svgEl("text", { x, y, "text-anchor": anchor, class: className || "axis-label" });
  text.textContent = value;
  return text;
}

function showTooltip(event, text) {
  let tooltip = document.querySelector(".chart-tooltip");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    document.body.appendChild(tooltip);
  }
  tooltip.textContent = text;
  tooltip.style.left = `${event.clientX + 12}px`;
  tooltip.style.top = `${event.clientY + 12}px`;
  tooltip.style.display = "block";
}

function hideTooltip() {
  const tooltip = document.querySelector(".chart-tooltip");
  if (tooltip) tooltip.style.display = "none";
}
