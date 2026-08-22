# Retail Commercial Analytics

Retail Commercial Analytics is a generic analytics engine for retail and commercial data. It is designed to support multiple retailer contexts without embedding client-identifying data in the public codebase.

The project separates a public analytics engine from a private semantic and configuration layer. The canonical model standardizes data shape across sources, while retailer-specific metric definitions, event rules, decision rules, thresholds, and mappings are supplied through configuration.

Deterministic analytics is performed by code. LLM usage, when introduced later, must happen only after a validated Evidence Pack has been produced, and must not calculate arithmetic, rewrite facts, infer missing data, or make unsupported causal claims.

Public files must remain publication-safe. Real client data, source-column mappings, retailer mappings, business definitions, metric rules, decision rules, and private notes belong only in private deployment context directories such as `config/private/` and `data/private/`.