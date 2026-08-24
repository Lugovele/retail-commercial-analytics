# Dashboard Presentation Catalog

This document defines publication-safe presentation terminology for the
`Аналитика продаж` dashboard. It maps internal deterministic backend concepts to
Russian user-facing labels and display placement.

It does not define business formulas, thresholds, metric semantics, or retailer
private rules. Internal identifiers remain English; user-facing labels are
Russian.

## Scope

Sources checked for this catalog:

- `config/public/dashboard_metric_catalog.yaml`
- `src/retail_analytics/dashboard/`
- `src/retail_analytics/mart/metric_catalog.py`
- `src/retail_analytics/mart/query.py`
- `src/retail_analytics/mart/portfolio.py`
- `src/retail_analytics/mart/rankings.py`
- `src/retail_analytics/mart/comparison_universe.py`
- `src/retail_analytics/mart/geography.py`
- public mart architecture docs

## UI Navigation

Main dashboard tabs:

| Tab | Purpose |
| --- | --- |
| Данные | Source-like rows and audit access. |
| Показатели | Core numeric metrics from the mart query layer. |
| Бизнес-оценки | Deterministic derived analytics and scoped business projections. |
| Сигналы | Confirmed deterministic signals and capability limitations. |
| Рекомендации | Placeholder until deterministic recommendation backend exists. |

Metric groups:

| Group | Purpose |
| --- | --- |
| Продажи | Revenue and unit sales. |
| Экономика | Margin and profitability. |
| Присутствие | Store presence, distribution, and velocity. |
| Цена | Shelf/input price metrics. |
| Структура | Assortment and active entity counts. |
| Доли | Share metrics with explicit denominator scope. |
| Рейтинги | Ranking projections. |
| ABC | Confirmed ABC classifications and future SKU tiering projections. |
| Конкуренты | Benchmarking and peer-related projections. |
| География | Regional projections where source geography is mapped. |

Presentation levels:

| Level | Meaning |
| --- | --- |
| `TOP_KPI` | May appear in compact KPI cards. |
| `DEFAULT_TABLE` | Default table column for the relevant group/tab. |
| `OPTIONAL_COLUMN` | Available as a selectable table/detail column. |
| `AUDIT_ONLY` | Available for provenance, limitation, or analyst review, not a default user metric. |

Principle: all confirmed data may be accessible, but not all columns are shown at
once.

## Terminology Decisions

Primary revenue convention: `Оборот`.

Alias: `РТО` may be used in private/customer-facing materials if a retailer or
business team requires it, but the generic public UI uses `Оборот`.

Comparison labels:

| Internal mode | User-facing label |
| --- | --- |
| `YOY` | Год к году |
| `MOM` | Месяц к месяцу |
| `PREVIOUS_AVAILABLE` | Предыдущий доступный период |
| `NONE` | Без сравнения |

Private-label terminology:

- Backend contract: `private_label_scope`.
- Generic description: `Учёт собственной марки`.
- Current retailer display may use `Учёт СТМ` through private/runtime display
  configuration.
- Public code must not hardcode retailer-specific private-label semantics.

Traceability action:

`Откуда эта цифра?`

Audit hierarchy:

```text
Исходные данные
→ Показатель
→ Сравнение
→ Бизнес-правило
→ Бизнес-оценка / сигнал
→ Рекомендация
```

## Core Metric Catalog

These concepts are present in the public metric catalog. Readiness for a concrete
retailer/source is still determined by the effective catalog and private
availability overrides.

