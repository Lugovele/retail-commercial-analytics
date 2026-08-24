const state = {
  runtime: null,
  catalog: [],
  response: null,
  periodMode: "SINGLE_PERIOD",
  comparisonMode: "YOY",
  activeTab: "metrics",
  metricGroup: "sales",
  chartMetric: "revenue",
  columnGroup: "sales",
  grain: "network",
  sortColumn: "value",
  sortDirection: "desc"
};

const metricGroups = {
  sales: ["revenue_vat", "revenue", "units", "selling_store_count", "sku_count"],
  economics: ["retailer_margin_abs", "retailer_margin_pct", "weighted_shelf_price_vat", "weighted_input_price_vat"],
  presence: ["selling_store_count", "active_store_count", "distribution", "velocity"],
  structure: ["category_revenue_share", "sku_count"]
};

const columnGroups = {
  sales: ["revenue_vat", "revenue", "units"],
  economics: ["retailer_margin_abs", "retailer_margin_pct"],
  presence: ["selling_store_count", "active_store_count", "distribution", "velocity"],
  price: ["weighted_shelf_price_vat", "weighted_input_price_vat"],
  share: ["category_revenue_share"],
  ratings: [],
  competitors: []
};

const comparisonLabels = {
  YOY: "Год к году",
  MOM: "Месяц к месяцу",
  PREVIOUS_AVAILABLE: "Предыдущий доступный период",
  NONE: "Без сравнения"
};

const syntheticPeriods = [
  "2025-03-01",
  "2025-04-01",
  "2025-06-01",
  "2025-09-01",
  "2025-12-01",
  "2026-03-01",
  "2026-04-01",
  "2026-06-01"
];

const filters = {
  category: ["Все категории", "CATEGORY_STANDARD"],
  manufacturer: ["Все производители", "MANUFACTURER_A"],
  brand: ["Все бренды", "BRAND_A"],
  sku: ["Все SKU", "SKU_A_001"],
  store: ["Все ТТ", "STORE_A_001"]
};

document.addEventListener("DOMContentLoaded", async () => {
  bindStaticControls();
  await loadRuntime();
  await loadCatalog();
  setupControls();
  await runQuery();
  switchTab("metrics");
});

function bindStaticControls() {
  document.querySelectorAll("[data-period-mode]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.periodMode = button.dataset.periodMode;
      document.querySelectorAll("[data-period-mode]").forEach((item) => item.classList.toggle("is-active", item === button));
      document.getElementById("compare-fields").classList.toggle("is-hidden", state.periodMode !== "SINGLE_PERIOD");
      document.getElementById("range-fields").classList.toggle("is-hidden", state.periodMode === "SINGLE_PERIOD");
      await runQuery();
    });
  });

  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });

  document.querySelectorAll("[data-metric-group]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.metricGroup = button.dataset.metricGroup;
      state.chartMetric = firstAvailableMetric(metricGroups[state.metricGroup]) || state.chartMetric;
      document.querySelectorAll("[data-metric-group]").forEach((item) => item.classList.toggle("is-active", item === button));
      await runQuery();
    });
  });

  document.querySelectorAll("[data-open-provenance]").forEach((button) => {
    button.addEventListener("click", openProvenance);
  });
  document.getElementById("close-drawer").addEventListener("click", closeProvenance);
  document.getElementById("scrim").addEventListener("click", closeProvenance);
}

async function loadRuntime() {
  state.runtime = await getJson("/api/dashboard/runtime");
  document.getElementById("system-state").textContent = "Контекст витрины готов";
}

async function loadCatalog() {
  const retailer = selectedRetailer();
  const source = retailer.source_id;
  const payload = await getJson(`/api/dashboard/catalog?retailer_id=${encodeURIComponent(retailer.retailer_id)}&source_id=${encodeURIComponent(source)}`);
  state.catalog = payload.metrics;
}

