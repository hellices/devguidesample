# migration-lab

Azure Cache for Redis(ACR) → Azure Managed Redis(AMR) 마이그레이션을 **GB 규모에서 실제로 돌려 보기 위한** 스크립트 모음입니다.
결론 숫자는 [마이그레이션 가이드](../azure-cache-to-managed-redis-migration.md)에, 측정 방법과 해석은
[이관 경로와 실측](../migration-guide/03-migration-paths.md)에 정리했습니다.

소규모(수십 개 키) 테스트로는 마이그레이션의 진짜 비용이 보이지 않습니다. 복사가 순식간에 끝나서
"복사하는 동안 들어온 쓰기를 잃는 구간"이 드러나지 않기 때문입니다. 이 랩은 그 구간을 숫자로 만드는 것이 목적입니다.

## 스크립트

| 파일 | 역할 |
|---|---|
| `audit_commands.sh` | **데이터를 옮기기 전에** 애플리케이션 소스에서 AMR 비호환 Redis 명령을 등급별로 스캔 |
| `policy_matrix_test.py` | `clusteringPolicy` × 클라이언트 조합별로 어떤 명령이 통과하는지 실측 |
| `load_data.py` | 타입·값 크기를 섞은 GB 규모 테스트 데이터를 소스에 적재 |
| `concurrent_writer.py` | 마이그레이션 중 소스에 일정 속도로 프로브 키를 쓰고 로컬에 기록 |
| `migrate_scan_copy.py` | `SCAN` + 파이프라인 `DUMP`/`PTTL` → `RESTORE`로 복사 (경로 B) |
| `import_rdb.py` | RDB Export/Import 경로(A) 보조 |
| `verify_migration.py` | 쓰기 유실·TTL 보존·값 무결성 검증 |
| `results/` | 실측 결과 JSON |

## 0. 먼저 명령어를 감사하세요

데이터 이관보다 앞서야 하는 단계입니다. 여기서 나온 결과가 `clusteringPolicy` 선택을 결정하고,
TIER 1 항목이 있으면 **코드 수정 없이는 마이그레이션 자체가 불가능**합니다.

```bash
./audit_commands.sh ../../src ../../config     # 감사할 소스 디렉터리들
echo $?                                        # TIER 1 적중이 있으면 1
```

| 등급 | 의미 | 조치 |
|---|---|---|
| TIER 1 | 다중 DB 사용, 키스페이스 알림 의존 — **정책으로 해결 안 됨** | 코드 수정 / 별도 판단 |
| TIER 2 | 허용 목록 6개 밖의 크로스 슬롯 다중 키 명령 | 해시 태그 / 로직 대체 / `NoCluster` |
| TIER 3 | 허용 목록 6개의 다중 키 호출 | `OSSCluster`를 고를 때만 문제 |
| TIER 4 | 서버·관리 명령 | 대부분 양쪽에서 차단 |