| Internal concept | User-facing name | Description | Unit/format | Tab | Group | Presentation level | Grain applicability | Known limitation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `revenue_vat` | Оборот с НДС | Оборот с НДС из deterministic metric outputs. | currency | Показатели | Продажи | TOP_KPI | network, category, manufacturer, brand, SKU, ТТ when available | Range-safe as sum over available periods. |
| `revenue` | Оборот без НДС | Оборот без НДС из deterministic metric outputs. | currency | Показатели | Продажи | TOP_KPI | network, category, manufacturer, brand, SKU, ТТ when available | Range-safe as sum over available periods. |
| `units` | Продажи, шт. | Продажи в штуках из deterministic metric outputs. | decimal | Показатели | Продажи | TOP_KPI | network, category, manufacturer, brand, SKU, ТТ when available | Range-safe as sum over available periods. |
| `retailer_margin_abs` | Абсолютная маржа | Абсолютная маржа из deterministic metric outputs. | currency | Показатели | Экономика | TOP_KPI | network, category, manufacturer, brand, SKU, ТТ when available | Range-safe as sum over available periods. |
| `retailer_margin_pct` | Маржинальность | Маржинальность; range-safe только через сохранённые numerator и denominator. | percent | Показатели | Экономика | TOP_KPI | network, category, manufacturer, brand, SKU, ТТ when numerator/denominator are available | Range value must be ratio of summed components, not average of period percentages. |
| `weighted_shelf_price_vat` | Средняя полочная цена с НДС | Средневзвешенная полочная цена с НДС из deterministic metric outputs. | currency | Показатели | Цена | DEFAULT_TABLE | network, category, manufacturer, brand, SKU, ТТ when available | Range value must be weighted from stored components, not arithmetic average. |
| `weighted_input_price_vat` | Средняя входная цена с НДС | Средневзвешенная входная цена с НДС из deterministic metric outputs. | currency | Показатели | Цена | DEFAULT_TABLE | network, category, manufacturer, brand, SKU, ТТ when available | Range value must be weighted from stored components, not arithmetic average. |
| `selling_store_count` | ТТ с продажами | Количество ТТ с продажами на уровне периода. | integer | Показатели | Присутствие | DEFAULT_TABLE | category, manufacturer, brand, SKU; network where defined | Period-only in current catalog. |
| `active_store_count` | Активные ТТ | Количество активных ТТ на уровне периода. | integer | Показатели | Присутствие | OPTIONAL_COLUMN | network/category where defined | Period-only in current catalog. |
| `distribution` | Дистрибуция | Дистрибуция на уровне периода; arbitrary selected-range recomputation не объявлен. | percent | Показатели | Присутствие | DEFAULT_TABLE | category, manufacturer, brand, SKU where defined | Arbitrary range aggregation is not declared; do not average periods. |
| `velocity` | Продажи на ТТ | Продажи на ТТ на уровне периода; arbitrary selected-range recomputation не объявлен. | ratio | Показатели | Присутствие | DEFAULT_TABLE | category, manufacturer, brand, SKU where defined | Period-only; do not average periods. |
| `revenue_velocity` | Оборот на ТТ | Оборот на ТТ на уровне периода. | currency | Показатели | Присутствие | OPTIONAL_COLUMN | category, manufacturer, brand, SKU where defined | Period-only; do not average periods. |
| `margin_velocity` | Маржа на ТТ | Маржа на ТТ на уровне периода. | currency | Показатели | Присутствие | OPTIONAL_COLUMN | category, manufacturer, brand, SKU where defined | Period-only; do not average periods. |
| `sku_count` | SKU в периоде | Количество distinct SKU на уровне периода. | integer | Показатели | Структура | TOP_KPI | network, category, manufacturer, brand where defined | Period-only; selected-range count requires explicit contract. |
| `brand_count` | Активные бренды | Количество distinct брендов на уровне периода. | integer | Показатели | Структура | OPTIONAL_COLUMN | network, category, manufacturer where defined | Period-only; do not infer delisting from one missing period. |
| `category_count` | Категории | Количество distinct категорий на уровне периода. | integer | Показатели | Структура | OPTIONAL_COLUMN | network/manufacturer where defined | Period-only. |
| `category_revenue_share` | Доля в обороте категории | Долевая метрика; selected-range support требует объявленный numerator и denominator scope. | percent | Показатели | Доли | DEFAULT_TABLE | manufacturer, brand, SKU where denominator scope is declared | Range support requires declared numerator/denominator scope; do not average monthly shares. |
| `category_units_share` | Доля в штуках категории | Долевая метрика; selected-range support требует объявленный numerator и denominator scope. | percent | Показатели | Доли | OPTIONAL_COLUMN | manufacturer, brand, SKU where denominator scope is declared | Range support requires declared numerator/denominator scope; do not average monthly shares. |
| `category_margin_share` | Доля в марже категории | Долевая метрика; selected-range support требует объявленный numerator и denominator scope. | percent | Показатели | Доли | OPTIONAL_COLUMN | manufacturer, brand, SKU where denominator scope is declared | Range support requires declared numerator/denominator scope; do not average monthly shares. |

## Extended Dashboard Projections

These concepts are implemented as deterministic backend projections, not as new
metric formulas in the frontend. They should be surfaced through backend/query
contracts or future presentation adapters only when the selected retailer/source
availability supports them.

