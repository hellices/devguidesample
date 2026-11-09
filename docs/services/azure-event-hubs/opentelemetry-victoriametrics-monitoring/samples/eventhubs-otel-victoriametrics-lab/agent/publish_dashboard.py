"""Publish a dashboard JSON to Grafana with the admin credentials from the environment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from verify_panels import grafana_request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dashboard", type=Path)
    args = parser.parse_args()
    result = grafana_request(
        os.environ["GRAFANA_URL"].rstrip("/"),
        os.environ.get("GRAFANA_USER", "admin"),
        os.environ["GRAFANA_PASSWORD"],
        "/api/dashboards/db",
        {"dashboard": json.loads(args.dashboard.read_text()), "overwrite": True,
         "message": "agent build"},
    )
    print(f"published {result['uid']} version={result['version']} path={result['url']}")


if __name__ == "__main__":
    main()
