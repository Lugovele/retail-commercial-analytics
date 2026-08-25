# Dashboard Screen Specification

Version: `dashboard_screen_specification.v1.1.0`

This document defines the approved screen-level product structure for
`Аналитика продаж`. It is public-safe and contains no private retailer data.

The specification describes screen purpose, block order, hierarchy, main
visualization, tables, drilldown behavior, provenance access, and readiness. It
does not define business formulas.

## Global Shell

The six business areas form one continuous analytical report, not mutually
exclusive hidden pages. Navigation is an in-page section navigator over stable
report anchors:

- `#overview`
- `#sales-drivers`
- `#portfolio-market`
- `#stores`
- `#signals`
- `#data`

Manual scrolling and navigation clicks must keep exactly one active section in
the business navigation. Native anchors plus `IntersectionObserver` scrollspy
are the preferred implementation. Sections use scroll margins so headings are
not hidden behind the sticky workspace.

Top-level navigation order:

1. `overview` — Обзор
2. `sales_drivers` — Продажи и драйверы
3. `portfolio_market` — Портфель и рынок
4. `stores` — Точки продаж
5. `signals` — Сигналы
6. `data` — Данные

Global analytical scope persists across report sections:

- retailer;
- period mode and selected periods;
- comparison mode;
- category;
- manufacturer;
- brand;
- SKU;
- store;
- private-label scope.

Global scope controls must not be duplicated per section. The report shell uses
one compact analytical scope row in this order:

```text
Сеть | Период | Категория | Производитель | Бренд | SKU | Точка продаж | Ассортимент
```

The period control is collapsed in the row and opens a popover for:

- `Один период`;
- `Сравнение`;
- `Весь диапазон`.

Network/report identity must use runtime display metadata in the primary UI,
never internal ids such as `retailer_a` or `source_001`. Secondary filters show
their selected value in the control itself; selected values must not be repeated
in a second chip row or long scope sentence. `Сбросить` appears only for active
optional filters and must not reset network or primary period accidentally.

Breadcrumbs represent drilldown only:

```text
Категория -> Производитель -> Бренд -> SKU -> ТТ
```

They are not a filter toolbar and should be hidden when no drilldown exists.
Changing scope while the user is reading a lower section must refresh affected
data without jumping back to Overview.

## Обзор

Purpose: let a commercial user understand the current situation in 5-10 seconds
and choose the next drilldown.

Primary questions:

- Что произошло?
- Насколько существенно?
- Кто внёс вклад в изменение?
- Что изменилось одновременно?
- Что проверить?
- Куда идти дальше?

Readiness: `READY_QUERY` for current Overview core, with signals shown only when
confirmed deterministic facts are available.

Wireframe:

```text
┌ Global application header ───────────────────────────────────────────────┐
├ Sticky business navigation ─────────────────────────────────────────────┤
├ Sticky one-row analytical scope toolbar ────────────────────────────────┤
│ Coverage note only when meaningful                                       │
├─────────────────────────────────────────────────────────────────────────┤
│ KPI: Оборот │ KPI: Продажи, шт. │ KPI: Абсолютная маржа │ KPI: Маржинальность │
├─────────────────────────────────────────────────────────────────────────┤
│ Main trend: selected metric, actual periods                              │
│ X/Y axes, units, A/B markers, sparse history                             │
├─────────────────────────────────────────────────────────────────────────┤
│ Вклад в изменение                                                        │
│ Ranked contribution table when additive comparison is valid; otherwise    │
│ neutral scoped object table                                               │
├─────────────────────────────────────────────────────────────────────────┤
│ Картина изменений                                                         │
│ Descriptive driver matrix: sales, price, presence, economics, structure   │
├─────────────────────────────────────────────────────────────────────────┤
│ Что проверить                                                             │
│ Confirmed signals only; calm empty state when no confirmed signals exist  │
└ Provenance drawer available from important numbers ──────────────────────┘
```

Default KPI:

- `revenue`
- `units`
- `retailer_margin_abs`
- `retailer_margin_pct`

Main visualization: `LINE`.

Primary table: `RANKED_TABLE` for `contribution_to_delta` when comparison and
additive metric support exist; otherwise bounded `DETAIL_TABLE`.

Drilldown:

```text
network -> category -> manufacturer -> brand -> sku -> store
```

Explicitly excluded:

- ranking wall;
- ABC/tiering as primary content;
- unapproved brand status;
- delisting terminology;
- recommendations;
- technical data metadata as primary content.

## Продажи и драйверы

Purpose: show how the result and accompanying commercial parameters moved.

Primary users: KAM, category manager, analyst.

Primary questions:

- Как изменился коммерческий результат?
- Это объём, цена, присутствие, скорость, экономика или структура?
- Какие параметры изменились одновременно?

