#!/usr/bin/env python3
"""ACR가 내보낸 RDB를 Azure Managed Redis로 import한다.

이 스크립트가 단순한 `az redisenterprise database import` 한 줄이 아닌 이유는
실제 엔터프라이즈 테넌트의 제약 때문이다.

1. import API는 SAS URI만 받는다. 관리 ID 옵션이 없다.
2. 그런데 많은 테넌트가 정책으로 스토리지 계정의 공유 키를 비활성화한다.
   공유 키가 없으면 계정 키 기반 SAS를 만들 수 없다.

그래서 Entra 기반 '사용자 위임 SAS'를 만들어 쓴다. SAS는 그 자체가 자격
증명이므로, 발급과 사용을 같은 프로세스 안에서 끝내 밖으로 흘리지 않는다.

사용법:
    python3 import_rdb.py --account <sa> --container <c> --blob <b> --database-id <arm-id>
"""

import argparse
import datetime
import json
import sys
import time
import urllib.error
import urllib.request

from azure.identity import ManagedIdentityCredential
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas

POLL_INTERVAL = 10
SAS_HOURS = 3


def build_sas_uri(cred, account, container, blob):
    svc = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=cred)
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(minutes=5)  # 시계 오차 여유
    expiry = now + datetime.timedelta(hours=SAS_HOURS)

    udk = svc.get_user_delegation_key(start, expiry)
    print("사용자 위임 키 획득 OK", flush=True)

    sas = generate_blob_sas(
        account_name=account,
        container_name=container,
        blob_name=blob,
        user_delegation_key=udk,
        permission=BlobSasPermissions(read=True),
        start=start,
        expiry=expiry,
    )
    return f"https://{account}.blob.core.windows.net/{container}/{blob}?{sas}"


def run_import(arm_token, database_id, sas_uri, api_version):
    body = json.dumps({"sasUris": [sas_uri]}).encode()
    req = urllib.request.Request(
        f"https://management.azure.com{database_id}/import?api-version={api_version}",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {arm_token}", "Content-Type": "application/json"},
    )

    started = datetime.datetime.now(datetime.timezone.utc)
    t0 = time.time()
    print(f"IMPORT 시작 {started.isoformat()}", flush=True)

    try:
        resp = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        # 오류 본문에 SAS가 섞여 나올 수 있으므로 그대로 찍지 않는다.
        detail = e.read().decode(errors="replace")
        print(f"IMPORT 요청 실패 HTTP {e.code}: {detail[:800].replace(sas_uri, '<SAS>')}", flush=True)
        return None

    poll = resp.headers.get("Azure-AsyncOperation") or resp.headers.get("Location")
    print(f"요청 수락 HTTP {resp.status}", flush=True)

    status = None
    while poll:
        time.sleep(POLL_INTERVAL)
        r = urllib.request.Request(poll, headers={"Authorization": f"Bearer {arm_token}"})
        payload = urllib.request.urlopen(r).read().decode() or "{}"
        d = json.loads(payload)
        status = d.get("status") or d.get("properties", {}).get("provisioningState")
        print(f"[{time.time() - t0:6.0f}s] {status}", flush=True)
        if status in ("Succeeded", "Failed", "Canceled"):
            if status != "Succeeded":
                print(json.dumps(d, indent=2)[:1500], flush=True)
            break

    ended = datetime.datetime.now(datetime.timezone.utc)
    print(f"IMPORT 종료 {ended.isoformat()} 소요 {time.time() - t0:.1f}s 상태 {status}", flush=True)
    return {
        "status": status,
        "started_at_ms": int(started.timestamp() * 1000),
        "ended_at_ms": int(ended.timestamp() * 1000),
        "duration_sec": round(time.time() - t0, 1),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--account", required=True)
    p.add_argument("--container", required=True)
    p.add_argument("--blob", required=True)
    p.add_argument("--database-id", required=True, help="AMR database의 ARM 리소스 ID")
    p.add_argument("--api-version", default="2025-04-01")
    p.add_argument("--report", help="결과 JSON 경로")
    args = p.parse_args()

    cred = ManagedIdentityCredential()
    sas_uri = build_sas_uri(cred, args.account, args.container, args.blob)
    arm_token = cred.get_token("https://management.azure.com/.default").token

    result = run_import(arm_token, args.database_id, sas_uri, args.api_version)
    if result is None:
        return 1

    if args.report:
        with open(args.report, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"결과 저장: {args.report}", flush=True)
    return 0 if result["status"] == "Succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())
