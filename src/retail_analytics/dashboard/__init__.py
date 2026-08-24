"""Web dashboard shell over deterministic mart query contracts."""

from retail_analytics.dashboard.app import create_dashboard_wsgi_app
from retail_analytics.dashboard.runtime import (
    DashboardRuntime,
    DashboardRuntimeConfig,
    DashboardRuntimeMode,
    DashboardRuntimeRetailer,
    build_dashboard_runtime,
    build_private_dashboard_runtime,
    build_synthetic_dashboard_runtime,
    load_dashboard_runtime_config,
)
from retail_analytics.dashboard.schemas import (
    DashboardUiQueryPayload,
    DashboardUiRuntimeResponse,
    build_backend_query_request,
    serialize_dashboard_query_response,
)

__all__ = [
    "DashboardRuntime",
    "DashboardRuntimeConfig",
    "DashboardRuntimeMode",
    "DashboardRuntimeRetailer",
    "DashboardUiQueryPayload",
    "DashboardUiRuntimeResponse",
    "build_backend_query_request",
    "build_dashboard_runtime",
    "build_private_dashboard_runtime",
    "build_synthetic_dashboard_runtime",
    "create_dashboard_wsgi_app",
    "load_dashboard_runtime_config",
    "serialize_dashboard_query_response",
]
