"""Local server entrypoint for the dashboard WSGI app."""

from __future__ import annotations

import argparse
from wsgiref.simple_server import make_server

from retail_analytics.dashboard.app import create_dashboard_wsgi_app


def main() -> None:
    """Run the dashboard with the synthetic/public-safe runtime."""

    parser = argparse.ArgumentParser(description="Run the dashboard web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    with make_server(args.host, args.port, create_dashboard_wsgi_app()) as server:
        print(f"Dashboard listening on http://{args.host}:{args.port}/", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
