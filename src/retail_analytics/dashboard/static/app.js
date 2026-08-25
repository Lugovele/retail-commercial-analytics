const state = {
  runtime: null,
  catalog: [],
  options: { periods: [], entities: {} },
  summaryResponse: null,
  chartResponse: null,
  tableResponse: null,
  contributionResponse: null,
  salesDriversResponse: null,
  salesDriversChartResponse: null,
  salesDriversTableResponse: null,
  portfolioMarketResponse: null,
  storesResponse: null,
  storesScopeStatus: "ready",
  signalsResponse: null,
  signalsLoadStatus: "idle",
  signalKindFilter: "all",
  signalGrainFilter: "all",
  dataResponse: null,
  dataPageOffset: 0,
  activeView: "overview",
  loadedViews: {},
  periodMode: "COMPARE",
  comparisonMode: "YOY",
  currentGrain: "network",
  drilldownPath: [],
  chartMetric: "revenue",
  salesDriverMetric: "revenue",
  storesMetric: "revenue",
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
const salesDriverBuckets = [
  { title: "Результат", concepts: ["revenue"] },
  { title: "Объём", concepts: ["units"] },
  { title: "Цена", concepts: ["weighted_shelf_price_vat", "weighted_input_price_vat"] },
  { title: "Присутствие", concepts: ["selling_store_count", "distribution"] },
  { title: "Скорость", concepts: ["velocity", "revenue_velocity"] },
  { title: "Экономика", concepts: ["retailer_margin_abs", "retailer_margin_pct"] },
  { title: "Структура", concepts: ["sku_count", "brand_count", "category_count"] }
];
const salesDriverGrainSupport = {
  revenue: ["network", "category", "manufacturer", "brand", "sku", "store"],
  units: ["network", "category", "manufacturer", "brand", "sku", "store"],
  retailer_margin_abs: ["network", "category", "manufacturer", "brand", "sku", "store"],
  retailer_margin_pct: ["network", "category", "manufacturer", "brand", "sku", "store"],
  weighted_shelf_price_vat: ["network", "category", "manufacturer", "brand", "sku", "store"],
  weighted_input_price_vat: ["network", "category", "manufacturer", "brand", "sku", "store"],
  selling_store_count: ["network", "category", "manufacturer", "brand", "sku"],
  distribution: ["category", "manufacturer", "brand", "sku"],
  velocity: ["category", "manufacturer", "brand", "sku"],
  revenue_velocity: ["category", "manufacturer", "brand", "sku"],
  sku_count: ["network", "category", "manufacturer", "brand", "store"],
  brand_count: ["network", "category", "manufacturer", "store"],
  category_count: ["network", "manufacturer", "store"]
};
const portfolioMarketConcepts = [
  "category_revenue_share",
  "category_units_share",
  "category_margin_share",
  "manufacturer_rank_revenue",
  "manufacturer_rank_units",
  "manufacturer_population_count",
  "active_sku_count",
  "historical_peak_active_sku_count",
  "active_sku_change_pct",
  "brand_delta_pct",
  "category_delta_pct",
  "brand_category_delta_gap_pp",
  "market_segment_delta_pct",
  "broad_competitors"
];
const portfolioShareConcepts = ["category_revenue_share", "category_units_share", "category_margin_share"];
const portfolioRankConcepts = ["manufacturer_rank_revenue", "manufacturer_rank_units"];
const portfolioActiveSkuConcepts = ["active_sku_count", "historical_peak_active_sku_count", "active_sku_change_pct"];
const portfolioBrandCategoryConcepts = ["brand_delta_pct", "category_delta_pct", "brand_category_delta_gap_pp"];
const portfolioMarketUniverseConcepts = ["market_segment_delta_pct"];
const portfolioCompetitorConcepts = ["broad_competitors"];
const storeRankingMetrics = ["revenue", "units", "retailer_margin_abs"];
const storeKpiConcepts = ["revenue", "units", "retailer_margin_abs", "sku_count"];
const storeTableConcepts = ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct", "sku_count"];
const signalKindLabels = {
  all: "Все",
  commercial: "Коммерческие",
  pattern: "Паттерны",
  quality: "Качество данных"
};
const signalTypeLabels = {
  COMMERCIAL_SIGNAL: "Коммерческий",
  DETERMINISTIC_PATTERN: "Паттерн",
  DATA_QUALITY_ALERT: "Качество данных",
  CAPABILITY_LIMITATION: "Ограничение"
};
const signalEventLabels = {
  MATERIAL_REVENUE_DECLINE: "Оборот снизился по подтверждённому правилу",
  MATERIAL_REVENUE_GROWTH: "Оборот вырос по подтверждённому правилу",
  MATERIAL_UNITS_DECLINE: "Продажи, шт. снизились по подтверждённому правилу",
  MATERIAL_UNITS_GROWTH: "Продажи, шт. выросли по подтверждённому правилу",
  MATERIAL_MARGIN_DECLINE: "Абсолютная маржа снизилась по подтверждённому правилу",
  MATERIAL_MARGIN_GROWTH: "Абсолютная маржа выросла по подтверждённому правилу",
  DISTRIBUTION_LOSS: "Снижение присутствия по подтверждённому правилу",
  DISTRIBUTION_GAIN: "Рост присутствия по подтверждённому правилу",
  VELOCITY_LOSS: "Снижение продаж на ТТ по подтверждённому правилу",
  VELOCITY_GAIN: "Рост продаж на ТТ по подтверждённому правилу",
  PRICE_INCREASE: "Изменение цены по подтверждённому правилу",
  PRICE_PRESSURE_PATTERN: "Ценовой паттерн требует проверки",
  DATA_QUALITY_ALERT: "Вопрос к качеству данных"
};
const signalSeverityLabels = {
  CRITICAL: "Критический",
  HIGH: "Высокий",
  MEDIUM: "Средний",
  LOW: "Низкий",
  INFO: "Информационный"
};
const portfolioPresentationFallback = {
  category_revenue_share: { display_label: "Доля в обороте категории", format: "percent" },
  category_units_share: { display_label: "Доля в штуках категории", format: "percent" },
  category_margin_share: { display_label: "Доля в марже категории", format: "percent" },
  manufacturer_rank_revenue: { display_label: "Место производителя по обороту", format: "integer" },
  manufacturer_rank_units: { display_label: "Место производителя по штукам", format: "integer" },
  manufacturer_population_count: { display_label: "Производителей в рейтинге", format: "integer" },
  active_sku_count: { display_label: "Активные SKU", format: "integer" },
  historical_peak_active_sku_count: { display_label: "Пиковое число активных SKU", format: "integer" },
  active_sku_change_pct: { display_label: "Изменение активных SKU от пика", format: "percent" },
  brand_delta_pct: { display_label: "Изменение бренда", format: "percent" },
  category_delta_pct: { display_label: "Изменение категории", format: "percent" },
  brand_category_delta_gap_pp: { display_label: "Отклонение бренда от категории", format: "percentage_points" },
  market_segment_delta_pct: { display_label: "Изменение сегмента рынка", format: "percent" },
  broad_competitors: { display_label: "Конкуренты категории", format: "text" }
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
  store: {
    label: "Все ТТ",
    childFilters: []
  }
};
const searchFilterIds = ["manufacturer", "brand", "sku", "store"];
const drilldownOrder = ["network", "category", "manufacturer", "brand", "sku", "store"];
const maxComboboxOptions = 20;
const sectionIdByView = {
  overview: "overview",
  sales_drivers: "sales-drivers",
  portfolio_market: "portfolio-market",
  stores: "stores",
  signals: "signals",
  data: "data"
};
const viewBySectionId = Object.fromEntries(Object.entries(sectionIdByView).map(([view, sectionId]) => [sectionId, view]));
let sectionObserver = null;
let scrollspyFrame = null;

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
      updatePeriodSummary();
      invalidateLoadedViews();
      resetDataPagination();
      await runActiveViewQuery();
    });
  });

  document.querySelectorAll("[data-view]").forEach((link) => {
    link.addEventListener("click", async (event) => {
      event.preventDefault();
      await navigateToView(link.dataset.view);
    });
  });
  document.querySelectorAll("[data-signal-kind]").forEach((button) => {
    button.addEventListener("click", () => {
      state.signalKindFilter = button.dataset.signalKind || "all";
      updatePressedGroup("[data-signal-kind]", "signalKind", state.signalKindFilter);
      renderSignals();
    });
  });
  document.querySelectorAll("[data-signal-grain]").forEach((button) => {
    button.addEventListener("click", () => {
      state.signalGrainFilter = button.dataset.signalGrain || "all";
      updatePressedGroup("[data-signal-grain]", "signalGrain", state.signalGrainFilter);
      renderSignals();
    });
  });
  document.getElementById("data-prev-page")?.addEventListener("click", async () => {
    state.dataPageOffset = Math.max(0, state.dataPageOffset - state.tablePageSize);
    await runDataQuery();
  });
  document.getElementById("data-next-page")?.addEventListener("click", async () => {
    state.dataPageOffset += state.tablePageSize;
    await runDataQuery();
  });
  document.querySelectorAll("[data-header-action]").forEach((button) => {
    if (button.disabled) return;
    button.addEventListener("click", () => {
      if (button.dataset.headerAction === "reports") openReportsPanel();
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
    resetDataPagination();
    await refreshRuntimeOptions();
    updatePreviewGrain();
    invalidateLoadedViews();
    await runActiveViewQuery();
  });
  bindPeriodPopover();
}

function bindPeriodPopover() {
  const button = document.getElementById("period-popover-button");
  const popover = document.getElementById("period-popover");
  if (!button || !popover) return;
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    togglePeriodPopover();
  });
  popover.addEventListener("click", (event) => event.stopPropagation());
  document.addEventListener("click", () => closePeriodPopover());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePeriodPopover();
  });
}

function togglePeriodPopover() {
  const popover = document.getElementById("period-popover");
  const button = document.getElementById("period-popover-button");
  const isOpen = popover && !popover.classList.contains("is-hidden");
  popover?.classList.toggle("is-hidden", isOpen);
  button?.setAttribute("aria-expanded", isOpen ? "false" : "true");
}

function closePeriodPopover() {
  document.getElementById("period-popover")?.classList.add("is-hidden");
  document.getElementById("period-popover-button")?.setAttribute("aria-expanded", "false");
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
    const hashView = viewFromHash();
    setActiveView(hashView || state.activeView, { refresh: false, scroll: false });
    renderChartMetricOptions();
    await runActiveViewQuery();
    setupSectionObserver();
    if (hashView) scrollToView(hashView, { behavior: "auto" });
  } catch (error) {
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

function setActiveView(view, { refresh = true, scroll = false } = {}) {
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
  if (scroll) {
    updateHash(target);
    scrollToView(target);
  }
  if (refresh) void ensureActiveViewData();
}

async function navigateToView(view) {
  const target = view || "overview";
  setActiveView(target, { refresh: false, scroll: false });
  updateHash(target);
  scrollToView(target);
  void ensureActiveViewData();
}

function viewFromHash() {
  const sectionId = window.location.hash.replace(/^#/, "");
  return viewBySectionId[sectionId] || null;
}

function updateHash(view) {
  const sectionId = sectionIdByView[view];
  if (!sectionId) return;
  const hash = `#${sectionId}`;
  if (window.location.hash === hash) return;
  history.pushState(null, "", hash);
}

function scrollToView(view, { behavior = "smooth" } = {}) {
  const section = document.getElementById(sectionIdByView[view]);
  section?.scrollIntoView({ behavior, block: "start" });
}

function setupSectionObserver() {
  sectionObserver?.disconnect();
  const sections = Array.from(document.querySelectorAll(".report-section"));
  if (!sections.length || !("IntersectionObserver" in window)) return;
  sectionObserver = new IntersectionObserver((entries) => {
    if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4) {
      const lastView = sections[sections.length - 1]?.dataset.viewPanel;
      if (lastView && lastView !== state.activeView) setActiveView(lastView, { refresh: true, scroll: false });
      return;
    }
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((left, right) => Math.abs(left.boundingClientRect.top - 150) - Math.abs(right.boundingClientRect.top - 150));
    const active = visible[0]?.target;
    const view = active?.dataset.viewPanel;
    if (view && view !== state.activeView) setActiveView(view, { refresh: true, scroll: false });
  }, {
    rootMargin: "-150px 0px -55% 0px",
    threshold: [0.02, 0.18, 0.36]
  });
  sections.forEach((section) => sectionObserver.observe(section));
  window.addEventListener("scroll", () => {
    if (scrollspyFrame) return;
    scrollspyFrame = window.requestAnimationFrame(() => {
      scrollspyFrame = null;
      updateActiveSectionFromScroll();
    });
  }, { passive: true });
  window.addEventListener("hashchange", () => {
    const view = viewFromHash();
    if (view) setActiveView(view, { scroll: true });
  });
}

function updateActiveSectionFromScroll() {
  const sections = Array.from(document.querySelectorAll(".report-section"));
  if (!sections.length) return;
  if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4) {
    const lastView = sections[sections.length - 1]?.dataset.viewPanel;
    if (lastView && lastView !== state.activeView) setActiveView(lastView, { refresh: true, scroll: false });
    return;
  }
  const current = sections
    .map((section) => ({ view: section.dataset.viewPanel, distance: Math.abs(section.getBoundingClientRect().top - 150) }))
    .sort((left, right) => left.distance - right.distance)[0];
  if (current?.view && current.view !== state.activeView) setActiveView(current.view, { refresh: true, scroll: false });
}

