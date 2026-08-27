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
  storesGeographyResponse: null,
  storesScopeStatus: "ready",
  signalsResponse: null,
  signalsLoadStatus: "idle",
  signalKindFilter: "all",
  signalGrainFilter: "all",
  dataResponse: null,
  dataPageOffset: 0,
  activeView: "overview",
  loadedViews: {},
  scopeVersion: 0,
  sectionRequests: {},
  periodMode: "COMPARE",
  comparisonMode: "YOY",
  currentGrain: "network",
  drilldownPath: [],
  filters: { category: [], manufacturer: [], brand: [], sku: [], store: [] },
  pendingFilters: {},
  filterQueries: { category: "", manufacturer: "", brand: "", sku: "", store: "" },
  openFilterId: null,
  scopeEditView: null,
  suppressScrollspyUntil: 0,
  chartMetric: "revenue",
  salesDriverMetric: "revenue",
  storesMetric: "revenue",
  storesGroupMode: "store",
  portfolioEntityLevel: "manufacturer",
  portfolioBasis: "revenue",
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
  { title: "Присутствие", concepts: ["selling_store_count", "active_store_count", "distribution"] },
  { title: "Скорость", concepts: ["velocity", "revenue_velocity", "margin_velocity"] },
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
  active_store_count: ["network", "category", "manufacturer", "brand", "sku"],
  distribution: ["category", "manufacturer", "brand", "sku"],
  velocity: ["category", "manufacturer", "brand", "sku"],
  revenue_velocity: ["category", "manufacturer", "brand", "sku"],
  margin_velocity: ["category", "manufacturer", "brand", "sku"],
  sku_count: ["network", "category", "manufacturer", "brand", "store"],
  brand_count: ["network", "category", "manufacturer", "store"],
  category_count: ["network", "manufacturer", "store"]
};
const portfolioMarketConcepts = [
  "category_revenue_share",
  "category_units_share",
  "category_margin_share",
  "entity_revenue_share",
  "entity_units_share",
  "entity_margin_share",
  "entity_cumulative_revenue_share",
  "entity_cumulative_units_share",
  "entity_cumulative_margin_share",
  "category_rank_revenue",
  "category_rank_units",
  "category_rank_margin_abs",
  "manufacturer_rank_revenue",
  "manufacturer_rank_units",
  "manufacturer_rank_margin_abs",
  "brand_rank_revenue",
  "brand_rank_units",
  "brand_rank_margin_abs",
  "sku_rank_revenue",
  "sku_rank_units",
  "sku_rank_margin_abs",
  "manufacturer_abc_revenue",
  "manufacturer_abc_units",
  "manufacturer_abc_margin_abs",
  "sku_abc_revenue",
  "sku_abc_units",
  "sku_abc_margin_abs",
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
const portfolioContributionConcepts = ["entity_revenue_share", "entity_units_share", "entity_margin_share"];
const portfolioCumulativeShareConcepts = [
  "entity_cumulative_revenue_share",
  "entity_cumulative_units_share",
  "entity_cumulative_margin_share"
];
const portfolioRankConcepts = [
  "category_rank_revenue",
  "category_rank_units",
  "category_rank_margin_abs",
  "manufacturer_rank_revenue",
  "manufacturer_rank_units",
  "manufacturer_rank_margin_abs",
  "brand_rank_revenue",
  "brand_rank_units",
  "brand_rank_margin_abs",
  "sku_rank_revenue",
  "sku_rank_units",
  "sku_rank_margin_abs"
];
const portfolioAbcConcepts = [
  "manufacturer_abc_revenue",
  "manufacturer_abc_units",
  "manufacturer_abc_margin_abs",
  "sku_abc_revenue",
  "sku_abc_units",
  "sku_abc_margin_abs"
];
const portfolioActiveSkuConcepts = ["active_sku_count", "historical_peak_active_sku_count", "active_sku_change_pct"];
const portfolioBrandCategoryConcepts = ["brand_delta_pct", "category_delta_pct", "brand_category_delta_gap_pp"];
const portfolioMarketUniverseConcepts = ["market_segment_delta_pct"];
const portfolioCompetitorConcepts = ["broad_competitors"];
const storeRankingMetrics = ["revenue", "units", "retailer_margin_abs"];
const storeKpiConcepts = ["revenue", "units", "retailer_margin_abs", "sku_count"];
const storeTableConcepts = ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct", "sku_count"];
const storeGroupModes = [
  { value: "store", label: "ТТ" },
  { value: "region", label: "Регионы" },
  { value: "store_format", label: "Форматы ТТ" },
  { value: "region_store_format", label: "Регион × формат" }
];
const geographyMetricConcepts = ["revenue", "units", "retailer_margin_abs", "retailer_margin_pct"];
const geographyRankingMetrics = ["revenue", "units", "retailer_margin_abs"];
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
  entity_revenue_share: {
    display_label: "Доля по обороту",
    format: "percent",
    unit_label: "%",
    business_meaning: "Доля объекта в выбранном аналитическом рынке по обороту.",
    decision_use: "Показывает вклад объекта в текущую вселенную без оценки хорошо/плохо.",
    formula_summary: "значение объекта / значение всего выбранного рынка",
    delta_semantics: "NEUTRAL_DIRECTIONAL"
  },
  entity_units_share: {
    display_label: "Доля по штукам",
    format: "percent",
    unit_label: "%",
    business_meaning: "Доля объекта в выбранном аналитическом рынке по продажам в штуках.",
    decision_use: "Показывает вклад объекта в текущую вселенную без оценки хорошо/плохо.",
    formula_summary: "значение объекта / значение всего выбранного рынка",
    delta_semantics: "NEUTRAL_DIRECTIONAL"
  },
  entity_margin_share: {
    display_label: "Доля по марже",
    format: "percent",
    unit_label: "%",
    business_meaning: "Доля объекта в выбранном аналитическом рынке по абсолютной марже.",
    decision_use: "Показывает вклад объекта в текущую вселенную без оценки хорошо/плохо.",
    formula_summary: "значение объекта / значение всего выбранного рынка",
    delta_semantics: "NEUTRAL_DIRECTIONAL"
  },
  entity_cumulative_revenue_share: {
    display_label: "Накопленная доля по обороту",
    format: "percent",
    unit_label: "%",
    business_meaning: "Накопленная доля после сортировки объектов по обороту.",
    decision_use: "Показывает вклад строки в упорядоченной серии для портфельного анализа.",
    formula_summary: "сумма значений до текущей строки / значение всего выбранного рынка",
    delta_semantics: "NEUTRAL_DIRECTIONAL"
  },
  entity_cumulative_units_share: {
    display_label: "Накопленная доля по штукам",
    format: "percent",
    unit_label: "%",
    business_meaning: "Накопленная доля после сортировки объектов по продажам в штуках.",
    decision_use: "Показывает вклад строки в упорядоченной серии для портфельного анализа.",
    formula_summary: "сумма значений до текущей строки / значение всего выбранного рынка",
    delta_semantics: "NEUTRAL_DIRECTIONAL"
  },
  entity_cumulative_margin_share: {
    display_label: "Накопленная доля по марже",
    format: "percent",
    unit_label: "%",
    business_meaning: "Накопленная доля после сортировки объектов по абсолютной марже.",
    decision_use: "Показывает вклад строки в упорядоченной серии для портфельного анализа.",
    formula_summary: "сумма значений до текущей строки / значение всего выбранного рынка",
    delta_semantics: "NEUTRAL_DIRECTIONAL"
  },
  manufacturer_rank_revenue: { display_label: "Место производителя по обороту", format: "integer", delta_semantics: "RANK_DIRECTIONAL" },
  manufacturer_rank_units: { display_label: "Место производителя по штукам", format: "integer", delta_semantics: "RANK_DIRECTIONAL" },
  manufacturer_abc_revenue: { display_label: "ABC производителя по обороту", format: "text", unit_label: "A/B/C", business_meaning: "ABC-класс вклада производителя по обороту внутри одной категории и одного аналитического портфеля.", decision_use: "Разделяет вклад на A/B/C без рекомендаций и оценки качества.", formula_summary: "класс по накопленной доле после ранжирования по выбранному показателю" },
  manufacturer_abc_units: { display_label: "ABC производителя по штукам", format: "text", unit_label: "A/B/C", business_meaning: "ABC-класс вклада производителя по штукам внутри одной категории и одного аналитического портфеля.", decision_use: "Разделяет вклад на A/B/C без рекомендаций и оценки качества.", formula_summary: "класс по накопленной доле после ранжирования по выбранному показателю" },
  manufacturer_abc_margin_abs: { display_label: "ABC производителя по абсолютной марже", format: "text", unit_label: "A/B/C", business_meaning: "ABC-класс вклада производителя по абсолютной марже внутри одной категории и одного аналитического портфеля.", decision_use: "Разделяет вклад на A/B/C без рекомендаций и оценки качества.", formula_summary: "класс по накопленной доле после ранжирования по выбранному показателю" },
  sku_abc_revenue: { display_label: "ABC SKU по обороту", format: "text", unit_label: "A/B/C", business_meaning: "ABC-класс вклада SKU по обороту внутри одной категории и одного аналитического портфеля.", decision_use: "Разделяет вклад на A/B/C без рекомендаций и оценки качества.", formula_summary: "класс по накопленной доле после ранжирования по выбранному показателю" },
  sku_abc_units: { display_label: "ABC SKU по штукам", format: "text", unit_label: "A/B/C", business_meaning: "ABC-класс вклада SKU по штукам внутри одной категории и одного аналитического портфеля.", decision_use: "Разделяет вклад на A/B/C без рекомендаций и оценки качества.", formula_summary: "класс по накопленной доле после ранжирования по выбранному показателю" },
  sku_abc_margin_abs: { display_label: "ABC SKU по абсолютной марже", format: "text", unit_label: "A/B/C", business_meaning: "ABC-класс вклада SKU по абсолютной марже внутри одной категории и одного аналитического портфеля.", decision_use: "Разделяет вклад на A/B/C без рекомендаций и оценки качества.", formula_summary: "класс по накопленной доле после ранжирования по выбранному показателю" },
  manufacturer_population_count: { display_label: "Производителей в рейтинге", format: "integer" },
  active_sku_count: { display_label: "Активные SKU", format: "integer" },
  historical_peak_active_sku_count: { display_label: "Пиковое число активных SKU", format: "integer" },
  active_sku_change_pct: { display_label: "Изменение активных SKU от пика", format: "percent" },
  brand_delta_pct: { display_label: "Изменение бренда", format: "percent" },
  category_delta_pct: { display_label: "Изменение категории", format: "percent" },
  brand_category_delta_gap_pp: { display_label: "Отклонение бренда от категории", format: "percentage_points" },
  market_segment_delta_pct: { display_label: "Изменение сегмента рынка", format: "percent" },
  contribution_to_delta: { display_label: "Вклад в изменение", format: "percent", delta_semantics: "NEUTRAL_DIRECTIONAL" },
  broad_competitors: { display_label: "Конкуренты категории", format: "text" }
};
const outcomeDirectionalMetrics = new Set(["revenue", "revenue_vat", "units", "retailer_margin_abs", "retailer_margin_pct"]);
const neutralDirectionalMetrics = new Set([
  "weighted_shelf_price_vat",
  "weighted_input_price_vat",
  "selling_store_count",
  "active_store_count",
  "distribution",
  "velocity",
  "revenue_velocity",
  "margin_velocity",
  "sku_count",
  "brand_count",
  "category_count",
  "category_revenue_share",
  "category_units_share",
  "category_margin_share",
  "entity_revenue_share",
  "entity_units_share",
  "entity_margin_share",
  "entity_cumulative_revenue_share",
  "entity_cumulative_units_share",
  "entity_cumulative_margin_share",
  "active_sku_count",
  "historical_peak_active_sku_count",
  "active_sku_change_pct",
  "brand_delta_pct",
  "category_delta_pct",
  "brand_category_delta_gap_pp",
  "market_segment_delta_pct",
  "contribution_to_delta"
]);
const rankDirectionalMetrics = new Set(["manufacturer_rank_revenue", "manufacturer_rank_units"]);
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
  AVAILABLE_MONTH_SET: "Среднее за сопоставимые месяцы",
  NONE: "Без сравнения"
};
const filterConfig = {
  category: { label: "Все", title: "Категория", searchPlaceholder: "Найти категорию", childFilters: ["manufacturer", "brand", "sku"] },
  manufacturer: { label: "Все", title: "Производитель", searchPlaceholder: "Найти производителя", childFilters: ["brand", "sku"] },
  brand: { label: "Все", title: "Бренд", searchPlaceholder: "Найти бренд", childFilters: ["sku"] },
  sku: { label: "Все", title: "SKU", searchPlaceholder: "Найти SKU", childFilters: [] },
  store: {
    label: "Все",
    title: "ТТ",
    searchPlaceholder: "Найти ТТ",
    childFilters: []
  }
};
const multiFilterIds = ["category", "manufacturer", "brand", "sku", "store"];
const searchFilterIds = ["category", "manufacturer", "brand", "sku", "store"];
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
let stickyGeometryFrame = null;
let stickyGeometryObserver = null;

document.addEventListener("DOMContentLoaded", async () => {
  bindStaticControls();
  setupStickyGeometryTracking();
  await initializeDashboard();
});

