# Dashboard Visualization and Screen Design Policy

Version: `dashboard_visualization_policy.v1.1.0`

This document is the authoritative public-safe design policy for the
`Аналитика продаж` dashboard. It governs dashboard information architecture,
visualization choices, screen composition, readiness gating, and review
lifecycle.

It does not define formulas, thresholds, private retailer rules, or metric
semantics. Metric semantics remain in the Metric Catalog, Capability Matrix,
business-rule configuration, and deterministic backend code.

## Core Principle

Metric Catalog is the taxonomy of data.

Dashboard navigation is the taxonomy of business questions.

Future UI work must not derive screens directly from metric groups. A metric may
exist in the catalog and still be inappropriate for a primary screen, a KPI card,
a chart, a range view, or a signal.

## Expert Model

Every material dashboard design decision must be checked from six perspectives:

| Perspective | Responsibility |
| --- | --- |
| Senior FMCG Commercial Analytics Lead | Business questions, KPI priority, decision usefulness, meaningful comparisons, KAM/category/sales relevance, diagnostic hierarchy. |
| Senior Product / Information Architect | Screen purpose, block hierarchy, progressive disclosure, drilldown, navigation, duplication avoidance. |
| Senior BI / Data Visualization Specialist | Visualization type, axes, comparisons, sparse history, rankings, shares, contributions, density, misleading-chart prevention. |
| Senior B2B Analytics UI/UX Designer | Layout, scan speed, filters, tables, interaction, responsive behavior, accessibility, design-system consistency. |
| Retail/Data Architecture Reviewer | `READY_QUERY` versus `READY_PROJECTION`, routes, provenance, performance, no frontend calculations, grain/period constraints. |
| Retail Business Rules Reviewer | Formulas, aggregation validity, no unsupported causality, no invented statuses, comparison semantics, private-label scope, period/grain validity. |

These perspectives may be represented by structured review passes in existing
reviewer agents. They do not require six separate concurrent agents.

## Authoritative Business IA

The approved top-level dashboard IA is:

| Order | Internal ID | User-facing label | Purpose |
| --- | --- | --- | --- |
| 1 | `overview` | Обзор | What happened, how material it is, where to look, what changed together, what to check next. |
| 2 | `sales_drivers` | Продажи и драйверы | Result, volume, price, presence, sales speed, economics, and structure. |
| 3 | `portfolio_market` | Портфель и рынок | Category position, shares, rankings, assortment, brand-vs-category, market/private-label, competitors where ready. |
| 4 | `stores` | Точки продаж | Store-level sales, economics, assortment/mix, and physical place of result formation. |
| 5 | `signals` | Сигналы | Deterministic attention items and data-quality alerts, separated from limitations and recommendations. |
| 6 | `data` | Данные | Data coverage, quality, source-like rows, and audit/provenance access. |

Do not add `Рекомендации`, `География`, or `Разбор` as top-level items until a
separate policy update approves them.

## Screen Contracts

### Обзор

Business questions:

- Что произошло?
- Насколько существенно?
- Где произошло изменение?
- Что изменилось одновременно?
- Что проверить?
- Куда идти дальше?

Default structure:

1. Four KPI.
2. Main trend.
3. Contribution / drilldown.
4. `Картина изменений`.
5. `Что проверить`.
6. Provenance and drilldown affordances.

Default primary KPI:

- `revenue`
- `units`
- `retailer_margin_abs`
- `retailer_margin_pct`

Overview must not become a full metric catalog. Default KPI maximum is four.

### Продажи и драйверы

Business question:

Как изменился коммерческий результат и какие параметры изменились одновременно?

Business dimensions:

- Результат
- Объём
- Цена
- Присутствие
- Скорость
- Экономика
- Структура

Preferred primary presentation is `DRIVER_MATRIX` with metric, current value,
reference value, and delta, plus one selected metric trend. Do not implement this
as seven equal cards.

Until an approved mathematical decomposition exists, this screen is descriptive,
not causal.

### Портфель и рынок

Business questions:

- Как мы стоим в категории?
- Что происходит с долей?
- Какое место производителя?
- Что происходит с ассортиментом?
- Как бренд движется относительно категории?
- Что делает рынок / СТМ?
- Что видно по конкурентам?

Preferred sections:

1. Позиция в категории.
2. Ассортимент.
3. Бренд относительно категории.
4. Рынок и СТМ.
5. Конкуренты.

Do not show unapproved composite brand statuses, tiering, delisting terminology,
or direct peers without approved flavor semantics.

### Точки продаж

Business question:

Где физически формируется результат?

Preferred primary presentation:

- `RANKED_BAR`
- `DETAIL_TABLE`

Map is not the default primary visualization. Distribution and velocity must not
be shown as store-grain metrics unless a future backend contract explicitly
supports them.

