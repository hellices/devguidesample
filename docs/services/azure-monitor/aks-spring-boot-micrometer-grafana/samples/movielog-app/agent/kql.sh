#!/usr/bin/env bash
# Runs a KQL query against Application Insights and prints the result as a table.
# Usage: kql.sh <query-file.kql>   (needs APPINSIGHTS_APP_ID, or APPINSIGHTS_NAME + RESOURCE_GROUP)
set -euo pipefail

query_file="${1:?usage: kql.sh <query-file.kql>}"
app_id="${APPINSIGHTS_APP_ID:-}"
if [[ -z "$app_id" ]]; then
  app_id="$(az monitor app-insights component show \
    --resource-group "${RESOURCE_GROUP:?set RESOURCE_GROUP}" \
    --app "${APPINSIGHTS_NAME:?set APPINSIGHTS_NAME}" \
    --query appId -o tsv)"
fi

az monitor app-insights query --app "$app_id" --analytics-query "$(cat "$query_file")" -o json \
  | python3 -c '
import json, sys
table = json.load(sys.stdin)["tables"][0]
names = [c["name"] for c in table["columns"]]
rows = [[("" if v is None else str(v)) for v in row] for row in table["rows"]]
widths = [max([len(n)] + [len(r[i]) for r in rows]) for i, n in enumerate(names)]
print("  ".join(n.ljust(w) for n, w in zip(names, widths)))
print("  ".join("-" * w for w in widths))
for r in rows:
    print("  ".join(v.ljust(w) for v, w in zip(r, widths)))
print(f"({len(rows)} rows)")
'
