#!/usr/bin/env python3
"""Azure Retail Prices API에서 리전의 v7 VM Linux on-demand 시간당 가격(USD)을 JSON으로 저장합니다.

사용법: prices.py <region> <output.json> [sku-substring]
"""
import json
import sys
import urllib.parse
import urllib.request

region, out = sys.argv[1], sys.argv[2]
needle = sys.argv[3] if len(sys.argv) > 3 else "_v7"
flt = (f"serviceName eq 'Virtual Machines' and armRegionName eq '{region}' "
       f"and priceType eq 'Consumption' and contains(armSkuName, '{needle}')")
url = "https://prices.azure.com/api/retail/prices?" + urllib.parse.urlencode({"$filter": flt})
prices = {}
while url:
    with urllib.request.urlopen(url, timeout=60) as r:
        page = json.load(r)
    for it in page["Items"]:
        name = it.get("productName", "") + " " + it.get("skuName", "")
        if "Windows" in name or "Spot" in name or "Low Priority" in name:
            continue
        prices[it["armSkuName"]] = it["retailPrice"]
    url = page.get("NextPageLink")
json.dump(dict(sorted(prices.items())), open(out, "w"), indent=1)
print(f"{len(prices)} SKUs -> {out}")