async function ensureActiveViewData({ force = false } = {}) {
  if (!force && state.loadedViews[state.activeView]) return;
  await runActiveViewQuery();
}

function invalidateLoadedViews() {
  state.loadedViews = {};
}

function updatePressedGroup(selector, datasetKey, activeValue) {
  document.querySelectorAll(selector).forEach((button) => {
    const isActive = button.dataset[datasetKey] === activeValue;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function resetDataPagination() {
  state.dataPageOffset = 0;
}

function setupRetailerControl() {
  const retailerSelect = document.getElementById("retailer-select");
  retailerSelect.replaceChildren(
    ...state.runtime.retailers.map((retailer) => option(retailer.retailer_id, retailer.display_label))
  );
  retailerSelect.value = state.runtime.default_retailer_id;
  renderRetailerIdentity();
  retailerSelect.addEventListener("change", async () => {
    resetAllEntityFilters();
    resetDataPagination();
    renderRetailerIdentity();
    await loadCatalog();
    await refreshRuntimeOptions({ resetPeriods: true, resetEntities: true });
    updatePrivateLabelTerminology();
    updatePreviewGrain();
    invalidateLoadedViews();
    await runActiveViewQuery();
  });
}

function renderRetailerIdentity() {
  const control = document.getElementById("retailer-control");
  const identity = document.getElementById("retailer-identity");
  const selectControl = document.getElementById("retailer-select-control");
  const retailer = selectedRetailer();
  const hasMultipleRetailers = (state.runtime?.retailers || []).length > 1;

  selectControl?.classList.toggle("is-hidden", !hasMultipleRetailers);
  identity?.classList.toggle("is-hidden", hasMultipleRetailers);
  control?.classList.toggle("has-multiple-retailers", hasMultipleRetailers);
  if (!identity || hasMultipleRetailers) return;
  identity.replaceChildren();
  appendText(identity, "strong", retailer.display_label || "Текущий отчёт");
  appendText(identity, "span", "Текущий отчёт");
}

function bindDynamicControls() {
  document.getElementById("comparison-mode").addEventListener("change", async (event) => {
    state.comparisonMode = event.target.value;
    updatePeriodSummary();
    invalidateLoadedViews();
    resetDataPagination();
    await runActiveViewQuery();
  });
  document.getElementById("private-label-scope").addEventListener("change", async () => {
    resetDataPagination();
    await refreshRuntimeOptions();
    updatePrivateLabelTerminology();
    invalidateLoadedViews();
    await runActiveViewQuery();
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
  document.getElementById("stores-metric").addEventListener("change", () => {
    state.storesMetric = document.getElementById("stores-metric").value;
    state.sortColumn = storeSortColumn();
    state.sortDirection = "desc";
    renderStores();
  });

  for (const id of Object.keys(filterConfig)) {
    const select = document.getElementById(`${id}-filter`);
    select.addEventListener("change", async () => {
      resetChildFilters(id);
      applyFilterDrilldown(id);
      resetDataPagination();
      await refreshRuntimeOptions();
      updatePreviewGrain();
      invalidateLoadedViews();
      await runActiveViewQuery();
    });
  }

  searchFilterIds.forEach((id) => {
    const input = document.getElementById(`${id}-search`);
    input.addEventListener("input", () => populateEntityFilter(id));
    input.addEventListener("focus", () => {
      setTimeout(() => {
        populateEntityFilter(id);
        openCombobox(id);
      }, 120);
    });
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
      resetDataPagination();
      await refreshRuntimeOptions();
      updatePreviewGrain();
      invalidateLoadedViews();
      await runActiveViewQuery();
    });
  });

  ["period-single", "period-a", "date-from", "date-to"].forEach((id) => {
    document.getElementById(id).addEventListener("change", async () => {
      updatePeriodSummary();
      resetDataPagination();
      await refreshRuntimeOptions();
      invalidateLoadedViews();
      await runActiveViewQuery();
    });
  });
  document.getElementById("sales-drivers-provenance")?.addEventListener("click", () => openSalesDriverProvenance());
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
  if (resetEntities) resetAllEntityFilters();
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
  updatePeriodSummary();
}

function setupPeriodSelect(id, selected, resetSelection) {
  const select = document.getElementById(id);
  const previous = select.value;
  select.replaceChildren(...state.options.periods.map((period) => option(period.value, formatPeriod(period.value))));
  select.value = !resetSelection && previous && state.options.periods.some((period) => period.value === previous)
    ? previous
    : selected;
}

async function runActiveViewQuery() {
  if (state.activeView === "sales_drivers") {
    await runSalesDriversQuery();
    return;
  }
  if (state.activeView === "portfolio_market") {
    await runPortfolioMarketQuery();
    return;
  }
  if (state.activeView === "stores") {
    await runStoresQuery();
    return;
  }
  if (state.activeView === "signals") {
    await runSignalsQuery();
    return;
  }
  if (state.activeView === "data") {
    await runDataQuery();
    return;
  }
  if (state.activeView === "overview") {
    await runOverviewQuery();
  }
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
    state.loadedViews.overview = true;
    setLoading(false, "Данные обновлены");
  } catch (error) {
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

async function runSalesDriversQuery() {
  setLoading(true, "Запрос к витрине");
  renderSalesDriverSkeletons();
  try {
    const concepts = salesDriverConcepts();
    if (!concepts.length) {
      renderSalesDriversUnavailable("Для выбранного среза нет поддержанных показателей.");
      state.loadedViews.sales_drivers = true;
      setLoading(false, "Данные обновлены");
      return;
    }
    if (!concepts.includes(state.salesDriverMetric)) state.salesDriverMetric = concepts[0];
    const summaryPayload = buildQueryPayload(state.currentGrain, entityIdsForSummary(), concepts);
    const chartPayload = buildSalesDriverChartQueryPayload();
    const detailPayload = buildQueryPayload(salesDriverDetailGrain(), entityIdsForSalesDriverDetail(), salesDriverDetailConcepts());
    state.salesDriversResponse = await postJson("/api/dashboard/query", summaryPayload);
    state.salesDriversChartResponse = await postJson("/api/dashboard/query", chartPayload);
    state.salesDriversTableResponse = await postJson("/api/dashboard/query", detailPayload);
    renderSalesDrivers();
    state.loadedViews.sales_drivers = true;
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

async function runPortfolioMarketQuery() {
  setLoading(true, "Запрос к витрине");
  renderPortfolioMarketSkeletons();
  try {
    state.portfolioMarketResponse = await postJson("/api/dashboard/portfolio-market", buildPortfolioMarketPayload());
    renderPortfolioMarket();
    state.loadedViews.portfolio_market = true;
    setLoading(false, "Данные обновлены");
  } catch (error) {
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

async function runStoresQuery() {
  setLoading(true, "Запрос к витрине");
  renderStoresSkeletons();
  if (!storeConcepts().length) {
    state.storesResponse = null;
    state.storesScopeStatus = "no_supported_metrics";
    renderStores();
    state.loadedViews.stores = true;
    setLoading(false, "Показатели ТТ недоступны");
    return;
  }
  if (storesHasProductFilters()) {
    state.storesResponse = null;
    state.storesScopeStatus = "product_filter_unsupported";
    renderStores();
    state.loadedViews.stores = true;
    setLoading(false, "Есть ограничение среза");
    return;
  }
  state.storesScopeStatus = "ready";
  try {
    state.storesResponse = await postJson("/api/dashboard/query", buildStoresPayload());
    renderStores();
    state.loadedViews.stores = true;
    setLoading(false, "Данные обновлены");
  } catch (error) {
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

async function runSignalsQuery() {
  setLoading(true, "Запрос к ленте сигналов");
  state.signalsResponse = null;
  state.signalsLoadStatus = "loading";
  renderSignalsSkeletons();
  try {
    state.signalsResponse = await postJson("/api/dashboard/signals", buildSignalsPayload());
    state.signalsLoadStatus = "loaded";
    renderSignals();
    state.loadedViews.signals = true;
    setLoading(false, "Данные обновлены");
  } catch (error) {
    state.signalsResponse = null;
    state.signalsLoadStatus = "error";
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

async function runDataQuery() {
  setLoading(true, "Запрос к данным");
  renderDataSkeletons();
  try {
    state.dataResponse = await postJson("/api/dashboard/data", buildDataPayload());
    renderDataScreen();
    state.loadedViews.data = true;
    setLoading(false, "Данные обновлены");
  } catch (error) {
    state.dataResponse = null;
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
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
    comparison_mode: state.periodMode === "COMPARE" ? selectedComparisonMode() : "NONE",
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

function buildSalesDriverChartQueryPayload() {
  const periods = state.options.periods.map((period) => period.value);
  const dateFrom = state.periodMode === "DATE_RANGE" ? selectedDateFrom() : periods[0] || selectedDateFrom();
  const dateTo = state.periodMode === "DATE_RANGE" ? selectedDateTo() : periods[periods.length - 1] || selectedDateTo();
  return {
    ...buildQueryPayload(state.currentGrain, entityIdsForSummary(), [state.salesDriverMetric]),
    date_from: dateFrom,
    date_to: dateTo,
    period_mode: "DATE_RANGE",
    comparison_mode: "NONE"
  };
}

function buildContributionPayload() {
  if (state.periodMode !== "COMPARE") return null;
  if (hasNonDrilldownFilters()) return null;
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

function buildPortfolioMarketPayload() {
  const retailer = selectedRetailer();
  return {
    retailer_id: retailer.retailer_id,
    source_id: retailer.source_id,
    date_from: selectedDateFrom(),
    date_to: selectedDateTo(),
    period_mode: backendPeriodMode(),
    period_grain: "month",
    grain_id: state.currentGrain,
    entity_ids: entityIdsForSummary(),
    entity_filters: selectedFilterValuesForPortfolio(),
    concept_ids: portfolioMarketConcepts,
    comparison_mode: state.periodMode === "COMPARE" ? selectedComparisonMode() : "NONE",
    include_lineage: true,
    mart_build_id: retailer.default_mart_build_id,
    private_label_scope: document.getElementById("private-label-scope").value
  };
}

function buildStoresPayload() {
  return buildQueryPayload("store", entityIdsForStores(), storeConcepts());
}

function buildSignalsPayload() {
  const retailer = selectedRetailer();
  return {
    retailer_id: retailer.retailer_id,
    source_id: retailer.source_id,
    date_from: selectedDateFrom(),
    date_to: selectedDateTo(),
    period_mode: backendPeriodMode(),
    period_grain: "month",
    grain_id: state.currentGrain,
    entity_ids: entityIdsForSummary(),
    entity_filters: selectedFilterValuesForPortfolio(),
    comparison_mode: state.periodMode === "COMPARE" ? selectedComparisonMode() : "NONE",
    include_lineage: true,
    mart_build_id: retailer.default_mart_build_id,
    private_label_scope: document.getElementById("private-label-scope").value,
    signal_types: ["COMMERCIAL_SIGNAL", "DETERMINISTIC_PATTERN", "DATA_QUALITY_ALERT"],
    limit: 50
  };
}

function buildDataPayload() {
  const retailer = selectedRetailer();
  return {
    retailer_id: retailer.retailer_id,
    source_id: retailer.source_id,
    date_from: selectedDateFrom(),
    date_to: selectedDateTo(),
    period_mode: backendPeriodMode(),
    period_grain: "month",
    grain_id: state.currentGrain,
    entity_ids: entityIdsForSummary(),
    entity_filters: selectedFilterValuesForPortfolio(),
    comparison_mode: state.periodMode === "COMPARE" ? selectedComparisonMode() : "NONE",
    mart_build_id: retailer.default_mart_build_id,
    private_label_scope: document.getElementById("private-label-scope").value,
    limit: state.tablePageSize,
    offset: state.dataPageOffset
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

function salesDriverConcepts() {
  return [...new Set(salesDriverBuckets.flatMap((group) => group.concepts))]
    .filter((concept) => salesDriverMetricEntry(concept));
}

function storeConcepts() {
  return [...new Set([...storeRankingMetrics, ...storeKpiConcepts, ...storeTableConcepts])]
    .filter((concept) => metricEntryForGrain(concept, "store"));
}

function tableConcepts() {
  return previewColumns[state.previewGrain].filter((concept) => catalogEntry(concept));
}

function salesDriverDetailConcepts() {
  const grain = salesDriverDetailGrain();
  return (previewColumns[grain] || ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct"])
    .filter((concept) => metricEntryForGrain(concept, grain));
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

function renderSalesDrivers() {
  renderContextStripForResponse(state.salesDriversResponse);
  renderBreadcrumb();
  renderSalesDriverMatrix();
  renderSalesDriverTrend();
  renderSalesDriverDetailTable();
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

function renderSalesDriverMatrix() {
  const table = document.getElementById("sales-drivers-matrix");
  if (!state.salesDriversResponse?.metric_results?.length) {
    renderMessageRow(table, "За выбранный период данных нет.");
    document.getElementById("sales-drivers-context").textContent = "Нет данных для выбранного среза.";
    return;
  }
  const headers = salesDriverMatrixHeaders();
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
  salesDriverRows().forEach(({ group, concept, result, entry }) => {
    const tr = document.createElement("tr");
    tr.className = concept === state.salesDriverMetric ? "is-selected" : "";
    const groupCell = document.createElement("td");
    groupCell.textContent = group;
    tr.appendChild(groupCell);
    const metricCell = document.createElement("td");
    const metricButton = document.createElement("button");
    metricButton.type = "button";
    metricButton.className = "table-link";
    metricButton.textContent = displayLabel(concept);
    metricButton.setAttribute("aria-pressed", concept === state.salesDriverMetric ? "true" : "false");
    metricButton.addEventListener("click", async () => {
      state.salesDriverMetric = concept;
      await runSalesDriversQuery();
    });
    metricCell.appendChild(metricButton);
    tr.appendChild(metricCell);
    salesDriverMetricCells(result, entry).forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    });
    const actionCell = document.createElement("td");
    if (result?.provenance) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "inline-link";
      button.textContent = "Откуда?";
      button.addEventListener("click", () => openProvenance(concept));
      actionCell.appendChild(button);
    } else {
      actionCell.textContent = "н/д";
    }
    tr.appendChild(actionCell);
    tbody.appendChild(tr);
  });
  table.replaceChildren(thead, tbody);
  const caption = table.createCaption();
  caption.textContent = salesDriverMatrixCaption();
  document.getElementById("sales-drivers-context").textContent = salesDriversContextText();
}

function salesDriverMatrixHeaders() {
  if (state.periodMode === "COMPARE") {
    return ["Группа", "Показатель", "Сейчас", "Сравнение", "Изменение", "Доказательство"];
  }
  if (state.periodMode === "DATE_RANGE") return ["Группа", "Показатель", "Диапазон", "Статус", "Доказательство"];
  return ["Группа", "Показатель", "Сейчас", "Статус", "Доказательство"];
}

function salesDriverRows() {
  const rows = [];
  salesDriverBuckets.forEach((bucket) => {
    bucket.concepts
      .filter((concept) => salesDriverMetricEntry(concept))
      .forEach((concept) => {
        rows.push({
          group: bucket.title,
          concept,
          result: salesDriverResultFor(concept),
          entry: catalogEntry(concept)
        });
      });
  });
  return rows;
}

function salesDriverMetricCells(result, entry) {
  if (!result || !entry) {
    return state.periodMode === "COMPARE"
      ? ["Недоступно", "Недоступно", "Недоступно"]
      : ["Недоступно", "Показатель недоступен для выбранного среза."];
  }
  const limitation = limitationText(result);
  if (state.periodMode === "DATE_RANGE") {
    if (entry.range_aggregation_strategy === "period_only" || result.limitations?.includes("range_aggregation_period_only")) {
      return ["Недоступно", "Показатель доступен только по отдельным периодам."];
    }
    return [compactMetricText(result, entry), limitation || "Показано за доступные периоды диапазона."];
  }
  if (state.periodMode === "SINGLE_PERIOD") {
    return [formatValue(result.value, entry.format), limitation || "Состояние за выбранный период."];
  }
  const comparison = comparisonFor(state.salesDriversResponse, result);
  if (!comparison) {
    return [formatValue(result.value, entry.format), "Нет периода", "Нет подходящего периода сравнения."];
  }
  const deltaFormat = entry.format === "percent" ? "percentage_points" : entry.format;
  return [
    formatValue(comparison.current_value, entry.format),
    formatValue(comparison.comparison_value, entry.format),
    `${formatDeltaValue(comparison.delta, deltaFormat)} · ${formatValue(comparison.pct_delta, "percent")}`
  ];
}

function renderSalesDriverTrend() {
  const result = salesDriverChartResultFor(state.salesDriverMetric) || salesDriverResultFor(state.salesDriverMetric);
  const entry = catalogEntry(state.salesDriverMetric);
  const box = document.getElementById("sales-drivers-chart-box");
  const footnote = document.getElementById("sales-drivers-chart-footnote");
  document.getElementById("sales-drivers-trend-title").textContent = entry ? `Динамика: ${entry.display_label}` : "Динамика показателя";
  document.getElementById("sales-drivers-trend-context").textContent =
    "Один выбранный показатель, фактические доступные периоды без заполнения пропусков.";
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
  const missing = (state.salesDriversChartResponse?.missing_periods || []).map(formatPeriod).join(", ");
  footnote.textContent = [
    missing ? `Пропущены периоды: ${missing}` : "Показаны только реальные доступные периоды.",
    limitationText(result)
  ].filter(Boolean).join(" ");
}

function renderSalesDriverDetailTable() {
  const table = document.getElementById("sales-drivers-detail-table");
  const grain = salesDriverDetailGrain();
  const concepts = salesDriverDetailConcepts();
  const headers = [grainLabels[grain], ...concepts.map(displayLabel)];
  document.getElementById("sales-drivers-table-title").textContent = `${grainLabels[grain]}: детализация`;
  if (!state.salesDriversTableResponse?.metric_results?.length) {
    renderMessageRow(table, "За выбранный период данных нет.");
    document.getElementById("sales-drivers-table-context").textContent = `Нет объектов уровня «${grainLabels[grain]}» для текущего среза.`;
    return;
  }
  const entities = [...new Set(state.salesDriversTableResponse.metric_results.map((result) => result.entity_id))];
  const rows = entities.map((entityId) => {
    const cells = concepts.map((concept) => {
      const result = salesDriverTableResultFor(concept, entityId);
      const entry = catalogEntry(concept);
      return result && entry ? metricCellTextForResponse(result, entry, state.salesDriversTableResponse) : "Недоступно";
    });
    return { cells: [entityDisplayLabel(grain, entityId) || entityId, ...cells], meta: { entityId } };
  });
  renderRows(table, headers, rows, {
    onFirstCellClick: (_label, meta) => {
      if (meta?.entityId) void drillIntoEntity(String(meta.entityId));
    },
    rowLimit: state.tablePageSize,
    onSort: renderSalesDriverDetailTable
  });
  const caption = table.createCaption();
  caption.textContent = `Показаны первые ${Math.min(rows.length, state.tablePageSize)} из ${entities.length}`;
  document.getElementById("sales-drivers-table-context").textContent =
    `${grainLabels[grain]} для текущего среза; сортировка доступна по столбцам таблицы.`;
}

function renderSalesDriverSkeletons() {
  const matrix = document.getElementById("sales-drivers-matrix");
  const detail = document.getElementById("sales-drivers-detail-table");
  if (matrix) renderMessageRow(matrix, "Загрузка показателей...");
  replaceWithMessage(document.getElementById("sales-drivers-chart-box"), "loading-state", "Загрузка динамики...");
  if (detail) renderMessageRow(detail, "Загрузка детализации...");
}

function renderSalesDriversUnavailable(message) {
  renderMessageRow(document.getElementById("sales-drivers-matrix"), message);
  replaceWithMessage(document.getElementById("sales-drivers-chart-box"), "empty-state", message);
  renderMessageRow(document.getElementById("sales-drivers-detail-table"), message);
}

function renderPortfolioMarket() {
  renderPortfolioContextStripForResponse(state.portfolioMarketResponse);
  renderBreadcrumb();
  document.getElementById("portfolio-market-context").textContent = portfolioContextText();
  document.getElementById("portfolio-market-private-label-title").textContent = `Рынок и ${privateLabelDisplayName()}`;
  renderPortfolioPosition();
  renderPortfolioAssortment();
  renderPortfolioBrandCategory();
  renderPortfolioMarketUniverse();
  renderPortfolioCompetitors();
}

function renderPortfolioMarketSkeletons() {
  replaceWithMessage(document.getElementById("portfolio-share-strip"), "loading-state compact", "Загрузка позиции...");
  replaceWithMessage(document.getElementById("portfolio-rank-list"), "loading-state compact", "Загрузка рейтинга...");
  replaceWithMessage(document.getElementById("portfolio-assortment"), "loading-state compact", "Загрузка ассортимента...");
  replaceWithMessage(document.getElementById("portfolio-brand-category"), "loading-state compact", "Загрузка сравнения...");
  replaceWithMessage(document.getElementById("portfolio-market-private-label"), "loading-state compact", "Загрузка рыночного сравнения...");
  renderMessageRow(document.getElementById("portfolio-competitors-table"), "Загрузка конкурентного окружения...");
}

function renderStores() {
  if (state.storesResponse) {
    renderContextStripForResponse(state.storesResponse);
  } else {
    renderStoresContextStripWithoutResponse();
  }
  renderBreadcrumb();
  renderStoreMetricOptions();
  if (state.storesScopeStatus === "no_supported_metrics") {
    renderStoresNoSupportedMetrics();
    return;
  }
  if (state.storesScopeStatus === "product_filter_unsupported") {
    renderStoresProductFilterUnsupported();
    return;
  }
  renderStoreRanking();
  renderSelectedStoreKpi();
  renderStoresTable();
  renderStoreDetailState();
}

function renderStoresSkeletons() {
  replaceWithMessage(document.getElementById("stores-ranking"), "loading-state compact", "Загрузка рейтинга ТТ...");
  replaceWithMessage(document.getElementById("stores-selected-kpi"), "loading-state compact", "Загрузка выбранной ТТ...");
  renderMessageRow(document.getElementById("stores-table"), "Загрузка таблицы ТТ...");
}

function renderStoresProductFilterUnsupported() {
  document.getElementById("stores-ranking-context").textContent =
    "Текущая витрина поддерживает рейтинг ТТ по сети, без продуктных фильтров.";
  replaceWithMessage(
    document.getElementById("stores-ranking"),
    "empty-state compact",
    "Разрез ТТ внутри выбранной категории, производителя, бренда или SKU пока не рассчитан."
  );
  document.getElementById("stores-selected-context").textContent =
    "Снимите продуктные фильтры, чтобы увидеть подтверждённые store-level показатели.";
  replaceWithMessage(
    document.getElementById("stores-selected-kpi"),
    "empty-state compact",
    "Показатели выбранной ТТ в продуктном срезе недоступны."
  );
  document.getElementById("stores-table-context").textContent =
    "Чтобы не показывать неподтверждённую аналитику, таблица ТТ скрыта для этого среза.";
  renderMessageRow(
    document.getElementById("stores-table"),
    "Store-level витрина не содержит подтверждённого разреза по выбранным продуктным фильтрам."
  );
  document.getElementById("stores-detail").textContent =
    "Детализация ТТ по категориям, брендам и SKU требует отдельного подтверждённого маршрута данных.";
}

function renderStoresNoSupportedMetrics() {
  document.getElementById("stores-ranking-context").textContent =
    "Для выбранной сети нет подтверждённых store-level показателей этого экрана.";
  replaceWithMessage(
    document.getElementById("stores-ranking"),
    "empty-state compact",
    "Показатели ТТ недоступны для выбранного среза."
  );
  document.getElementById("stores-selected-context").textContent =
    "Выбранная ТТ появится после доступности store-level показателей.";
  replaceWithMessage(
    document.getElementById("stores-selected-kpi"),
    "empty-state compact",
    "Компактный срез ТТ недоступен."
  );
  document.getElementById("stores-table-context").textContent =
    "Таблица ТТ скрыта, чтобы не показывать неподтверждённые показатели.";
  renderMessageRow(document.getElementById("stores-table"), "Нет подтверждённых показателей для таблицы ТТ.");
  document.getElementById("stores-detail").textContent =
    "Детализация ТТ недоступна без подтверждённых store-level показателей.";
}

function renderSignals() {
  if (state.signalsLoadStatus === "error") {
    renderSignalsErrorState();
    return;
  }
  renderSignalsContextStrip();
  renderBreadcrumb();
  updateSignalsFilterCounts();
  renderSignalList();
  renderSignalLimitations();
}

function renderSignalsErrorState() {
  updateFilterCount();
  renderBreadcrumb();
  updateSignalsFilterCounts();
  const context = [signalPeriodContextText(), contextFilterText()].filter(Boolean).join(" · ");
  document.getElementById("context-strip").textContent = context;
  document.getElementById("context-coverage-note").textContent = "";
  document.getElementById("signals-context").textContent = "Не удалось загрузить ленту сигналов.";
  document.getElementById("signals-feed-context").textContent = "Повторите попытку после обновления данных.";
  replaceWithMessage(
    document.getElementById("signals-list"),
    "error-state",
    "Не удалось загрузить данные. Повторите попытку.",
  );
  replaceWithMessage(
    document.getElementById("signals-limitations"),
    "error-state compact",
    "Доступность ленты не удалось проверить. Повторите попытку.",
  );
}

function renderSignalsContextStrip() {
  updateFilterCount();
  const response = state.signalsResponse;
  const parts = [
    signalPeriodContextText(),
    contextFilterText(),
    privateLabelScopeText(response?.private_label_scope || document.getElementById("private-label-scope").value)
  ].filter(Boolean);
  document.getElementById("context-strip").textContent = parts.join(" · ");
  document.getElementById("context-coverage-note").textContent = signalLimitations()
    .map((item) => item.message || signalLimitationText(item.code || item))
    .slice(0, 1)
    .join("");
}

function renderSignalsSkeletons() {
  replaceWithMessage(document.getElementById("signals-list"), "loading-state compact", "Загрузка подтверждённых сигналов...");
  replaceWithMessage(document.getElementById("signals-limitations"), "loading-state compact", "Проверка доступности ленты...");
}

function renderSignalList() {
  const target = document.getElementById("signals-list");
  const rows = filteredSignalRows();
  const allRows = signalRows();
  document.getElementById("signals-context").textContent = signalContextText();
  document.getElementById("signals-feed-context").textContent = signalFeedContextText(allRows.length, rows.length);
  if (!allRows.length) {
    replaceWithMessage(target, "empty-state compact", "Для выбранного среза нет подтверждённых сигналов.");
    return;
  }
  if (!rows.length) {
    replaceWithMessage(target, "empty-state compact", "Для выбранного фильтра подтверждённых сигналов нет.");
    return;
  }
  target.replaceChildren(...rows.map((row) => signalRowNode(row)));
}

function signalRowNode(row) {
  const node = document.createElement("article");
  node.className = `signal-row ${signalKindClass(row)}`;
  node.setAttribute("role", "listitem");
  const priority = document.createElement("div");
  priority.className = "signal-priority";
  appendText(priority, "span", severityLabel(row));
  appendText(priority, "small", signalTypeLabels[row.signal_type] || row.signal_type || "Сигнал");
  node.appendChild(priority);

  const body = document.createElement("div");
  body.className = "signal-body";
  appendText(body, "strong", signalObjectLabel(row));
  appendText(body, "span", signalObservationText(row));
  const meta = document.createElement("p");
  meta.textContent = signalMetaText(row);
  body.appendChild(meta);
  node.appendChild(body);

  const values = document.createElement("div");
  values.className = "signal-values";
  appendText(values, "span", `Сейчас: ${signalValueText(row.current_value)}`);
  appendText(values, "span", `Сравнение: ${signalValueText(row.reference_value)}`);
  appendText(values, "strong", `Изменение: ${signalDeltaText(row)}`);
  node.appendChild(values);

  const reason = document.createElement("div");
  reason.className = "signal-reason";
  appendText(reason, "span", signalReasonText(row));
  const button = document.createElement("button");
  button.type = "button";
  button.className = "inline-link";
  button.textContent = "Доказательство";
  button.addEventListener("click", () => openSignalEvidence(row));
  reason.appendChild(button);
  node.appendChild(reason);
  return node;
}

function renderSignalLimitations() {
  const target = document.getElementById("signals-limitations");
  const limitations = signalLimitations();
  if (!limitations.length) {
    replaceWithMessage(target, "empty-state compact", "Ограничений доступности для выбранного среза нет.");
    return;
  }
  target.replaceChildren(...limitations.map((item) => {
    const node = document.createElement("article");
    node.className = "signal-limitation";
    appendText(node, "strong", "Ограничение доступности");
    appendText(node, "span", item.message || signalLimitationText(item.code || item));
    return node;
  }));
}

function updateSignalsFilterCounts() {
  const rows = signalRows();
  const counts = {
    all: rows.length,
    commercial: rows.filter((row) => row.signal_type === "COMMERCIAL_SIGNAL").length,
    pattern: rows.filter((row) => row.signal_type === "DETERMINISTIC_PATTERN").length,
    quality: rows.filter((row) => row.signal_type === "DATA_QUALITY_ALERT").length
  };
  document.querySelectorAll("[data-signal-kind]").forEach((button) => {
    const key = button.dataset.signalKind || "all";
    button.textContent = `${signalKindLabels[key] || "Все"} · ${counts[key] || 0}`;
  });
}

function signalRows() {
  const response = state.signalsResponse || {};
  const patternRows = response[["deter", "ministic_patterns"].join("")] || [];
  return [
    ...(response.signals || []),
    ...patternRows,
    ...(response.data_quality_alerts || [])
  ];
}

function filteredSignalRows() {
  return signalRows()
    .filter((row) => state.signalKindFilter === "all" || signalKindClass(row) === state.signalKindFilter)
    .filter((row) => state.signalGrainFilter === "all" || row.object_grain === state.signalGrainFilter)
    .sort((a, b) => (a.priority || 99) - (b.priority || 99));
}

function signalKindClass(row) {
  if (row.signal_type === "COMMERCIAL_SIGNAL") return "commercial";
  if (row.signal_type === "DETERMINISTIC_PATTERN") return "pattern";
  if (row.signal_type === "DATA_QUALITY_ALERT") return "quality";
  return "other";
}

function signalLimitations() {
  const response = state.signalsResponse || {};
  const structured = response.capability_limitations || [];
  const plain = (response.limitations || []).map((code) => ({ code, message: signalLimitationText(code) }));
  const seen = new Set();
  return [...structured, ...plain].filter((item) => {
    const key = item.code || item.message || String(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function signalContextText() {
  const response = state.signalsResponse;
  if (!response) return "Подтверждённые события и вопросы к качеству данных для выбранного среза.";
  const total = signalRows().length;
  const period = signalPeriodContextText();
  if (!total) return `${period} · подтверждённых сигналов нет.`;
  return `${period} · ${total} ${pluralRu(total, "подтверждённый сигнал", "подтверждённых сигнала", "подтверждённых сигналов")}.`;
}

function signalPeriodContextText() {
  if (state.periodMode === "DATE_RANGE") return `${formatPeriod(selectedDateFrom())} — ${formatPeriod(selectedDateTo())}`;
  if (state.periodMode === "SINGLE_PERIOD") return formatPeriod(selectedDateFrom());
  return `${formatPeriod(selectedDateFrom())} · ${comparisonLabels[state.comparisonMode]}`;
}

function signalFeedContextText(total, filtered) {
  if (!total) return "Обычные изменения показателей не превращаются в сигналы без подтверждённого правила.";
  if (total === filtered) return "Показаны подтверждённые события выбранного среза.";
  return `Показано ${filtered} из ${total} по локальному фильтру.`;
}

function renderDataSkeletons() {
  replaceWithMessage(document.getElementById("data-coverage-grid"), "loading-state compact", "Загрузка покрытия периодов...");
  replaceWithMessage(document.getElementById("data-quality-summary"), "loading-state compact", "Проверка качества данных...");
  renderMessageRow(document.getElementById("data-source-table"), "Загрузка строк для проверки...");
  replaceWithMessage(document.getElementById("data-audit-content"), "loading-state compact", "Загрузка аудита расчёта...");
}

function renderDataScreen() {
  const response = state.dataResponse;
  updateFilterCount();
  renderBreadcrumb();
  document.getElementById("context-strip").textContent = [
    periodContextText(response),
    contextFilterText(),
    privateLabelScopeText(response?.private_label_scope || document.getElementById("private-label-scope").value)
  ].filter(Boolean).join(" · ");
  document.getElementById("context-coverage-note").textContent = dataAvailabilityNote(response);
  document.getElementById("data-context").textContent = "Текущий аналитический набор данных, покрытие, качество и проверка расчёта.";
  renderDataAvailability();
  renderDataQuality();
  renderDataRows();
  renderDataAudit();
}

function renderDataAvailability() {
  const target = document.getElementById("data-coverage-grid");
  const grid = state.dataResponse?.coverage_grid;
  if (!grid || grid.status !== "READY") {
    replaceWithMessage(target, "empty-state compact", "Покрытие периодов недоступно для текущего набора данных.");
    return;
  }
  const table = document.createElement("table");
  table.className = "availability-table";
  const tbody = document.createElement("tbody");
  (grid.years || []).forEach((yearRow) => {
    const row = document.createElement("tr");
    const yearHeader = document.createElement("th");
    yearHeader.scope = "row";
    yearHeader.textContent = yearRow.year;
    row.appendChild(yearHeader);
    (yearRow.months || []).forEach((month) => {
      const cell = document.createElement("td");
      cell.className = month.available ? "available" : "missing";
      cell.setAttribute("aria-label", `${month.label}: ${month.available ? "есть данные" : "нет данных"}`);
      appendText(cell, "span", month.available ? "●" : "—");
      appendText(cell, "small", month.label);
      row.appendChild(cell);
    });
    tbody.appendChild(row);
  });
  table.appendChild(tbody);
  target.replaceChildren(table);
}

function renderDataQuality() {
  const target = document.getElementById("data-quality-summary");
  const quality = state.dataResponse?.quality_summary;
  if (!quality) {
    replaceWithMessage(target, "empty-state compact", "Сводка качества недоступна.");
    return;
  }
  const items = [
    ["Статус витрины", martBuildStatusText(quality.mart_build_status)],
    ["Активные ревизии", quality.active_revision_count ?? "н/д"],
    ["Строки источника", formatValue(quality.source_row_count, "integer")],
    ["Строки витрины", formatValue(quality.fact_row_count, "integer")],
    ["Проверки", quality.warnings?.length ? `${quality.warnings.length} требует внимания` : "доступные проверки без предупреждений"]
  ];
  const list = document.createElement("div");
  list.className = "quality-list";
  items.forEach(([label, value]) => {
    const item = document.createElement("div");
    appendText(item, "span", label);
    appendText(item, "strong", value);
    list.appendChild(item);
  });
  if (quality.warnings?.length) {
    const warning = document.createElement("p");
    warning.className = "quality-warning";
    warning.textContent = "Есть предупреждения качества. Подробности доступны в аудите расчёта.";
    list.appendChild(warning);
  }
  target.replaceChildren(list);
}

function renderDataRows() {
  const table = document.getElementById("data-source-table");
  const rowsPayload = state.dataResponse?.source_like_rows;
  const prev = document.getElementById("data-prev-page");
  const next = document.getElementById("data-next-page");
  if (!rowsPayload || rowsPayload.status !== "READY") {
    document.getElementById("data-rows-context").textContent =
      "Проверочный набор строк не подключён для текущего режима; аналитические расчёты остаются доступными.";
    renderMessageRow(table, "Строки для проверки пока недоступны для текущего набора данных.");
    prev.disabled = true;
    next.disabled = true;
    return;
  }
  const columns = rowsPayload.columns || [];
  const rows = rowsPayload.rows || [];
  document.getElementById("data-rows-context").textContent =
    `Показано ${rows.length} из ${rowsPayload.total_count || 0}. Строки ограничены выбранным срезом.`;
  const thead = table.querySelector("thead") || document.createElement("thead");
  const tbody = table.querySelector("tbody") || document.createElement("tbody");
  const headerRow = document.createElement("tr");
  columns.forEach((column) => appendText(headerRow, "th", dataColumnLabel(column)));
  thead.replaceChildren(headerRow);
  if (!rows.length) {
    renderMessageRow(table, "Для выбранного среза строк не найдено.");
  } else {
    tbody.replaceChildren(...rows.map((row) => {
      const tr = document.createElement("tr");
      columns.forEach((column) => appendText(tr, "td", dataCellText(row[column], column)));
      return tr;
    }));
    table.replaceChildren(thead, tbody);
  }
  const offset = rowsPayload.offset || 0;
  const limit = rowsPayload.limit || state.tablePageSize;
  const total = rowsPayload.total_count || 0;
  prev.disabled = offset <= 0;
  next.disabled = offset + limit >= total;
}

function renderDataAudit() {
  const target = document.getElementById("data-audit-content");
  const audit = state.dataResponse?.audit;
  if (!audit) {
    replaceWithMessage(target, "empty-state compact", "Аудит расчёта недоступен.");
    return;
  }
  target.replaceChildren(section(null, [
    ["Ревизии источника", compactList((audit.source_revisions || []).map((item) => item.source_revision_id))],
    ["Статус обработки", compactList((audit.source_revisions || []).map((item) => item.processing_status))],
    ["Периоды источника", compactList(audit.coverage_periods)],
    ["Версия аналитической витрины", audit.mart_build?.mart_build_id || "н/д"],
    ["Статус витрины", martBuildStatusText(audit.mart_build?.status)],
    ["Запуск анализа", compactList(audit.mart_build?.analysis_run_ids)],
    ["Версии правил", compactList(audit.mart_build?.rule_versions)],
    ["Учёт ассортимента", privateLabelScopeText(audit.private_label_scope)]
  ]));
}

function dataAvailabilityNote(response) {
  const periods = response?.coverage_grid?.available_periods || [];
  if (!periods.length) return "Покрытие периодов не найдено.";
  return `${periods.length} ${pluralRu(periods.length, "период доступен", "периода доступны", "периодов доступны")}.`;
}

function dataColumnLabel(column) {
  return {
    period: "Период",
    category: "Категория",
    manufacturer: "Производитель",
    brand: "Бренд",
    sku_name: "SKU",
    units: "Продажи, шт.",
    revenue_vat: "Оборот с НДС",
    private_label_flag: "Признак ассортимента"
  }[column] || column;
}

function dataCellText(value, column) {
  if (value === null || value === undefined || value === "") return "—";
  if (column === "period") return formatPeriod(value);
  if (column === "private_label_flag") return value ? "да" : "нет";
  if (column === "units") return formatValue(Number(value), "integer");
  if (column === "revenue_vat") return formatValue(Number(value), "currency");
  return String(value);
}

function martBuildStatusText(status) {
  return {
    approved: "утверждена",
    built: "собрана",
    superseded: "заменена",
    failed: "ошибка"
  }[status] || status || "н/д";
}

function signalObjectLabel(row) {
  const grain = row.object_grain || state.currentGrain;
  const label = entityDisplayLabel(grain, row.object_id);
  return [grainLabels[grain] || grain, label].filter(Boolean).join(": ") || "Выбранный срез";
}

function signalObservationText(row) {
  return signalEventLabels[row.event_type] || signalEventLabels[row.event_family] || "Подтверждённое наблюдение требует проверки.";
}

function signalMetaText(row) {
  const pieces = [
    row.period ? formatPeriod(row.period) : "",
    row.reference_period ? `сравнение: ${formatPeriod(row.reference_period)}` : "",
    comparisonLabels[row.comparison_type] || "",
    row.comparison_quality ? signalQualityText(row.comparison_quality) : "",
    privateLabelScopeText(row.private_label_scope)
  ];
  return pieces.filter(Boolean).join(" · ");
}

function signalReasonText(row) {
  const confidence = row.confidence ? `доверие: ${signalQualityText(row.confidence)}` : "";
  const status = row.status ? signalQualityText(row.status) : "";
  return [severityLabel(row), status, confidence].filter(Boolean).join(" · ") || "Подтверждено правилом ленты сигналов.";
}

function severityLabel(row) {
  return signalSeverityLabels[row.severity] || signalSeverityLabels[String(row.severity || "").toUpperCase()] || "Приоритет не задан";
}

function signalValueText(value) {
  return value === null || value === undefined ? "н/д" : formatValue(value, "decimal");
}

function signalDeltaText(row) {
  if (row.delta_pp !== null && row.delta_pp !== undefined) return formatDeltaValue(row.delta_pp, "percentage_points");
  if (row.delta_pct !== null && row.delta_pct !== undefined) return formatDeltaValue(row.delta_pct, "percent");
  if (row.delta_abs !== null && row.delta_abs !== undefined) return formatDeltaValue(row.delta_abs, "decimal");
  return "н/д";
}

function signalLimitationText(code) {
  return {
    signal_events_path_not_configured: "Лента сигналов не подключена к подтверждённым событиям.",
    no_enabled_event_rules: "Для выбранного источника нет включённых правил сигналов.",
    no_confirmed_events: "Для выбранного среза нет подтверждённых событий.",
    no_surfaced_signals_in_scope: "Для выбранного среза нет событий, разрешённых к показу как сигналы.",
    no_confirmed_events_in_scope: "Для выбранного среза нет подтверждённых сигналов.",
    event_private_label_scope_not_materialized: "События не содержат подтверждённого среза по учёту ассортимента.",
    event_entity_scope_not_materialized: "События не содержат подтверждённой детализации объекта.",
    event_category_scope_not_materialized: "События не содержат подтверждённого среза категории.",
    event_manufacturer_scope_not_materialized: "События не содержат подтверждённого среза производителя.",
    event_brand_scope_not_materialized: "События не содержат подтверждённого среза бренда.",
    event_sku_scope_not_materialized: "События не содержат подтверждённого среза SKU.",
    event_store_scope_not_materialized: "События не содержат подтверждённого среза ТТ."
  }[code] || "Есть ограничение доступности ленты сигналов.";
}

function signalQualityText(value) {
  return {
    READY: "готово",
    COMPLETE: "полное",
    PARTIAL: "частично",
    VALID: "проверено",
    INVALID: "не подтверждено",
    CONFIRMED: "подтверждено",
    MISSING_EVIDENCE: "не хватает доказательств",
    NO_CONFIRMED_EVENTS: "нет подтверждённых событий",
    NOT_CONFIGURED: "не подключено",
    HIGH: "высокое",
    MEDIUM: "среднее",
    LOW: "низкое"
  }[value] || value;
}

function renderStoresContextStripWithoutResponse() {
  updateFilterCount();
  const parts = [
    periodContextText(),
    contextFilterText(),
    privateLabelScopeText(document.getElementById("private-label-scope").value)
  ].filter(Boolean);
  let coverageNote = "";
  if (state.storesScopeStatus === "product_filter_unsupported") {
    parts.push("Разрез ТТ по продуктным фильтрам пока не рассчитан");
    coverageNote = "Разрез ТТ по выбранным продуктным фильтрам требует отдельного подтверждённого маршрута данных.";
  }
  if (state.storesScopeStatus === "no_supported_metrics") {
    coverageNote = "Для выбранной сети нет подтверждённых store-level показателей этого экрана.";
  }
  document.getElementById("context-strip").textContent = parts.join(" · ");
  document.getElementById("context-coverage-note").textContent = coverageNote;
}

function renderStoreMetricOptions() {
  const select = document.getElementById("stores-metric");
  const metrics = storeRankingMetrics.filter((concept) => metricEntryForGrain(concept, "store"));
  select.replaceChildren(...metrics.map((concept) => option(concept, displayLabel(concept))));
  if (!metrics.includes(state.storesMetric)) {
    state.storesMetric = metrics[0] || "revenue";
    state.sortColumn = storeSortColumn();
    state.sortDirection = "desc";
  }
  select.value = state.storesMetric;
}

function renderStoreRanking() {
  const target = document.getElementById("stores-ranking");
  const rows = storeRowsByMetric(state.storesMetric);
  if (!rows.length) {
    replaceWithMessage(target, "empty-state compact", "За выбранный период данных по ТТ нет.");
    document.getElementById("stores-ranking-context").textContent = "Рейтинг строится только по подтверждённым store-level показателям.";
    return;
  }
  const maxValue = Math.max(...rows.map((row) => Math.abs(Number(row.result.value) || 0)), 1);
  target.replaceChildren(...rows.map((row, index) => {
    const node = document.createElement("article");
    node.className = row.entityId === selectedStoreId() ? "store-ranking-row is-selected" : "store-ranking-row";
    const labelButton = document.createElement("button");
    labelButton.type = "button";
    labelButton.className = "table-link store-rank-label";
    labelButton.textContent = `${index + 1}. ${entityDisplayLabel("store", row.entityId)}`;
    labelButton.addEventListener("click", () => {
      void selectStore(row.entityId);
    });
    node.appendChild(labelButton);
    const barWrap = document.createElement("div");
    barWrap.className = "ranked-bar-track";
    const bar = document.createElement("div");
    bar.className = "ranked-bar-fill";
    bar.style.width = `${Math.max(3, (Math.abs(Number(row.result.value) || 0) / maxValue) * 100)}%`;
    barWrap.appendChild(bar);
    node.appendChild(barWrap);
    appendText(node, "strong", storeMetricWithDelta(row.result, catalogEntry(state.storesMetric), state.storesResponse));
    return node;
  }));
  document.getElementById("stores-ranking-context").textContent = state.periodMode === "COMPARE"
    ? "Показан текущий уровень и изменение к периоду сравнения. Это не вклад в изменение."
    : "Показан текущий уровень по выбранному показателю.";
}

function renderSelectedStoreKpi() {
  const target = document.getElementById("stores-selected-kpi");
  const storeId = selectedStoreId();
  if (!storeId) {
    replaceWithMessage(target, "empty-state compact", "Выберите ТТ в рейтинге или фильтре.");
    document.getElementById("stores-selected-context").textContent = "Компактный срез появляется только для выбранной торговой точки.";
    return;
  }
  const cards = storeKpiConcepts
    .map((concept) => storeResultFor(concept, storeId))
    .filter(Boolean)
    .map((result) => storeKpiCard(result));
  if (!cards.length) {
    replaceWithMessage(target, "empty-state compact", "Показатели выбранной ТТ недоступны для этого среза.");
    return;
  }
  target.replaceChildren(...cards);
  document.getElementById("stores-selected-context").textContent =
    `${entityDisplayLabel("store", storeId)} · подтверждённые store-level показатели.`;
}

function renderStoresTable() {
  const table = document.getElementById("stores-table");
  const rows = storeRowsByMetric(state.storesMetric);
  if (!rows.length) {
    renderMessageRow(table, "За выбранный период данных по ТТ нет.");
    document.getElementById("stores-table-context").textContent = "Таблица использует только подтверждённые store-level показатели.";
    return;
  }
  const headers = ["Точка продаж", "Оборот", "Δ", "Продажи, шт.", "Δ", "Абсолютная маржа", "Маржинальность", "SKU"];
  if (!headers.includes(state.sortColumn)) {
    state.sortColumn = storeSortColumn();
    state.sortDirection = "desc";
  }
  const tableRows = rows.map((row) => ({
    cells: [
      entityDisplayLabel("store", row.entityId),
      storeTableValue("revenue", row.entityId),
      storeTableDelta("revenue", row.entityId),
      storeTableValue("units", row.entityId),
      storeTableDelta("units", row.entityId),
      storeTableValue("retailer_margin_abs", row.entityId),
      storeTableValue("retailer_margin_pct", row.entityId),
      storeTableValue("sku_count", row.entityId)
    ],
    meta: { entityId: row.entityId }
  }));
  renderRows(table, headers, tableRows, {
    rowLimit: state.tablePageSize,
    onFirstCellClick: (_label, meta) => {
      if (meta?.entityId) void selectStore(meta.entityId);
    },
    onSort: renderStoresTable
  });
  const caption = table.createCaption();
  caption.textContent = `Показаны ${Math.min(tableRows.length, state.tablePageSize)} из ${tableRows.length} ТТ · сортировка по выбранному показателю`;
  document.getElementById("stores-table-context").textContent = state.periodMode === "COMPARE"
    ? "Δ показывает изменение к периоду сравнения; вклад по ТТ не рассчитывается в этом разделе."
    : "Таблица ранжирована по выбранному показателю.";
}

function renderStoreDetailState() {
  const target = document.getElementById("stores-detail");
  const storeId = selectedStoreId();
  target.textContent = storeId
    ? "Детализация выбранной ТТ по категориям, брендам и SKU будет подключена после подтверждения отдельного разреза данных."
    : "Выберите ТТ, чтобы зафиксировать магазин в глобальном срезе.";
}

function storeKpiCard(result) {
  const entry = catalogEntry(result.metric_concept);
  const node = document.createElement("article");
  node.className = "store-kpi";
  appendText(node, "span", displayLabel(result.metric_concept));
  appendText(node, "strong", storeMetricWithDelta(result, entry, state.storesResponse));
  const limitation = limitationText(result);
  if (limitation) appendText(node, "small", limitation);
  const button = storeProvenanceButton(result);
  if (button) node.appendChild(button);
  return node;
}

function storeRowsByMetric(metricConcept) {
  return storeEntityIds()
    .map((entityId) => ({ entityId, result: storeResultFor(metricConcept, entityId) }))
    .filter((row) => row.result && row.result.value !== null && row.result.value !== undefined)
    .sort((left, right) => Number(right.result.value || 0) - Number(left.result.value || 0));
}

function storeEntityIds() {
  return [...new Set((state.storesResponse?.metric_results || []).map((result) => result.entity_id))];
}

function storeResultFor(concept, entityId) {
  return state.storesResponse?.metric_results.find((result) => result.metric_concept === concept && result.entity_id === entityId);
}

function storeTableValue(concept, entityId) {
  const result = storeResultFor(concept, entityId);
  const entry = catalogEntry(concept);
  if (!result || !entry) return "Недоступно";
  if (result.limitations?.includes("range_aggregation_period_only")) return "только по периодам";
  return formatValue(result.value, entry.format);
}

function storeTableDelta(concept, entityId) {
  if (state.periodMode !== "COMPARE") return "—";
  const result = storeResultFor(concept, entityId);
  const entry = catalogEntry(concept);
  const comparison = comparisonFor(state.storesResponse, result);
  if (!result || !entry || !comparison) return "н/д";
  return formatDeltaValue(comparison.delta, entry.format);
}

function storeMetricWithDelta(result, entry, response) {
  if (!result || !entry) return "Недоступно";
  const value = formatValue(result.value, entry.format);
  const comparison = comparisonFor(response, result);
  if (state.periodMode === "COMPARE" && comparison) {
    return `${value} · ${formatDeltaValue(comparison.delta, entry.format)}`;
  }
  if (result.limitations?.includes("range_aggregation_period_only")) return "только по периодам";
  return value;
}

function storeSortColumn() {
  return displayLabel(state.storesMetric);
}

function storeProvenanceButton(result) {
  if (!result?.provenance) return null;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "inline-link";
  button.textContent = "Откуда?";
  button.addEventListener("click", () => openStoreProvenance(result));
  return button;
}

function openStoreProvenance(result) {
  const content = document.getElementById("provenance-content");
  content.replaceChildren();
  provenanceSections(result.provenance || {}, result).forEach((section) => content.appendChild(section));
  document.getElementById("provenance-drawer").classList.add("is-open");
  document.getElementById("provenance-drawer").setAttribute("aria-hidden", "false");
  document.getElementById("scrim").classList.add("is-open");
}

function renderPortfolioContextStripForResponse(response) {
  if (!response) return;
  updateFilterCount();
  document.getElementById("context-strip").textContent = contextSummaryText(response);
  document.getElementById("context-coverage-note").textContent = coverageNoteText(response);
}

function renderPortfolioPosition() {
  const shareStrip = document.getElementById("portfolio-share-strip");
  const rankList = document.getElementById("portfolio-rank-list");
  const shareItems = portfolioItems(portfolioShareConcepts).filter(isDisplayablePortfolioItem);
  const rank = portfolioItem("manufacturer_rank_revenue");
  const rows = rank?.rows || [];
  const selectedManufacturer = selectedFilterValues().manufacturer || (state.currentGrain === "manufacturer" ? entityIdsForSummary()[0] : "");

  if (shareItems.length) {
    shareStrip.replaceChildren(...shareItems.map((item) => portfolioMetricTile(item)));
  } else {
    replaceWithMessage(shareStrip, "empty-state compact", portfolioShareUnavailableText());
  }

  if (rows.length) {
    const maxValue = Math.max(...rows.map((row) => Math.abs(Number(row.metric_value) || 0)), 1);
    rankList.replaceChildren(...rows.slice(0, 10).map((row) => {
      const node = document.createElement("article");
      node.className = row.manufacturer === selectedManufacturer ? "ranked-bar-row is-selected" : "ranked-bar-row";
      const label = entityDisplayLabel("manufacturer", row.manufacturer) || row.manufacturer;
      appendText(node, "span", `${row.rank}. ${label}`);
      const barWrap = document.createElement("div");
      barWrap.className = "ranked-bar-track";
      const bar = document.createElement("div");
      bar.className = "ranked-bar-fill";
      bar.style.width = `${Math.max(4, (Math.abs(Number(row.metric_value) || 0) / maxValue) * 100)}%`;
      barWrap.appendChild(bar);
      node.appendChild(barWrap);
      appendText(node, "strong", `${formatValue(row.metric_value, catalogEntry("revenue")?.format || "decimal")} · ${row.rank} из ${row.population_count}`);
      const provenanceButton = portfolioProvenanceButton({
        ...rank,
        value: row.rank,
        entity_id: row.manufacturer,
        provenance: row.provenance || rank.provenance
      });
      if (provenanceButton) node.appendChild(provenanceButton);
      return node;
    }));
    document.getElementById("portfolio-position-context").textContent =
      "Рейтинг производителей внутри выбранной категории; выделение показывает текущий выбранный производитель.";
  } else {
    replaceWithMessage(rankList, "empty-state compact", portfolioRankUnavailableText(rank));
  }
}

function renderPortfolioAssortment() {
  const target = document.getElementById("portfolio-assortment");
  const active = portfolioItem("active_sku_count");
  const peak = portfolioItem("historical_peak_active_sku_count");
  const change = portfolioItem("active_sku_change_pct");
  if (![active, peak, change].some(isDisplayablePortfolioItem)) {
    replaceWithMessage(target, "empty-state compact", portfolioAssortmentUnavailableText(active || peak || change));
    return;
  }
  const current = Number(active?.value) || 0;
  const peakValue = Number(peak?.value) || 0;
  const width = peakValue > 0 ? Math.max(3, Math.min(100, (current / peakValue) * 100)) : 0;
  const bullet = document.createElement("div");
  bullet.className = "bullet-metric";
  const values = document.createElement("div");
  values.className = "bullet-values";
  appendText(values, "span", `${displayLabel("active_sku_count")}: ${formatValue(active?.value, "integer")}`);
  appendText(values, "span", `${displayLabel("historical_peak_active_sku_count")}: ${formatValue(peak?.value, "integer")}`);
  appendText(values, "strong", `${displayLabel("active_sku_change_pct")}: ${formatValue(change?.value, "percent")}`);
  bullet.appendChild(values);
  const track = document.createElement("div");
  track.className = "bullet-track";
  const fill = document.createElement("div");
  fill.className = "bullet-fill";
  fill.style.width = `${width}%`;
  track.appendChild(fill);
  bullet.appendChild(track);
  const button = portfolioProvenanceButton(active || peak || change);
  if (button) bullet.appendChild(button);
  target.replaceChildren(bullet);
  document.getElementById("portfolio-assortment-context").textContent =
    "Активность SKU основана на продажах за выбранный период и сравнении с пиком доступной истории.";
}

function renderPortfolioBrandCategory() {
  const target = document.getElementById("portfolio-brand-category");
  const brand = portfolioItem("brand_delta_pct");
  const category = portfolioItem("category_delta_pct");
  const gap = portfolioItem("brand_category_delta_gap_pp");
  if (![brand, category, gap].some(isDisplayablePortfolioItem)) {
    replaceWithMessage(target, "empty-state compact", portfolioBrandUnavailableText(brand || category || gap));
    return;
  }
  const node = document.createElement("div");
  node.className = "dumbbell-comparison";
  const values = [Number(brand?.value) || 0, Number(category?.value) || 0];
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const span = max - min || 1;
  const markerPosition = (value) => ((Number(value) - min) / span) * 100;
  const track = document.createElement("div");
  track.className = "dumbbell-track";
  [
    { item: brand, className: "brand-marker", label: "Бренд" },
    { item: category, className: "category-marker", label: "Категория" }
  ].forEach(({ item, className, label }) => {
    const marker = document.createElement("span");
    marker.className = `dumbbell-marker ${className}`;
    marker.style.left = `${markerPosition(item?.value)}%`;
    marker.title = `${label}: ${formatValue(item?.value, "percent")}`;
    track.appendChild(marker);
  });
  node.appendChild(track);
  const rows = document.createElement("div");
  rows.className = "comparison-strip";
  [brand, category, gap].filter(Boolean).forEach((item) => rows.appendChild(portfolioMetricTile(item)));
  node.appendChild(rows);
  target.replaceChildren(node);
  document.getElementById("portfolio-brand-context").textContent =
    "Показан разрыв темпа бренда и категории; это не статус и не объяснение причины.";
}

function renderPortfolioMarketUniverse() {
  const target = document.getElementById("portfolio-market-private-label");
  const items = portfolioItems(portfolioMarketUniverseConcepts).filter(isDisplayablePortfolioItem);
  if (!items.length) {
    replaceWithMessage(target, "empty-state compact", portfolioGatedText(portfolioMarketUniverseConcepts));
    document.getElementById("portfolio-market-private-label-context").textContent =
      "Сравнительная вселенная показывается только после готовой маршрутизации и доказательства.";
    return;
  }
  target.replaceChildren(...items.map((item) => portfolioMetricTile(item)));
}

function renderPortfolioCompetitors() {
  const table = document.getElementById("portfolio-competitors-table");
  const competitors = portfolioItems(portfolioCompetitorConcepts).filter(isDisplayablePortfolioItem);
  if (!competitors.length || !competitors.some((item) => item.rows?.length)) {
    renderMessageRow(table, portfolioGatedText(portfolioCompetitorConcepts));
    document.getElementById("portfolio-competitors-context").textContent =
      "Широкие конкурентные группы будут показаны, когда маршрут вернёт подтверждённые данные.";
    return;
  }
  const rows = competitors.flatMap((item) => (item.rows || []).map((row) => ({
    cells: [row.label || row.entity_id || "н/д", item.label || displayLabel(item.concept_id), item.status],
    meta: { item }
  })));
  renderRows(table, ["Объект", "Показатель", "Статус"], rows, { rowLimit: state.tablePageSize, onSort: renderPortfolioCompetitors });
}

function portfolioMetricTile(item) {
  const node = document.createElement("article");
  node.className = "portfolio-metric";
  appendText(node, "span", displayLabel(item.concept_id));
  appendText(node, "strong", formatPortfolioItemValue(item));
  const detail = portfolioItemDetailText(item);
  if (detail) appendText(node, "small", detail);
  const button = portfolioProvenanceButton(item);
  if (button) node.appendChild(button);
  return node;
}

function portfolioProvenanceButton(item) {
  if (!item?.provenance) return null;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "inline-link";
  button.textContent = "Откуда?";
  button.addEventListener("click", () => openPortfolioProvenance(item));
  return button;
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
    onFirstCellClick: (entityId) => {
      void drillIntoEntity(String(entityId));
    },
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
    entityButton.addEventListener("click", () => {
      void drillIntoEntity(String(row.child_entity_id));
    });
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
  renderContextStripForResponse(state.summaryResponse);
}

function renderContextStripForResponse(response) {
  if (!response) return;
  updateComparisonPeriodDisplay(response);
  updateFilterCount();
  document.getElementById("context-strip").textContent = contextSummaryText(response);
  document.getElementById("context-coverage-note").textContent = coverageNoteText(response);
}

function renderBreadcrumb() {
  const row = document.getElementById("breadcrumb-row");
  if (!row) return;
  const activePath = state.drilldownPath.filter((item) => document.getElementById(`${item.grain}-filter`)?.value === item.value);
  if (activePath.length !== state.drilldownPath.length) state.drilldownPath = activePath;
  if (!activePath.length) {
    row.replaceChildren();
    row.classList.add("is-empty");
    return;
  }
  row.classList.remove("is-empty");
  row.replaceChildren(...activePath.map((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "crumb";
    const { grain, value } = item;
    button.dataset.drillGrain = grain;
    const isActive = grain === state.currentGrain || index === activePath.length - 1 && !activePath.some((pathItem) => pathItem.grain === state.currentGrain);
    button.classList.toggle("is-active", isActive);
    if (isActive) button.setAttribute("aria-current", "page");
    button.textContent = breadcrumbLabel(grain, value);
    button.addEventListener("click", async () => {
      await activateBreadcrumbGrain(grain);
    });
    return button;
  }));
}

function canActivateSummaryGrain(grain) {
  if (grain === "network") return true;
  return Boolean(document.getElementById(`${grain}-filter`)?.value);
}

async function activateBreadcrumbGrain(grain) {
  if (!canActivateSummaryGrain(grain)) return;
  const index = drilldownOrder.indexOf(grain);
  drilldownOrder.slice(index + 1).forEach((child) => {
    if (child !== "network") clearEntityFilter(child, { resetChildren: false, preserveCurrentGrain: true });
  });
  state.drilldownPath = state.drilldownPath.filter((item) => drilldownOrder.indexOf(item.grain) <= index);
  state.currentGrain = grain;
  renderBreadcrumb();
  updatePreviewGrain();
  resetDataPagination();
  await refreshRuntimeOptions();
  await runActiveViewQuery();
}

function breadcrumbLabel(grain, value) {
  if (grain === "network") return "Все данные";
  return `${grainLabels[grain]}: ${entityDisplayLabel(grain, value)}`;
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
  updatePeriodSummary();
}

function updatePeriodSummary() {
  const summary = document.getElementById("period-summary");
  const detail = document.getElementById("period-summary-detail");
  if (!summary || !detail) return;
  if (state.periodMode === "DATE_RANGE") {
    summary.textContent = `${formatCompactPeriod(selectedDateFrom())} — ${formatCompactPeriod(selectedDateTo())}`;
    detail.textContent = "Весь диапазон";
    return;
  }
  if (state.periodMode === "SINGLE_PERIOD") {
    summary.textContent = formatCompactPeriod(selectedDateFrom()) || "Выберите период";
    detail.textContent = "Один период";
    return;
  }
  const reference = document.getElementById("period-b-derived")?.textContent || "период сравнения";
  summary.textContent = `${formatCompactPeriod(selectedDateFrom())} / ${formatCompactPeriodText(reference)}`;
  detail.textContent = comparisonLabels[state.comparisonMode] || "Сравнение";
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
  updatePeriodSummary();
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
  const allValues = state.options.entities?.[id] || [];
  const selected = allValues.find((item) => item.value === previous);
  const rawQuery = input?.value || "";
  const query = input && selected && document.activeElement === input && rawQuery === selected.label ? "" : rawQuery;
  if (config.querySupported === false) {
    select.replaceChildren(option("", config.label));
    select.value = "";
    if (input) {
      input.value = "";
      input.placeholder = config.unavailableText;
      input.disabled = true;
      input.title = config.unavailableText;
      input.setAttribute("aria-disabled", "true");
      document.querySelector(`[data-clear-filter="${id}"]`)?.setAttribute("disabled", "disabled");
      document.querySelector(`[data-combobox="${id}"]`)?.classList.add("is-disabled");
      renderComboboxUnavailable(id, config.unavailableText);
    }
    updateFilterCount();
    return;
  }
  const values = rankedEntityOptions(allValues, query);
  if (!input) {
    select.replaceChildren(option("", config.label), ...values.map((item) => option(item.value, item.label)));
    select.value = values.some((item) => item.value === previous) ? previous : "";
    updateFilterCount();
    return;
  }
  select.replaceChildren(option("", config.label), ...(selected ? [option(selected.value, selected.label)] : []));
  select.value = selected ? selected.value : "";
  if (input && selected && document.activeElement !== input) input.value = selected.label;
  renderComboboxOptions(id, values, allValues.length);
  select.title = allValues.length > maxComboboxOptions ? "Можно открыть список или начать вводить название." : "Выбор меняет аналитический срез.";
  updateFilterCount();
}

function renderComboboxUnavailable(id, message) {
  const list = document.getElementById(`${id}-options`);
  if (!list) return;
  const item = document.createElement("div");
  item.className = "combo-empty";
  item.textContent = message;
  list.replaceChildren(item);
  list.classList.add("is-open");
}

function rankedEntityOptions(values, rawQuery) {
  const query = rawQuery.trim().toLocaleLowerCase("ru-RU");
  if (!query) return [...values].sort(compareEntityLabels);
  return values
    .map((item) => ({ item, rank: searchRank(item, query) }))
    .filter((candidate) => candidate.rank < 4)
    .sort((left, right) => left.rank - right.rank || compareEntityLabels(left.item, right.item))
    .map((candidate) => candidate.item);
}

function searchRank(item, query) {
  const haystack = `${item.label} ${item.value}`.toLocaleLowerCase("ru-RU");
  const label = String(item.label || "").toLocaleLowerCase("ru-RU");
  if (label === query || String(item.value || "").toLocaleLowerCase("ru-RU") === query) return 0;
  if (label.startsWith(query)) return 1;
  if (label.split(/\s+/).some((word) => word.startsWith(query))) return 2;
  if (haystack.includes(query)) return 3;
  return 4;
}

function compareEntityLabels(left, right) {
  return String(left.label).localeCompare(String(right.label), "ru-RU", { numeric: true, sensitivity: "base" });
}

function renderComboboxOptions(id, values, totalCount) {
  const input = document.getElementById(`${id}-search`);
  const list = document.getElementById(`${id}-options`);
  if (!input || !list) return;
  const visibleValues = values.slice(0, maxComboboxOptions);
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
    const count = document.createElement("div");
    count.className = "combo-count";
    count.textContent = `Показано ${visibleValues.length} из ${totalCount}`;
    list.appendChild(count);
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
  resetDataPagination();
  await refreshRuntimeOptions();
  updatePreviewGrain();
  invalidateLoadedViews();
  await runActiveViewQuery();
}

function handleComboboxKeydown(event, id) {
  const list = document.getElementById(`${id}-options`);
  const options = Array.from(list?.querySelectorAll(".combo-option") || []);
  if (event.key === "Escape") {
    closeCombobox(id);
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    openCombobox(id);
    options[0]?.focus();
  }
  if (event.key === "Enter") {
    event.preventDefault();
    openCombobox(id);
    options[0]?.click();
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

function clearEntityFilter(id, { resetChildren = true, preserveCurrentGrain = false } = {}) {
  document.getElementById(`${id}-filter`).value = "";
  const search = document.getElementById(`${id}-search`);
  if (search) search.value = "";
  if (resetChildren) resetChildFilters(id);
  trimDrilldownFrom(id);
  if (!preserveCurrentGrain && state.currentGrain === id) state.currentGrain = nearestDrilldownGrain();
  renderBreadcrumb();
}

function resetChildFilters(filterId) {
  (filterConfig[filterId]?.childFilters || []).forEach((id) => {
    document.getElementById(`${id}-filter`).value = "";
    const search = document.getElementById(`${id}-search`);
    if (search) search.value = "";
    closeCombobox(id);
    trimDrilldownFrom(id);
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
  state.drilldownPath = [];
  renderBreadcrumb();
  updatePreviewGrain();
  updateFilterCount();
}

function applyFilterDrilldown(filterId) {
  trimDrilldownFrom(filterId);
  state.currentGrain = nearestDrilldownGrain();
  renderBreadcrumb();
  updatePreviewGrain();
  updateFilterCount();
}

async function drillIntoEntity(entityId) {
  const targetGrain = state.previewGrain;
  const select = document.getElementById(`${targetGrain}-filter`);
  if (!select) return;
  const item = (state.options.entities?.[targetGrain] || []).find((optionItem) => optionItem.value === entityId);
  if (item && searchFilterIds.includes(targetGrain)) {
    select.replaceChildren(option("", filterConfig[targetGrain].label), option(item.value, item.label));
    const search = document.getElementById(`${targetGrain}-search`);
    if (search) search.value = item.label;
  }
  select.value = entityId;
  state.currentGrain = targetGrain;
  setExplicitDrilldown(targetGrain, entityId);
  resetChildFilters(targetGrain);
  renderBreadcrumb();
  updatePreviewGrain();
  await refreshRuntimeOptions();
  invalidateLoadedViews();
  await runActiveViewQuery();
}

async function selectStore(entityId) {
  const select = document.getElementById("store-filter");
  if (!select) return;
  const item = (state.options.entities?.store || []).find((optionItem) => optionItem.value === entityId);
  if (item) {
    select.replaceChildren(option("", filterConfig.store.label), option(item.value, item.label));
    const search = document.getElementById("store-search");
    if (search) search.value = item.label;
  }
  select.value = entityId;
  state.currentGrain = "store";
  setExplicitDrilldown("store", entityId);
  renderBreadcrumb();
  updateFilterCount();
  await refreshRuntimeOptions();
  invalidateLoadedViews();
  await runStoresQuery();
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

function nearestDrilldownGrain() {
  const active = state.drilldownPath
    .filter((item) => document.getElementById(`${item.grain}-filter`)?.value === item.value)
    .map((item) => item.grain);
  return active[active.length - 1] || "network";
}

function selectedParentFiltersForGrain(grain) {
  const selected = selectedFilterValues();
  const selectedEntity = grain === state.currentGrain ? document.getElementById(`${grain}-filter`)?.value || "" : "";
  return Object.fromEntries(
    Object.entries(selected)
      .filter(([key, value]) => !(key === grain && value === selectedEntity))
      .map(([key, value]) => [key, [value]])
  );
}

function setExplicitDrilldown(grain, value) {
  const index = drilldownOrder.indexOf(grain);
  state.drilldownPath = state.drilldownPath
    .filter((item) => drilldownOrder.indexOf(item.grain) < index)
    .filter((item) => document.getElementById(`${item.grain}-filter`)?.value === item.value);
  state.drilldownPath.push({ grain, value });
}

function trimDrilldownFrom(grain) {
  const index = drilldownOrder.indexOf(grain);
  state.drilldownPath = state.drilldownPath.filter((item) => drilldownOrder.indexOf(item.grain) < index);
}

function hasNonDrilldownFilters() {
  const drilldownGrains = new Set(state.drilldownPath.map((item) => item.grain));
  return Object.keys(selectedFilterValues()).some((grain) => !drilldownGrains.has(grain));
}

function salesDriverDetailGrain() {
  return previewByGrain[state.currentGrain] || "store";
}

function entityIdsForSummary() {
  if (state.currentGrain === "network") return firstEntityIds("network", 1);
  const selected = document.getElementById(`${state.currentGrain}-filter`)?.value;
  if (selected) return [selected];
  state.currentGrain = nearestDrilldownGrain();
  renderBreadcrumb();
  updatePreviewGrain();
  return state.currentGrain === "network" ? firstEntityIds("network", 1) : entityIdsForSummary();
}

function entityIdsForPreview() {
  return firstEntityIds(state.previewGrain, state.overviewPreviewRowLimit);
}

function entityIdsForSalesDriverDetail() {
  return firstEntityIds(salesDriverDetailGrain(), state.tablePageSize);
}

function entityIdsForStores() {
  const selected = selectedStoreId();
  if (selected) return [selected];
  return firstEntityIds("store", state.tablePageSize);
}

function selectedStoreId() {
  return document.getElementById("store-filter")?.value || "";
}

function storesHasProductFilters() {
  const selected = selectedFilterValues();
  return ["category", "manufacturer", "brand", "sku"].some((key) => Boolean(selected[key]));
}

function firstEntityIds(grain, limit) {
  return (state.options.entities?.[grain] || []).slice(0, limit).map((item) => item.value);
}

function catalogEntry(concept) {
  return state.catalog.find((entry) => entry.metric_concept === concept);
}

function catalogEntries(concept) {
  return state.catalog.filter((entry) => entry.metric_concept === concept);
}

function salesDriverMetricEntry(concept) {
  return metricEntryForGrain(concept, state.currentGrain);
}

function metricEntryForGrain(concept, grain) {
  const entry = catalogEntries(concept).find((item) => item.grain_support?.includes(grain));
  if (!entry || !["READY", "PARTIAL"].includes(entry.availability_status)) return null;
  if (!salesDriverGrainSupport[concept]?.includes(grain)) return null;
  if (state.periodMode === "DATE_RANGE" && entry.range_aggregation_strategy === "period_only") return entry;
  return entry;
}

function displayLabel(concept) {
  return catalogEntry(concept)?.display_label || portfolioPresentationFallback[concept]?.display_label || concept;
}

function portfolioItems(concepts) {
  return (state.portfolioMarketResponse?.items || []).filter((item) => concepts.includes(item.concept_id));
}

function portfolioItem(concept) {
  return portfolioItems([concept])[0] || null;
}

function isDisplayablePortfolioItem(item) {
  return item && ["READY", "PARTIAL"].includes(item.status) && (item.value !== null || item.rows?.length);
}

function formatPortfolioItemValue(item) {
  const entry = catalogEntry(item.concept_id) || portfolioPresentationFallback[item.concept_id];
  const format = entry?.format || (item.unit === "percentage_points" ? "percentage_points" : item.unit || "decimal");
  return formatValue(item.value, format);
}

function portfolioItemDetailText(item) {
  const entry = catalogEntry(item.concept_id) || portfolioPresentationFallback[item.concept_id];
  const format = entry?.format || (item.unit === "percentage_points" ? "percentage_points" : item.unit || "decimal");
  const pieces = [];
  if (state.periodMode === "COMPARE" && item.current_value !== null && item.current_value !== undefined) {
    pieces.push(`${formatValue(item.current_value, format)} сейчас`);
  }
  if (state.periodMode === "COMPARE" && item.reference_value !== null && item.reference_value !== undefined) {
    pieces.push(`${formatValue(item.reference_value, format)} сравнение`);
  }
  if (state.periodMode === "COMPARE" && item.delta !== null && item.delta !== undefined) {
    const deltaFormat = format === "percent" ? "percentage_points" : format;
    pieces.push(`${formatDeltaValue(item.delta, deltaFormat)} изменение`);
  }
  if (item.limitations?.length) pieces.push(portfolioLimitationText(item.limitations[0]));
  return pieces.join(" · ");
}

function selectedFilterValuesForPortfolio() {
  const selected = selectedFilterValues();
  return Object.fromEntries(
    ["category", "manufacturer", "brand", "sku", "store"]
      .filter((key) => selected[key])
      .map((key) => [key, [selected[key]]])
  );
}

function privateLabelDisplayName() {
  return selectedRetailer().private_label_display_name || "выбранный ассортимент";
}

function portfolioContextText() {
  if (state.periodMode === "COMPARE") return "Показывает долю, место, ассортимент и относительную динамику там, где это готово для выбранного сравнения.";
  if (state.periodMode === "DATE_RANGE") return "Диапазон используется только для тех портфельных показателей, где маршрут явно поддерживает такой режим.";
  return "Показывает позицию и состав портфеля за выбранный период.";
}

function portfolioShareUnavailableText() {
  if (state.currentGrain === "network" || state.currentGrain === "category") {
    return "Доля показывается для производителя, бренда или SKU внутри выбранной категории.";
  }
  return "Для выбранного среза долевые показатели не рассчитаны.";
}

function portfolioRankUnavailableText(item) {
  if (!selectedFilterValues().category && state.currentGrain !== "category") {
    return "Выберите категорию, чтобы увидеть рейтинг производителей.";
  }
  if (item?.limitations?.length) return portfolioLimitationText(item.limitations[0]);
  return "Рейтинг производителей недоступен для выбранного среза.";
}

function portfolioAssortmentUnavailableText(item) {
  if (state.periodMode === "DATE_RANGE") return "Активные SKU показываются по отдельному периоду, не как скаляр за диапазон.";
  if (item?.limitations?.length) return portfolioLimitationText(item.limitations[0]);
  return "Ассортиментный показатель недоступен для выбранного среза.";
}

function portfolioBrandUnavailableText(item) {
  if (state.periodMode !== "COMPARE") return "Сравнение бренда с категорией доступно в режиме сравнения.";
  if (state.currentGrain !== "brand" && !selectedFilterValues().brand) return "Выберите бренд внутри категории, чтобы увидеть сравнение с категорией.";
  if (item?.limitations?.length) return portfolioLimitationText(item.limitations[0]);
  return "Сравнение бренда с категорией недоступно для выбранного среза.";
}

function portfolioGatedText(concepts) {
  const item = portfolioItems(concepts)[0];
  if (item?.limitations?.length) return portfolioLimitationText(item.limitations[0]);
  return "Для выбранного среза этот блок ещё не подключён как подтверждённая аналитика.";
}

function portfolioLimitationText(code) {
  return {
    category_share_requires_child_grain: "Доля применима только к объектам внутри категории.",
    share_range_requires_recompute_share_scope: "Доля не показывается за диапазон без пересчёта числителя и знаменателя.",
    manufacturer_rank_requires_category_scope: "Место производителя рассчитывается только внутри категории.",
    manufacturer_population_requires_category_scope: "Размер рейтинга доступен только внутри категории.",
    active_sku_scalar_not_defined_for_range: "Активные SKU показываются по отдельному периоду.",
    active_sku_requires_current_period: "Выберите период для расчёта активных SKU.",
    brand_vs_category_requires_compare_mode: "Сравнение бренда с категорией доступно только в режиме сравнения.",
    brand_vs_category_requires_category_and_brand: "Нужны выбранные категория и бренд.",
    market_universe_identity_not_materialized: "Сравнительная рыночная вселенная ещё не подготовлена для пользовательского экрана.",
    broad_competitor_projection_not_route_ready: "Широкое конкурентное окружение ещё не подключено к пользовательскому маршруту.",
    comparison_period_unavailable: "Нет подходящего периода сравнения.",
    no_manufacturer_metric_facts: "Нет данных для рейтинга производителей.",
    no_sku_units_metric_facts: "Нет данных для расчёта активных SKU."
  }[code] || "Показатель недоступен для выбранного среза.";
}

function contributionMetricForOverview() {
  if (additiveContributionMetrics.includes(state.chartMetric)) return state.chartMetric;
  return catalogEntry("revenue") ? "revenue" : null;
}

function summaryResultFor(concept) {
  return state.summaryResponse?.metric_results.find((result) => result.metric_concept === concept);
}

function salesDriverResultFor(concept) {
  return state.salesDriversResponse?.metric_results.find((result) => result.metric_concept === concept);
}

function salesDriverChartResultFor(concept) {
  return state.salesDriversChartResponse?.metric_results.find((result) => result.metric_concept === concept);
}

function salesDriverTableResultFor(concept, entityId) {
  return state.salesDriversTableResponse?.metric_results.find((result) => result.metric_concept === concept && result.entity_id === entityId);
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

function metricCellTextForResponse(result, entry, response) {
  const comparison = comparisonFor(response, result);
  if (state.periodMode === "COMPARE" && comparison) {
    const deltaFormat = entry.format === "percent" ? "percentage_points" : entry.format;
    return `${formatValue(result.value, entry.format)} (${formatDeltaValue(comparison.delta, deltaFormat)})`;
  }
  if (result.limitations?.includes("range_aggregation_period_only")) return "только по периодам";
  return formatValue(result.value, entry.format);
}

function resultForProvenance(concept) {
  if (state.activeView === "stores") {
    const storeId = selectedStoreId() || storeEntityIds()[0];
    return storeResultFor(concept, storeId) || state.storesResponse?.metric_results[0];
  }
  if (state.activeView === "sales_drivers") {
    return salesDriverResultFor(concept) || state.salesDriversResponse?.metric_results[0] || state.salesDriversTableResponse?.metric_results[0];
  }
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
  return metricCellTextForResponse(result, entry, response);
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

function contextSummaryText(response) {
  const selected = selectedFilterValues();
  const count = Object.keys(selected).length;
  const filterText = count ? `${count} ${pluralRu(count, "фильтр", "фильтра", "фильтров")}` : "Все категории";
  return [
    periodContextText(),
    filterText,
    privateLabelScopeText(response.private_label_scope)
  ].filter(Boolean).join(" · ");
}

function privateLabelScopeText(scope) {
  const scopeName = selectedRetailer().private_label_display_name || "выбранного ассортимента";
  return {
    INCLUDE: "Весь ассортимент",
    EXCLUDE: `Без ${scopeName}`,
    ONLY: `Только ${scopeName}`
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
  if (target) target.textContent = count ? `${count} выбрано` : "не выбраны";
  document.getElementById("reset-filters")?.classList.toggle("is-hidden", count === 0);
  Object.keys(filterConfig).forEach((id) => {
    const hasValue = Boolean(document.getElementById(`${id}-filter`)?.value);
    document.querySelector(`[data-clear-filter="${id}"]`)?.classList.toggle("is-hidden", !hasValue);
  });
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

function salesDriversContextText() {
  if (state.periodMode === "COMPARE") return "Показатели сравниваются без вывода о том, что одно изменение объясняет другое.";
  if (state.periodMode === "DATE_RANGE") return "Диапазон используется для динамики; периодические показатели не показываются как агрегат.";
  return "Текущее состояние показателей и историческая динамика.";
}

function salesDriverMatrixCaption() {
  const unavailable = salesDriverRows().filter(({ result }) => result?.limitations?.includes("range_aggregation_period_only")).length;
  if (state.periodMode === "DATE_RANGE" && unavailable) {
    return `${unavailable} ${pluralRu(unavailable, "показатель доступен", "показателя доступны", "показателей доступны")} только по отдельным периодам.`;
  }
  return "Строка матрицы переключает динамику выбранного показателя.";
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
  const scopeName = selectedRetailer().private_label_display_name || "выбранного ассортимента";
  const select = document.getElementById("private-label-scope");
  document.getElementById("private-label-label").textContent = "Ассортимент";
  const labels = {
    INCLUDE: "Весь ассортимент",
    EXCLUDE: `Без ${scopeName}`,
    ONLY: `Только ${scopeName}`
  };
  Array.from(select?.options || []).forEach((optionNode) => {
    optionNode.textContent = labels[optionNode.value] || optionNode.textContent;
  });
}

function pluralRu(count, one, few, many) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
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

function openSalesDriverProvenance() {
  openProvenance(state.salesDriverMetric);
}

function openContributionProvenance(row) {
  const content = document.getElementById("provenance-content");
  content.replaceChildren();
  contributionProvenanceSections(row.provenance || {}, row).forEach((section) => content.appendChild(section));
  document.getElementById("provenance-drawer").classList.add("is-open");
  document.getElementById("provenance-drawer").setAttribute("aria-hidden", "false");
  document.getElementById("scrim").classList.add("is-open");
}

function openPortfolioProvenance(item) {
  const content = document.getElementById("provenance-content");
  content.replaceChildren();
  portfolioProvenanceSections(item.provenance || {}, item).forEach((section) => content.appendChild(section));
  document.getElementById("provenance-drawer").classList.add("is-open");
  document.getElementById("provenance-drawer").setAttribute("aria-hidden", "false");
  document.getElementById("scrim").classList.add("is-open");
}

function openSignalEvidence(row) {
  const content = document.getElementById("provenance-content");
  content.replaceChildren();
  signalEvidenceSections(row.provenance || {}, row).forEach((section) => content.appendChild(section));
  document.getElementById("provenance-drawer").classList.add("is-open");
  document.getElementById("provenance-drawer").setAttribute("aria-hidden", "false");
  document.getElementById("scrim").classList.add("is-open");
}

function signalEvidenceSections(provenance, row) {
  const signal = provenance.signal || {};
  const scope = provenance.current_analytical_scope || {};
  const rule = provenance.business_rule || {};
  const quality = provenance.quality || {};
  const run = provenance.lineage || {};
  const source = provenance.source_evidence || {};
  const sections = [
    section("Что это за сигнал", [
      ["Тип", signalTypeLabels[row.signal_type] || row.signal_type || "Сигнал"],
      ["Наблюдение", signalObservationText(row)],
      ["Приоритет", severityLabel(row)]
    ]),
    section("Срез", [
      ["Сеть / источник", [selectedRetailer().display_label, selectedRetailer().source_label].filter(Boolean).join(" / ") || "н/д"],
      ["Объект", signalObjectLabel(row)],
      ["Период", row.period ? formatPeriod(row.period) : "н/д"],
      ["Учёт ассортимента", privateLabelScopeText(row.private_label_scope || scope.private_label_scope)]
    ]),
    section("Факты", [
      ["Сейчас", signalValueText(row.current_value)],
      ["Сравнение", signalValueText(row.reference_value)],
      ["Изменение", signalDeltaText(row)]
    ]),
    section("Сравнение", [
      ["Тип", comparisonLabels[row.comparison_type || signal.comparison_type] || row.comparison_type || "н/д"],
      ["Период сравнения", row.reference_period ? formatPeriod(row.reference_period) : "н/д"],
      ["Качество", signalQualityText(row.comparison_quality || quality.comparison_quality || "н/д")]
    ]),
    section("Основание", [
      ["Проверка", "событие прошло подтверждённое правило ленты сигналов"],
      ["Порог / контекст", signalTriggerText(rule.thresholds, rule.trigger_values)],
      ["Наблюдаемые факторы", compactList(rule.observed_drivers)],
      ["Недостающие доказательства", compactList(rule.missing_evidence)]
    ]),
    section("Качество", [
      ["Статус", signalQualityText(row.status || quality.evidence_status || "н/д")],
      ["Доверие", row.confidence ? signalQualityText(row.confidence) : "н/д"],
      ["Ограничения", compactList(quality.limitations)]
    ])
  ];
  const technical = document.createElement("details");
  technical.className = "provenance-technical";
  const summary = document.createElement("summary");
  summary.textContent = "Технические детали";
  technical.appendChild(summary);
  technical.appendChild(section(null, [
    ["Событие", row.signal_id || signal.signal_id || "н/д"],
    ["Тип события", row.event_type || signal.event_type || "н/д"],
    ["Семейство события", row.event_family || signal.event_family || "н/д"],
    ["Правило", rule.event_rule_id || row.rule_id || "н/д"],
    ["Версия правила", rule.event_rule_version || row.rule_version || "н/д"],
    ["Хэш конфигурации правила", rule.event_config_hash || row.event_config_hash || "н/д"],
    ["Запуск анализа", run.analysis_run_id || "н/д"],
    ["Версия аналитической витрины", run.mart_build_id || state.signalsResponse?.mart_build_id || "н/д"],
    ["Ревизия источника", compactList(run.source_revision_ids || state.signalsResponse?.source_revision_ids)],
    ["Линия показателя", compactList(run.metric_lineage)],
    ["Линия сравнения", compactList(run.benchmark_lineage)],
    ["Доказательство по источнику", source.status || "н/д"]
  ]));
  sections.push(technical);
  return sections;
}

function signalTriggerText(thresholds, triggerValues) {
  const thresholdKeys = thresholds && typeof thresholds === "object" ? Object.keys(thresholds) : [];
  const triggerKeys = triggerValues && typeof triggerValues === "object" ? Object.keys(triggerValues) : [];
  const pieces = [];
  if (thresholdKeys.length) pieces.push(`порогов: ${thresholdKeys.length}`);
  if (triggerKeys.length) pieces.push(`проверенных значений: ${triggerKeys.length}`);
  return pieces.join(" · ") || "определено правилом";
}

function portfolioProvenanceSections(provenance, item) {
  if (provenance.metric || provenance.value) {
    return provenanceSections(provenance, {
      ...item,
      metric_concept: item.concept_id
    });
  }
  const scope = provenance.current_analytical_scope || {};
  const projection = provenance.projection || {};
  const inputFacts = provenance.input_metric_facts || {};
  const run = provenance.run_lineage || {};
  const source = provenance.source_evidence || {};
  const quality = provenance.quality || {};
  const sections = [
    section("Что это за показатель", [
      ["Показатель", displayLabel(item.concept_id)],
      ["Значение", formatPortfolioItemValue(item)]
    ]),
    section("Срез", [
      ["Сеть / источник", [selectedRetailer().display_label, selectedRetailer().source_label].filter(Boolean).join(" / ") || "н/д"],
      ["Объект", [grainLabels[scope.grain_id] || scope.grain_id, entityDisplayLabel(scope.grain_id, item.entity_id || scope.entity_ids?.[0])].filter(Boolean).join(" / ") || "н/д"],
      ["Сравнение", comparisonLabels[scope.comparison_mode] || scope.comparison_mode || "н/д"],
      ["Учёт ассортимента", privateLabelScopeText(scope.private_label_scope)]
    ]),
    section("Расчёт", [
      ["Семантика", projectionSemanticsText(projection.projection_semantics)],
      ["Базовые показатели", compactList((projection.component_metric_concepts || []).map(displayLabel))],
      ["Размер набора", inputFacts.fact_count ?? "н/д"]
    ]),
    section("Покрытие данных", [
      ["Доступные периоды", compactList((projection.evaluated_periods || []).map(formatPeriod))],
      ["Доказательство по источнику", source.status || "н/д"]
    ]),
    section("Бизнес-правило", [
      ["Правило", projection.tie_policy ? `ранжирование: ${projection.tie_policy}` : "определено витриной"]
    ]),
    section("Качество", [
      ["Статусы", compactList(quality.quality_statuses)],
      ["Ограничения", compactList((quality.limitations || []).map(portfolioLimitationText))]
    ])
  ];
  const technical = document.createElement("details");
  technical.className = "provenance-technical";
  const summary = document.createElement("summary");
  summary.textContent = "Технические детали";
  technical.appendChild(summary);
  technical.appendChild(section(null, [
    ["Концепт", item.concept_id],
    ["Технический срез", [scope.retailer_id, scope.source_id, scope.grain_id, scope.private_label_scope].filter(Boolean).join(" / ") || "н/д"],
    ["Определения показателей", compactList(inputFacts.metric_definition_ids)],
    ["Запуск анализа", compactList(run.analysis_run_ids)],
    ["Версия аналитической витрины", run.mart_build_id || "н/д"],
    ["Ревизия источника", compactList(run.source_revision_ids)],
    ["Недостающие поля", compactList(provenance.missing_fields)]
  ]));
  sections.push(technical);
  return sections;
}

function projectionSemanticsText(value) {
  return {
    competition_rank_by_summed_additive_metric: "место в категории по суммарному показателю",
    manufacturer_population_count_in_category_rank_universe: "число производителей в рейтинге категории",
    sales_based_active_sku_count_against_available_period_peak: "активные SKU по продажам и пик доступной истории",
    brand_percentage_delta_minus_category_percentage_delta: "разница темпа бренда и категории",
    not_applicable: "не применимо для выбранного среза"
  }[value] || "определено аналитической витриной";
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
  const normalizedRows = rows.map((row) => Array.isArray(row) ? { cells: row, meta: null } : row);
  const renderedRows = sortedRows(headers, normalizedRows).slice(0, options.rowLimit || normalizedRows.length);
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach((header) => {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = header;
    th.addEventListener("click", () => {
      state.sortColumn = header;
      state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
      if (options.onSort) {
        options.onSort();
      } else {
        renderOverviewTable();
      }
    });
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  const tbody = document.createElement("tbody");
  renderedRows.forEach((row) => {
    const tr = document.createElement("tr");
    row.cells.forEach((cell, index) => {
      const td = document.createElement("td");
      if (index === 0 && options.onFirstCellClick) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "table-link";
        button.textContent = cell;
        button.addEventListener("click", () => options.onFirstCellClick(cell, row.meta));
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
    return String(left.cells[index]).localeCompare(String(right.cells[index]), "ru-RU", { numeric: true }) * direction;
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

function formatCompactPeriod(value) {
  if (!value) return "н/д";
  const date = new Date(`${value}T00:00:00`);
  const months = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
  return `${months[date.getMonth()]} ${date.getFullYear()}`;
}

function formatCompactPeriodText(text) {
  const known = (state.options.periods || []).find((period) => formatPeriod(period.value) === text);
  return known ? formatCompactPeriod(known.value) : text;
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
  const target = state.activeView === "sales_drivers"
    ? document.getElementById("sales-drivers-chart-box")
    : state.activeView === "portfolio_market"
      ? document.getElementById("portfolio-share-strip")
      : state.activeView === "stores"
        ? document.getElementById("stores-ranking")
        : state.activeView === "signals"
          ? document.getElementById("signals-list")
          : state.activeView === "data"
            ? document.getElementById("data-coverage-grid")
            : document.getElementById("chart-box");
  replaceWithMessage(target, "error-state", "Не удалось загрузить данные. Повторите попытку.");
  if (state.activeView === "signals") {
    replaceWithMessage(
      document.getElementById("signals-limitations"),
      "error-state compact",
      "Доступность ленты не удалось проверить. Повторите попытку.",
    );
  }
  if (state.activeView === "data") {
    replaceWithMessage(document.getElementById("data-quality-summary"), "error-state compact", "Качество данных не удалось проверить.");
    renderMessageRow(document.getElementById("data-source-table"), "Строки для проверки не удалось загрузить.");
    replaceWithMessage(document.getElementById("data-audit-content"), "error-state compact", "Аудит расчёта не удалось загрузить.");
  }
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