정적 스캔은 **프레임워크가 대신 호출하는 명령을 놓칩니다**(Spring Session, Celery, Sidekiq, Redisson 등).
소스 ACR에서 `INFO commandstats`나 짧은 `MONITOR` 표본으로 반드시 교차 확인하세요.
등급별 명령 목록과 근거는 [클라이언트·SDK 확인사항](../migration-guide/02-client-audit.md)에 있습니다.
무엇을 먼저 할지에 대한 우선순위는 [마이그레이션 가이드 5절](../azure-cache-to-managed-redis-migration.md#5-우선순위와-순서)에 있습니다.

## 0-1. 정책을 고르기 전에 직접 확인하고 싶다면

감사 결과가 애매하면 실제 AMR 데이터베이스를 하나씩 만들어 직접 돌려 보는 편이 빠릅니다.
`policy_matrix_test.py`가 같은 명령 집합을 **비클러스터 / 클러스터 클라이언트 두 가지로**,
**크로스 슬롯 키와 해시 태그로 모은 키 두 가지로** 실행해 무엇이 통과하는지 기록합니다.

```bash
# 액세스 키는 환경 변수로 넘깁니다 — 명령행에 적으면 셸 히스토리와 ps 출력에 남습니다
read -rs REDIS_PASSWORD && export REDIS_PASSWORD

# EnterpriseCluster
python3 policy_matrix_test.py --host <amr>.<region>.redis.azure.net --port 10000 \
  --policy EnterpriseCluster --repeat 3 \
  --report results/policy-matrix-ent.json

# OSSCluster — 클러스터 클라이언트가 샤드 IP로 재접속하므로 호스트명 대조를 꺼야 붙습니다
python3 policy_matrix_test.py --host <amr>.<region>.redis.azure.net --port 10000 \
  --policy OSSCluster --repeat 3 --no-ssl-check-hostname \
  --report results/policy-matrix-oss.json
```

- `--repeat`는 같은 케이스를 몇 번 돌릴지입니다. 결과가 갈리면 `불안정`으로 표시됩니다.
- `--no-ssl-check-hostname`은 **체인 검증은 유지한 채 호스트명 대조만 끕니다.**
  인증서가 `<region>.redis.azure.net` 이름으로 발급돼 있어 샤드 IP로는 검증에 실패하기 때문입니다.
- 픽스처 준비는 파이프라인으로 묶여 있습니다. 왕복 지연이 큰 곳에서 순차로 보내면
  실행 시간이 수십 분으로 늘어납니다 (이 랩의 180ms 환경에서 38분).
- `clusteringPolicy`는 `OSSCluster`/`EnterpriseCluster`로 만들고 나면 DB를 지워야만 바꿀 수 있으므로, 비교하려면 **정책별로 클러스터를 따로 만들어야 합니다.**
- 이 랩의 결과는 [`results/policy-matrix-ent.json`](results/policy-matrix-ent.json)과
  [`results/policy-matrix-oss.json`](results/policy-matrix-oss.json)에 있고,
  해석은 [ACR과 AMR의 차이 2.4절](../migration-guide/01-differences.md#24-실측-정책--클라이언트-조합별-명령-호환성)에 있습니다.

## 사전 조건

- 소스 ACR과 타깃 AMR에 TCP로 닿는 리눅스 호스트 (같은 리전 VM 권장 — 클라이언트 왕복 지연이 그대로 복사 시간이 됩니다)
- Python 3.8+, `pip install redis`
- **타깃 AMR 데이터베이스는 `--clustering-policy EnterpriseCluster`로 생성**되어 있어야 합니다.
  기본값인 `OSSCluster`에서는 비클러스터 클라이언트가 `MOVED`/`CROSSSLOT`으로 실패하며,
  이 값은 **한 번 `OSSCluster`/`EnterpriseCluster`로 만들면 DB를 지우지 않고는 바꿀 수 없습니다**
  (`NoCluster`에서 나오는 방향만 `az redisenterprise database update`로 변경됩니다).

```bash
az redisenterprise database create \
  --cluster-name <amr-name> --resource-group <rg> \
  --clustering-policy EnterpriseCluster --access-keys-auth Enabled
```

## 실행 순서

```bash
export SRC_HOST=<acr>.redis.cache.windows.net SRC_PORT=6380
export DST_HOST=<amr>.<region>.redis.azure.net DST_PORT=10000

# 액세스 키는 환경 변수로만 넘깁니다 — 명령행에 적으면 셸 히스토리와 ps 출력에 남습니다
read -rs SRC_REDIS_PASSWORD && export SRC_REDIS_PASSWORD
read -rs DST_REDIS_PASSWORD && export DST_REDIS_PASSWORD
export REDIS_PASSWORD="$SRC_REDIS_PASSWORD"   # 소스 한쪽만 보는 스크립트가 읽는 이름

# 1. 테스트 데이터 적재
python3 load_data.py --host "$SRC_HOST" --port "$SRC_PORT" --target-gb 4

# 2. 마이그레이션 중 쓰기 부하 시작 (실행마다 --prefix를 다르게)
python3 concurrent_writer.py --host "$SRC_HOST" --port "$SRC_PORT" \
  --rate 200 --prefix run1 --log probes.jsonl &

# 3. 복사 (수렴시키려면 같은 명령을 반복 실행)
python3 migrate_scan_copy.py \
  --src-host "$SRC_HOST" --src-port "$SRC_PORT" \
  --dst-host "$DST_HOST" --dst-port "$DST_PORT" \
  --report pass1.json

# 4. 쓰기 차단 후 최종 패스 → 이 패스의 duration_sec이 실제로 필요한 다운타임입니다
touch /tmp/writer.stop
python3 migrate_scan_copy.py ... --report final.json

# 5. 검증
python3 verify_migration.py \
  --src-host "$SRC_HOST" --src-port "$SRC_PORT" \
  --dst-host "$DST_HOST" --dst-port "$DST_PORT" \
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
