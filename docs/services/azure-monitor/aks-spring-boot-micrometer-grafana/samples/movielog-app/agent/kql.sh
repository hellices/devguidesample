#!/usr/bin/env bash
# Runs a KQL query against Application Insights and prints the result as a table.
# Usage: kql.sh <query-file.kql>   (needs APPINSIGHTS_APP_ID, or APPINSIGHTS_NAME + RESOURCE_GROUP)
# The CLI also limits every query to the last KQL_OFFSET (default 1h, format ##d##h), on top of
# the query's own time filter; raise it to look further back.
set -euo pipefail

query_file="${1:?usage: kql.sh <query-file.kql>}"
app_id="${APPINSIGHTS_APP_ID:-}"
if [[ -z "$app_id" ]]; then
  app_id="$(az monitor app-insights component show \
    --resource-group "${RESOURCE_GROUP:?set RESOURCE_GROUP}" \
    --app "${APPINSIGHTS_NAME:?set APPINSIGHTS_NAME}" \
    --query appId -o tsv)"
fi

query="$(cat -- "$query_file")"
az monitor app-insights query --app "$app_id" --offset "${KQL_OFFSET:-1h}" \
  --analytics-query "$query" -o json \
  | python3 -c '
import json, sys, unicodedata
table = json.load(sys.stdin)["tables"][0]

ESCAPES = {"\\": "\\\\", "\r": "\\r", "\n": "\\n", "\t": "\\t"}

def cell(value):
    # One line per cell, and no raw control characters (ESC, backspace, ...) reach the terminal.
    text = "" if value is None else str(value)
    out = []
    for ch in text:
        if ch in ESCAPES:
            out.append(ESCAPES[ch])
        elif not ch.isprintable():
            out.append(f"\\x{ord(ch):02x}" if ord(ch) < 0x100 else f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)

def width(text):
    # Terminal columns: East Asian wide/fullwidth characters take two, combining marks none.
    return sum(0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in text)

def pad(text, cols):
    return text + " " * (cols - width(text))

names = [cell(c["name"]) for c in table["columns"]]
rows = [[cell(v) for v in row] for row in table["rows"]]
widths = [max([width(n)] + [width(r[i]) for r in rows]) for i, n in enumerate(names)]
print("  ".join(pad(n, w) for n, w in zip(names, widths)))
print("  ".join("-" * w for w in widths))
for r in rows:
    print("  ".join(pad(v, w) for v, w in zip(r, widths)))
print(f"({len(rows)} rows)")
'