Readiness: `READY_QUERY` for core metric facts; decomposition remains future.

Wireframe:

```text
┌ Screen title and short purpose ─────────────────────────────────────────┐
├ Driver matrix ──────────────────────────────────────────────────────────┤
│ Result │ Volume │ Price │ Presence │ Sales speed │ Economics │ Structure │
│ metric │ current │ reference │ delta │ quality/limitation                 │
├ Selected metric trend ─────────────────────────────────────────────────┤
│ One metric at a time, compatible units only                             │
├ Driver detail table ───────────────────────────────────────────────────┤
│ Grain-aware rows and optional columns                                   │
└ Provenance drawer ─────────────────────────────────────────────────────┘
```

Preferred visualization: `DRIVER_MATRIX` plus one `LINE`.

Do not use seven equal cards. Do not use causal wording unless approved
decomposition exists.

Explicitly excluded:

- rankings and market-position blocks;
- recommendations;
- causality claims.

## Портфель и рынок

Purpose: show position in category, assortment, brand versus category, market /
private-label relationship, and competitors where ready.

Primary users: KAM, category manager, analyst.

Primary questions:

- Как мы стоим в категории?
- Что происходит с долей?
- Какое место производителя?
- Что происходит с ассортиментом?
- Как бренд движется относительно категории?
- Что видно по рынку, СТМ и конкурентам?

Readiness: mixed. Use `READY_PROJECTION` only where route/provenance is ready;
otherwise show partial or future state.

Wireframe:

```text
┌ Screen title and purpose ───────────────────────────────────────────────┐
├ Позиция в категории ───────────────────────────────────────────────────┤
│ RANKED_BAR / RANKED_TABLE for manufacturer rank and category share       │
├ Ассортимент ────────────────────────────────────────────────────────────┤
│ BULLET / COMPARISON_STRIP for active SKU versus peak                     │
├ Бренд относительно категории ──────────────────────────────────────────┤
│ DUMBBELL / COMPARISON_STRIP, no status badge                             │
├ Рынок и СТМ ────────────────────────────────────────────────────────────┤
│ BAR / COMPARISON_STRIP only for approved comparison universes            │
├ Конкуренты ─────────────────────────────────────────────────────────────┤
│ DETAIL_TABLE for broad competitors; direct peers remain gated            │
└ Provenance drawer where supported ─────────────────────────────────────┘
```

Explicitly excluded:

- composite growth/decline/critical status;
- delisting terminology;
- direct peers without approved flavor semantics;
- opportunity facts;
- recommendations.

## Точки продаж

Purpose: show where physical store-level result forms.

Primary users: sales manager, KAM, analyst.

Primary questions:

- Какие ТТ формируют результат?
- Где меняются продажи и экономика?
- Где требуется store-level follow-up?

Readiness: `READY_QUERY` for store metric facts; geography projections are
secondary and partial.

Wireframe:

```text
┌ Screen title and purpose ───────────────────────────────────────────────┐
├ Store ranking ──────────────────────────────────────────────────────────┤
│ RANKED_BAR by selected additive metric or supported business metric       │
├ Store detail table ─────────────────────────────────────────────────────┤
│ store │ current │ reference │ delta │ margin │ SKU count │ quality        │
├ Geography detail, when mapped ─────────────────────────────────────────┤
│ Secondary table/bar; map is not default                                  │
└ Provenance drawer ─────────────────────────────────────────────────────┘
```

Do not show distribution, velocity, revenue velocity, or margin velocity as
store-grain metrics.

## Сигналы

Purpose: manage attention without pretending to recommend actions.

Primary users: executive, KAM, analyst.

Primary questions:

- Что требует внимания?
- Какой объект затронут?
- На каком правиле или качестве данных основан сигнал?
- Куда перейти для проверки?

Readiness: `PARTIAL`. The backend route for confirmed deterministic signal
outputs is productized, but current signal availability depends on enabled
private rule packages and materialized event outputs. Empty confirmed-signal
responses are valid and must not be filled with ordinary metric deltas.

Wireframe:

```text
┌ Screen title and purpose ───────────────────────────────────────────────┐
├ Commercial signals ─────────────────────────────────────────────────────┤
│ object │ observation │ current │ reference │ delta │ threshold │ severity │
├ Data-quality alerts ───────────────────────────────────────────────────┤
│ source/period/grain │ issue │ affected scope │ quality │ evidence         │
├ Limitations ────────────────────────────────────────────────────────────┤
│ Separated from commercial signals                                        │
└ Signal evidence chain ─────────────────────────────────────────────────┘
```

Evidence chain:

```text
Исходные данные -> Показатель -> Сравнение -> Бизнес-правило -> Сигнал
```

Explicitly excluded:

- fake recommendations;
- ordinary deltas labeled as signals;
- limitations mixed into commercial alert feed.

## Данные

Purpose: show what data is included and whether it can be trusted.

Primary users: analyst, admin, KAM when checking coverage.

Primary questions:

- Какие данные используются?
- Какие периоды доступны?
- Есть ли пробелы или quality issues?
- Как открыть source-like/audit details?

Readiness: `READY_QUERY` for coverage and quality metadata; source-like rows
depend on the current runtime contract.

Wireframe:

```text
┌ Screen title and purpose ───────────────────────────────────────────────┐
├ Period coverage ────────────────────────────────────────────────────────┤
│ AVAILABILITY_GRID, available and missing periods                         │
├ Quality summary ────────────────────────────────────────────────────────┤
│ SIGNAL_LIST / DETAIL_TABLE for quality issues                            │
├ Source-like rows ───────────────────────────────────────────────────────┤
│ Bounded table, close to uploaded source shape where approved              │
├ Audit/provenance access ────────────────────────────────────────────────┤
│ Technical details in collapsed/progressive disclosure                     │
└ Runtime/build/source metadata as audit detail, not primary content ─────┘
```

Explicitly excluded:

- hashes, run IDs, and build IDs as primary business content;
- private config contents;
- raw private source columns in public fixtures/docs.

## Grain-Specific Defaults

| Current grain | Top question | Default KPI | Diagnostic metrics | Next drilldown | Metrics to hide |
| --- | --- | --- | --- | --- | --- |
| network | What happened in the whole selected business? | revenue, units, margin abs, margin pct | price, presence, SKU count, category mix | category | manufacturer rank as network KPI |
| category | Which manufacturers or brands explain movement? | revenue, units, margin abs, margin pct | share, price, presence, SKU count | manufacturer | category count |
| manufacturer | Which brands explain movement and category position? | revenue, units, margin abs, margin pct | rank, share, price, presence | brand | network-only category count |
| brand | Which SKU explain movement and how brand compares to category? | revenue, units, margin abs, margin pct | brand-vs-category, price, presence | sku | composite status |
| sku | Which stores carry the SKU movement? | revenue, units, margin abs, shelf price | store presence, velocity where supported | store | brand/category counts as KPI |
| store | What happened in a physical store? | revenue, units, margin abs, margin pct | SKU count, price where supported | none | distribution, velocity |

## Table Defaults

| Table | Default columns | Optional columns | Audit-only columns | Default sort | Click action |
| --- | --- | --- | --- | --- | --- |
| Category | category, revenue, contribution, units, margin abs, margin pct, SKU count, selling stores | price, share, quality | metric definition, run/build | contribution absolute delta desc when available | drill to manufacturer |
| Manufacturer | manufacturer, revenue, contribution, units, margin abs, margin pct, revenue rank | units rank, share, price, presence | rank population, metric definition | contribution absolute delta desc when available | drill to brand |
| Brand | brand, revenue, contribution, units, margin abs, category share | price, presence, brand-vs-category | technical lineage | contribution absolute delta desc when available | drill to SKU |
| SKU | SKU, revenue, contribution, units, margin abs, shelf price, selling stores | input price, velocity where supported | source identifiers | contribution absolute delta desc when available; store contribution requires a future route | drill to store |
| Store | store, revenue, units, margin abs, margin pct, SKU count | price, source quality | source revision/run/build | current value desc | open details |

## Period Mode Matrix

| Metric/block | Single period | Compare | Date range | Notes |
| --- | --- | --- | --- | --- |
| Additive KPI | valid | valid | range-safe | Sum available periods. |
| Margin % | valid | valid | range-safe | Ratio of sums, never average. |
| Weighted price | valid | valid | range-safe | Weighted ratio from stored components. |
| Distribution | valid | valid | partial | Period-only until explicit range contract. |
| Velocity | valid | valid | partial | Period-only; do not average. |
| Selling stores | valid | valid | partial | Period-only. |
| SKU/brand/category counts | valid | valid | partial | Selected-range distinct count requires explicit contract. |
| Shares | valid | valid | partial | Recompute numerator/denominator; never average monthly shares. |
| ABC | valid where wired | limited | not supported | No custom range ABC without policy. |
| Contribution to delta | not applicable | valid for additive metrics | not applicable | Comparison-driven only. |
| Signals | partial | partial | partial | Only confirmed deterministic signal routes. |

## Provenance Defaults

Every important number should offer `Откуда эта цифра?` when backend provenance
is available.

Default drawer hierarchy:

1. Что это за показатель.
2. Срез.
3. Расчёт.
4. Сравнение.
5. Покрытие данных.
6. Бизнес-правило.
7. Качество.
8. Технические детали.

Technical details are collapsed by default.