### Сигналы

Business question:

Что требует внимания?

Primary presentation is `SIGNAL_LIST`.

Separate:

- commercial signals;
- data-quality alerts;
- deterministic patterns;
- capability limitations.

Limitations are not commercial signals. Signals are not recommendations. A
normal delta is not automatically a signal.

### Данные

Business question:

Какие данные используются и можно ли им доверять?

Preferred blocks:

1. Period coverage.
2. Quality.
3. Source-like rows.
4. Audit/provenance.

Technical run/build/hash metadata belongs in progressive disclosure, not as
primary business content.

## Approved Visualization Vocabulary

Allowed visualization types:

- `KPI`
- `LINE`
- `BAR`
- `STACKED_BAR`
- `RANKED_BAR`
- `RANKED_TABLE`
- `DETAIL_TABLE`
- `DRIVER_MATRIX`
- `COMPARISON_STRIP`
- `DUMBBELL`
- `BULLET`
- `AVAILABILITY_GRID`
- `SIGNAL_LIST`
- `PROVENANCE_DRAWER`
- `HEATMAP`
- `WATERFALL`

Discouraged unless explicitly approved:

- `PIE`
- `DONUT`
- `RADAR`
- `GAUGE`
- `MULTI_AXIS_CHART`

No new visualization type should be introduced without design review.

## Visualization Decision Rules

| Concept | Preferred presentation | Do not use |
| --- | --- | --- |
| Revenue, units, absolute margin | KPI on Overview; line trend; detail table | Pie, donut, gauge, decorative chart |
| Margin percentage | KPI or comparison strip; line trend when single unit | Arithmetic average over periods |
| Weighted prices | Line or comparison strip | Arithmetic average over periods |
| Additive contribution | Ranked table; optional directional bar | Pie, donut, default waterfall |
| Sparse time history | Line with actual periods only | Zero fill, smoothing, interpolation |
| Shares | Horizontal bar, comparison strip, detail table | Pie or donut by default |
| Manufacturer ranking | Ranked bar plus table/badge | KPI-only presentation |
| Active SKU versus peak | Bullet or comparison strip | Unexplained status badge |
| Brand versus category | Dumbbell or comparison strip | Composite growth/decline status badge |
| Market / STM / portfolio | Grouped bar or comparison strip | Pie by default |
| Stores | Horizontal ranked bar plus detail table | Map as default |
| Signals | Signal list | Metric cards or recommendation text |
| Coverage | Availability grid | Line chart |
| Provenance | Drawer | Always-visible technical metadata |

## Contribution Rule

Additive contribution is currently supported only for:

- `revenue_vat`
- `revenue`
- `units`
- `retailer_margin_abs`

Preferred visualization: `RANKED_TABLE`.

Required columns:

- Object.
- Current value.
- Reference value.
- Delta.
- Contribution to change.

Default sort: absolute delta descending.

Signed contribution may be above `100%` or below `0%` when contributors offset
one another. Do not clamp it. Do not label it good or bad. Do not use pie or
donut. Waterfall is reserved for a small, mathematically closed decomposition
with limited components; it is not the default contribution view.

## Sales Driver Causality Guardrail

Until approved decomposition exists, use descriptive language:

- `изменилось одновременно`
- `при этом`
- `динамика`
- `картина изменений`
- `сопутствующее изменение`

Do not use causal language without deterministic decomposition:

- `причина`
- `из-за`
- `вызвано`
- `привело к`
- `driver of decline`

Future decomposition examples, such as units into selling stores and velocity or
revenue into volume and price, require a separate metric and business-rule
contract.

## Period Rules

Every visualization must declare support for:

- `SINGLE_PERIOD`
- `COMPARE`
- `DATE_RANGE`

Rules:

- Additive metrics are range-safe through sum over available periods.
- Margin percentage is range-safe only as ratio of summed components.
- Weighted prices are range-safe only as weighted ratio from stored components.
- Distribution is period-only until an explicit range contract exists.
- Velocity is period-only.
- Selling-store counts are period-only.
- SKU, brand, and category counts are period-only unless an explicit selected-range
  semantics exists.
- Shares must be recomputed from numerator and denominator; never average monthly
  shares.
- Missing calendar periods must never be rendered as zero.

## Grain Rules

Every visualization must declare grain support for:

- `network`
- `category`
- `manufacturer`
- `brand`
- `sku`
- `store`

Rules:

- Store grain must not show distribution or velocity.
- Manufacturer rank and share are meaningful within category context.
- Brand-vs-category is meaningful for brand within category context.
- SKU views may use price, presence, velocity, and category share where supported.
- Network views should avoid showing entity-specific ranks as universal KPIs.
- No visual component may assume every metric works at every grain.

## Density Policy

Desktop analytics defaults:

- Maximum default top KPI: four on Overview, six elsewhere only with explicit
  design approval.
- Maximum primary charts visible at once: one or two.
- Maximum Overview contribution preview rows: eight.
- Maximum Overview signal preview items: three.

Avoid:

- card walls;
- one metric equals one card;
- giant empty surfaces;
- decorative charts;
- repeated labels/context;
- always-visible technical metadata.

Use progressive disclosure.

## Table Policy

Tables are first-class analytical components. Every table must define:

- purpose;
- grain;
- default columns;
- optional columns;
- audit-only columns;
- default sort;
- pagination;
- drilldown target;
- provenance affordance;
- conditional formatting rules.

Do not create one universal table for all grains.

Large-cardinality lists require search and bounded queries. Store-level lists may
often show all rows when the store count is small, but the policy still requires
bounded rendering.

## Color and Emphasis

Color may represent:

- direction;
- selection;
- reference series;
- attention severity;
- quality.

Color must not automatically imply positive equals good or negative equals bad.
For example, revenue growth may coexist with margin deterioration.

Use arrows, signs, labels, line styles, or markers in addition to color. Do not
encode meaning with red/green alone.

## Role Depth

Use one layered dashboard rather than separate products:

- Executive: KPI, trend, top contributors, high-priority signals.
- KAM: drilldowns, driver matrix, portfolio, stores.
- Analyst: optional columns, detailed comparisons, provenance, quality/audit.

Depth is achieved through progressive disclosure, not duplicate dashboards.

## Filter and Interaction Policy

The dashboard is one continuous analytical report. Business navigation items are
sticky in-page section links, not mutually exclusive hidden tabs. Manual scroll
and navigation clicks must keep exactly one active section through scrollspy.

Required section anchors:

- `#overview`
- `#sales-drivers`
- `#portfolio-market`
- `#stores`
- `#signals`
- `#data`

Global analytical scope persists across report sections and scope changes must
not jump the user back to Overview.

All analytical controls belong to one compact row:

- retailer;
- period.
- category;
- manufacturer;
- brand;
- SKU;
- store;
- STM/private-label scope.

The period control is collapsed in the row and opens a popover for single,
comparison, and full-range modes. Network/report identity must use display
metadata, never internal ids. Large lists require both browse and searchable
combobox/typeahead; typing filters options locally and must not trigger a full
analytics reload before selection. Filter hierarchy is category to manufacturer
to brand to SKU. Store is orthogonal. Do not duplicate filter bars, selected
filter chips, or long current-scope sentences per section. Breadcrumbs represent
analytical drilldown, not filters or the full technical query state.

## Readiness Gating

Every visualization block must declare one of:

- `READY_QUERY`
- `READY_PROJECTION`
- `BACKEND_ROUTE_REQUIRED`
- `PARTIAL`
- `BUSINESS_RULE_REQUIRED`
- `FUTURE`
- `AUDIT_ONLY`

A deterministic function existing in code does not automatically mean product UI
is ready. `READY_PROJECTION` must not be shown as a first-class production UI
unless route and provenance are ready.

## Prohibited Patterns

Future implementation agents must not:

- invent a chart because it looks nice;
- select visualization without policy lookup;
- create cards for every metric;
- expose `READY_PROJECTION` as production-ready UI without route/provenance;
- fill empty screens with fake content;
- use unsupported business statuses;
- put business calculations in JavaScript;
- average percentages, shares, distribution, or velocity unsafely;
- fill missing periods with zero;
- add map, pie, gauge, radar, or multi-axis charts decoratively;
- make positive green equal good by default;
- introduce duplicate filters/context;
- preserve bad UI solely because it already exists.

## Lifecycle Requirements

Before code, every dashboard/UI task must read:

- Dashboard Presentation Catalog.
- Dashboard Capability Matrix.
- Dashboard Visualization Policy.
- Dashboard Screen Specification.

It must classify:

- business question;
- screen;
- metric concepts;
- readiness;
- visualization type;
- period mode;
- grain;
- provenance and private-label behavior.

After implementation, dashboard/UI units require:

- rendered inspection where a UI is changed;
- PRIVATE real-data inspection when private runtime behavior is affected;
- FMCG usefulness review;
- BI visualization review;
- B2B UI/UX review;
- architecture review where contracts change;
- business-rule review where semantics are affected.

Tests are required evidence, not a substitute for review.

## Versioning

The current policy version is `dashboard_visualization_policy.v1.1.0`.

Semantic design changes require a version bump. CSS-only implementation changes
do not require a policy version bump unless they alter screen hierarchy,
visualization choice, or user-facing analytical meaning.

## Public Safety

This policy is retailer-neutral. It must not include real retailer names, brands,
SKU, store names, source columns, private source paths, private thresholds, or
private business-rule excerpts.