function setupControls() {
  const retailerSelect = document.getElementById("retailer-select");
  retailerSelect.replaceChildren(...state.runtime.retailers.map((retailer) => option(retailer.retailer_id, retailer.display_label)));
  retailerSelect.addEventListener("change", async () => {
    await loadCatalog();
    updatePrivateLabelTerminology();
    await runQuery();
  });

  setupPeriodSelect("period-a", syntheticPeriods[syntheticPeriods.length - 1]);
  setupPeriodSelect("date-from", syntheticPeriods[0]);
  setupPeriodSelect("date-to", syntheticPeriods[syntheticPeriods.length - 1]);

  document.getElementById("comparison-mode").addEventListener("change", async (event) => {
    state.comparisonMode = event.target.value;
    await runQuery();
  });
  document.getElementById("private-label-toggle").addEventListener("change", async (event) => {
    document.getElementById("private-label-scope").value = event.target.checked ? "INCLUDE" : "EXCLUDE";
    await runQuery();
  });
  document.getElementById("private-label-scope").addEventListener("change", async (event) => {
    document.getElementById("private-label-toggle").checked = event.target.value === "INCLUDE";
    await runQuery();
  });
  document.getElementById("grain-select").addEventListener("change", async (event) => {
    state.grain = event.target.value;
    syncFilterAvailability();
    await runQuery();
  });
  document.getElementById("column-group").addEventListener("change", async (event) => {
    state.columnGroup = event.target.value;
    await runQuery();
  });
  document.getElementById("chart-metric").addEventListener("change", async (event) => {
    state.chartMetric = event.target.value;
    await runQuery();
  });

  for (const [id, values] of Object.entries(filters)) {
    const select = document.getElementById(`${id}-filter`);
    select.replaceChildren(...values.map((value) => option(value, value)));
    select.addEventListener("change", async () => {
      applyFilterGrain(id);
      await runQuery();
    });
  }

  updatePrivateLabelTerminology();
  renderChartMetricOptions();
  syncFilterAvailability();
}

function setupPeriodSelect(id, selected) {
  const select = document.getElementById(id);
  select.replaceChildren(...syntheticPeriods.map((period) => option(period, formatPeriod(period))));
  select.value = selected;
  select.addEventListener("change", runQuery);
}

async function runQuery() {
  const payload = buildQueryPayload();
  setLoading(true);
  try {
    state.response = await postJson("/api/dashboard/query", payload);
    renderAll();
    setLoading(false);
  } catch (error) {
    setLoading(false, `Ошибка витрины: ${error.message}`);
  }
}

function buildQueryPayload() {
  const periodMode = state.periodMode;
  const privateLabelScope = document.getElementById("private-label-scope").value;
  const metricConcepts = [...new Set([
    ...metricGroups[state.metricGroup],
    ...columnGroups[state.columnGroup],
    state.chartMetric
  ].filter(Boolean))];
  return {
    retailer_id: document.getElementById("retailer-select").value,
    source_id: selectedRetailer().source_id,
    date_from: periodMode === "SINGLE_PERIOD" ? document.getElementById("period-a").value : document.getElementById("date-from").value,
    date_to: periodMode === "SINGLE_PERIOD" ? document.getElementById("period-a").value : document.getElementById("date-to").value,
    period_mode: periodMode,
    period_grain: "month",
    grain_id: state.grain,
    entity_ids: [selectedEntityForGrain(state.grain)],
    entity_filters: { entity_id: [selectedEntityForGrain(state.grain)] },
    metric_concepts: metricConcepts,
    comparison_mode: periodMode === "SINGLE_PERIOD" ? state.comparisonMode : "NONE",
    include_lineage: true,
    mart_build_id: selectedRetailer().default_mart_build_id,
    private_label_scope: privateLabelScope
  };
}

function renderAll() {
  renderContextStrip();
  renderChartMetricOptions();
  renderKpis();
  renderChart();
  renderComparisonTable();
  renderDetailTable();
  renderSourceTable();
  renderBusiness();
  renderSignals();
}

function renderContextStrip() {
  const runtime = selectedRetailer();
  const response = state.response;
  const derivedPeriod = derivedComparisonPeriod();
  document.getElementById("period-b-derived").textContent = derivedPeriod ? formatPeriod(derivedPeriod) : "Недоступен";
  const periodText = state.periodMode === "SINGLE_PERIOD"
    ? `${formatPeriod(document.getElementById("period-a").value)} vs ${derivedPeriod ? formatPeriod(derivedPeriod) : "нет периода"} · ${comparisonLabel(state.comparisonMode)}`
    : `${formatPeriod(document.getElementById("date-from").value)} — ${formatPeriod(document.getElementById("date-to").value)}`;
  const scopeName = runtime.private_label_display_name;
  const scopeText = {
    INCLUDE: `${scopeName} включены`,
    EXCLUDE: `${scopeName} исключены`,
    ONLY: `только ${scopeName}`
  }[response.private_label_scope] || response.private_label_scope;
  const available = response.available_periods.length;
  const requested = available + response.missing_periods.length;
  document.getElementById("context-strip").textContent =
    `${runtime.display_label} · ${periodText} · Все категории · ${state.grain} · ${scopeText} · ${available} из ${requested} периодов доступны`;
}

