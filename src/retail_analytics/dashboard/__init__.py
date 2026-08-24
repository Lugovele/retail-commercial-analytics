"""Web dashboard shell over deterministic mart query contracts."""

from retail_analytics.dashboard.app import create_dashboard_wsgi_app
from retail_analytics.dashboard.runtime import (
    DashboardRuntime,
    DashboardRuntimeRetailer,
    build_synthetic_dashboard_runtime,
)
from retail_analytics.dashboard.schemas import (
    DashboardUiQueryPayload,
    DashboardUiRuntimeResponse,
    build_backend_query_request,
    serialize_dashboard_query_response,
)

__all__ = [
    "DashboardRuntime",
    "DashboardRuntimeRetailer",
    "DashboardUiQueryPayload",
    "DashboardUiRuntimeResponse",
    "build_backend_query_request",
    "build_synthetic_dashboard_runtime",
    "create_dashboard_wsgi_app",
    "serialize_dashboard_query_response",
]
