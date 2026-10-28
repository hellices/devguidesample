"""Set the default data source of the SQL Server dashboard and wrap it for the Grafana API.

Usage:
    python3 render_dashboard.py <dashboard.json> <prometheus-datasource-uid> > payload.json
"""

import json
import sys
from pathlib import Path


def render(dashboard, datasource_uid):
    dashboard = json.loads(json.dumps(dashboard))
    for variable in dashboard["templating"]["list"]:
        if variable["name"] == "datasource":
            variable["current"] = {"selected": True, "text": datasource_uid, "value": datasource_uid}
    dashboard.pop("id", None)
    return {"dashboard": dashboard, "overwrite": True}


def main(argv):
    dashboard = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    json.dump(render(dashboard, argv[2]), sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv)