function comparisonLabel(mode) {
  return comparisonLabels[mode] || mode;
}

function statusLabel(status) {
  return {
    READY: "Готово",
    PARTIAL: "Частично",
    NOT_AVAILABLE: "Недоступно",
    NOT_APPLICABLE: "Не применимо",
    COMPLETE: "Полное",
    UNSUPPORTED: "Не поддерживается"
  }[status] || status;
}

function renderChartMetricOptions() {
  const select = document.getElementById("chart-metric");
  const metrics = metricGroups[state.metricGroup].filter((concept) => catalogEntry(concept));
  select.replaceChildren(...metrics.map((concept) => option(concept, catalogEntry(concept).display_label)));
  if (!metrics.includes(state.chartMetric)) {
    state.chartMetric = metrics[0] || "revenue";
  }
  select.value = state.chartMetric;
}

function renderKpis() {
  const grid = document.getElementById("kpi-grid");
  const concepts = metricGroups[state.metricGroup].filter((concept) => resultFor(concept));
  grid.replaceChildren(...concepts.slice(0, 4).map((concept) => {
    const result = resultFor(concept);
    const entry = catalogEntry(concept);
    const card = document.createElement("article");
    card.className = "kpi-card";
    appendText(card, "small", entry.display_label);
    appendText(card, "strong", formatValue(result.value, entry.format));
    appendText(card, "span", result.range_aggregation_strategy);
    return card;
  }));
}

function renderChart() {
  const result = resultFor(state.chartMetric);
  const entry = catalogEntry(state.chartMetric);
  const box = document.getElementById("chart-box");
  if (!result) {
    replaceWithMessage(box, "empty-state", "Показатель недоступен в текущем срезе каталога.");
    return;
  }
  const points = result.period_values.map((item) => ({ period: item.period_start, value: item.value })).filter((item) => item.value !== null);
  if (!points.length) {
    replaceWithMessage(box, "limitation", `Значение диапазона недоступно: ${result.limitations.join(", ") || "нет периодов"}`);
    return;
  }
  box.replaceChildren();
  box.appendChild(buildSvgChart(points, entry));
}

