"""Local server entrypoint for the dashboard WSGI app."""

from __future__ import annotations

import argparse
from wsgiref.simple_server import make_server

from retail_analytics.dashboard.app import create_dashboard_wsgi_app
from retail_analytics.dashboard.runtime import build_dashboard_runtime


def main() -> None:
    """Run the dashboard with an explicit demo or private runtime."""

    parser = argparse.ArgumentParser(description="Run the dashboard web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument(
        "--mode",
        choices=("DEMO", "PRIVATE", "PRODUCTION"),
        default="DEMO",
        help="Runtime mode. PRIVATE/PRODUCTION require --config or RETAIL_ANALYTICS_DASHBOARD_CONFIG.",
    )
    parser.add_argument("--config", help="Path to generic private dashboard runtime YAML.")
    args = parser.parse_args()
    runtime = build_dashboard_runtime(mode=args.mode, config_path=args.config)
    with make_server(args.host, args.port, create_dashboard_wsgi_app(runtime)) as server:
        print(f"Dashboard listening on http://{args.host}:{args.port}/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