function bindStaticControls() {
  document.querySelectorAll("[data-period-mode]").forEach((button) => {
    button.addEventListener("click", async () => {
      await applyScopeChange(async () => {
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
  document.getElementById("portfolio-entity-level")?.addEventListener("change", async (event) => {
    await applyScopeChange(async () => {
      state.portfolioEntityLevel = event.target.value || "manufacturer";
      invalidateLoadedViews();
      await runActiveViewQuery();
    });
  });
  document.getElementById("portfolio-basis")?.addEventListener("change", async (event) => {
    await applyScopeChange(async () => {
      state.portfolioBasis = event.target.value || "revenue";
      invalidateLoadedViews();
      await runActiveViewQuery();
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
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMetricInspector();
      closeReportsPanel();
    }
  });
  document.addEventListener("click", (event) => {
    if (event.target?.closest?.("#close-drawer")) closeMetricInspector();
  });
  document.getElementById("reset-filters").addEventListener("click", async () => {
    await applyScopeChange(async () => {
      resetAllEntityFilters();
      resetDataPagination();
      await refreshRuntimeOptions();
      updatePreviewGrain();
      invalidateLoadedViews();
      await runActiveViewQuery();
    });
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
  if (!isOpen) state.scopeEditView = viewFromHash() || state.activeView || "overview";
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
  if (!section) return;
  const stickyOffset = stickyStackOffset();
  const target = section.getBoundingClientRect().top + window.scrollY - stickyOffset;
  if (behavior === "auto") {
    window.scrollTo(0, Math.max(target, 0));
    return;
  }
  window.scrollTo({ top: Math.max(target, 0), behavior });
}

function stickyStackOffset() {
  const header = document.querySelector(".app-header")?.getBoundingClientRect().height || 54;
  const nav = document.querySelector(".workflow-nav")?.getBoundingClientRect().height || 36;
  const scope = document.querySelector(".scope-panel")?.getBoundingClientRect().height || 78;
  return Math.ceil(header + nav + scope);
}

function setupStickyGeometryTracking() {
  updateStickyGeometryVars();
  window.addEventListener("resize", scheduleStickyGeometryUpdate, { passive: true });
  if (!("ResizeObserver" in window)) return;
  stickyGeometryObserver?.disconnect();
  stickyGeometryObserver = new ResizeObserver(scheduleStickyGeometryUpdate);
  [".app-header", ".workflow-nav", ".scope-panel"].forEach((selector) => {
    const element = document.querySelector(selector);
    if (element) stickyGeometryObserver.observe(element);
  });
}

function scheduleStickyGeometryUpdate() {
  if (stickyGeometryFrame) return;
  stickyGeometryFrame = window.requestAnimationFrame(() => {
    stickyGeometryFrame = null;
    updateStickyGeometryVars();
  });
}

function updateStickyGeometryVars() {
  const navHeight = document.querySelector(".workflow-nav")?.getBoundingClientRect().height || 36;
  document.documentElement.style.setProperty("--workflow-nav-current-height", `${Math.ceil(navHeight)}px`);
  document.documentElement.style.setProperty("--report-scroll-margin-top", `${stickyStackOffset()}px`);
}

async function applyScopeChange(work) {
  const preservedView = state.scopeEditView || state.activeView || viewFromHash() || "overview";
  state.suppressScrollspyUntil = Date.now() + 1200;
  setActiveView(preservedView, { refresh: false, scroll: false });
  await work();
  state.suppressScrollspyUntil = Date.now() + 1200;
  setActiveView(preservedView, { refresh: false, scroll: false });
  updateHash(preservedView);
  scrollToView(preservedView, { behavior: "auto" });
  [250, 900, 1800, 3000].forEach((delay) => {
    window.setTimeout(() => {
      state.suppressScrollspyUntil = Date.now() + 900;
      setActiveView(preservedView, { refresh: false, scroll: false });
      scrollToView(preservedView, { behavior: "auto" });
    }, delay);
  });
  state.scopeEditView = null;
}

function setupSectionObserver() {
  sectionObserver?.disconnect();
  const sections = Array.from(document.querySelectorAll(".report-section"));
  if (!sections.length || !("IntersectionObserver" in window)) return;
  const stickyOffset = stickyStackOffset();
  sectionObserver = new IntersectionObserver((entries) => {
    if (Date.now() < state.suppressScrollspyUntil) return;
    if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4) {
      const lastView = sections[sections.length - 1]?.dataset.viewPanel;
      if (lastView && lastView !== state.activeView) setActiveView(lastView, { refresh: true, scroll: false });
      return;
    }
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((left, right) => Math.abs(left.boundingClientRect.top - stickyOffset) - Math.abs(right.boundingClientRect.top - stickyOffset));
    const active = visible[0]?.target;
    const view = active?.dataset.viewPanel;
    if (view && view !== state.activeView) setActiveView(view, { refresh: true, scroll: false });
  }, {
    rootMargin: `-${stickyOffset}px 0px -55% 0px`,
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
  if (Date.now() < state.suppressScrollspyUntil) return;
  const sections = Array.from(document.querySelectorAll(".report-section"));
  if (!sections.length) return;
  if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4) {
    const lastView = sections[sections.length - 1]?.dataset.viewPanel;
    if (lastView && lastView !== state.activeView) setActiveView(lastView, { refresh: true, scroll: false });
    return;
  }
  const current = sections
    .map((section) => ({ view: section.dataset.viewPanel, distance: Math.abs(section.getBoundingClientRect().top - stickyStackOffset()) }))
    .sort((left, right) => left.distance - right.distance)[0];
  if (current?.view && current.view !== state.activeView) setActiveView(current.view, { refresh: true, scroll: false });
}

async function ensureActiveViewData({ force = false } = {}) {
  if (!force && state.loadedViews[state.activeView]) return;
  await runActiveViewQuery();
}

function invalidateLoadedViews() {
  state.scopeVersion += 1;
  state.loadedViews = {};
  markInactiveSectionsPending();
}

function sectionRequestToken(view) {
  const token = { view, scopeVersion: state.scopeVersion, sequence: (state.sectionRequests[view] || 0) + 1 };
  state.sectionRequests[view] = token.sequence;
  return token;
}

function isCurrentSectionRequest(token) {
  return state.scopeVersion === token.scopeVersion && state.sectionRequests[token.view] === token.sequence;
}

function markInactiveSectionsPending() {
  ["overview", "sales_drivers", "portfolio_market", "stores", "signals", "data"]
    .filter((view) => view !== state.activeView)
    .forEach((view) => {
      if (view === "overview") {
        renderSkeletons();
      } else if (view === "sales_drivers") {
        renderSalesDriverSkeletons();
      } else if (view === "portfolio_market") {
        renderPortfolioMarketSkeletons();
      } else if (view === "stores") {
        state.storesResponse = null;
        state.storesGeographyResponse = null;
        state.storesScopeStatus = "ready";
        renderStoresSkeletons();
      } else if (view === "signals") {
        state.signalsResponse = null;
        state.signalsLoadStatus = "idle";
        renderSignalsSkeletons();
      } else if (view === "data") {
        state.dataResponse = null;
        renderDataSkeletons();
      }
    });
}

function updatePressedGroup(selector, datasetKey, activeValue) {
  document.querySelectorAll(selector).forEach((button) => {
    const isActive = button.dataset[datasetKey] === activeValue;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function setInfoButtonLabel(button, label = "Проверить показатель") {
  button.textContent = "i";
  button.setAttribute("aria-label", label);
}

function metricValueButton({ concept, text, result = null, response = null, className = "", mode = "value", sections = null }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `metric-value-button ${className}`.trim();
  button.textContent = text;
  button.setAttribute("aria-label", `Проверить показатель: ${displayLabel(concept)}`);
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    openMetricInspector({ concept, result, response, mode, sections });
  });
  return button;
}

function metricDeltaButton({ concept, text, value, result = null, response = null, className = "", sections = null }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `metric-value-button metric-delta-button ${deltaSemanticClass(concept, value)} ${className}`.trim();
  button.textContent = text;
  button.setAttribute("aria-label", `Проверить изменение: ${displayLabel(concept)}`);
  button.dataset.deltaSemantics = deltaSemanticsFor(concept);
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    openMetricInspector({ concept, result, response, mode: "comparison", sections });
  });
  return button;
}

function metricComparisonCell({ concept, label, text, result = null, response = null, role = "current", deltaValue = null }) {
  const wrap = document.createElement("div");
  wrap.className = `metric-comparison-cell metric-comparison-cell--${role}`;
  if (label) appendText(wrap, "span", label);
  const value = document.createElement("strong");
  value.className = role === "reference" ? "metric-reference" : role === "delta" ? "metric-delta" : "metric-current";
  if (result) {
    value.appendChild(
      role === "delta"
        ? metricDeltaButton({ concept, text, value: deltaValue, result, response })
        : metricValueButton({ concept, text, result, response })
    );
  } else {
    value.textContent = text;
  }
  wrap.appendChild(value);
  return wrap;
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
    await applyScopeChange(async () => {
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
  appendText(identity, "strong", retailer.display_label || "Текущий отчёт").className = "scope-value";
}

function bindDynamicControls() {
  document.getElementById("comparison-mode").addEventListener("change", async (event) => {
    await applyScopeChange(async () => {
      state.comparisonMode = event.target.value;
      updatePeriodSummary();
      invalidateLoadedViews();
      resetDataPagination();
      await runActiveViewQuery();
    });
  });
  document.getElementById("private-label-scope").addEventListener("change", async () => {
    await applyScopeChange(async () => {
      resetDataPagination();
      await refreshRuntimeOptions();
      updatePrivateLabelTerminology();
      invalidateLoadedViews();
      await runActiveViewQuery();
    });
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
  document.getElementById("stores-group-mode")?.addEventListener("change", async (event) => {
    state.storesGroupMode = event.target.value || "store";
    state.sortColumn = storeSortColumn();
    state.sortDirection = "desc";
    await runStoresQuery();
  });

  multiFilterIds.forEach((id) => {
    document.getElementById(`${id}-filter-trigger`)?.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleFilterPopover(id);
    });
    document.getElementById(`${id}-filter-popover`)?.addEventListener("click", (event) => event.stopPropagation());
    document.getElementById(`${id}-search`)?.addEventListener("input", (event) => {
      state.filterQueries[id] = event.target.value || "";
      renderFilterOptions(id);
    });
    document.getElementById(`${id}-search`)?.addEventListener("keydown", (event) => handleFilterSearchKeydown(event, id));
    document.querySelector(`[data-select-all="${id}"]`)?.addEventListener("change", (event) => {
      const available = visibleEntityOptions(id);
      const next = new Set(pendingValuesForFilter(id));
      available.forEach((item) => {
        if (event.target.checked) next.add(item.value);
        else next.delete(item.value);
      });
      state.pendingFilters[id] = Array.from(next);
      renderFilterOptions(id);
    });
  });

  document.querySelectorAll("[data-clear-pending-filter]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.pendingFilters[button.dataset.clearPendingFilter] = [];
      renderFilterOptions(button.dataset.clearPendingFilter);
    });
  });

  document.querySelectorAll("[data-inline-clear-filter]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      await applyScopeChange(async () => {
        clearEntityFilter(button.dataset.inlineClearFilter);
        closeFilterPopover(button.dataset.inlineClearFilter);
        resetDataPagination();
        await refreshRuntimeOptions();
        updatePreviewGrain();
        invalidateLoadedViews();
        await runActiveViewQuery();
      });
    });
  });

  document.querySelectorAll("[data-apply-filter]").forEach((button) => {
    button.addEventListener("click", async () => {
      await applyPendingFilter(button.dataset.applyFilter);
    });
  });

  document.addEventListener("click", () => closeAllFilterPopovers());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAllFilterPopovers();
  });

  ["period-single", "period-a", "period-available-end", "date-from", "date-to"].forEach((id) => {
    document.getElementById(id).addEventListener("change", async () => {
      await applyScopeChange(async () => {
        updatePeriodSummary();
        resetDataPagination();
        await refreshRuntimeOptions();
        invalidateLoadedViews();
        await runActiveViewQuery();
      });
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
  Object.entries(selectedFilterValues()).forEach(([key, values]) => {
    values.forEach((value) => params.append(key, value));
  });
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
  setupPeriodSelect("period-available-end", latest, resetPeriods);
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
  const token = sectionRequestToken("overview");
  setLoading(true, "Запрос к витрине");
  renderSkeletons();
  try {
    const summaryPayload = buildQueryPayload(state.currentGrain, entityIdsForSummary(), overviewConcepts());
    const chartPayload = buildChartQueryPayload();
    const previewPayload = buildQueryPayload(state.previewGrain, entityIdsForPreview(), tableConcepts());
    const summaryResponse = await postJson("/api/dashboard/query", summaryPayload);
    const chartResponse = await postJson("/api/dashboard/query", chartPayload);
    const contributionResponse = await loadContributionRows(summaryResponse);
    const tableResponse = await postJson("/api/dashboard/query", previewPayload);
    if (!isCurrentSectionRequest(token)) return;
    state.summaryResponse = summaryResponse;
    state.chartResponse = chartResponse;
    state.contributionResponse = contributionResponse;
    state.tableResponse = tableResponse;
    renderOverview();
    state.loadedViews.overview = true;
    setLoading(false, "Данные обновлены");
  } catch (error) {
    if (!isCurrentSectionRequest(token)) return;
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

async function runSalesDriversQuery() {
  const token = sectionRequestToken("sales_drivers");
  setLoading(true, "Запрос к витрине");
  renderSalesDriverSkeletons();
  try {
    const summaryGrain = salesDriverSummaryGrain();
    const concepts = salesDriverConcepts(summaryGrain);
    if (!concepts.length) {
      renderSalesDriversUnavailable("Для выбранного среза нет поддержанных показателей.");
      state.loadedViews.sales_drivers = true;
      setLoading(false, "Данные обновлены");
      return;
    }
    if (!concepts.includes(state.salesDriverMetric)) state.salesDriverMetric = concepts[0];
    const summaryPayload = buildQueryPayload(summaryGrain, entityIdsForSalesDriverSummary(summaryGrain), concepts);
    const chartPayload = buildSalesDriverChartQueryPayload();
    const detailPayload = buildQueryPayload(salesDriverDetailGrain(), entityIdsForSalesDriverDetail(), salesDriverDetailConcepts());
    const salesDriversResponse = await postJson("/api/dashboard/query", summaryPayload);
    const salesDriversChartResponse = await postJson("/api/dashboard/query", chartPayload);
    const salesDriversTableResponse = await postJson("/api/dashboard/query", detailPayload);
    if (!isCurrentSectionRequest(token)) return;
    state.salesDriversResponse = salesDriversResponse;
    state.salesDriversChartResponse = salesDriversChartResponse;
    state.salesDriversTableResponse = salesDriversTableResponse;
    renderSalesDrivers();
    state.loadedViews.sales_drivers = true;
    setLoading(false, "Данные обновлены");
  } catch (error) {
    if (!isCurrentSectionRequest(token)) return;
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

async function loadContributionRows(summaryResponse = state.summaryResponse) {
  const payload = buildContributionPayload(summaryResponse);
  if (!payload) return null;
  return postJson("/api/dashboard/contribution", payload);
}

async function runPortfolioMarketQuery() {
  const token = sectionRequestToken("portfolio_market");
  setLoading(true, "Запрос к витрине");
  renderPortfolioMarketSkeletons();
  try {
    const portfolioMarketResponse = await postJson("/api/dashboard/portfolio-market", buildPortfolioMarketPayload());
    if (!isCurrentSectionRequest(token)) return;
    state.portfolioMarketResponse = portfolioMarketResponse;
    renderPortfolioMarket();
    state.loadedViews.portfolio_market = true;
    setLoading(false, "Данные обновлены");
  } catch (error) {
    if (!isCurrentSectionRequest(token)) return;
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

async function runStoresQuery() {
  const token = sectionRequestToken("stores");
  setLoading(true, "Запрос к витрине");
  renderStoresSkeletons();
  if (state.storesGroupMode !== "store") {
    state.storesScopeStatus = "ready";
    try {
      const geographyResponse = await postJson("/api/dashboard/geography", buildStoresGeographyPayload());
      if (!isCurrentSectionRequest(token)) return;
      state.storesGeographyResponse = geographyResponse;
      renderStores();
      state.loadedViews.stores = true;
      setLoading(false, "Данные обновлены");
    } catch (error) {
      if (!isCurrentSectionRequest(token)) return;
      setLoading(false, "Не удалось загрузить данные.");
      showPageError(error);
    }
    return;
  }
  if (!storeConcepts().length) {
    state.storesResponse = null;
    state.storesGeographyResponse = null;
    state.storesScopeStatus = "no_supported_metrics";
    renderStores();
    state.loadedViews.stores = true;
    setLoading(false, "Показатели ТТ недоступны");
    return;
  }
  state.storesScopeStatus = "ready";
  try {
    const storesResponse = await postJson("/api/dashboard/query", buildStoresPayload());
    if (!isCurrentSectionRequest(token)) return;
    state.storesResponse = storesResponse;
    state.storesGeographyResponse = null;
    renderStores();
    state.loadedViews.stores = true;
    setLoading(false, "Данные обновлены");
  } catch (error) {
    if (!isCurrentSectionRequest(token)) return;
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

async function runSignalsQuery() {
  const token = sectionRequestToken("signals");
  setLoading(true, "Запрос к ленте сигналов");
  state.signalsResponse = null;
  state.signalsLoadStatus = "loading";
  renderSignalsSkeletons();
  try {
    const signalsResponse = await postJson("/api/dashboard/signals", buildSignalsPayload());
    if (!isCurrentSectionRequest(token)) return;
    state.signalsResponse = signalsResponse;
    state.signalsLoadStatus = "loaded";
    renderSignals();
    state.loadedViews.signals = true;
    setLoading(false, "Данные обновлены");
  } catch (error) {
    if (!isCurrentSectionRequest(token)) return;
    state.signalsResponse = null;
    state.signalsLoadStatus = "error";
    setLoading(false, "Не удалось загрузить данные.");
    showPageError(error);
  }
}

async function runDataQuery() {
  const token = sectionRequestToken("data");
  setLoading(true, "Запрос к данным");
  renderDataSkeletons();
  try {
    const dataResponse = await postJson("/api/dashboard/data", buildDataPayload());
    if (!isCurrentSectionRequest(token)) return;
    state.dataResponse = dataResponse;
    renderDataScreen();
    state.loadedViews.data = true;
    setLoading(false, "Данные обновлены");
  } catch (error) {
    if (!isCurrentSectionRequest(token)) return;
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
    date_from: queryDateFrom(),
    date_to: queryDateTo(),
    period_mode: periodMode,
    period_grain: "month",
    grain_id: grain,
    entity_ids: entityIds,
    entity_filters: selectedParentFiltersForGrain(grain),
    metric_concepts: metricConcepts,
    comparison_mode: selectedComparisonMode(),
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
  const summaryGrain = salesDriverSummaryGrain();
  return {
    ...buildQueryPayload(summaryGrain, entityIdsForSalesDriverSummary(summaryGrain), [state.salesDriverMetric]),
    date_from: dateFrom,
    date_to: dateTo,
    period_mode: "DATE_RANGE",
    comparison_mode: "NONE"
  };
}

function buildContributionPayload(summaryResponse = state.summaryResponse) {
  if (state.periodMode !== "COMPARE") return null;
  if (hasNonDrilldownFilters()) return null;
  const metricConcept = contributionMetricForOverview();
  if (!metricConcept) return null;
  const comparison = summaryResponse?.comparisons?.[0];
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
  const grain = portfolioAnalysisGrain();
  return {
    retailer_id: retailer.retailer_id,
    source_id: retailer.source_id,
    date_from: queryDateFrom(),
    date_to: queryDateTo(),
    period_mode: backendPeriodMode(),
    period_grain: "month",
    grain_id: grain,
    entity_ids: [],
    entity_filters: selectedPortfolioExecutionFilters(grain),
    user_entity_filters: selectedFilterValuesForPortfolio(),
    concept_ids: portfolioMarketConcepts,
    comparison_mode: state.periodMode === "AVAILABLE_MONTH_SET" ? "NONE" : selectedComparisonMode(),
    include_lineage: true,
    mart_build_id: retailer.default_mart_build_id,
    private_label_scope: document.getElementById("private-label-scope").value
  };
}

function buildStoresPayload() {
  return buildQueryPayload("store", entityIdsForStores(), storeConcepts());
}

function buildStoresGeographyPayload() {
  const retailer = selectedRetailer();
  return {
    retailer_id: retailer.retailer_id,
    source_id: retailer.source_id,
    date_from: queryDateFrom(),
    date_to: queryDateTo(),
    period_mode: backendPeriodMode(),
    period_grain: "month",
    grouping: state.storesGroupMode,
    entity_filters: selectedFilterValuesForPortfolio(),
    metric_concepts: geographyMetricConcepts,
    comparison_mode: selectedComparisonMode(),
    include_lineage: true,
    mart_build_id: retailer.default_mart_build_id,
    private_label_scope: document.getElementById("private-label-scope").value
  };
}

function buildSignalsPayload() {
  const retailer = selectedRetailer();
  return {
    retailer_id: retailer.retailer_id,
    source_id: retailer.source_id,
    date_from: queryDateFrom(),
    date_to: queryDateTo(),
    period_mode: backendPeriodMode(),
    period_grain: "month",
    grain_id: state.currentGrain,
    entity_ids: entityIdsForSummary(),
    entity_filters: selectedFilterValuesForPortfolio(),
    comparison_mode: selectedComparisonMode(),
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
    date_from: queryDateFrom(),
    date_to: queryDateTo(),
    period_mode: backendPeriodMode(),
    period_grain: "month",
    grain_id: state.currentGrain,
    entity_ids: entityIdsForSummary(),
    entity_filters: selectedFilterValuesForPortfolio(),
    comparison_mode: selectedComparisonMode(),
    mart_build_id: retailer.default_mart_build_id,
    private_label_scope: document.getElementById("private-label-scope").value,
    limit: state.tablePageSize,
    offset: state.dataPageOffset
  };
}

function backendPeriodMode() {
  if (state.periodMode === "DATE_RANGE") return "DATE_RANGE";
  if (state.periodMode === "AVAILABLE_MONTH_SET") return "AVAILABLE_MONTH_SET";
  return "SINGLE_PERIOD";
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

function salesDriverConcepts(grain = salesDriverSummaryGrain()) {
  return [...new Set(salesDriverBuckets.flatMap((group) => group.concepts))]
    .filter((concept) => salesDriverMetricEntry(concept, grain));
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
    const valueWrap = document.createElement("strong");
    valueWrap.className = "metric-current";
    valueWrap.appendChild(metricValueButton({
      concept,
      text: formatValue(result.value, entry.format),
      result,
      response: state.summaryResponse,
      className: "metric-value-button--kpi"
    }));
    card.appendChild(valueWrap);
    const meta = document.createElement("span");
    meta.className = "kpi-meta";
    if (isComparisonDisplayMode() && comparison) {
      meta.appendChild(metricDeltaButton({
        concept,
        text: kpiContextText(comparison, entry),
        value: comparison.delta,
        result,
        response: state.summaryResponse
      }));
    } else {
      meta.textContent = kpiContextText(comparison, entry);
    }
    card.appendChild(meta);
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
    const valueWrap = document.createElement("strong");
    valueWrap.appendChild(metricValueButton({
      concept,
      text: compactMetricText(result, entry),
      result,
      response: state.summaryResponse
    }));
    item.appendChild(valueWrap);
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
  box.replaceChildren(buildOverviewSvgChart(points, entry));
  const missing = (coverage?.missing_periods || []).map(formatPeriod).join(", ");
  const limitation = limitationText(result);
  footnote.textContent = [
    missing ? `Пропущены периоды: ${missing}` : "Все запрошенные периоды с данными показаны.",
    limitation
  ].filter(Boolean).join(" ");
}

function buildOverviewSvgChart(points, entry) {
  const width = 860;
  const height = 318;
  const pad = { left: 72, right: 34, top: 30, bottom: 54 };
  const svg = svgEl("svg", { class: "chart-svg overview-chart-svg", viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": `${entry.display_label}: динамика` });
  const values = points.map((point) => point.value);
  const max = Math.max(...values, 1);
  const min = Math.min(0, ...values);
  const range = max - min || 1;
  const x = (monthIndex) => pad.left + (monthIndex * (width - pad.left - pad.right)) / 11;
  const y = (value) => pad.top + (max - value) * (height - pad.top - pad.bottom) / range;
  const series = chartYearSeries(points);

  for (let tick = 0; tick <= 4; tick += 1) {
    const value = min + (range * tick) / 4;
    const yy = y(value);
    svg.appendChild(svgEl("line", { class: "grid-line", x1: pad.left, y1: yy, x2: width - pad.right, y2: yy }));
    svg.appendChild(svgText(pad.left - 10, yy + 4, formatValue(value, entry.format), "end", "axis-label"));
  }
  svg.appendChild(svgEl("line", { class: "axis-line", x1: pad.left, y1: height - pad.bottom, x2: width - pad.right, y2: height - pad.bottom }));
  svg.appendChild(svgEl("line", { class: "axis-line", x1: pad.left, y1: pad.top, x2: pad.left, y2: height - pad.bottom }));
  svg.appendChild(svgText(pad.left, 14, unitLabel(entry.format), "start", "axis-unit"));

  monthLabelsShort().forEach((month, index) => {
    const xx = x(index);
    svg.appendChild(svgEl("line", { class: "month-grid-line", x1: xx, y1: pad.top, x2: xx, y2: height - pad.bottom }));
    svg.appendChild(svgText(xx, height - 28, month, "middle", "axis-label month-label"));
  });

  series.forEach((yearSeries, seriesIndex) => {
    chartPathSegments(yearSeries.points).forEach((segment) => {
      if (segment.length > 1) {
        const path = segment.map((point, index) => `${index === 0 ? "M" : "L"} ${x(point.monthIndex)} ${y(point.value)}`).join(" ");
        svg.appendChild(svgEl("path", { class: `overview-chart-line overview-chart-line--series-${seriesIndex % 3}`, d: path }));
      }
    });
    yearSeries.points.forEach((point) => {
      const circle = svgEl("circle", {
        class: `overview-chart-point overview-chart-point--series-${seriesIndex % 3}`,
        cx: x(point.monthIndex),
        cy: y(point.value),
        r: isSelectedComparisonPeriod(point.period) ? 4.8 : 3.6,
        tabindex: 0
      });
      const tooltip = `${formatPeriod(point.period)} · ${entry.display_label}: ${formatValue(point.value, entry.format)}`;
      circle.addEventListener("mousemove", (event) => showTooltip(event, tooltip));
      circle.addEventListener("focus", (event) => showTooltip(event, tooltip));
      circle.addEventListener("mouseleave", hideTooltip);
      circle.addEventListener("blur", hideTooltip);
      circle.addEventListener("click", () => openProvenance(entry.metric_concept));
      svg.appendChild(circle);
      if (isSelectedComparisonPeriod(point.period)) {
        svg.appendChild(svgEl("circle", {
          class: "comparison-point-marker",
          cx: x(point.monthIndex),
          cy: y(point.value),
          r: 7.2
        }));
        svg.appendChild(svgText(x(point.monthIndex), y(point.value) - 10, point.period === selectedDateFrom() ? "A" : "B", "middle", "marker-label"));
      }
    });
    svg.appendChild(svgText(width - pad.right - 58, pad.top + 14 + seriesIndex * 18, String(yearSeries.year), "start", `chart-legend chart-legend--series-${seriesIndex % 3}`));
  });
  return svg;
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

function chartYearSeries(points) {
  const byYear = new Map();
  points.forEach((point) => {
    const date = new Date(`${point.period}T00:00:00`);
    const year = date.getFullYear();
    const monthIndex = date.getMonth();
    if (!byYear.has(year)) byYear.set(year, []);
    byYear.get(year).push({ ...point, year, monthIndex });
  });
  return Array.from(byYear.entries())
    .sort(([left], [right]) => left - right)
    .map(([year, yearPoints]) => ({
      year,
      points: yearPoints.sort((left, right) => left.monthIndex - right.monthIndex)
    }));
}

function chartPathSegments(points) {
  const segments = [];
  let current = [];
  points.forEach((point) => {
    const previous = current[current.length - 1];
    if (previous && point.monthIndex !== previous.monthIndex + 1) {
      segments.push(current);
      current = [];
    }
    current.push(point);
  });
  if (current.length) segments.push(current);
  return segments;
}

function monthLabelsShort() {
  return ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
}

function isSelectedComparisonPeriod(period) {
  return comparisonMarkerPeriods().includes(period);
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
    const valueWrap = document.createElement("strong");
    valueWrap.appendChild(metricValueButton({
      concept,
      text: compactMetricText(result, entry),
      result,
      response: state.summaryResponse
    }));
    card.appendChild(valueWrap);
    appendText(card, "p", movementText(result, entry));
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
    if (result && salesDriverMetricEntry(concept)) {
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
    } else {
      metricCell.textContent = displayLabel(concept);
      metricCell.className = "limitation-state-cell";
    }
    tr.appendChild(metricCell);
    salesDriverMetricCells(result, entry).forEach((cell) => {
      const td = document.createElement("td");
      if (cell.role) td.className = `metric-table-cell metric-table-cell--${cell.role}`;
      if (cell.inspectable) {
        const label = cell.role === "reference"
          ? "Период сравнения"
          : cell.role === "delta"
            ? "Изменение"
            : "Текущий период";
        td.appendChild(metricComparisonCell({
          concept,
          label,
          text: cell.text,
          result,
          response: state.salesDriversResponse,
          role: cell.role || "current",
          deltaValue: cell.deltaValue
        }));
      } else {
        td.textContent = cell.text;
        if (cell.text.includes("Недоступно") || cell.text.includes("только")) td.classList.add("limitation-state-cell");
      }
      tr.appendChild(td);
    });
    const actionCell = document.createElement("td");
    if (result?.provenance) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "inline-link";
      setInfoButtonLabel(button);
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
  if (isComparisonDisplayMode()) {
    return ["Группа", "Показатель", "Сейчас", "Сравнение", "Изменение", "Доказательство"];
  }
  if (state.periodMode === "DATE_RANGE") return ["Группа", "Показатель", "Диапазон", "Статус", "Доказательство"];
  return ["Группа", "Показатель", "Сейчас", "Статус", "Доказательство"];
}

function salesDriverRows() {
  const rows = [];
  salesDriverBuckets.forEach((bucket) => {
    bucket.concepts
      .filter((concept) => salesDriverDisplayEntry(concept))
      .forEach((concept) => {
        rows.push({
          group: bucket.title,
          concept,
          result: salesDriverResultFor(concept),
          entry: salesDriverDisplayEntry(concept)
        });
      });
  });
  return rows;
}

function salesDriverMetricCells(result, entry) {
  const staticCell = (text) => ({ text, inspectable: false });
  const valueCell = (text, role = "current") => ({ text, inspectable: true, isDelta: false, role });
  const deltaCell = (text, deltaValue) => ({ text, inspectable: true, isDelta: true, deltaValue, role: "delta" });
  if (!result || !entry) {
    return isComparisonDisplayMode()
      ? [staticCell("Недоступно"), staticCell("Недоступно"), staticCell("Недоступно")]
      : [staticCell("Недоступно"), staticCell("Показатель недоступен для выбранного среза.")];
  }
  const limitation = limitationText(result);
  if (state.periodMode === "DATE_RANGE") {
    if (entry.range_aggregation_strategy === "period_only" || result.limitations?.includes("range_aggregation_period_only")) {
      return [staticCell("Недоступно"), staticCell(periodOnlyLimitationText())];
    }
    return [valueCell(compactMetricText(result, entry)), staticCell(limitation || "Показано за доступные периоды диапазона.")];
  }
  if (state.periodMode === "SINGLE_PERIOD") {
    return [valueCell(formatValue(result.value, entry.format)), staticCell(limitation || "Состояние за выбранный период.")];
  }
  if (state.periodMode === "AVAILABLE_MONTH_SET" && result.limitations?.includes("range_aggregation_period_only")) {
    return [staticCell("Недоступно"), staticCell("Недоступно"), staticCell(periodOnlyLimitationText())];
  }
  const comparison = comparisonFor(state.salesDriversResponse, result);
  if (!comparison) {
    return [valueCell(formatValue(result.value, entry.format)), staticCell("Нет периода"), staticCell("Нет подходящего периода сравнения.")];
  }
  const deltaFormat = entry.format === "percent" ? "percentage_points" : entry.format;
  return [
    valueCell(formatValue(comparison.current_value, entry.format), "current"),
    valueCell(formatValue(comparison.comparison_value, entry.format), "reference"),
    deltaCell(`${formatDeltaValue(comparison.delta, deltaFormat)} · ${formatValue(comparison.pct_delta, "percent")}`, comparison.delta)
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
      return result && entry
        ? {
            text: metricCellTextForResponse(result, entry, state.salesDriversTableResponse),
            concept,
            result,
            response: state.salesDriversTableResponse,
            inspectable: true,
            deltaValue: comparisonFor(state.salesDriversTableResponse, result)?.delta
          }
        : "Недоступно";
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
  syncPortfolioControls();
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
  const response = state.storesGroupMode === "store" ? state.storesResponse : state.storesGeographyResponse;
  if (response) {
    renderContextStripForResponse(response);
  } else {
    renderStoresContextStripWithoutResponse();
  }
  renderBreadcrumb();
  renderStoreGroupModeOptions();
  renderStoreMetricOptions();
  if (state.storesScopeStatus === "no_supported_metrics") {
    renderStoresNoSupportedMetrics();
    return;
  }
  if (state.storesGroupMode !== "store") {
    renderStoresGeography();
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
    replaceWithMessage(target, "empty-state compact limitation-state", "Ограничений доступности для выбранного среза нет.");
    return;
  }
  target.replaceChildren(...limitations.map((item) => {
    const node = document.createElement("article");
    node.className = "signal-limitation limitation-state";
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
  if (state.periodMode === "AVAILABLE_MONTH_SET") return `Сопоставимые месяцы · ${availableMonthSummaryText(state.summaryResponse || state.signalsResponse)}`;
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
  list.className = quality.warnings?.length ? "quality-list has-warning" : "quality-list is-clear";
  items.forEach(([label, value]) => {
    const item = document.createElement("div");
    appendText(item, "span", label);
    appendText(item, "strong", value);
    list.appendChild(item);
  });
  if (quality.warnings?.length) {
    const warning = document.createElement("p");
    warning.className = "quality-warning data-quality-state";
    warning.textContent = "Есть предупреждения качества. Подробности доступны в аудите расчёта.";
    list.appendChild(warning);
  } else {
    const clear = document.createElement("p");
    clear.className = "quality-clear data-quality-state";
    clear.textContent = "Доступные проверки качества не нашли предупреждений для текущей витрины.";
    list.appendChild(clear);
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
  if (state.storesScopeStatus === "no_supported_metrics") {
    coverageNote = "Для выбранной сети нет подтверждённых store-level показателей этого экрана.";
  }
  document.getElementById("context-strip").textContent = parts.join(" · ");
  document.getElementById("context-coverage-note").textContent = coverageNote;
}

function renderStoreMetricOptions() {
  const select = document.getElementById("stores-metric");
  const sourceMetrics = state.storesGroupMode === "store" ? storeRankingMetrics : geographyRankingMetrics;
  const metrics = sourceMetrics.filter((concept) =>
    state.storesGroupMode === "store" ? metricEntryForGrain(concept, "store") : catalogEntry(concept)
  );
  select.replaceChildren(...metrics.map((concept) => option(concept, displayLabel(concept))));
  if (!metrics.includes(state.storesMetric)) {
    state.storesMetric = metrics[0] || "revenue";
    state.sortColumn = storeSortColumn();
    state.sortDirection = "desc";
  }
  select.value = state.storesMetric;
}

function renderStoreGroupModeOptions() {
  const select = document.getElementById("stores-group-mode");
  if (!select) return;
  select.replaceChildren(...storeGroupModes.map((mode) => option(mode.value, mode.label)));
  if (!storeGroupModes.some((mode) => mode.value === state.storesGroupMode)) state.storesGroupMode = "store";
  select.value = state.storesGroupMode;
}

function renderStoresGeography() {
  renderGeographyRanking();
  renderGeographyContextPanel();
  renderGeographyTable();
  renderGeographyDetailState();
}

function renderGeographyRanking() {
  const target = document.getElementById("stores-ranking");
  const rows = geographyRowsByMetric(state.storesMetric);
  if (!rows.length) {
    replaceWithMessage(target, "empty-state compact", "Для выбранного географического разреза данных нет.");
    document.getElementById("stores-ranking-context").textContent =
      "Регион и формат показываются только по подтверждённым additive показателям.";
    return;
  }
  const maxValue = Math.max(...rows.map((row) => Math.abs(Number(row.result.value) || 0)), 1);
  target.replaceChildren(...rows.map((row, index) => {
    const node = document.createElement("article");
    node.className = "store-ranking-row";
    const label = document.createElement("div");
    label.className = "store-rank-label";
    label.textContent = `${index + 1}. ${geographyEntityLabel(row.entityId)}`;
    node.appendChild(label);
    const barWrap = document.createElement("div");
    barWrap.className = "ranked-bar-track";
    const bar = document.createElement("div");
    bar.className = "ranked-bar-fill";
    bar.style.width = `${Math.max(3, (Math.abs(Number(row.result.value) || 0) / maxValue) * 100)}%`;
    barWrap.appendChild(bar);
    node.appendChild(barWrap);
    const valueWrap = document.createElement("strong");
    valueWrap.appendChild(storeRankingValueNode(row.result, catalogEntry(state.storesMetric), state.storesGeographyResponse));
    node.appendChild(valueWrap);
    return node;
  }));
  document.getElementById("stores-ranking-context").textContent = isComparisonDisplayMode()
    ? `${storeGroupModeLabel()} · текущий уровень и изменение к периоду сравнения.`
    : `${storeGroupModeLabel()} · ранжирование по выбранному additive показателю.`;
}

function renderGeographyContextPanel() {
  const target = document.getElementById("stores-selected-kpi");
  const rows = geographyRowsByMetric("revenue");
  const totalStores = rows.reduce((sum, row) => sum + Number(row.result.store_count || 0), 0);
  const items = [
    ["Режим", storeGroupModeLabel()],
    ["Строк", formatValue(geographyEntityIds().length, "integer")],
    ["ТТ в строках", totalStores ? formatValue(totalStores, "integer") : "н/д"]
  ];
  const cards = items.map(([label, value]) => {
    const card = document.createElement("article");
    card.className = "store-kpi";
    appendText(card, "span", label);
    appendText(card, "strong", value);
    return card;
  });
  target.replaceChildren(...cards);
  const selectedStore = selectedStoreId();
  document.getElementById("stores-selected-context").textContent = selectedStore
    ? `Выбранная ТТ учитывается как обычный фильтр: ${entityDisplayLabel("store", selectedStore)}.`
    : "География агрегируется по текущему срезу без неподтверждённых разрезов и дистрибуции.";
}

function renderGeographyTable() {
  const table = document.getElementById("stores-table");
  const rows = geographyRowsByMetric(state.storesMetric);
  if (!rows.length) {
    renderMessageRow(table, "Для выбранного географического разреза данных нет.");
    document.getElementById("stores-table-context").textContent =
      "Нет строк с подтверждёнными значениями региона или формата ТТ в текущем срезе.";
    return;
  }
  const headers = geographyTableHeaders();
  if (!headers.includes(state.sortColumn)) {
    state.sortColumn = storeSortColumn();
    state.sortDirection = "desc";
  }
  const tableRows = rows.map((row) => ({
    cells: [
      ...geographyIdentityCells(row.entityId),
      geographyTableInspectableCell("revenue", row.entityId),
      geographyTableDeltaCell("revenue", row.entityId),
      geographyTableInspectableCell("units", row.entityId),
      geographyTableDeltaCell("units", row.entityId),
      geographyTableInspectableCell("retailer_margin_abs", row.entityId),
      geographyTableInspectableCell("retailer_margin_pct", row.entityId),
      formatValue(row.result.store_count, "integer")
    ],
    meta: { entityId: row.entityId }
  }));
  renderRows(table, headers, tableRows, {
    rowLimit: state.tablePageSize,
    onSort: renderGeographyTable
  });
  const caption = table.createCaption();
  caption.textContent = `Показаны ${Math.min(tableRows.length, state.tablePageSize)} из ${tableRows.length} строк · ${storeGroupModeLabel()}`;
  document.getElementById("stores-table-context").textContent = isComparisonDisplayMode()
    ? "Δ показывает изменение к периоду сравнения; margin % пересчитан backend как отношение сумм."
    : "Таблица показывает revenue, units, абсолютную маржу и margin % по выбранной группировке.";
}

function renderGeographyDetailState() {
  const target = document.getElementById("stores-detail");
  target.textContent =
    "Неподтверждённые географические разрезы и дистрибуция по географии остаются закрытыми до отдельного правила.";
}

function geographyTableHeaders() {
  const identity = state.storesGroupMode === "region_store_format" ? ["Регион", "Формат ТТ"] : [storeGroupModeLabel()];
  return [...identity, "Оборот", "Δ", "Продажи, шт.", "Δ", "Абсолютная маржа", "Маржинальность", "ТТ"];
}

function geographyIdentityCells(entityId) {
  const result = geographyResultFor("revenue", entityId) || geographyResultFor(state.storesMetric, entityId);
  if (state.storesGroupMode === "region_store_format") {
    return [
      result?.dimension_values?.region || "н/д",
      result?.dimension_values?.store_format || "н/д"
    ];
  }
  return [geographyEntityLabel(entityId)];
}

function geographyRowsByMetric(metricConcept) {
  return geographyEntityIds()
    .map((entityId) => ({ entityId, result: geographyResultFor(metricConcept, entityId) }))
    .filter((row) => row.result && row.result.value !== null && row.result.value !== undefined)
    .sort((left, right) => Number(right.result.value || 0) - Number(left.result.value || 0));
}

function geographyEntityIds() {
  return [...new Set((state.storesGeographyResponse?.metric_results || []).map((result) => result.entity_id))];
}

function geographyResultFor(concept, entityId) {
  return state.storesGeographyResponse?.metric_results.find((result) => result.metric_concept === concept && result.entity_id === entityId);
}

function geographyEntityLabel(entityId) {
  const result = geographyResultFor("revenue", entityId) || geographyResultFor(state.storesMetric, entityId);
  return result?.label || entityId || "н/д";
}

function geographyTableInspectableCell(concept, entityId) {
  const result = geographyResultFor(concept, entityId);
  const entry = catalogEntry(concept);
  return {
    text: result && entry ? formatValue(result.value, entry.format) : "Недоступно",
    concept,
    result,
    response: state.storesGeographyResponse,
    inspectable: Boolean(result && entry),
    role: "current"
  };
}

function geographyTableDeltaCell(concept, entityId) {
  const result = geographyResultFor(concept, entityId);
  const entry = catalogEntry(concept);
  const comparison = comparisonFor(state.storesGeographyResponse, result);
  const deltaFormat = entry?.format === "percent" ? "percentage_points" : entry?.format;
  return {
    text: isComparisonDisplayMode() && comparison && entry ? formatDeltaValue(comparison.delta, deltaFormat) : "—",
    concept,
    result,
    response: state.storesGeographyResponse,
    inspectable: Boolean(result && comparison),
    deltaValue: comparison?.delta,
    role: "delta"
  };
}

function storeGroupModeLabel() {
  return storeGroupModes.find((mode) => mode.value === state.storesGroupMode)?.label || "ТТ";
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
    const valueWrap = document.createElement("strong");
    valueWrap.appendChild(storeRankingValueNode(row.result, catalogEntry(state.storesMetric), state.storesResponse));
    node.appendChild(valueWrap);
    return node;
  }));
  document.getElementById("stores-ranking-context").textContent = isComparisonDisplayMode()
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
      storeTableInspectableCell("revenue", row.entityId),
      storeTableDeltaCell("revenue", row.entityId),
      storeTableInspectableCell("units", row.entityId),
      storeTableDeltaCell("units", row.entityId),
      storeTableInspectableCell("retailer_margin_abs", row.entityId),
      storeTableInspectableCell("retailer_margin_pct", row.entityId),
      storeTableInspectableCell("sku_count", row.entityId)
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
  document.getElementById("stores-table-context").textContent = isComparisonDisplayMode()
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
  node.appendChild(storeRankingValueNode(result, entry, state.storesResponse));
  const limitation = limitationText(result);
  if (limitation) appendText(node, "small", limitation);
  return node;
}

function storeRankingValueNode(result, entry, response) {
  const comparison = comparisonFor(response, result);
  if (isComparisonDisplayMode() && comparison) {
    const wrap = document.createElement("span");
    wrap.className = "store-value-stack";
    wrap.appendChild(metricComparisonCell({
      concept: result.metric_concept,
      label: "Сейчас",
      text: formatValue(comparison.current_value, entry.format),
      result,
      response,
      role: "current"
    }));
    wrap.appendChild(metricComparisonCell({
      concept: result.metric_concept,
      label: "Δ",
      text: formatDeltaValue(comparison.delta, deltaFormatFor(entry.format)),
      result,
      response,
      role: "delta",
      deltaValue: comparison.delta
    }));
    return wrap;
  }
  return metricValueButton({
    concept: result.metric_concept,
    text: storeMetricWithDelta(result, entry, response),
    result,
    response
  });
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

function storeTableInspectableCell(concept, entityId) {
  const result = storeResultFor(concept, entityId);
  const entry = catalogEntry(concept);
  return {
    text: storeTableValue(concept, entityId),
    concept,
    result,
    response: state.storesResponse,
    inspectable: Boolean(result && entry && !result.limitations?.includes("range_aggregation_period_only")),
    role: "current"
  };
}

function storeTableDelta(concept, entityId) {
  if (!isComparisonDisplayMode()) return "—";
  const result = storeResultFor(concept, entityId);
  const entry = catalogEntry(concept);
  const comparison = comparisonFor(state.storesResponse, result);
  if (!result || !entry || !comparison) return "н/д";
  const deltaFormat = entry.format === "percent" ? "percentage_points" : entry.format;
  return formatDeltaValue(comparison.delta, deltaFormat);
}

function storeTableDeltaCell(concept, entityId) {
  const result = storeResultFor(concept, entityId);
  const comparison = comparisonFor(state.storesResponse, result);
  return {
    text: storeTableDelta(concept, entityId),
    concept,
    result,
    response: state.storesResponse,
    inspectable: Boolean(result && comparison),
    deltaValue: comparison?.delta,
    role: "delta"
  };
}

function storeMetricWithDelta(result, entry, response) {
  if (!result || !entry) return "Недоступно";
  const value = formatValue(result.value, entry.format);
  const comparison = comparisonFor(response, result);
  if (isComparisonDisplayMode() && comparison) {
    return `${value} · ${formatDeltaValue(comparison.delta, deltaFormatFor(entry.format))}`;
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
  setInfoButtonLabel(button);
  button.addEventListener("click", () => openStoreProvenance(result));
  return button;
}

function openStoreProvenance(result) {
  openMetricInspector({ concept: result.metric_concept, result, response: state.storesResponse, mode: "value" });
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
  const contributionRows = portfolioContributionRows();
  const rank = portfolioItem(portfolioBasisConcept("rank"));
  const rows = rank?.rows || [];
  const selectedManufacturer =
    selectedFilterValues().manufacturer?.[0] || (state.currentGrain === "manufacturer" ? entityIdsForSummary()[0] : "");

  if (contributionRows.length) {
    shareStrip.replaceChildren(...portfolioPositionSummaryTiles(contributionRows));
  } else if (shareItems.length) {
    shareStrip.replaceChildren(...shareItems.map((item) => portfolioMetricTile(item)));
  } else {
    replaceWithMessage(shareStrip, "empty-state compact", portfolioShareUnavailableText());
  }

  if (contributionRows.length) {
    rankList.replaceChildren(...contributionRows.slice(0, 12).map((row) => portfolioDecisionRow(row)));
    document.getElementById("portfolio-position-context").textContent =
      `${portfolioDecisionContextText()} · Доля и ABC нейтральны: это вклад в выбранной вселенной, не оценка качества.`;
    return;
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
      const rankValue = document.createElement("strong");
      rankValue.appendChild(metricValueButton({
        concept: "manufacturer_rank_revenue",
        text: `${formatValue(row.metric_value, catalogEntry("revenue")?.format || "decimal")} · ${row.rank} из ${row.population_count}`,
        result: portfolioResultForInspector({
          ...rank,
          value: row.rank,
          entity_id: row.manufacturer,
          provenance: row.provenance || rank.provenance
        })
      }));
      node.appendChild(rankValue);
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

function portfolioContributionRows() {
  const shareItem = portfolioItem(portfolioBasisConcept("share"));
  const cumulativeItem = portfolioItem(portfolioBasisConcept("cumulative"));
  const rankItem = portfolioItem(portfolioBasisConcept("rank"));
  const abcItem = portfolioItem(portfolioBasisConcept("abc"));
  const baseItem = [shareItem, abcItem, rankItem].find((item) => item?.rows?.length);
  if (!baseItem?.rows?.length) return [];
  const cumulativeByEntity = rowsByEntityId(cumulativeItem?.rows || []);
  const rankByEntity = rowsByEntityId(rankItem?.rows || []);
  const shareByEntity = rowsByEntityId(shareItem?.rows || []);
  const abcByEntity = rowsByEntityId(abcItem?.rows || []);
  return (baseItem.rows || []).map((baseRow) => {
    const entityId = baseRow.entity_id;
    const shareRow = shareByEntity.get(entityId) || baseRow;
    return {
      entityId,
      entityType: baseRow.entity_type || baseRow.share_entity_type || baseItem.grain_id || state.currentGrain,
      label: entityDisplayLabel(baseRow.entity_type || baseRow.share_entity_type || baseItem.grain_id, entityId) || entityId,
      valueItem: shareItem || abcItem || rankItem,
      valueRow: shareRow,
      shareItem,
      shareRow,
      cumulativeItem,
      cumulativeRow: cumulativeByEntity.get(entityId) || (baseRow.cumulative_share !== undefined ? baseRow : null),
      rankItem,
      rankRow: rankByEntity.get(entityId) || (baseRow.rank !== undefined ? baseRow : null),
      abcItem,
      abcRow: abcByEntity.get(entityId) || (baseRow.abc_class !== undefined ? baseRow : null)
    };
  });
}

function portfolioPositionSummaryTiles(rows) {
  const first = rows[0] || {};
  const grain = portfolioAnalysisGrain();
  const universeSize = first.shareRow?.universe_size ?? first.rankRow?.universe_size ?? first.shareRow?.current_universe_size;
  const period = state.periodMode === "AVAILABLE_MONTH_SET"
    ? "сопоставимые месяцы"
    : state.periodMode === "COMPARE" ? "сравнение периодов" : state.periodMode === "DATE_RANGE" ? "диапазон" : "один период";
  return [
    portfolioSummaryTile("Уровень", grainLabels[grain] || grain, hasSingleCategoryScope() ? "внутри выбранной категории" : "обзор рынка по категориям"),
    portfolioSummaryTile("Показатель", portfolioBasisLabel(state.portfolioBasis), period),
    portfolioSummaryTile("Вселенная", universeSize ? `${formatValue(universeSize, "integer")} объектов` : `${rows.length} строк`, ownershipLabel(first.abcRow || first.shareRow) || privateLabelScopeText(document.getElementById("private-label-scope").value))
  ];
}

function portfolioSummaryTile(label, value, detail) {
  const node = document.createElement("article");
  node.className = "portfolio-metric";
  appendText(node, "span", label);
  appendText(node, "strong", value);
  appendText(node, "small", detail);
  return node;
}

function portfolioDecisionRow(model) {
  const node = document.createElement("article");
  const ownershipClass = portfolioOwnershipClass(model.abcRow || model.shareRow);
  const selectedClass = selectedValuesForFilter(model.entityType).includes(model.entityId) ? "is-selected" : "";
  node.className = ["portfolio-decision-row", ownershipClass, selectedClass].filter(Boolean).join(" ");

  const entity = document.createElement("div");
  entity.className = "portfolio-entity-cell";
  appendText(entity, "span", grainLabels[model.entityType] || model.entityType || "Объект");
  const title = document.createElement("button");
  title.type = "button";
  title.className = "portfolio-entity-link";
  title.textContent = model.label;
  title.addEventListener("click", () => {
    void selectPortfolioEntity(model.entityType, model.entityId);
  });
  entity.appendChild(title);
  const ownership = ownershipBadge(model.abcRow || model.shareRow);
  if (ownership) entity.appendChild(ownership);
  node.appendChild(entity);

  node.appendChild(portfolioCurrentReferenceCell(model));
  node.appendChild(portfolioRankCell(model));
  node.appendChild(portfolioShareCell(model));
  node.appendChild(portfolioAbcCell(model));
  return node;
}

function portfolioCurrentReferenceCell(model) {
  const cell = document.createElement("div");
  cell.className = "portfolio-current-cell";
  appendText(cell, "span", "Текущий вклад");
  const row = model.valueRow || model.shareRow || model.abcRow;
  const currentValue = row?.current_metric_value ?? row?.metric_value;
  const current = document.createElement("strong");
  current.className = "metric-current";
  current.appendChild(metricValueButton({
    concept: row?.basis_metric_id || model.valueItem?.concept_id || model.shareItem?.concept_id || model.abcItem?.concept_id,
    text: formatValue(currentValue, catalogEntry(row?.basis_metric_id)?.format || "decimal"),
    result: portfolioRowResultForInspector(model.valueItem || model.shareItem || model.abcItem, row),
    response: state.portfolioMarketResponse,
    sections: portfolioRowProvenanceSections(model.valueItem || model.abcItem || model.shareItem, row, model)
  }));
  cell.appendChild(current);
  const reference = document.createElement("small");
  reference.className = "metric-reference";
  reference.textContent = portfolioReferenceText(row);
  cell.appendChild(reference);
  return cell;
}

function portfolioRankCell(model) {
  const row = model.rankRow || model.shareRow;
  const cell = document.createElement("div");
  cell.className = "portfolio-rank-cell";
  appendText(cell, "span", "Место");
  const rank = document.createElement("strong");
  rank.className = "rank-value";
  rank.appendChild(metricValueButton({
    concept: model.rankItem?.concept_id || "manufacturer_rank_revenue",
    text: row.rank !== null && row.rank !== undefined ? `№${row.rank}` : "н/д",
    result: portfolioRowResultForInspector(model.rankItem || model.shareItem, row),
    response: state.portfolioMarketResponse,
    sections: portfolioRowProvenanceSections(model.rankItem || model.abcItem || model.shareItem, row, model)
  }));
  cell.appendChild(rank);
  const movement = rankMovementBadge(row);
  if (movement) cell.appendChild(movement);
  return cell;
}

function portfolioShareCell(model) {
  const shareRow = model.shareRow || model.abcRow || {};
  const share = Number(shareRow.share);
  const cumulative = Number(model.cumulativeRow?.cumulative_share ?? shareRow.cumulative_share);
  const cell = document.createElement("div");
  cell.className = "portfolio-share-cell";
  appendText(cell, "span", "Доля / накопл.");
  const value = document.createElement("strong");
  value.className = "share-value";
  value.appendChild(metricValueButton({
    concept: model.shareItem?.concept_id || model.abcItem?.concept_id,
    text: formatValue(shareRow.share, "percent"),
    result: portfolioRowResultForInspector(model.shareItem || model.abcItem, shareRow),
    response: state.portfolioMarketResponse,
    sections: portfolioRowProvenanceSections(model.shareItem || model.abcItem, shareRow, model)
  }));
  cell.appendChild(value);
  const track = document.createElement("div");
  track.className = "share-track";
  const fill = document.createElement("div");
  fill.className = "share-fill";
  fill.style.width = `${Number.isFinite(share) ? Math.max(3, Math.min(100, share * 100)) : 0}%`;
  const cumulativeMarker = document.createElement("span");
  cumulativeMarker.className = "cumulative-marker";
  cumulativeMarker.style.left = `${Number.isFinite(cumulative) ? Math.max(0, Math.min(100, cumulative * 100)) : 0}%`;
  track.append(fill, cumulativeMarker);
  cell.appendChild(track);
  const note = document.createElement("small");
  note.className = "metric-reference";
  note.textContent = Number.isFinite(cumulative) ? `накопл. ${formatValue(cumulative, "percent")}` : "накопл. н/д";
  cell.appendChild(note);
  return cell;
}

function portfolioAbcCell(model) {
  const cell = document.createElement("div");
  cell.className = "portfolio-abc-cell";
  appendText(cell, "span", portfolioAbcContextLabel(model.abcItem));
  const chip = abcChip(model.abcRow?.abc_class);
  cell.appendChild(chip);
  const basis = document.createElement("small");
  basis.className = "metric-reference";
  basis.textContent = portfolioBasisLabel(model.abcRow?.abc_basis_metric || model.shareRow?.basis_metric_id);
  cell.appendChild(basis);
  return cell;
}

function rowsByEntityId(rows) {
  return new Map(rows.map((row) => [row.entity_id, row]));
}

function portfolioBasisMetric(item) {
  return item?.rows?.[0]?.basis_metric_id || item?.rows?.[0]?.share_basis_metric || item?.rows?.[0]?.abc_basis_metric || "";
}

function portfolioBasisLabel(metric) {
  return {
    revenue: "по обороту",
    units: "по штукам",
    retailer_margin_abs: "по абсолютной марже"
  }[metric] || "по выбранному показателю";
}

function portfolioReferenceText(row) {
  if (row.reference_share !== null && row.reference_share !== undefined) {
    const delta = row.share_delta_pp !== null && row.share_delta_pp !== undefined
      ? ` · ${formatDeltaValue(row.share_delta_pp, "percentage_points")}`
      : "";
    return `сравн. ${formatValue(row.reference_share, "percent")}${delta}`;
  }
  return row.universe_metric_value !== null && row.universe_metric_value !== undefined
    ? `вселенная ${formatValue(row.universe_metric_value, catalogEntry(row.basis_metric_id)?.format || "decimal")}`
    : "сравнение недоступно";
}

function rankMovementBadge(row) {
  const stateValue = row.rank_movement_state || row.movement_state;
  const movement = row.rank_movement_positions ?? row.rank_movement ?? row.rank_delta;
  if (!stateValue && (movement === null || movement === undefined)) return null;
  const badge = document.createElement("small");
  const normalized = stateValue || (movement < 0 ? "IMPROVED" : movement > 0 ? "DECLINED" : "UNCHANGED");
  badge.className = `rank-movement ${rankMovementClass(normalized)}`;
  badge.textContent = rankMovementText(normalized, movement);
  badge.setAttribute("aria-label", `Движение в рейтинге: ${badge.textContent}`);
  return badge;
}

function rankMovementClass(stateValue) {
  return {
    IMPROVED: "is-improved",
    DECLINED: "is-declined",
    UNCHANGED: "is-stable",
    NEW_IN_RANK_UNIVERSE: "is-new",
    EXITED_RANK_UNIVERSE: "is-exited"
  }[stateValue] || "is-stable";
}

function rankMovementText(stateValue, movement) {
  if (stateValue === "NEW_IN_RANK_UNIVERSE") return "Новый";
  if (stateValue === "EXITED_RANK_UNIVERSE") return "Вышел";
  const amount = Math.abs(Number(movement) || 0);
  if (stateValue === "IMPROVED") return `↑ ${formatValue(amount, "integer")} поз.`;
  if (stateValue === "DECLINED") return `↓ ${formatValue(amount, "integer")} поз.`;
  return "→";
}

function abcChip(value) {
  const normalized = ["A", "B", "C"].includes(value) ? value : "н/д";
  const chip = document.createElement("strong");
  const classSuffix = normalized === "н/д" ? "na" : String(normalized).toLowerCase();
  chip.className = `abc-chip abc-chip-${classSuffix}`;
  chip.textContent = normalized;
  chip.setAttribute("aria-label", normalized === "н/д" ? "ABC недоступна" : `ABC класс ${normalized}`);
  return chip;
}

function portfolioAbcContextLabel(item) {
  if (!item) return "ABC";
  return displayLabel(item.concept_id).replace(/^ABC /, "ABC · ");
}

function ownershipBadge(row) {
  const label = ownershipLabel(row);
  if (!label) return null;
  const badge = document.createElement("small");
  badge.className = "ownership-badge";
  badge.textContent = label;
  return badge;
}

function ownershipLabel(row) {
  const ownership = row?.ownership_universe;
  if (ownership === "OWN_PORTFOLIO_CATEGORY") return `свой портфель · ${privateLabelDisplayName()}`;
  if (ownership === "COMPETITOR_CATEGORY") return "конкуренты";
  const scope = row?.private_label_scope;
  if (scope === "ONLY") return `свой портфель · ${privateLabelDisplayName()}`;
  if (scope === "EXCLUDE") return "конкуренты";
  return "";
}

function portfolioOwnershipClass(row) {
  const label = ownershipLabel(row);
  if (label.startsWith("свой")) return "is-own";
  if (label === "конкуренты") return "is-competitor";
  return "";
}

function portfolioDecisionContextText() {
  const row = portfolioContributionRows()[0];
  const category = selectedFilterValues().category?.length === 1
    ? entityDisplayLabel("category", selectedFilterValues().category[0])
    : "";
  const ownership = ownershipLabel(row?.abcRow || row?.shareRow) || privateLabelScopeText(document.getElementById("private-label-scope").value);
  const basis = portfolioBasisLabel(row?.shareRow?.basis_metric_id);
  if (portfolioAnalysisGrain() === "category") {
    return `Категории рынка · вклад ${basis} · нажмите категорию, чтобы открыть производителей, бренды и SKU`;
  }
  return [
    category ? `Категория: ${category}` : "Категория задана срезом",
    ownership,
    `вклад ${basis}`
  ].filter(Boolean).join(" · ");
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
  appendPortfolioAssortmentValue(values, "span", "active_sku_count", active, "integer");
  appendPortfolioAssortmentValue(values, "span", "historical_peak_active_sku_count", peak, "integer");
  appendPortfolioAssortmentValue(values, "strong", "active_sku_change_pct", change, "percent");
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

function appendPortfolioAssortmentValue(parent, tagName, concept, item, format) {
  const node = document.createElement(tagName);
  node.append(`${displayLabel(concept)}: `);
  if (item) {
    node.appendChild(metricValueButton({
      concept,
      text: formatValue(item.value, format),
      result: portfolioResultForInspector(item),
      response: state.portfolioMarketResponse,
      className: "metric-value-button--inline"
    }));
  } else {
    node.append("Недоступно");
  }
  parent.appendChild(node);
  return node;
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
  const valueWrap = document.createElement("strong");
  valueWrap.appendChild(metricValueButton({
    concept: item.concept_id,
    text: formatPortfolioItemValue(item),
    result: portfolioResultForInspector(item),
    response: state.portfolioMarketResponse
  }));
  node.appendChild(valueWrap);
  const detail = portfolioItemDetailText(item);
  if (detail) appendText(node, "small", detail);
  return node;
}

function portfolioProvenanceButton(item) {
  if (!item?.provenance) return null;
  const button = document.createElement("button");
  button.type = "button";
  button.className = "inline-link";
  setInfoButtonLabel(button);
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
      return result && entry
        ? {
            text: metricCellText(result, entry, state.tableResponse),
            concept,
            result,
            response: state.tableResponse,
            inspectable: true,
            deltaValue: comparisonFor(state.tableResponse, result)?.delta,
            role: comparisonFor(state.tableResponse, result)?.delta === undefined ? "current" : "delta"
          }
        : "Недоступно";
    });
    return { cells: [entityDisplayLabel(state.previewGrain, entityId) || entityId, ...cells], meta: { entityId } };
  });
  renderRows(table, headers, rows, {
    onFirstCellClick: (_label, meta) => {
      if (meta?.entityId) void drillIntoEntity(String(meta.entityId));
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
      { text: formatValue(row.current_value, metric?.format || "decimal"), value: row.current_value, type: "value", role: "current" },
      { text: formatValue(row.reference_value, metric?.format || "decimal"), value: row.reference_value, type: "value", role: "reference" },
      { text: formatDeltaValue(row.delta, deltaFormatFor(metric?.format || "decimal")), value: row.delta, type: "delta", role: "delta" },
      {
        text: row.contribution_share === null ? "н/д" : formatValue(row.contribution_share, "percent"),
        value: row.contribution_share,
        type: "contribution",
        role: "neutral"
      }
    ].forEach((cell) => {
      const rowSections = contributionProvenanceSections(row.provenance || {}, row);
      const td = document.createElement("td");
      td.className = `metric-table-cell metric-table-cell--${cell.role}`;
      if (cell.text === "н/д") {
        td.textContent = cell.text;
      } else if (cell.type === "delta") {
        td.appendChild(metricDeltaButton({
          concept: state.contributionResponse.metric_concept,
          text: cell.text,
          value: cell.value,
          result: contributionResultFromRow(row, cell.value),
          response: state.contributionResponse,
          sections: rowSections
        }));
      } else {
        td.appendChild(metricValueButton({
          concept: cell.type === "contribution" ? "contribution_to_delta" : state.contributionResponse.metric_concept,
          text: cell.text,
          result: contributionResultFromRow(row, cell.value),
          response: state.contributionResponse,
          sections: rowSections
        }));
      }
      tr.appendChild(td);
    });
    const actionCell = document.createElement("td");
    const provenanceButton = document.createElement("button");
    provenanceButton.type = "button";
    provenanceButton.className = "inline-link";
    setInfoButtonLabel(provenanceButton);
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
  const activePath = state.drilldownPath.filter((item) => selectedValuesForFilter(item.grain).includes(item.value));
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
  return selectedValuesForFilter(grain).length > 0;
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
  invalidateLoadedViews();
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
  document.getElementById("available-month-fields").classList.toggle("is-hidden", state.periodMode !== "AVAILABLE_MONTH_SET");
  document.getElementById("range-fields").classList.toggle("is-hidden", state.periodMode !== "DATE_RANGE");
  updateAvailableMonthDisclosure();
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
  if (state.periodMode === "AVAILABLE_MONTH_SET") {
    const end = selectedDateTo();
    const year = end ? new Date(`${end}T00:00:00`).getFullYear() : null;
    summary.textContent = year ? `${year} vs ${year - 1}` : "Выберите период";
    detail.textContent = "Сопоставимые месяцы";
    return;
  }
  const reference = derivedComparisonPeriodLabel();
  summary.textContent = `${formatCompactPeriod(selectedDateFrom())} / ${formatCompactPeriodText(reference)}`;
  detail.textContent = comparisonLabels[state.comparisonMode] || "Сравнение";
}

function derivedComparisonPeriodLabel() {
  const explicitReference = document.getElementById("period-b-derived")?.textContent || "";
  if (explicitReference && !["Не используется", "Нет подходящего периода"].includes(explicitReference)) {
    return explicitReference;
  }
  const current = selectedDateFrom();
  const periods = (state.options?.periods || []).map((period) => period.value);
  if (!current || !periods.length) return explicitReference || "период сравнения";
  if (state.comparisonMode === "YOY") {
    const yoy = shiftMonth(current, -12);
    return periods.includes(yoy) ? formatPeriod(yoy) : "Нет подходящего периода";
  }
  if (state.comparisonMode === "MOM") {
    const mom = shiftMonth(current, -1);
    return periods.includes(mom) ? formatPeriod(mom) : "Нет подходящего периода";
  }
  if (state.comparisonMode === "PREVIOUS_AVAILABLE") {
    const previous = periods.filter((period) => period < current).at(-1);
    return previous ? formatPeriod(previous) : "Нет подходящего периода";
  }
  return explicitReference || "период сравнения";
}

function shiftMonth(value, offset) {
  const [year, month] = value.split("-").map(Number);
  if (!year || !month) return "";
  const shifted = new Date(Date.UTC(year, month - 1 + offset, 1));
  return shifted.toISOString().slice(0, 10);
}

function updateComparisonPeriodDisplay(response) {
  const target = document.getElementById("period-b-derived");
  if (target && state.periodMode !== "COMPARE") {
    target.textContent = "Не используется";
  } else if (target) {
    const comparison = response?.comparisons?.[0];
    target.textContent = comparison?.comparison_period_start
      ? formatPeriod(comparison.comparison_period_start)
      : "Нет подходящего периода";
  }
  updateAvailableMonthDisclosure(response);
  updatePeriodSummary();
}

function updateAvailableMonthDisclosure(response) {
  const target = document.getElementById("available-months-derived");
  if (!target) return;
  if (state.periodMode !== "AVAILABLE_MONTH_SET") {
    target.textContent = "Не используется";
    return;
  }
  target.textContent = availableMonthSummaryText(response);
}

function availableMonthSummaryText(response) {
  const comparisonSet = availableMonthComparisonSet(response);
  const current = formatPeriodList(comparisonSet?.current_included_periods);
  const reference = formatPeriodList(comparisonSet?.comparison_included_periods);
  if (current && reference) return `${current} vs ${reference}`;
  const resultSet = availableMonthResultSet(response);
  const included = formatPeriodList(resultSet?.included_periods);
  return included || "Определяются витриной";
}

function availableMonthComparisonSet(response) {
  const comparison = response?.comparisons?.find((item) => item.current_included_periods?.length);
  if (comparison) return comparison;
  const provenanceSet = response?.metric_results
    ?.map((item) => item.provenance?.comparison?.period_set)
    .find((periodSet) => periodSet?.current_included_periods?.length);
  return provenanceSet || null;
}

function availableMonthResultSet(response) {
  return response?.metric_results
    ?.map((item) => item.provenance?.current_analytical_scope?.period_set)
    .find((periodSet) => periodSet?.included_periods?.length) || null;
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
  const allValues = state.options.entities?.[id] || [];
  const availableValues = new Set(allValues.map((item) => item.value));
  state.filters[id] = selectedValuesForFilter(id).filter((value) => availableValues.has(value));
  if (state.pendingFilters[id]) {
    state.pendingFilters[id] = state.pendingFilters[id].filter((value) => availableValues.has(value));
  }
  if (config.querySupported === false) {
    state.filters[id] = [];
    state.pendingFilters[id] = [];
    document.getElementById(`${id}-search`)?.setAttribute("disabled", "disabled");
    document.querySelector(`[data-clear-filter="${id}"]`)?.setAttribute("disabled", "disabled");
    document.querySelector(`[data-filter="${id}"]`)?.classList.add("is-disabled");
    renderFilterUnavailable(id, config.unavailableText);
    syncFilterControl(id);
    updateFilterCount();
    return;
  }
  document.getElementById(`${id}-search`)?.removeAttribute("disabled");
  document.querySelector(`[data-clear-filter="${id}"]`)?.removeAttribute("disabled");
  document.querySelector(`[data-filter="${id}"]`)?.classList.remove("is-disabled");
  syncFilterControl(id);
  renderFilterOptions(id);
  updateFilterCount();
}

function renderFilterUnavailable(id, message) {
  const list = document.getElementById(`${id}-options`);
  if (!list) return;
  const item = document.createElement("div");
  item.className = "filter-empty";
  item.textContent = message;
  list.replaceChildren(item);
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

function renderFilterOptions(id) {
  const input = document.getElementById(`${id}-search`);
  const list = document.getElementById(`${id}-options`);
  if (!input || !list) return;
  const values = rankedEntityOptions(state.options.entities?.[id] || [], state.filterQueries[id] || "");
  const totalCount = state.options.entities?.[id]?.length || 0;
  const visibleValues = visibleEntityOptions(id);
  const pending = new Set(pendingValuesForFilter(id));
  list.replaceChildren();
  if (!visibleValues.length) {
    const empty = document.createElement("div");
    empty.className = "filter-empty";
    empty.textContent = "Ничего не найдено";
    list.appendChild(empty);
  } else {
    visibleValues.forEach((item, index) => {
      const label = document.createElement("label");
      label.className = "filter-option";
      label.id = `${id}-option-${index}`;
      label.dataset.value = item.value;
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = pending.has(item.value);
      checkbox.addEventListener("change", () => {
        togglePendingFilterValue(id, item.value, checkbox.checked);
      });
      checkbox.addEventListener("keydown", (event) => handleFilterOptionKeydown(event, id, index));
      const text = document.createElement("span");
      text.textContent = item.label;
      label.append(checkbox, text);
      list.appendChild(label);
    });
    const count = document.createElement("div");
    count.className = "filter-count-note";
    count.textContent = `Показано ${visibleValues.length} из ${totalCount}`;
    list.appendChild(count);
  }
  input.setAttribute("aria-expanded", state.openFilterId === id ? "true" : "false");
  updateFilterPopoverFooter(id);
}

function visibleEntityOptions(id) {
  return rankedEntityOptions(state.options.entities?.[id] || [], state.filterQueries[id] || "")
    .slice(0, maxComboboxOptions);
}

function togglePendingFilterValue(id, value, checked) {
  const next = new Set(pendingValuesForFilter(id));
  if (checked) next.add(value);
  else next.delete(value);
  state.pendingFilters[id] = Array.from(next);
  renderFilterOptions(id);
}

async function applyPendingFilter(id) {
  await applyScopeChange(async () => {
    const previous = selectedValuesForFilter(id);
    const next = pendingValuesForFilter(id);
    state.filters[id] = next;
    if (valuesChanged(previous, next)) {
      resetChildFilters(id);
      applyFilterDrilldown(id);
    }
    closeFilterPopover(id);
    resetDataPagination();
    await refreshRuntimeOptions();
    updatePreviewGrain();
    invalidateLoadedViews();
    await runActiveViewQuery();
  });
}

function handleFilterSearchKeydown(event, id) {
  const list = document.getElementById(`${id}-options`);
  const options = Array.from(list?.querySelectorAll(".filter-option input") || []);
  if (event.key === "Escape") {
    closeFilterPopover(id);
    document.getElementById(`${id}-filter-trigger`)?.focus();
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    openFilterPopover(id);
    options[0]?.focus();
  }
  if (event.key === "Enter") {
    event.preventDefault();
    if (options[0]) {
      options[0].checked = !options[0].checked;
      options[0].dispatchEvent(new Event("change"));
    }
  }
}

function handleFilterOptionKeydown(event, id, index) {
  const options = Array.from(document.querySelectorAll(`#${id}-options .filter-option input`));
  if (!options.length) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    options[Math.min(index + 1, options.length - 1)]?.focus();
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    if (index === 0) document.getElementById(`${id}-search`)?.focus();
    else options[Math.max(index - 1, 0)]?.focus();
  } else if (event.key === "Home") {
    event.preventDefault();
    options[0]?.focus();
  } else if (event.key === "End") {
    event.preventDefault();
    options[options.length - 1]?.focus();
  } else if (event.key === "Enter") {
    event.preventDefault();
    options[index].checked = !options[index].checked;
    options[index].dispatchEvent(new Event("change"));
  } else if (event.key === "Escape") {
    event.preventDefault();
    closeFilterPopover(id);
    document.getElementById(`${id}-filter-trigger`)?.focus();
  }
}

function toggleFilterPopover(id) {
  if (state.openFilterId === id) {
    closeFilterPopover(id);
    return;
  }
  openFilterPopover(id);
}

function openFilterPopover(id) {
  closeAllFilterPopovers();
  state.scopeEditView = viewFromHash() || state.activeView || "overview";
  state.openFilterId = id;
  state.pendingFilters[id] = selectedValuesForFilter(id);
  state.filterQueries[id] = "";
  const input = document.getElementById(`${id}-search`);
  if (input) input.value = "";
  document.getElementById(`${id}-filter-popover`)?.classList.remove("is-hidden");
  document.getElementById(`${id}-filter-trigger`)?.setAttribute("aria-expanded", "true");
  renderFilterOptions(id);
  setTimeout(() => document.getElementById(`${id}-search`)?.focus(), 0);
}

function closeFilterPopover(id) {
  document.getElementById(`${id}-filter-popover`)?.classList.add("is-hidden");
  document.getElementById(`${id}-filter-trigger`)?.setAttribute("aria-expanded", "false");
  document.getElementById(`${id}-search`)?.setAttribute("aria-expanded", "false");
  if (state.openFilterId === id) state.openFilterId = null;
}

function closeAllFilterPopovers() {
  multiFilterIds.forEach(closeFilterPopover);
}

function syncAllFilterControls() {
  multiFilterIds.forEach(syncFilterControl);
}

function syncFilterControl(id) {
  syncHiddenFilterSelect(id);
  updateFilterTriggerSummary(id);
  updateFilterPopoverFooter(id);
}

function syncHiddenFilterSelect(id) {
  const select = document.getElementById(`${id}-filter`);
  if (!select) return;
  const selected = new Set(selectedValuesForFilter(id));
  const options = state.options.entities?.[id] || [];
  select.replaceChildren(...options.map((item) => {
    const node = option(item.value, item.label);
    node.selected = selected.has(item.value);
    return node;
  }));
}

function updateFilterTriggerSummary(id) {
  const summary = document.getElementById(`${id}-filter-summary`);
  const trigger = document.getElementById(`${id}-filter-trigger`);
  if (!summary || !trigger) return;
  const selected = selectedValuesForFilter(id);
  document.querySelector(`[data-inline-clear-filter="${id}"]`)?.classList.toggle("is-hidden", selected.length === 0);
  trigger.classList.toggle("has-selection", selected.length > 0);
  summary.classList.toggle("is-default", selected.length === 0);
  summary.classList.toggle("is-active-value", selected.length > 0);
  if (!selected.length) {
    summary.textContent = filterConfig[id].label;
    trigger.removeAttribute("title");
    return;
  }
  const labels = selected.map((value) => entityDisplayLabel(id, value)).filter(Boolean);
  const text = labels.length === 1 ? labels[0] : `${labels.length} выбрано`;
  summary.textContent = text;
  trigger.title = labels.join(", ");
}

function updateFilterPopoverFooter(id) {
  const selectedCount = pendingValuesForFilter(id).length;
  const footer = document.getElementById(`${id}-selected-count`);
  if (footer) footer.textContent = `Выбрано: ${selectedCount}`;
  const selected = new Set(pendingValuesForFilter(id));
  const visible = visibleEntityOptions(id);
  const selectAll = document.querySelector(`[data-select-all="${id}"]`);
  if (selectAll) {
    const visibleValues = visible.map((item) => item.value);
    selectAll.checked = visibleValues.length > 0 && visibleValues.every((value) => selected.has(value));
    selectAll.indeterminate = visibleValues.some((value) => selected.has(value)) && !selectAll.checked;
  }
}

function clearEntityFilter(id, { resetChildren = true, preserveCurrentGrain = false } = {}) {
  state.filters[id] = [];
  state.pendingFilters[id] = [];
  state.filterQueries[id] = "";
  syncFilterControl(id);
  if (resetChildren) resetChildFilters(id);
  trimDrilldownFrom(id);
  if (!preserveCurrentGrain && state.currentGrain === id) state.currentGrain = nearestDrilldownGrain();
  renderBreadcrumb();
  renderFilterOptions(id);
  syncAllFilterControls();
}

function resetChildFilters(filterId) {
  (filterConfig[filterId]?.childFilters || []).forEach((id) => {
    state.filters[id] = [];
    state.pendingFilters[id] = [];
    state.filterQueries[id] = "";
    closeFilterPopover(id);
    syncFilterControl(id);
    trimDrilldownFrom(id);
  });
}

function resetAllEntityFilters() {
  Object.keys(filterConfig).forEach((id) => {
    state.filters[id] = [];
    state.pendingFilters[id] = [];
    state.filterQueries[id] = "";
    closeFilterPopover(id);
    syncFilterControl(id);
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
  if (!document.getElementById(`${targetGrain}-filter`)) return;
  state.filters[targetGrain] = [entityId];
  state.pendingFilters[targetGrain] = [entityId];
  syncFilterControl(targetGrain);
  state.currentGrain = targetGrain;
  setExplicitDrilldown(targetGrain, entityId);
  resetChildFilters(targetGrain);
  renderBreadcrumb();
  updatePreviewGrain();
  await refreshRuntimeOptions();
  invalidateLoadedViews();
  await runActiveViewQuery();
}

async function selectPortfolioEntity(grain, entityId) {
  if (!entityId || !document.getElementById(`${grain}-filter`)) return;
  await applyScopeChange(async () => {
    state.filters[grain] = [entityId];
    state.pendingFilters[grain] = [entityId];
    syncFilterControl(grain);
    resetChildFilters(grain);
    state.currentGrain = grain;
    setExplicitDrilldown(grain, entityId);
    if (grain === "category") state.portfolioEntityLevel = "manufacturer";
    renderBreadcrumb();
    updatePreviewGrain();
    updateFilterCount();
    await refreshRuntimeOptions();
    invalidateLoadedViews();
    await runActiveViewQuery();
  });
}

async function selectStore(entityId) {
  if (!document.getElementById("store-filter")) return;
  state.filters.store = [entityId];
  state.pendingFilters.store = [entityId];
  syncFilterControl("store");
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
  if (state.periodMode === "AVAILABLE_MONTH_SET") return document.getElementById("period-available-end")?.value || "";
  return document.getElementById("period-a")?.value || "";
}

function selectedDateTo() {
  if (state.periodMode === "DATE_RANGE") return document.getElementById("date-to")?.value || "";
  if (state.periodMode === "SINGLE_PERIOD") return document.getElementById("period-single")?.value || "";
  if (state.periodMode === "AVAILABLE_MONTH_SET") return document.getElementById("period-available-end")?.value || "";
  return document.getElementById("period-a")?.value || "";
}

function selectedComparisonMode() {
  if (state.periodMode === "COMPARE") return state.comparisonMode;
  if (state.periodMode === "AVAILABLE_MONTH_SET") return "YOY";
  return "NONE";
}

function queryDateFrom() {
  if (state.periodMode !== "AVAILABLE_MONTH_SET") return selectedDateFrom();
  const end = selectedDateTo();
  if (!end) return "";
  return `${new Date(`${end}T00:00:00`).getFullYear()}-01-01`;
}

function queryDateTo() {
  return selectedDateTo();
}

function isComparisonDisplayMode() {
  return state.periodMode === "COMPARE" || state.periodMode === "AVAILABLE_MONTH_SET";
}

function selectedValuesForFilter(id) {
  return Array.isArray(state.filters[id]) ? [...state.filters[id]] : [];
}

function pendingValuesForFilter(id) {
  return Array.isArray(state.pendingFilters[id]) ? [...state.pendingFilters[id]] : selectedValuesForFilter(id);
}

function valuesChanged(left, right) {
  if (left.length !== right.length) return true;
  const leftValues = new Set(left);
  return right.some((value) => !leftValues.has(value));
}

function selectedFilterValues() {
  return Object.fromEntries(
    Object.keys(filterConfig)
      .map((id) => [id, selectedValuesForFilter(id).filter(Boolean)])
      .filter(([, values]) => values.length)
  );
}

function nearestDrilldownGrain() {
  const active = state.drilldownPath
    .filter((item) => selectedValuesForFilter(item.grain).includes(item.value))
    .map((item) => item.grain);
  return active[active.length - 1] || "network";
}

function selectedParentFiltersForGrain(grain) {
  const selected = selectedFilterValues();
  return Object.fromEntries(
    Object.entries(selected)
      .filter(([key]) => key !== grain)
      .filter(([, values]) => values.length)
  );
}

function setExplicitDrilldown(grain, value) {
  const index = drilldownOrder.indexOf(grain);
  state.drilldownPath = state.drilldownPath
    .filter((item) => drilldownOrder.indexOf(item.grain) < index)
    .filter((item) => selectedValuesForFilter(item.grain).includes(item.value));
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

function salesDriverSummaryGrain() {
  const selected = selectedFilterValues();
  const focalOrder = ["sku", "brand", "manufacturer", "category"];
  const focalGrain = focalOrder.find((grain) => selected[grain]?.length === 1);
  return focalGrain || state.currentGrain;
}

function entityIdsForSalesDriverSummary(grain = salesDriverSummaryGrain()) {
  if (grain === "network") return firstEntityIds("network", 1);
  const selected = selectedValuesForFilter(grain);
  if (selected.length === 1) return selected;
  if (grain === state.currentGrain) return entityIdsForSummary();
  return firstEntityIds(grain, 1);
}

function salesDriverDetailGrain() {
  return previewByGrain[salesDriverSummaryGrain()] || "store";
}

function entityIdsForSummary() {
  if (state.currentGrain === "network") return firstEntityIds("network", 1);
  const selected = selectedValuesForFilter(state.currentGrain);
  if (selected.length) return selected;
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
  const selected = selectedStoreIds();
  if (selected.length) return selected;
  return firstEntityIds("store", state.tablePageSize);
}

function selectedStoreIds() {
  return selectedValuesForFilter("store");
}

function selectedStoreId() {
  return selectedStoreIds()[0] || "";
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

function salesDriverMetricEntry(concept, grain = salesDriverSummaryGrain()) {
  return metricEntryForGrain(concept, grain);
}

function salesDriverDisplayEntry(concept) {
  return salesDriverMetricEntry(concept) || catalogEntry(concept);
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

function metricPresentation(concept) {
  return catalogEntry(concept) || portfolioPresentationFallback[concept] || {};
}

function deltaSemanticsFor(concept) {
  const declared = metricPresentation(concept)?.delta_semantics;
  if (declared) return declared;
  if (rankDirectionalMetrics.has(concept)) return "RANK_DIRECTIONAL";
  if (outcomeDirectionalMetrics.has(concept)) return "OUTCOME_DIRECTIONAL";
  if (neutralDirectionalMetrics.has(concept)) return "NEUTRAL_DIRECTIONAL";
  return "NEUTRAL_DIRECTIONAL";
}

function deltaSemanticClass(concept, value) {
  if (value === null || value === undefined || Number.isNaN(value) || Number(value) === 0) return "delta-neutral";
  const semantics = deltaSemanticsFor(concept);
  const sign = Number(value) > 0 ? "up" : "down";
  if (semantics === "RANK_DIRECTIONAL") return sign === "up" ? "delta-rank-declined" : "delta-rank-improved";
  if (semantics === "OUTCOME_DIRECTIONAL") return sign === "up" ? "delta-outcome-up" : "delta-outcome-down";
  return sign === "up" ? "delta-neutral-up" : "delta-neutral-down";
}

function deltaSemanticsText(concept) {
  const semantics = deltaSemanticsFor(concept);
  if (semantics === "RANK_DIRECTIONAL") return "Для места в рейтинге меньшее значение означает движение вверх в позиции.";
  if (semantics === "OUTCOME_DIRECTIONAL") return "Цвет показывает направление изменения показателя, а не оценку хорошо/плохо.";
  return "Изменение показано нейтрально: рост или снижение не оценивается как хорошо/плохо без бизнес-контекста.";
}

function metricInspectorDefinition(concept) {
  const entry = metricPresentation(concept);
  return {
    business_alias: entry.display_alias || null,
    business_meaning: entry.business_meaning || entry.description || "н/д",
    business_question: entry.business_question || "н/д",
    decision_use: entry.decision_use || "н/д",
    formula_summary: entry.formula_summary || "н/д",
    unit_label: entry.unit_label || unitLabel(entry.format)
  };
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
  if (isComparisonDisplayMode() && item.current_value !== null && item.current_value !== undefined) {
    pieces.push(`${formatValue(item.current_value, format)} сейчас`);
  }
  if (isComparisonDisplayMode() && item.reference_value !== null && item.reference_value !== undefined) {
    pieces.push(`${formatValue(item.reference_value, format)} сравнение`);
  }
  if (isComparisonDisplayMode() && item.delta !== null && item.delta !== undefined) {
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
      .map((key) => [key, selected[key]])
  );
}

function selectedPortfolioExecutionFilters(grain) {
  const selected = selectedFilterValuesForPortfolio();
  const executionFilters = Object.create(null);
  if (selected.category?.length) executionFilters.category = selected.category;
  if (selected.store?.length) executionFilters.store = selected.store;
  const focalGrains = ["manufacturer", "brand", "sku"];
  focalGrains.forEach((candidate) => {
    if (candidate !== grain && selected[candidate]?.length) executionFilters[candidate] = selected[candidate];
  });
  return executionFilters;
}

function selectedCategoryCount() {
  return selectedFilterValues().category?.length || 0;
}

function hasSingleCategoryScope() {
  return selectedCategoryCount() === 1;
}

function portfolioAnalysisGrain() {
  if (!hasSingleCategoryScope()) return "category";
  if (["manufacturer", "brand", "sku"].includes(state.portfolioEntityLevel)) return state.portfolioEntityLevel;
  return "manufacturer";
}

function portfolioBasisConcept(prefix) {
  const suffix = {
    revenue: "revenue",
    units: "units",
    retailer_margin_abs: "margin_abs"
  }[state.portfolioBasis] || "revenue";
  if (prefix === "share") {
    return {
      revenue: "entity_revenue_share",
      units: "entity_units_share",
      retailer_margin_abs: "entity_margin_share"
    }[state.portfolioBasis] || "entity_revenue_share";
  }
  if (prefix === "cumulative") {
    return {
      revenue: "entity_cumulative_revenue_share",
      units: "entity_cumulative_units_share",
      retailer_margin_abs: "entity_cumulative_margin_share"
    }[state.portfolioBasis] || "entity_cumulative_revenue_share";
  }
  return `${portfolioAnalysisGrain()}_${prefix}_${suffix}`;
}

function syncPortfolioControls() {
  const entityLevel = document.getElementById("portfolio-entity-level");
  const basis = document.getElementById("portfolio-basis");
  if (entityLevel) {
    const effectiveGrain = portfolioAnalysisGrain();
    Array.from(entityLevel.options).forEach((item) => {
      item.disabled = item.value !== "category" && !hasSingleCategoryScope();
    });
    entityLevel.value = effectiveGrain;
    entityLevel.disabled = !hasSingleCategoryScope();
    entityLevel.title = hasSingleCategoryScope()
      ? "Выберите уровень объектов внутри категории"
      : "Выберите одну категорию, чтобы перейти к производителям, брендам или SKU";
  }
  if (basis) {
    basis.value = state.portfolioBasis;
  }
}

function privateLabelDisplayName() {
  return selectedRetailer().private_label_display_name || "выбранный ассортимент";
}

function portfolioContextText() {
  if (state.periodMode === "COMPARE") return "Показывает вклад, место и движение позиции; ABC остаётся текущей классификацией там, где она поддержана.";
  if (state.periodMode === "DATE_RANGE") return "Диапазон используется только для тех портфельных показателей, где маршрут явно поддерживает такой режим.";
  return "Показывает вклад, место, накопленную долю и ABC там, где это поддержано выбранным срезом.";
}

function portfolioShareUnavailableText() {
  if (!hasSingleCategoryScope()) {
    return "Нет строк категорий для текущего рынка; проверьте период или фильтры.";
  }
  return "Для выбранного среза долевые показатели не рассчитаны.";
}

function portfolioRankUnavailableText(item) {
  if (!hasSingleCategoryScope() && portfolioAnalysisGrain() !== "category") {
    return "Выберите одну категорию, чтобы открыть рейтинг производителей, брендов или SKU.";
  }
  if (item?.limitations?.length) return portfolioLimitationText(item.limitations[0]);
  return "Портфельная аналитика недоступна для выбранного среза.";
}

function portfolioAssortmentUnavailableText(item) {
  if (state.periodMode === "DATE_RANGE") return "Активные SKU показываются по отдельному периоду, не как скаляр за диапазон.";
  if (item?.limitations?.length) return portfolioLimitationText(item.limitations[0]);
  return "Ассортиментный показатель недоступен для выбранного среза.";
}

function portfolioBrandUnavailableText(item) {
  if (state.periodMode !== "COMPARE") return "Сравнение бренда с категорией доступно в режиме сравнения.";
  if (state.currentGrain !== "brand" && !selectedFilterValues().brand?.length) return "Выберите бренд внутри категории, чтобы увидеть сравнение с категорией.";
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
    share_entity_grain_unsupported: "Доля поддержана для категорий, производителей, брендов и SKU.",
    share_range_semantics_unsupported: "Доля не усредняется по месяцам; выберите один период или поддержанное сравнение.",
    cumulative_share_comparison_semantics_unsupported: "Накопленная доля показывается для текущего периода без сравнения строк между периодами.",
    manufacturer_share_requires_category_scope: "Доля производителя рассчитывается внутри одной категории.",
    brand_share_requires_category_scope: "Доля бренда рассчитывается внутри одной категории.",
    sku_share_requires_category_scope: "Доля SKU рассчитывается внутри одной категории.",
    rank_scope_filter_unsupported: "Рейтинг не поддержан для выбранного фильтра ТТ или территории.",
    share_scope_filter_unsupported: "Доля не поддержана для выбранного фильтра ТТ или территории.",
    abc_scope_filter_unsupported: "ABC не поддержана для выбранного фильтра ТТ или территории.",
    rank_range_semantics_unsupported: "Рейтинг не показывается как агрегат за произвольный диапазон.",
    manufacturer_rank_requires_category_scope: "Место производителя рассчитывается только внутри категории.",
    brand_rank_requires_category_scope: "Место бренда рассчитывается только внутри категории.",
    sku_rank_requires_category_scope: "Место SKU рассчитывается только внутри категории.",
    manufacturer_population_requires_category_scope: "Размер рейтинга доступен только внутри категории.",
    abc_range_semantics_unsupported: "ABC не рассчитывается для произвольного диапазона.",
    abc_comparison_semantics_unsupported: "ABC показывается как классификация текущего периода, не как сравнение классов.",
    abc_ownership_universe_required: "ABC доступна для отдельной вселенной: Без СТМ или Только СТМ.",
    abc_requires_single_category_scope: "ABC рассчитывается только внутри одной категории.",
    no_abc_rows_after_focal_selection: "Для выбранного объекта нет строки ABC в текущей вселенной.",
    active_sku_scalar_not_defined_for_range: "Активные SKU показываются по отдельному периоду.",
    active_sku_requires_current_period: "Выберите период для расчёта активных SKU.",
    brand_vs_category_requires_compare_mode: "Сравнение бренда с категорией доступно только в режиме сравнения.",
    brand_vs_category_requires_category_and_brand: "Нужны выбранные категория и бренд.",
    portfolio_requires_single_category: "Выберите одну категорию, чтобы показатель имел однозначную базу сравнения.",
    brand_vs_category_requires_single_brand: "Выберите один бренд, чтобы сравнение с категорией было однозначным.",
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
  if (isComparisonDisplayMode() && comparison) {
    const deltaFormat = entry.format === "percent" ? "percentage_points" : entry.format;
    return `${formatValue(result.value, entry.format)} (${formatDeltaValue(comparison.delta, deltaFormat)})`;
  }
  if (result.limitations?.includes("range_aggregation_period_only")) return "только по периодам";
  return formatValue(result.value, entry.format);
}

function resultForProvenance(concept) {
  if (state.activeView === "stores") {
    if (state.storesGroupMode !== "store") {
      const entityId = geographyEntityIds()[0];
      return geographyResultFor(concept, entityId) || state.storesGeographyResponse?.metric_results[0];
    }
    const storeId = selectedStoreId() || storeEntityIds()[0];
    return storeResultFor(concept, storeId) || state.storesResponse?.metric_results[0];
  }
  if (state.activeView === "sales_drivers") {
    return salesDriverResultFor(concept) || state.salesDriversResponse?.metric_results[0] || state.salesDriversTableResponse?.metric_results[0];
  }
  return summaryResultFor(concept) || state.summaryResponse?.metric_results[0] || state.tableResponse?.metric_results[0];
}

function contributionResultFromRow(row, value = row.contribution_share) {
  return {
    metric_concept: state.contributionResponse?.metric_concept || "contribution_to_delta",
    value,
    provenance: row.provenance,
    lineage: {
      metric_definition_id: row.metric_definition_id
    }
  };
}

function portfolioResultForInspector(item) {
  return {
    metric_concept: item.concept_id,
    value: item.value,
    provenance: item.provenance
  };
}

function portfolioRowResultForInspector(item, row) {
  return {
    metric_concept: item?.concept_id,
    entity_id: row?.entity_id,
    value: row?.abc_class ?? row?.share ?? row?.rank ?? row?.metric_value,
    provenance: row?.provenance || item?.provenance
  };
}

function portfolioRowProvenanceSections(item, row, model) {
  const concept = item?.concept_id || row?.basis_metric_id || "revenue";
  const definition = metricInspectorDefinition(concept);
  const provenance = item?.provenance || {};
  const scope = provenance.current_analytical_scope || {};
  const projection = provenance.projection || {};
  const inputFacts = provenance.input_metric_facts || {};
  const run = provenance.run_lineage || {};
  const source = provenance.source_evidence || {};
  const quality = provenance.quality || {};
  return [
    section("Что это за показатель", [
      ["Показатель", displayLabel(concept)],
      ["Объект", [grainLabels[row?.entity_type] || row?.entity_type, entityDisplayLabel(row?.entity_type, row?.entity_id) || row?.entity_id].filter(Boolean).join(" / ") || "н/д"],
      ["Значение", formatPortfolioRowValue(concept, row)],
      ["Смысл", definition.business_meaning],
      ["Единица", definition.unit_label],
      ["Для решения", definition.decision_use]
    ]),
    section("Срез", [
      ["Сеть / источник", [selectedRetailer().display_label, selectedRetailer().source_label].filter(Boolean).join(" / ") || "н/д"],
      ["Категория", row?.category_scope || row?.category || projection.population_scope?.category || "н/д"],
      ["Вселенная", row?.universe_type || projection.population_scope?.universe_type || "н/д"],
      ["Учёт ассортимента", ownershipLabel(row) || privateLabelScopeText(row?.private_label_scope || scope.private_label_scope)]
    ]),
    section("Расчёт", [
      ["Формула", definition.formula_summary],
      ["Базовый показатель", displayLabel(row?.basis_metric_id || projection.population_scope?.share_basis_metric)],
      ["Значение объекта", formatValue(row?.metric_value, catalogEntry(row?.basis_metric_id)?.format || "decimal")],
      ["Значение вселенной", formatValue(row?.universe_metric_value, catalogEntry(row?.basis_metric_id)?.format || "decimal")],
      ["Доля", formatValue(row?.share, "percent")],
      ["Накопленная доля", formatValue(model?.cumulativeRow?.cumulative_share ?? row?.cumulative_share, "percent")],
      ["Место", row?.rank ? `№${row.rank}` : "н/д"],
      ["ABC", row?.abc_class || model?.abcRow?.abc_class || "н/д"]
    ]),
    section("Правила отображения", [
      ["Семантика изменения", deltaSemanticsText(concept)],
      ["Ранг", "меньшее место лучше; движение показывается отдельным маркером"],
      ["ABC", "класс вклада, не оценка качества и не рекомендация"],
      ["Портфель", ownershipLabel(row) || "общая аналитическая вселенная"]
    ]),
    section("Покрытие данных", [
      ["Доступные периоды", compactList((projection.evaluated_periods || []).map(formatPeriod))],
      ["Доказательство по источнику", source.status || "н/д"],
      ["Статусы", compactList(quality.quality_statuses)]
    ]),
    section("Технические детали", [
      ["Концепт", concept],
      ["Определения показателей", compactList(inputFacts.metric_definition_ids)],
      ["Запуск анализа", compactList(run.analysis_run_ids)],
      ["Версия аналитической витрины", run.mart_build_id || "н/д"],
      ["Ревизия источника", compactList(run.source_revision_ids)]
    ])
  ];
}

function formatPortfolioRowValue(concept, row) {
  if (concept?.includes("_abc_")) return row?.abc_class || "н/д";
  if (concept?.includes("_rank_")) return row?.rank ? `№${row.rank}` : "н/д";
  if (concept?.includes("_share")) return formatValue(row?.share, "percent");
  return formatValue(row?.metric_value, catalogEntry(row?.basis_metric_id || concept)?.format || "decimal");
}

function comparisonMarkerPeriods() {
  if (state.periodMode !== "COMPARE") return [];
  const comparison = state.summaryResponse?.comparisons?.[0];
  return [selectedDateFrom(), comparison?.comparison_period_start].filter(Boolean);
}

function kpiContextText(comparison, entry) {
  if (isComparisonDisplayMode() && comparison) {
    const deltaFormat = entry.format === "percent" ? "percentage_points" : entry.format;
    return `${formatDeltaValue(comparison.delta, deltaFormat)} · ${formatValue(comparison.pct_delta, "percent")}`;
  }
  if (state.periodMode === "DATE_RANGE") return "За доступные периоды диапазона";
  if (state.periodMode === "AVAILABLE_MONTH_SET") return "Среднее за сопоставимые месяцы";
  return "За выбранный период";
}

function compactMetricText(result, entry) {
  if (!result || !entry) return "Недоступно";
  const comparison = comparisonFor(state.summaryResponse, result);
  if (isComparisonDisplayMode() && comparison) {
    const deltaFormat = entry.format === "percent" ? "percentage_points" : entry.format;
    return `${formatValue(result.value, entry.format)} · ${formatDeltaValue(comparison.delta, deltaFormat)}`;
  }
  if (result.limitations?.includes("range_aggregation_period_only")) return "только по периодам";
  return formatValue(result.value, entry.format);
}

function movementText(result, entry) {
  if (!result || !entry) return "Показатель недоступен для выбранного среза.";
  if (state.periodMode === "DATE_RANGE") return "Показано за доступные периоды диапазона.";
  if (state.periodMode === "AVAILABLE_MONTH_SET") return "Сравнение по сопоставимым доступным месяцам.";
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
  if (result.limitations.includes("range_aggregation_period_only")) return periodOnlyLimitationText();
  return "Есть ограничения для выбранного среза.";
}

function periodOnlyLimitationText() {
  if (state.periodMode === "AVAILABLE_MONTH_SET") {
    return "Для этого показателя сравнение по сопоставимым месяцам пока не поддерживается.";
  }
  return "Показатель доступен только по отдельным периодам.";
}

function periodContextText() {
  if (state.periodMode === "DATE_RANGE") {
    return `${formatPeriod(selectedDateFrom())} — ${formatPeriod(selectedDateTo())}`;
  }
  if (state.periodMode === "SINGLE_PERIOD") return formatPeriod(selectedDateFrom());
  if (state.periodMode === "AVAILABLE_MONTH_SET") {
    return `Среднее за сопоставимые месяцы · ${availableMonthSummaryText(state.summaryResponse)}`;
  }
  const comparison = state.summaryResponse?.comparisons?.[0];
  const ref = comparison?.comparison_period_start ? formatPeriod(comparison.comparison_period_start) : "нет периода";
  return `${formatPeriod(selectedDateFrom())} vs ${ref} · ${comparisonLabels[state.comparisonMode]}`;
}

function contextFilterText() {
  const selected = selectedFilterValues();
  const parts = Object.entries(selected).map(([key, values]) => {
    const labels = values.map((value) => entityDisplayLabel(key, value)).filter(Boolean);
    return labels.length === 1 ? `${grainLabels[key]}: ${labels[0]}` : `${grainLabels[key]}: ${labels.length} выбрано`;
  });
  return parts.length ? parts.join(" · ") : "";
}

function contextSummaryText(response) {
  const selected = selectedFilterValues();
  const count = Object.values(selected).reduce((total, values) => total + values.length, 0);
  const filterText = count ? `${count} ${pluralRu(count, "фильтр", "фильтра", "фильтров")}` : "Без доп. фильтров";
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
  const count = Object.values(selectedFilterValues()).reduce((total, values) => total + values.length, 0);
  const target = document.getElementById("filter-count");
  if (target) target.textContent = count ? `${count} выбрано` : "не выбраны";
  document.getElementById("reset-filters")?.classList.toggle("is-hidden", count === 0);
  Object.keys(filterConfig).forEach((id) => {
    const hasValue = selectedValuesForFilter(id).length > 0;
    document.querySelector(`[data-clear-filter="${id}"]`)?.classList.toggle("is-hidden", !hasValue);
    syncFilterControl(id);
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
  if (state.periodMode === "AVAILABLE_MONTH_SET") return "Поддержанные показатели пересчитаны backend по сопоставимым доступным месяцам; периодические показатели ограничены.";
  if (state.periodMode === "DATE_RANGE") return "Диапазон используется для динамики; периодические показатели не показываются как агрегат.";
  return "Текущее состояние показателей и историческая динамика.";
}

function salesDriverMatrixCaption() {
  const unavailable = salesDriverRows().filter(({ result }) => result?.limitations?.includes("range_aggregation_period_only")).length;
  if ((state.periodMode === "DATE_RANGE" || state.periodMode === "AVAILABLE_MONTH_SET") && unavailable) {
    return `${unavailable} ${pluralRu(unavailable, "показатель доступен", "показателя доступны", "показателей доступны")} только по отдельным периодам.`;
  }
  return "Строка матрицы переключает динамику выбранного показателя.";
}

function contributionFallbackReason() {
  const status = state.contributionResponse?.status;
  if (state.periodMode !== "COMPARE") return "Вклад в изменение доступен только в режиме сравнения.";
  if (hasNonDrilldownFilters()) return "Вклад в изменение не рассчитывается для дополнительного фильтра; показаны объекты выбранного среза.";
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
  document.getElementById("private-label-label").textContent = "СТМ";
  const labels = {
    INCLUDE: "Весь ассортимент",
    EXCLUDE: `Без ${scopeName}`,
    ONLY: `Только ${scopeName}`
  };
  Array.from(select?.options || []).forEach((optionNode) => {
    optionNode.textContent = labels[optionNode.value] || optionNode.textContent;
  });
  select?.classList.toggle("is-default", select.value === "INCLUDE");
  select?.classList.toggle("is-active-value", select.value !== "INCLUDE");
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
  openMetricInspector({ concept, result, mode: "value" });
}

function openSalesDriverProvenance() {
  openProvenance(state.salesDriverMetric);
}

function openContributionProvenance(row) {
  openMetricInspector({
    concept: "contribution_to_delta",
    result: contributionResultFromRow(row),
    mode: "comparison",
    sections: contributionProvenanceSections(row.provenance || {}, row)
  });
}

function openPortfolioProvenance(item) {
  openMetricInspector({
    concept: item.concept_id,
    result: portfolioResultForInspector(item),
    mode: item.delta !== null && item.delta !== undefined ? "comparison" : "value",
    sections: portfolioProvenanceSections(item.provenance || {}, item)
  });
}

function openSignalEvidence(row) {
  openMetricInspector({
    concept: row.metric_concept || "signal",
    result: null,
    mode: "evidence",
    title: "Проверка сигнала",
    sections: signalEvidenceSections(row.provenance || {}, row)
  });
}

function openMetricInspector({ concept, result = null, response = null, mode = "value", title = null, sections = null }) {
  const content = document.getElementById("provenance-content");
  const heading = document.getElementById("metric-inspector-title");
  state.activeProvenanceConcept = concept || state.activeProvenanceConcept;
  if (heading) heading.textContent = title || "Проверка показателя";
  content.replaceChildren();
  const resolvedSections = sections || metricInspectorSections(concept, result, response, mode);
  resolvedSections.forEach((sectionNode) => content.appendChild(sectionNode));
  const drawer = document.getElementById("provenance-drawer");
  drawer.classList.add("is-open");
  drawer.setAttribute("aria-hidden", "false");
  document.getElementById("scrim").classList.add("is-open");
  document.getElementById("close-drawer")?.focus({ preventScroll: true });
}

function metricInspectorSections(concept, result, response, mode) {
  if (result?.provenance) {
    return provenanceSections(result.provenance, result, { mode, response });
  }
  const definition = metricInspectorDefinition(concept);
  return [
    section("Что это за показатель", [
      ["\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u0435\u043b\u044c", displayLabel(concept)],
      ...(definition.business_alias ? [["Бизнес-название", definition.business_alias]] : []),
      ["Смысл", definition.business_meaning],
      ["Единица", definition.unit_label],
      ["\u0411\u0438\u0437\u043d\u0435\u0441-\u0432\u043e\u043f\u0440\u043e\u0441", definition.business_question],
      ["\u0414\u043b\u044f \u0440\u0435\u0448\u0435\u043d\u0438\u044f", definition.decision_use]
    ]),
    section("Расчёт", [
      ["Формула", definition.formula_summary],
      ["Семантика изменения", deltaSemanticsText(concept)]
    ]),
    section("Качество", [
      ["Статус", "Происхождение из витрины недоступно для этого значения."]
    ])
  ];
}

function closeMetricInspector() {
  closeProvenance();
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
      ["Изменение объекта", formatDeltaValue(calculation.child_delta, deltaFormatFor(catalogEntry(metric.metric_concept)?.format || "decimal"))],
      ["Изменение родителя", formatDeltaValue(calculation.parent_delta, deltaFormatFor(catalogEntry(metric.metric_concept)?.format || "decimal"))],
      ["Формула", calculation.formula || "н/д"],
      ["Семантика изменения", deltaSemanticsText("contribution_to_delta")]
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

function provenanceSections(provenance, result, options = {}) {
  const scope = provenance.current_analytical_scope || {};
  const metric = provenance.metric || {};
  const value = provenance.value || {};
  const comparison = provenance.comparison || {};
  const rule = provenance.business_rule || {};
  const run = provenance.run_lineage || {};
  const source = provenance.source_evidence || {};
  const quality = provenance.quality || {};
  const concept = metric.metric_concept || result.metric_concept;
  const definition = metricInspectorDefinition(concept);
  const periodSet = scope.period_set || {};
  const comparisonSet = comparison.period_set || {};
  const sections = [
    section("Что это за показатель", [
      ["\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u0435\u043b\u044c", displayLabel(concept)],
      ...(definition.business_alias ? [["Бизнес-название", definition.business_alias]] : []),
      ["\u0417\u043d\u0430\u0447\u0435\u043d\u0438\u0435", formatValue(value.value ?? result.value, metricPresentation(concept)?.format || "decimal")],
      ["Смысл", definition.business_meaning],
      ["Единица", definition.unit_label],
      ["\u0411\u0438\u0437\u043d\u0435\u0441-\u0432\u043e\u043f\u0440\u043e\u0441", definition.business_question],
      ["\u0414\u043b\u044f \u0440\u0435\u0448\u0435\u043d\u0438\u044f", definition.decision_use]
    ]),
    section("Срез", [
      ["Сеть / источник", [selectedRetailer().display_label, selectedRetailer().source_label].filter(Boolean).join(" / ") || "н/д"],
      ["Периоды", compactList((scope.requested_periods || []).map(formatPeriod))],
      ...(periodSet.scope_type ? [["Режим периода", "Среднее за сопоставимые месяцы"]] : []),
      ...(periodSet.included_periods?.length ? [["Включённые месяцы", formatPeriodList(periodSet.included_periods)]] : []),
      ["Объект", [grainLabels[scope.grain_id] || scope.grain_id, entityDisplayLabel(scope.grain_id, scope.entity_id)].filter(Boolean).join(" / ") || "н/д"],
      ["Учёт ассортимента", privateLabelScopeText(scope.private_label_scope)]
    ]),
    section("Расчёт", [
      ["Числитель", value.numerator_value ?? "н/д"],
      ["Знаменатель", value.denominator_value ?? "н/д"],
      ["Формула", definition.formula_summary],
      ["Стратегия диапазона", rangeStrategyLabel(value.range_aggregation_strategy)],
      ...(value.available_month_aggregation_method ? [["Метод сопоставимых месяцев", availableMonthAggregationLabel(value.available_month_aggregation_method)]] : [])
    ]),
    section("Сравнение", [
      ["Тип", comparisonLabels[comparison.comparison_mode] || comparison.comparison_mode || "н/д"],
      ["Периоды", compactList((comparison.periods || []).map((item) => `${item.current_period_start} vs ${item.comparison_period_start}`))],
      ...(comparisonSet.current_included_periods?.length ? [["Текущие месяцы", formatPeriodList(comparisonSet.current_included_periods)]] : []),
      ...(comparisonSet.comparison_included_periods?.length ? [["Месяцы сравнения", formatPeriodList(comparisonSet.comparison_included_periods)]] : []),
      ...(comparisonSet.comparison_policy ? [["Политика сопоставления", comparisonSet.comparison_policy]] : []),
      ["Качество", compactList(comparison.quality_statuses)],
      ["Семантика изменения", deltaSemanticsText(concept)],
      ["Режим проверки", options.mode === "comparison" ? "изменение показателя" : "значение показателя"]
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
      if (cell && typeof cell === "object" && cell.role) {
        td.className = `metric-table-cell metric-table-cell--${cell.role}`;
      }
      if (index === 0 && options.onFirstCellClick) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "table-link";
        button.textContent = cellText(cell);
        button.addEventListener("click", () => options.onFirstCellClick(cell, row.meta));
        td.appendChild(button);
      } else if (cell && typeof cell === "object" && cell.inspectable) {
        td.appendChild(metricComparisonCell({
          concept: cell.concept,
          label: cell.role === "delta" ? "Δ" : "",
          text: cell.text,
          result: cell.result,
          response: cell.response,
          role: cell.role || (cell.deltaValue === null || cell.deltaValue === undefined ? "current" : "delta"),
          deltaValue: cell.deltaValue
        }));
      } else {
        td.textContent = cellText(cell);
        if (td.textContent.includes("Недоступно") || td.textContent.includes("только")) {
          td.classList.add("limitation-state-cell");
        }
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
  td.className = "empty-state table-message-cell";
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
    return cellText(left.cells[index]).localeCompare(cellText(right.cells[index]), "ru-RU", { numeric: true }) * direction;
  });
}

function cellText(cell) {
  if (cell && typeof cell === "object") return String(cell.text ?? "");
  return String(cell ?? "");
}

function formatValue(value, format) {
  if (value === null || value === undefined || Number.isNaN(value)) return "н/д";
  if (format === "text" || format === "abc_class") return String(value);
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

function deltaFormatFor(format) {
  return format === "percent" ? "percentage_points" : format;
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

function formatPeriodList(periods) {
  if (!periods?.length) return "";
  return periods.map(formatPeriod).join(", ");
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

function availableMonthAggregationLabel(method) {
  return {
    ARITHMETIC_MEAN_OF_MONTHLY_TOTALS: "средний доступный месяц по месячным итогам",
    RECOMPUTE_FROM_AVAILABLE_MONTH_COMPONENTS: "пересчёт из компонентов за включённые месяцы",
    POINT_IN_TIME_ONLY_UNSUPPORTED_FOR_AVAILABLE_MONTH_SET: "не поддерживается для сопоставимых месяцев",
    UNSUPPORTED: "не поддерживается"
  }[method] || method || "н/д";
}

function unitLabel(format) {
  return {
    currency: "руб.",
    percent: "%",
    decimal: "значение",
    integer: "кол-во",
    ratio: "\u0437\u043d\u0430\u0447\u0435\u043d\u0438\u0435"
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
