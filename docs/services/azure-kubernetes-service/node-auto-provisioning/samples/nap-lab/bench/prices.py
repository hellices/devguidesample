#!/usr/bin/env python3
"""Azure Retail Prices API에서 리전 VM의 Linux on-demand 시간당 가격(USD)을 JSON으로 저장합니다.

사용법: prices.py <region> <output.json> [sku-substring]
  sku-substring을 생략하면 '_v7'을 armSkuName에 포함한 SKU만 받습니다.
  가격을 하나도 받지 못하면 파일을 만들지 않고 실패합니다. 파일은 다 받은 뒤 한 번에 바꿉니다.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

if len(sys.argv) not in (3, 4):
    sys.exit("사용법: prices.py <region> <output.json> [sku-substring]")
region, out = sys.argv[1], sys.argv[2]
needle = sys.argv[3] if len(sys.argv) > 3 else "_v7"


def lit(v):  # OData 문자열 리터럴: 작은따옴표는 두 번 써서 이스케이프합니다.
    return "'" + v.replace("'", "''") + "'"


flt = (f"serviceName eq 'Virtual Machines' and armRegionName eq {lit(region)} "
       f"and priceType eq 'Consumption' and contains(armSkuName, {lit(needle)})")
url = "https://prices.azure.com/api/retail/prices?" + urllib.parse.urlencode({"$filter": flt})
prices = {}
while url:
    with urllib.request.urlopen(url, timeout=60) as r:
        page = json.load(r)
    for it in page["Items"]:
        # Linux on-demand meter만 씁니다. 기본 Linux 상품명은 "… Series"나 "…-series Linux"로 다르므로
        # OS 접미사가 아니라 Windows·Spot·Low Priority 제외로 거릅니다.
        name = it.get("productName", "") + " " + it.get("skuName", "")
        if "Windows" in name or "Spot" in name or "Low Priority" in name:
            continue
        sku, price = it["armSkuName"], it["retailPrice"]
        # 같은 SKU에 다른 가격이 오면 응답 순서에 따라 값이 바뀌지 않도록 임의로 고르지 않고 실패합니다.
        if sku in prices and prices[sku] != price:
            sys.exit(f"{sku}의 Linux on-demand 가격이 둘 이상입니다: {prices[sku]}, {price}")
        prices[sku] = price
    url = page.get("NextPageLink")
if not prices:
    sys.exit(f"가격을 찾지 못했습니다: region={region} sku-substring={needle}")
# 중간에 실패해도 불완전한 파일이 남지 않도록 같은 디렉터리의 임시 파일에 쓴 뒤 바꿉니다.
tmp = f"{out}.tmp"
with open(tmp, "w") as f:
    json.dump(dict(sorted(prices.items())), f, indent=1)
os.replace(tmp, out)
print(f"{len(prices)} SKUs -> {out}")