| Internal concept | User-facing name | Description | Unit/format | Tab | Group | Presentation level | Grain applicability | Known limitation |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `manufacturer_rank_revenue` | Место производителя по обороту | Manufacturer rank by summed revenue within category. | integer | Бизнес-оценки | Рейтинги | DEFAULT_TABLE | manufacturer within category | Competition-rank ties; scope is category only. |
| `manufacturer_rank_units` | Место производителя по штукам | Manufacturer rank by summed units within category. | integer | Бизнес-оценки | Рейтинги | DEFAULT_TABLE | manufacturer within category | Competition-rank ties; scope is category only. |
| `manufacturer_population_count` | Производителей в рейтинге | Population count used for manufacturer rank. | integer | Бизнес-оценки | Рейтинги | OPTIONAL_COLUMN | manufacturer within category | Must match the same category/period/private-label scope as rank. |
| `active_sku_count` | Активные SKU | SKU with positive unit sales in the selected current period. | integer | Бизнес-оценки | Структура | TOP_KPI | portfolio/category scope | Current source supports sales-based activity, not listing intent. |
| `historical_peak_active_sku_count` | Пиковое число активных SKU | Highest active SKU count across available evaluated periods. | integer | Бизнес-оценки | Структура | DEFAULT_TABLE | portfolio/category scope | Uses available periods only; missing calendar periods are not fake zeroes. |
| `active_sku_change_pct` | Изменение активных SKU от пика | Current active SKU count compared with historical peak. | percent | Бизнес-оценки | Структура | OPTIONAL_COLUMN | portfolio/category scope | Undefined when peak count is zero. |
| `brand_category_delta_gap_pp` | Отклонение бренда от категории | Brand growth-rate delta minus category growth-rate delta. | percentage_points | Бизнес-оценки | Структура | DEFAULT_TABLE | brand within category | Requires valid current/reference periods and matching metric. |
| `brand_delta_pct` | Изменение бренда | Brand metric change versus reference period. | percent | Бизнес-оценки | Структура | OPTIONAL_COLUMN | brand within category | Not a growth/decline status by itself. |
| `category_delta_pct` | Изменение категории | Category metric change versus reference period. | percent | Бизнес-оценки | Структура | OPTIONAL_COLUMN | category | Not a status by itself. |
| `market_segment_delta_pct` | Изменение сегмента рынка | Current/reference change for an explicit comparison universe. | percent | Бизнес-оценки | Конкуренты | DEFAULT_TABLE | total market, market excluding private label, private label, own portfolio | Supports only approved metrics: net/gross revenue and units. |
| `decline_speed_ratio` | Отношение темпов снижения | Ratio of portfolio decline to market decline. | ratio | Бизнес-оценки | Конкуренты | OPTIONAL_COLUMN | own portfolio vs market comparison | Emitted only when both deltas are valid declines and market decline is non-zero. |
| `private_label_growth_while_portfolio_declines` | Собственная марка растёт, портфель снижается | Neutral deterministic pattern signal. | text | Сигналы | Конкуренты | OPTIONAL_COLUMN | private-label universe vs own portfolio | Pattern only; no causal claim. |
| `regional_revenue` | Оборот региона | Regional net revenue over selected period/range. | currency | Бизнес-оценки | География | DEFAULT_TABLE | region | Requires mapped region field. |
| `regional_units` | Продажи региона, шт. | Regional unit sales over selected period/range. | decimal | Бизнес-оценки | География | OPTIONAL_COLUMN | region | Requires mapped region field. |
| `regional_margin_abs` | Маржа региона | Regional absolute margin over selected period/range. | currency | Бизнес-оценки | География | OPTIONAL_COLUMN | region | Requires mapped region field. |
| `regional_share_revenue` | Доля региона в обороте | Region revenue divided by scoped total revenue. | percent | Бизнес-оценки | География | DEFAULT_TABLE | region | Recomputed from scoped totals; do not average period shares. |

## Partial Or Audit-Only Concepts

| Concept area | User-facing term | Status | Presentation level | Limitation |
| --- | --- | --- | --- | --- |
| SKU tiering | Tiering SKU / ABC SKU | PARTIAL | AUDIT_ONLY | Business resolution says future display must reuse confirmed ABC only if explicitly approved for the dashboard context. Do not add a separate tiering algorithm. |
| Brand status labels | Рост / Падение / Критично / Делистинг | PARTIAL | AUDIT_ONLY | Composite evaluative labels are not ready without business policy. Safe factual presence states may be shown separately. |
| Direct peers | Прямые аналоги | PARTIAL | AUDIT_ONLY | Flavor semantic gap remains outside current dashboard-ready presentation. |
| Broad competitors | Конкуренты категории | PARTIAL | OPTIONAL_COLUMN | Broad pool exists, but dashboard presentation must keep direct and broad scopes separate. |
| Events | События | PARTIAL | AUDIT_ONLY | Scope-aware event views are limited; do not show full-universe events as scoped results. |
| EDLP/stability | Стабильность цены | NOT_AVAILABLE | AUDIT_ONLY | Window semantics remain unresolved. |
| Recommendations | Рекомендации | NOT_AVAILABLE | AUDIT_ONLY | Placeholder only until deterministic recommendation backend exists. |

## Unit and Delta Display Rules

| Format | Display rule |
| --- | --- |
| `currency` | Currency-style number; concrete currency sign is UI/runtime locale concern. |
| `integer` | Whole number. |
| `decimal` | Decimal number with compact precision. |
| `percent` | Percentage value. Relative deltas also use `%`. |
| `percentage_points` | Share or percentage-rate absolute delta shown as `п.п.`. |
| `ratio` | Ratio or per-store metric with explicit unit context. |
| `text` | Status, limitation, or signal code translated by the presentation layer. |

`%` and `п.п.` must not be interchanged. Share deltas and margin-rate deltas use
percentage points for absolute difference; relative growth rates use percent.

## Unsupported Presentation Claims

The dashboard must not present the following as confirmed metrics:

- arithmetic averages of margin percentages, shares, distribution, or velocity;
- custom date-range ABC unless an explicit rule is approved;
- evaluative brand statuses without approved composite policy;
- causal private-label replacement claims;
- fake recommendation text;
- missing calendar months as zero values.

## Public Safety

The catalog is retailer-neutral. Real retailer names, real SKU/store identifiers,
private rule thresholds, and private source column names belong in ignored private
configuration or validation artifacts, not in this public document.