function buildSvgChart(points, entry) {
  const width = 760;
  const height = 320;
  const pad = { left: 60, right: 24, top: 20, bottom: 48 };
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
    svg.appendChild(svgText(pad.left - 8, yy + 4, formatValue(value, entry.format), "end"));
  }
  svg.appendChild(svgEl("line", { class: "axis", x1: pad.left, y1: height - pad.bottom, x2: width - pad.right, y2: height - pad.bottom }));
  svg.appendChild(svgEl("line", { class: "axis", x1: pad.left, y1: pad.top, x2: pad.left, y2: height - pad.bottom }));
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${x(index)} ${y(point.value)}`).join(" ");
  svg.appendChild(svgEl("path", { class: "chart-line", d: path }));
  points.forEach((point, index) => {
    if (index % 2 === 0 || index === points.length - 1) {
      svg.appendChild(svgText(x(index), height - 24, formatPeriod(point.period), "middle"));
    }
    const circle = svgEl("circle", { class: "chart-point", cx: x(index), cy: y(point.value), r: 5, tabindex: 0 });
    circle.addEventListener("mousemove", (event) => showTooltip(event, `${formatPeriod(point.period)} · ${formatValue(point.value, entry.format)}`));
    circle.addEventListener("mouseleave", hideTooltip);
    svg.appendChild(circle);
  });
  if (state.periodMode === "SINGLE_PERIOD") {
    [document.getElementById("period-a").value, derivedComparisonPeriod()].filter(Boolean).forEach((period) => {
      const index = points.findIndex((point) => point.period === period);
      if (index >= 0) {
        svg.appendChild(svgEl("line", { class: "comparison-marker", x1: x(index), y1: pad.top, x2: x(index), y2: height - pad.bottom }));
      }
    });
  }
  return svg;
}

function renderComparisonTable() {
  const table = document.getElementById("comparison-table");
  if (state.periodMode !== "SINGLE_PERIOD" || !state.response.comparisons.length) {
    renderMessageRow(table, "Нет валидного A/B сравнения для текущего среза.");
    return;
  }
  const rows = state.response.comparisons.slice(0, 6).map((item) => {
    const concept = resultByDefinition(item.metric_definition_id)?.metric_concept;
    const entry = catalogEntry(concept);
    return [entry?.display_label || item.metric_definition_id, item.current_value, item.comparison_value, item.delta, item.pct_delta, entry?.format || "decimal"];
  });
  renderRows(table, ["Показатель", "A", "B", "Отклонение", "%"], rows.map((row) => [
    row[0],
    formatValue(row[1], row[5]),
    formatValue(row[2], row[5]),
    formatDeltaValue(row[3], row[5]),
    formatValue(row[4], "percent")
  ]));
}

function renderDetailTable() {
  const table = document.getElementById("detail-table");
  const concepts = columnGroups[state.columnGroup];
  if (!concepts.length) {
    renderMessageRow(table, "Группа колонок пока не поддержана каталогом витрины.", "limitation");
    return;
  }
  const rows = [[entityForGrain(state.grain), ...concepts.map((concept) => {
    const result = resultFor(concept);
    const entry = catalogEntry(concept);
    return result ? formatValue(result.value, entry.format) : "Недоступно";
  })]];
  renderRows(table, [state.grain, ...concepts.map((concept) => catalogEntry(concept)?.display_label || concept)], rows);
}

function renderSourceTable() {
  const table = document.getElementById("source-table");
  const result = resultFor("revenue") || state.response.metric_results[0];
  const rows = (result?.period_values || []).map((period) => [
    formatPeriod(period.period_start),
    entityForGrain(state.grain),
    period.business_period_id,
    formatValue(period.value, "currency"),
    period.quality_status
  ]);
  renderRows(table, ["Период", "Объект", "Период источника", "Оборот", "Качество данных"], rows);
}

function renderBusiness() {
  const list = document.getElementById("business-list");
  const items = [
    ["Доля в категории", "READY", "Показывается только при наличии объявленного среза знаменателя и компонентов витрины."],
    ["Место производителя", "PARTIAL", "Расширенная панель бизнес-оценок будет подключена отдельным этапом интерфейса."],
    ["ABC / группировка SKU", "PARTIAL", "Бизнес-ревью не подтвердило пользовательский термин группировки как готовый статус."],
    ["Статус бренда", "PARTIAL", "Оценочные статусы нельзя показывать без утверждённой политики."],
    ["Широкий пул конкурентов", "PARTIAL", "Доступен только через подтверждённые проекции витрины; отдельная панель будет подключена позже."]
  ];
  list.replaceChildren(...items.map(([title, status, text]) => {
    const node = document.createElement("article");
    node.className = "business-item";
    appendText(node, "strong", `${title} · ${statusLabel(status)}`);
    appendText(node, "span", text);
    return node;
  }));
}

function renderSignals() {
  const list = document.getElementById("signal-list");
  const limitationCodes = state.response.limitations.map((item) => item.issue_code);
  const items = [
    ["Покрытие периода", state.response.coverage_status, `${state.response.available_periods.length} доступно · ${state.response.missing_periods.length} пропущено`],
    ["Ограничения диапазона", limitationCodes.length ? limitationCodes.join(", ") : "Ограничения не возвращены"],
    ["Окна событий", "Недоступно", "Окна EDLP/стабильности требуют дополнительной семантики."]
  ];
  list.replaceChildren(...items.map(([title, status, text]) => {
    const node = document.createElement("article");
    node.className = "signal-item";
    const strong = appendText(node, "strong", `${title} · `);
    const statusNode = appendText(strong, "span", statusLabel(status));
    statusNode.className = "severity-warning";
    appendText(node, "span", text);
    return node;
  }));
}

function openProvenance() {
  const result = resultFor(state.chartMetric) || state.response.metric_results[0];
  const content = document.getElementById("provenance-content");
  const provenance = result?.provenance;
  content.replaceChildren();
  if (!provenance) {
    appendText(content, "dt", "Происхождение");
    appendText(content, "dd", "Происхождение из витрины недоступно для этого значения.");
  }
  Object.entries(provenanceFields(provenance || {})).forEach(([key, value]) => {
    appendText(content, "dt", key);
    appendText(content, "dd", String(value));
  });
  document.getElementById("provenance-drawer").classList.add("is-open");
  document.getElementById("provenance-drawer").setAttribute("aria-hidden", "false");
  document.getElementById("scrim").classList.add("is-open");
}

function provenanceFields(provenance) {
  const scope = provenance.current_analytical_scope || {};
  const metric = provenance.metric || {};
  const value = provenance.value || {};
  const comparison = provenance.comparison || {};
  const rule = provenance.business_rule || {};
  const run = provenance.run_lineage || {};
  const source = provenance.source_evidence || {};
  const quality = provenance.quality || {};
  return {
    "Текущий срез": compactJson(scope),
    "Сеть / источник": [scope.retailer_id, scope.source_id].filter(Boolean).join(" / ") || "н/д",
    "Период или периоды сравнения": compactJson({
      requested: scope.requested_periods,
      available: scope.available_periods,
      missing: scope.missing_periods,
      comparison: comparison.periods
    }),
    "Гранулярность / объект": [scope.grain_id, scope.entity_id].filter(Boolean).join(" / ") || "н/д",
    "Показатель": metric.metric_concept || "н/д",
    "Определение показателя": [metric.metric_definition_id, metric.metric_definition_version, metric.metric_config_hash].filter(Boolean).join(" / ") || "н/д",
    "Значение": value.value ?? "н/д",
    "Числитель": value.numerator_value ?? "н/д",
    "Знаменатель": value.denominator_value ?? "н/д",
    "Агрегация / стратегия диапазона": value.range_aggregation_strategy || "н/д",
    "Тип сравнения / качество": [comparison.comparison_mode, (comparison.quality_statuses || []).join(", ") || comparison.status].filter(Boolean).join(" / "),
    "Бизнес-правило": [rule.business_rule_id, rule.business_rule_version].filter(Boolean).join(" / ") || "н/д",
    "Запуск анализа": (run.analysis_run_ids || []).join(", ") || "н/д",
    "Версия аналитической витрины": run.mart_build_id || "н/д",
    "Ревизия источника": (run.source_revision_ids || []).join(", ") || "н/д",
    "Доказательство по источнику": source.status || "н/д",
    "Качество данных": compactJson(quality),
    "Срез с учётом выбранного ассортимента": scope.private_label_scope || "н/д",
    "Недостающие поля происхождения": (provenance.missing_fields || []).join(", ") || "нет"
  };
}

function compactJson(value) {
  if (value === null || value === undefined) return "н/д";
  if (Array.isArray(value)) return value.length ? value.join(", ") : "нет";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function closeProvenance() {
  document.getElementById("provenance-drawer").classList.remove("is-open");
  document.getElementById("provenance-drawer").setAttribute("aria-hidden", "true");
  document.getElementById("scrim").classList.remove("is-open");
}

function switchTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll(".folder-tab").forEach((button) => button.classList.toggle("is-active", button.dataset.tab === tab));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("is-active", panel.id === `tab-${tab}`));
}

function renderRows(table, headers, rows) {
  const renderedRows = sortedRows(headers, rows);
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  headers.forEach((header) => {
    const th = document.createElement("th");
    th.textContent = header;
    th.addEventListener("click", () => {
      state.sortColumn = header;
      state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
      renderAll();
    });
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  const tbody = document.createElement("tbody");
  renderedRows.forEach((row) => {
    const tr = document.createElement("tr");
    row.forEach((cell) => {
      const td = document.createElement("td");
      td.textContent = cell;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.replaceChildren(thead, tbody);
}

function renderMessageRow(table, message, className) {
  const tbody = document.createElement("tbody");
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  if (className) td.className = className;
  td.textContent = message;
  tr.appendChild(td);
  tbody.appendChild(tr);
  table.replaceChildren(tbody);
}

function catalogEntry(concept) {
  return state.catalog.find((entry) => entry.metric_concept === concept);
}

function resultFor(concept) {
  return state.response?.metric_results.find((result) => result.metric_concept === concept);
}

function resultByDefinition(metricDefinitionId) {
  return state.response?.metric_results.find((result) => result.lineage?.metric_definition_id === metricDefinitionId);
}

function firstAvailableMetric(concepts) {
  return concepts.find((concept) => catalogEntry(concept));
}

function entityForGrain(grain) {
  return {
    network: "network",
    category: "CATEGORY_STANDARD",
    manufacturer: "MANUFACTURER_A",
    brand: "BRAND_A",
    sku: "SKU_A_001",
    store: "STORE_A_001"
  }[grain];
}

function selectedEntityForGrain(grain) {
  const selectMap = {
    category: "category-filter",
    manufacturer: "manufacturer-filter",
    brand: "brand-filter",
    sku: "sku-filter",
    store: "store-filter"
  };
  const selectId = selectMap[grain];
  if (!selectId) return entityForGrain(grain);
  const value = document.getElementById(selectId).value;
  return value.startsWith("Все ") ? entityForGrain(grain) : value;
}

function applyFilterGrain(filterId) {
  const grainMap = {
    category: "category",
    manufacturer: "manufacturer",
    brand: "brand",
    sku: "sku",
    store: "store"
  };
  const select = document.getElementById(`${filterId}-filter`);
  if (select.value.startsWith("Все ")) return;
  state.grain = grainMap[filterId] || state.grain;
  document.getElementById("grain-select").value = state.grain;
  syncFilterAvailability();
}

function syncFilterAvailability() {
  ["category-filter", "manufacturer-filter", "brand-filter", "sku-filter", "store-filter"].forEach((id) => {
    document.getElementById(id).title = "Выбор меняет гранулярность и объект запроса";
  });
}

function selectedRetailer() {
  const selectedId = document.getElementById("retailer-select")?.value || state.runtime.default_retailer_id;
  return state.runtime.retailers.find((retailer) => retailer.retailer_id === selectedId) || state.runtime.retailers[0];
}

function updatePrivateLabelTerminology() {
  const scopeName = selectedRetailer().private_label_display_name;
  document.getElementById("private-label-label").textContent = `Учитывать ${scopeName}`;
  const options = {
    INCLUDE: `${scopeName}: включить`,
    EXCLUDE: `${scopeName}: исключить`,
    ONLY: `${scopeName}: только`
  };
  Array.from(document.getElementById("private-label-scope").options).forEach((item) => {
    item.textContent = options[item.value] || item.value;
  });
}

function derivedComparisonPeriod() {
  if (!state.response || !state.response.comparisons.length) return null;
  return state.response.comparisons[0].comparison_period_start;
}

function sortedRows(headers, rows) {
  const index = headers.indexOf(state.sortColumn);
  if (index < 0) return rows;
  return [...rows].sort((left, right) => {
    const direction = state.sortDirection === "asc" ? 1 : -1;
    return String(left[index]).localeCompare(String(right[index]), "ru-RU", { numeric: true }) * direction;
  });
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

function formatValue(value, format) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "н/д";
  }
  if (format === "currency") {
    return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value);
  }
  if (format === "percent") {
    return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value * 100)}%`;
  }
  if (format === "percentage_points") {
    return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value * 100)} п.п.`;
  }
  if (format === "integer") {
    return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value);
  }
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value);
}

function formatDeltaValue(value, format) {
  if (format === "percent") {
    return formatValue(value, "percentage_points");
  }
  return formatValue(value, format);
}

function formatPeriod(value) {
  const date = new Date(`${value}T00:00:00`);
  return new Intl.DateTimeFormat("ru-RU", { month: "short", year: "numeric" }).format(date);
}

function option(value, label) {
  const node = document.createElement("option");
  node.value = value;
  node.textContent = label;
  return node;
}

function setLoading(isLoading, message) {
  document.getElementById("system-state").textContent = message || (isLoading ? "Запрос к витрине" : "Контекст витрины готов");
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

function svgText(x, y, value, anchor) {
  const text = svgEl("text", { x, y, "text-anchor": anchor, class: "axis" });
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
