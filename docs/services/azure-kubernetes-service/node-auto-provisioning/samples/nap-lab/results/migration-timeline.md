# CAS → NAP 전환 리허설 기록 (2026-10-30, AKS 1.36.5, East US 2)

## 대상

- 클러스터 `aks-cas`: 시스템 풀 2노드, user 풀 `Standard_D4ds_v6` 2노드(CAS)
- 앱 `migrate/web`: podinfo 6 replica, 각 1 vCPU 요청, PDB `maxUnavailable: 1`,
  hostname 기준 `ScheduleAnyway` topology spread
- 클라이언트: 시스템 노드에서 0.2초 간격 `GET /healthz`, 1초 timeout

## 경로 1 실행 시각 (`migrate/in-place.sh`)

| UTC | 단계 | 소요 |
|---|---|---|
| 10:30:49 | user 풀 CAS 비활성화 (노드 2대 고정) | 38초 |
| 10:31:27 | `az aks update --node-provisioning-mode Auto` | 2분 40초 |
| 10:34:12 | user 풀 2 → 1 | 6분 17초, NAP 노드 3대 |
| 10:40:33 | user 풀 1 → 0 | 6분 11초, NAP 노드 6대 |
| 10:46:46 | 빈 user 풀 삭제 | 35초 |

- 전체 약 16분 30초
- 요청 4,691건 중 실패 5건(0.11%)
  - `503` 4건: 축소 단계에서 Pod가 종료되는 순간. podinfo는 종료 신호를 받으면
    `/healthz`에 503을 반환하지만 Service endpoint에서 빠지기 전까지 요청이 계속 들어옴
  - timeout 1건: NAP 활성화 중(10:31:52)
- NAP는 1 vCPU Pod 6개를 `Standard_D2als_v6` 6대에 1개씩 배치했습니다. Karpenter는
  `ScheduleAnyway` spread도 우선 지키려고 노드를 더 만듭니다.

## NAP drift로 노드 전체 교체 (`preStop` 효과 확인)

```bash
# NodePool template label을 바꾸면 모든 노드가 drift되어 budget 안에서 교체됩니다.
kubectl patch nodepool default --type merge \
  -p '{"spec":{"template":{"metadata":{"labels":{"rotation":"r1"}}}}}'

# 종료 전 10초 대기 추가
kubectl -n migrate patch deploy web --type strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"podinfo","lifecycle":{"preStop":{"sleep":{"seconds":10}}}}]}}}}'
```

| 조건 | 교체 시간 (노드 6대) | 요청 | 실패 |
|---|---|---|---|
| `preStop` 없음 | 10분 13초 | 2,838 | `503` 2건 |
| `preStop.sleep 10s` | 14분 18초 | 3,978 | 0건 |
