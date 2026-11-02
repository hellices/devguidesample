# CAS → NAP 전환 리허설 기록 (AKS 1.36.5, East US 2, on-demand 전용)

`azd hooks run postdeploy`로 `EXPERIMENT="migration drift"`를 실행한 기록입니다. 시각은 UTC입니다.

## 대상

- CAS 클러스터: 시스템 풀 2노드, user 풀 `Standard_D4ds_v7`(Regular) 2노드
- NAP: AKS 기본 `default` NodePool(on-demand 전용)
- 앱 `migrate/web`: podinfo 6 replica, 각 1 vCPU 요청, PDB `maxUnavailable: 1`,
  hostname 기준 `ScheduleAnyway` topology spread
- 클라이언트: 시스템 노드에서 0.2초 간격으로 `GET /healthz` 시작, 1초 timeout

## 경로 1 실행 시각 (`migrate/in-place.sh`)

| UTC | 단계 | 소요 |
|---|---|---|
| 07:32:41 | CAS가 켜진 풀(user)의 CAS 비활성화, 노드 2대 고정 | 1분 12초 |
| 07:33:53 | `az aks update --node-provisioning-mode Auto` | 6분 46초 |
| 07:40:44 | user 풀 2 → 1 | 5분 22초, NAP 노드 3대 |
| 07:46:16 | user 풀 1 → 0 | 4분 28초, NAP 노드 6대 |
| 07:50:46 | 빈 user 풀 삭제 | 35초 |

- 전체 약 18분 40초
- 요청 5,605건 중 실패 1건(0.02%): NAP 활성화 중(07:34:19) timeout
- NAP는 1 vCPU Pod 6개를 on-demand `Standard_D2als_v6` 6대에 1개씩 배치했습니다. Karpenter는
  `ScheduleAnyway` spread도 우선 지키려고 노드를 더 만듭니다.

## NAP drift로 노드 전체 교체 (`preStop` 효과 확인)

두 조건이 섞이지 않도록 `preStop` 변경은 rollout을 끝낸 뒤 drift를 시작했습니다.

```bash
# 1) preStop 없음: NodePool template label을 바꾸면 모든 노드가 drift되어 budget 안에서 교체됩니다.
kubectl patch nodepool default --type merge \
  -p '{"spec":{"template":{"metadata":{"labels":{"rotation":"r1"}}}}}'

# 2) preStop 10초 대기를 먼저 적용하고 rollout 완료를 기다린 뒤 다시 drift
kubectl -n migrate patch deploy web --type strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"podinfo","lifecycle":{"preStop":{"sleep":{"seconds":10}}}}]}}}}'
kubectl -n migrate rollout status deploy/web
kubectl patch nodepool default --type merge \
  -p '{"spec":{"template":{"metadata":{"labels":{"rotation":"r2"}}}}}'
```

| 조건 | 교체 시간 (노드 6대) | 요청 | 실패 |
|---|---|---|---|
| `preStop` 없음 | 8분 14초 | 2,470 | `503` 4건 |
| `preStop.sleep 10s` | 12분 26초 | 3,730 | 0건 |
