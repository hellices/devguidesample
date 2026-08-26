# migration-lab

Azure Cache for Redis(ACR) → Azure Managed Redis(AMR) 마이그레이션을 **GB 규모에서 실제로 돌려 보기 위한** 스크립트 모음입니다.
측정 결과와 해석은 [../azure-cache-to-managed-redis-migration.md](../azure-cache-to-managed-redis-migration.md)에 정리했습니다.

소규모(수십 개 키) 테스트로는 마이그레이션의 진짜 비용이 보이지 않습니다. 복사가 순식간에 끝나서
"복사하는 동안 들어온 쓰기를 잃는 구간"이 드러나지 않기 때문입니다. 이 랩은 그 구간을 숫자로 만드는 것이 목적입니다.

## 스크립트

| 파일 | 역할 |
|---|---|
| `load_data.py` | 타입·값 크기를 섞은 GB 규모 테스트 데이터를 소스에 적재 |
| `concurrent_writer.py` | 마이그레이션 중 소스에 일정 속도로 프로브 키를 쓰고 로컬에 기록 |
| `migrate_scan_copy.py` | `SCAN` + 파이프라인 `DUMP`/`PTTL` → `RESTORE`로 복사 (경로 B) |
| `import_rdb.py` | RDB Export/Import 경로(A) 보조 |
| `verify_migration.py` | 쓰기 유실·TTL 보존·값 무결성 검증 |
| `results/` | 실측 결과 JSON |

## 사전 조건

- 소스 ACR과 타깃 AMR에 TCP로 닿는 리눅스 호스트 (같은 리전 VM 권장 — 클라이언트 왕복 지연이 그대로 복사 시간이 됩니다)
- Python 3.8+, `pip install redis`
- **타깃 AMR 데이터베이스는 `--clustering-policy EnterpriseCluster`로 생성**되어 있어야 합니다.
  기본값인 `OSSCluster`에서는 비클러스터 클라이언트가 `MOVED`/`CROSSSLOT`으로 실패하며,
  이 값은 **생성 후 변경할 수 없습니다**.

```bash
az redisenterprise database create \
  --cluster-name <amr-name> --resource-group <rg> \
  --clustering-policy EnterpriseCluster --access-keys-auth Enabled
```

## 실행 순서

```bash
export SRC_HOST=<acr>.redis.cache.windows.net SRC_PORT=6380 SRC_KEY=...
export DST_HOST=<amr>.<region>.redis.azure.net DST_PORT=10000 DST_KEY=...

# 1. 테스트 데이터 적재
python3 load_data.py --host "$SRC_HOST" --port "$SRC_PORT" --password "$SRC_KEY" --target-gb 4

# 2. 마이그레이션 중 쓰기 부하 시작 (실행마다 --prefix를 다르게)
python3 concurrent_writer.py --host "$SRC_HOST" --port "$SRC_PORT" --password "$SRC_KEY" \
  --rate 200 --prefix run1 --log probes.jsonl &

# 3. 복사 (수렴시키려면 같은 명령을 반복 실행)
python3 migrate_scan_copy.py \
  --src-host "$SRC_HOST" --src-port "$SRC_PORT" --src-password "$SRC_KEY" \
  --dst-host "$DST_HOST" --dst-port "$DST_PORT" --dst-password "$DST_KEY" \
  --report pass1.json

# 4. 쓰기 차단 후 최종 패스 → 이 패스의 duration_sec이 실제로 필요한 다운타임입니다
touch /tmp/writer.stop
python3 migrate_scan_copy.py ... --report final.json

# 5. 검증
python3 verify_migration.py \
  --src-host "$SRC_HOST" --src-port "$SRC_PORT" --src-password "$SRC_KEY" \
  --dst-host "$DST_HOST" --dst-port "$DST_PORT" --dst-password "$DST_KEY" \
  --probe-log probes.jsonl --report verify.json
```

## 측정 시 주의

- **프로브 접두사를 실행마다 바꾸세요.** 이전 실행의 잔여 프로브 키가 섞이면 유실률이 실제보다 낮게 나옵니다.
  실제로 접두사를 고정한 채 재실행했을 때 이전 값이 타깃에 남아 측정이 오염되는 것을 확인했습니다.
- **`EXISTS`로 검증하지 마세요.** 키는 있는데 값이 옛것인 경우를 놓칩니다.
  `verify_migration.py`는 프로브 값(= 기록된 쓰기 시각)까지 대조합니다.
- **`DUMP` 페이로드를 바이트 비교하지 마세요.** RDB 버전 푸터가 들어 있어
  ACR(Redis 6.x)과 AMR(Redis 7.x) 사이에서는 값이 같아도 전부 불일치로 나옵니다. 타입별로 실제 값을 비교해야 합니다.
- **표본은 `RANDOMKEY`로 뽑으세요.** `SCAN` 앞부분만 모으면 먼저 적재된 키에 표본이 쏠려,
  뒤쪽에서 발생하는 유실을 놓칩니다.
- `migrate_scan_copy.py`는 **소스를 절대 수정하지 않습니다.** `--flush-target`은 타깃에만 적용됩니다.

## 정리

테스트가 끝나면 리소스 그룹을 통째로 삭제하세요. Premium P1 + Balanced_B5 + VM 조합은 방치하면 비용이 큽니다.

```bash
az group delete --name <rg> --yes --no-wait
```
