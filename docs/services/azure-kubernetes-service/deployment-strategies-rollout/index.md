---
title: AKS 애플리케이션 배포 전략과 Pod rollout 제어
description: 배포 전략의 선택 기준, Pod 교체 수와 진행 조건을 정하는 옵션, 전략별 추가 설정과 변경 방법
document_type: guide
services: [azure-kubernetes-service]
technologies: [kubernetes, gitops]
tags: [deploy, operate]
status: current
verification_status: verified
sources_checked_at: 2026-09-22
official_sources:
  - title: CI/CD for microservices
    url: https://learn.microsoft.com/azure/architecture/microservices/ci-cd
  - title: Deployment and cluster reliability best practices for Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/best-practices-app-cluster-reliability
  - title: Zero-downtime migration to Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/zero-downtime-migration
  - title: Configure rolling upgrades for Azure Kubernetes Service (AKS) node pools
    url: https://learn.microsoft.com/azure/aks/upgrade-aks-node-pools-rolling
  - title: Deployments
    url: https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
  - title: StatefulSets
    url: https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/
  - title: DaemonSet
    url: https://kubernetes.io/docs/reference/kubernetes-api/apps/daemon-set-v1/
  - title: Kubernetes v1.35.0 apps validation
    url: https://github.com/kubernetes/kubernetes/blob/v1.35.0/pkg/apis/apps/validation/validation.go
  - title: Disruptions
    url: https://kubernetes.io/docs/concepts/workloads/pods/disruptions/
  - title: Horizontal Pod Autoscaling
    url: https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/
  - title: Update API Objects in Place Using kubectl patch
    url: https://kubernetes.io/docs/tasks/manage-kubernetes-objects/update-api-object-kubectl-patch/
  - title: Getting Started
    url: https://github.com/argoproj/argo-rollouts/blob/v1.10.0/docs/getting-started.md
  - title: Canary Deployment Strategy
    url: https://github.com/argoproj/argo-rollouts/blob/v1.10.0/docs/features/canary/index.md
  - title: BlueGreen Deployment Strategy
    url: https://github.com/argoproj/argo-rollouts/blob/v1.10.0/docs/features/bluegreen.md
  - title: Rollouts Abort
    url: https://github.com/argoproj/argo-rollouts/blob/v1.10.0/docs/generated/kubectl-argo-rollouts/kubectl-argo-rollouts_abort.md
  - title: Request Routing
    url: https://github.com/istio/istio.io/blob/master/content/en/docs/tasks/traffic-management/request-routing/index.md
  - title: Mirroring
    url: https://github.com/istio/istio.io/blob/master/content/en/docs/tasks/traffic-management/mirroring/index.md
last_verified: 2026-09-22
review_cycle_days: 180
applies_to:
  - AKS의 apps/v1 Deployment
  - Argo Rollouts v1.10.0 설정 예시, 별도 설치 필요
  - StatefulSet과 DaemonSet은 컨트롤러별 조건 적용
---

# AKS 애플리케이션 배포 전략과 Pod rollout 제어

**Pod 교체 수는 `maxSurge`와 `maxUnavailable`로 조절합니다.** 다만 이
설정은 Deployment의 Rolling Update에 대한 제한이지, 고정된 배치 크기나
단계별 승인을 뜻하지 않습니다.

**신버전에 보낼 요청 비율이나 전환 시점까지 제어하려면 배포 전략을 함께
선택해야 합니다.** 아래는 전략 선택 → 옵션의 의미 → 변경 방법 순서입니다.

## 배포 전략 선택

| 전략 | 선택 기준 | 핵심 제어 |
|---|---|---|
| Rolling Update | 가용 수를 유지하면서 점진적으로 교체하고 싶을 때 | 추가 생성·사용 불가 Pod 수 제한 |
| Recreate | 배포 중 중단을 허용하고, 업데이트 시 신·구 버전의 동시 실행을 피할 때 | 기존 Pod 종료 후 신버전 생성 |
| Blue/Green | 신버전을 별도로 검증한 뒤 운영 대상을 전환하고 싶을 때 | 신·구 버전 병행 유지, Service·라우팅 전환 |
| Canary | 신버전을 일부에 노출한 뒤 결과를 보고 확대하고 싶을 때 | 노출 비율, 대기·승인·분석 단계 |

Deployment의 `spec.strategy.type`에 넣을 수 있는 값은 **`RollingUpdate`와
`Recreate`**입니다. Blue/Green과 Canary는 여러 워크로드와 Service·라우팅을
조합하거나 Argo Rollouts 같은 별도 컨트롤러로 구현합니다.

Rolling Update는 교체 중 두 버전이 공존하고, Blue/Green은 두 버전을 함께
실행할 용량이 필요합니다. 어떤 전략도 설정만으로 무중단을 보장하지 않으므로
readiness, 종료 처리, 신·구 버전의 API·데이터 호환성을 함께 확인합니다.

### A/B·Shadow·기능 플래그는 노출·검증 기법으로 구분

- **A/B:** 사용자 그룹·요청 헤더에 따라 버전을 나눕니다. Pod 교체 개수와는 별개입니다.
- **Shadow:** 운영 요청을 신버전에도 복제해 관측합니다. 복제 응답은 버리지만, 쓰기 부작용은 별도로 막아야 합니다.
- **기능 플래그:** 배포된 코드의 기능 공개 여부를 바꿉니다. Pod 교체나 데이터 복구를 대신하지 않습니다.

이 기법들은 배포 전략에 함께 사용할 수 있지만 `strategy.type`의 추가 값은
아닙니다. [전략 비교](https://learn.microsoft.com/azure/architecture/microservices/ci-cd#update-services),
[조건별 라우팅](https://github.com/istio/istio.io/blob/master/content/en/docs/tasks/traffic-management/request-routing/index.md),
[미러링](https://github.com/istio/istio.io/blob/master/content/en/docs/tasks/traffic-management/mirroring/index.md)을 참고합니다.

## Pod 교체 수와 진행 조건

아래는 **Deployment** 기준입니다. `maxSurge`와 `maxUnavailable`은
`spec.strategy.rollingUpdate`, 나머지 세 옵션은 `spec` 바로 아래에 둡니다.

| 옵션 | 무엇을 정하나 | 기본값·주의점 |
|---|---|---|
| `maxSurge` | 원하는 replica 수보다 추가 생성할 수 있는 수 | `25%`. 정수 또는 퍼센트, 퍼센트는 **올림** |
| `maxUnavailable` | 교체 중 사용할 수 없어도 되는 수 | `25%`. 정수 또는 퍼센트, 퍼센트는 **내림** |
| `replicas` | 원하는 전체 Pod 수 | `1`. 배치 크기가 아니며 HPA 관리 여부 확인 |
| `minReadySeconds` | 새 Pod를 Available로 인정하기 전 Ready 상태 유지 시간 | `0`초. 트래픽 유입을 그 시간만큼 차단하는 설정은 아님 |
| `progressDeadlineSeconds` | 진행 정체를 실패로 보고하는 기준 시간 | `600`초. 자동 롤백이 아니며 `minReadySeconds`보다 커야 함 |

### 값의 조합은 이렇게 고릅니다

정상적으로 서비스 중인 replica가 **10개**이고 목표 수가 바뀌지 않는 예시입니다.
아래 수치는 일괄 적용할 운영 권장값이 아닙니다.

| 의도 | `maxSurge` | `maxUnavailable` | 교체 시 유지하려는 가용 수 |
|---|---|---|---|
| 추가 용량을 작게 사용 | `1` | `0` | 10개 이상 |
| 추가 용량을 늘려 교체 여유 확보 | `3` | `0` | 10개 이상 |
| 추가 생성 없이 일부 가용 수 감소 허용 | `0` | `2` | 8개 이상 |

- 두 값을 **동시에 0으로 둘 수 없습니다.** 둘 다 0보다 큰 조합도 가능합니다.
- 기본값 `25%`를 replica 3개에 적용하면 추가 허용은 1개, 사용 불가 허용은 0개입니다.
- `maxSurge: 2`는 **정확히 2개씩 교체 후 대기**가 아니라 추가 생성 예산입니다.
- 종료 중인 `Terminating` Pod 때문에 실제 Pod 수와 자원 사용량은 일시적으로 `replicas + maxSurge`를 넘을 수 있습니다.

계산과 진행 조건의 기준은 [Kubernetes Deployment 문서](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)입니다.

## Blue/Green·Canary의 추가 옵션

다음은 **Argo Rollouts v1.10.0** 기준입니다. AKS 기본 Deployment 설정이
아니며, 컨트롤러·CRD와 CLI 플러그인을 별도로 준비한 `Rollout` 리소스에
적용합니다. 예시는 안정 버전이 이미 있는 **업데이트** 기준입니다.

### Blue/Green: 전환 대상과 시점

`spec.strategy.blueGreen`에서 설정합니다.

| 옵션 | 역할 |
|---|---|
| `activeService`, `previewService` | 운영용 Service와 신버전 검증용 Service 지정 |
| `previewReplicaCount` | 검증 단계의 신버전 Pod 수. 승격 시에는 `spec.replicas`까지 확장 |
| `autoPromotionEnabled` | `false`이면 자동 전환 대신 승인 대기 |
| `scaleDownDelaySeconds` | 운영 대상 전환 후 구버전 축소까지 대기할 시간 |

**검증용 Pod 수를 줄여도 전환 시 필요한 용량까지 줄어드는 것은 아닙니다.**
수동으로 구현한다면 두 Deployment의 수량과 운영 Service selector를 관리합니다.
Argo Rollouts가 관리하는 Service를 동시에 수동 patch하지 않습니다.

### Canary: 비율과 다음 단계로 넘어갈 조건

`spec.strategy.canary`에서 설정합니다.

| 옵션 | 역할 |
|---|---|
| `steps[].setWeight` | 단계별 신버전 비율 지정 |
| `steps[].pause` | `{}`는 수동 승격 대기, `duration`은 시간 대기 |
| `analysis` | 분석 템플릿으로 지표를 평가하고 실패 시 배포 중단 |
| `trafficRouting` | 트래픽 비율을 제어할 라우터 연동 |
| `maxSurge`, `maxUnavailable` | 라우터 없는 Basic Canary의 Pod 수 계산에 사용 |
| `steps[].setCanaryScale` | 라우터 연동 시 신버전 Pod 수를 트래픽 가중치와 별도로 제어 |

**Pod 수 비율과 실제 요청 비율은 다릅니다.** 라우터가 없으면 `setWeight`에
가까워지도록 신·구 Pod 수를 정수로 조절합니다. 라우터가 있으면 트래픽 가중치를
바꾸며, Pod 용량은 별도로 확인해야 합니다. 라우터 연동 시 Deployment의
`replicas + maxSurge` 계산을 전체 용량 상한으로 사용하지 않습니다.

??? example "Canary의 단계 설정 예시"
    기존 Rollout에서 수정할 부분만 발췌한 **Basic Canary** 예시입니다.
    `20 → 수동 승인 → 50 → 2분 대기 → 100` 순서로 진행합니다.

    ```yaml
    spec:
      replicas: 10
      strategy:
        canary:
          maxSurge: 2
          maxUnavailable: 0
          steps:
            - setWeight: 20
            - pause: {}
            - setWeight: 50
            - pause:
                duration: 2m
            - setWeight: 100
    ```

    첫 단계는 신·구 Pod 수를 2:8에 가깝게 맞추는 것이며 실제 요청의 정확히
    20%를 보장하지 않습니다. `duration: 2m`도 지표 검증은 아니므로 자동
    판단이 필요하면 분석 템플릿과 지표 공급자를 연결합니다.

    ```bash
    kubectl argo rollouts get rollout web-canary -n rollout-demo
    kubectl argo rollouts promote web-canary -n rollout-demo
    ```

    `web-canary`는 가상의 기존 Rollout 이름입니다. 관측 기준을 만족하고
    승인된 경우에만 `promote`로 현재 대기 단계를 진행합니다.

세부 동작: [Argo Blue/Green](https://github.com/argoproj/argo-rollouts/blob/v1.10.0/docs/features/bluegreen.md),
[Argo Canary](https://github.com/argoproj/argo-rollouts/blob/v1.10.0/docs/features/canary/index.md).

## 설정을 변경하는 방법

**지속적으로 유지할 값은 Git·매니페스트·Helm 원본에서 변경합니다.** Helm은
chart가 제공하는 values와 template 연결을 확인하고, GitOps는 원본 변경 후
동기화합니다. 직접 patch만 하면 이후 동기화에서 덮어써질 수 있습니다.

다음은 기존 Deployment의 `spec`에 반영할 발췌입니다. 완성된 배포
매니페스트가 아니며, `replicas`는 건드리지 않고 교체 예산과 진행 조건만
바꿉니다.

```yaml
spec:
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 2
      maxUnavailable: 0
  minReadySeconds: 10
  progressDeadlineSeconds: 600
```

**전략 변경만으로 새 rollout이 시작되지는 않습니다.** 새 이미지 등으로
`spec.template`을 변경해야 합니다. 같은 버전의 Pod를 다시 만들 목적이라면
`kubectl rollout restart`를 선택할 수 있습니다.

??? example "kubectl로 직접 변경할 때"
    Bash/zsh 기준이며 테스트 클러스터의 조회·변경 권한이 필요합니다.
    `rollout-demo` namespace와 `web` Deployment가 이미 있다고 가정합니다.
    먼저 대상 context, HPA, 진행 중인 rollout과 추가 Pod를 수용할 용량을
    확인합니다. GitOps 관리 리소스에는 해당 원본·동기화 절차를 우선합니다.

    ```bash
    kubectl config current-context
    kubectl -n rollout-demo get deployment web
    kubectl -n rollout-demo get hpa
    kubectl -n rollout-demo rollout status deployment/web --timeout=10m
    kubectl -n rollout-demo patch deployment web --type=merge -p '{
      "spec": {
        "strategy": {
          "type": "RollingUpdate",
          "rollingUpdate": {"maxSurge": 2, "maxUnavailable": 0}
        },
        "minReadySeconds": 10,
        "progressDeadlineSeconds": 600
      }
    }'
    kubectl -n rollout-demo get deployment web -o yaml
    ```

    같은 버전으로 재시작하려는 경우에만 다음 명령을 실행합니다.

    ```bash
    kubectl -n rollout-demo rollout restart deployment/web
    kubectl -n rollout-demo rollout status deployment/web --timeout=10m
    ```

??? example "Recreate로 바꿀 때"
    `rollingUpdate` 필드는 제거하고 `type`을 바꿉니다. 다음 Pod template
    업데이트에서 기존 Pod를 먼저 종료하므로 배포 중 중단을 수용해야 합니다.

    ```bash
    kubectl -n rollout-demo patch deployment web --type=merge \
      -p '{"spec":{"strategy":{"type":"Recreate","rollingUpdate":null}}}'
    ```

    이 순서는 Deployment 업데이트에 대한 동작입니다. 수동 Pod 삭제까지
    직렬화하거나 데이터베이스의 단일 writer를 보장하는 장치는 아닙니다.

변경 방식의 기준은 [kubectl patch](https://kubernetes.io/docs/tasks/manage-kubernetes-objects/update-api-object-kubectl-patch/)입니다.

## 검증과 복구

Deployment는 **신버전 수·Ready 수·Available 수와 실제 요청 성공 여부**를
함께 확인합니다. Blue/Green은 preview와 운영 경로를 나누어 검증하고,
Canary는 단계마다 버전별 요청량·오류율·지연을 확인합니다.

```bash
kubectl -n rollout-demo rollout status deployment/web --timeout=10m
kubectl -n rollout-demo get deployment web
```

`--timeout`은 클라이언트의 대기 한도이며 서버의 배포를 취소하지 않습니다.
실패 기준과 복귀 대상을 정해 둔 후 전략에 맞게 복구합니다.

| 대상 | 복구 방법 | 주의점 |
|---|---|---|
| Deployment | revision 확인 후 `kubectl rollout undo` | Pod template만 복원. 수량·전략·Service·DB까지 복원하지 않음 |
| 수동 Blue/Green | 운영 Service·라우팅을 구버전으로 복원 | 구버전의 용량과 Ready 상태를 먼저 확인 |
| Argo Canary·Blue/Green | 진행 중인 rollout을 `abort`하고 안정 버전 확인 | `spec.template`과 Git 원본도 이전 버전으로 되돌려야 완전한 복귀 |

Deployment가 pause 상태라면 undo 전에 resume이 필요합니다. pause는 이미
시작한 모든 Pod 작업의 즉시 취소가 아닙니다. 세부 절차는
[Deployment 롤백](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#rolling-back-a-deployment)과
[Argo abort](https://github.com/argoproj/argo-rollouts/blob/v1.10.0/docs/generated/kubectl-argo-rollouts/kubectl-argo-rollouts_abort.md)를 따릅니다.

## 컨트롤러별 차이와 운영 제약

### StatefulSet·DaemonSet에 같은 설정을 복사하지 않기

| 컨트롤러 | 설정 위치와 중요한 차이 |
|---|---|
| Deployment | `spec.strategy.rollingUpdate`에서 추가 생성 수와 사용 불가 수를 조절 |
| StatefulSet | `spec.updateStrategy`. 기본 RollingUpdate는 큰 ordinal부터 순서대로 교체하며 `partition`으로 대상 범위를 제한 |
| DaemonSet | `spec.updateStrategy.rollingUpdate`. 전체 replica 수가 아니라 Pod를 배치할 대상 노드 수를 기준으로 계산 |

- **StatefulSet:** `partition`은 업데이트할 ordinal의 하한이지 동시 교체 수가 아닙니다. `OnDelete`는 자동 교체를 하지 않습니다. 병렬 교체용 `maxUnavailable`은 Kubernetes 버전·기능 상태와 `podManagementPolicy` 조건을 별도로 확인합니다.
- **DaemonSet:** 기본값은 `maxUnavailable: 1`, `maxSurge: 0`이고 퍼센트는 올림입니다. surge가 0보다 크면 unavailable은 0이어야 하며 둘 다 0일 수는 없습니다.

컨트롤러별 조건은 [StatefulSet](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/),
[DaemonSet API](https://kubernetes.io/docs/reference/kubernetes-api/apps/daemon-set-v1/),
[DaemonSet 수량 검증](https://github.com/kubernetes/kubernetes/blob/v1.35.0/pkg/apis/apps/validation/validation.go#L474-L494)을 확인하고 실제 AKS 버전에 맞게 적용합니다.

### PDB·HPA·노드풀 업그레이드는 별도 제어

- **PDB:** node drain 같은 자발적 eviction의 예산입니다. Deployment의 애플리케이션 rollout 제한을 대신하지 않습니다.
- **HPA:** `replicas`를 바꾸므로 퍼센트 기반 예산도 달라집니다. HPA 관리 리소스에 고정 replica 수를 반복 적용하지 않습니다. 기존 필드 제거 시에도 일시적 축소 가능성을 확인합니다.
- **노드풀 `--max-surge`:** AKS 업그레이드의 추가 **노드 수**입니다. Deployment의 추가 **Pod 수**와 다릅니다.

기준: [PDB](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/#pod-disruption-budgets),
[HPA 전환](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/#migrating-deployments-and-statefulsets-to-horizontal-autoscaling),
[AKS 노드풀 업그레이드](https://learn.microsoft.com/azure/aks/upgrade-aks-node-pools-rolling).

## 관련 문서와 공식 참고 자료

- [Argo CD Image Updater와 ACR 연동](../argocd-image-updater-acr/index.md): GitOps 이미지 갱신 흐름
- [CI/CD for microservices](https://learn.microsoft.com/azure/architecture/microservices/ci-cd): 전략 선택과 GitOps
- [AKS 배포 안정성 지침](https://learn.microsoft.com/azure/aks/best-practices-app-cluster-reliability): readiness·종료 처리·배포 용량
- [기존 AKS 클러스터의 애플리케이션 배포](https://learn.microsoft.com/azure/aks/zero-downtime-migration#release-an-application-in-an-existing-aks-cluster): 배포와 관측·검증
- [Argo Rollouts 시작하기](https://github.com/argoproj/argo-rollouts/blob/v1.10.0/docs/getting-started.md): 별도 설치 요건과 진행·승격

검증 범위: **2026-09-22 UTC**에 Microsoft Learn과 upstream 공식 원문을
대조했습니다. 실제 AKS 클러스터에서 배포·부하·장애 복구를 실행한 결과는 아닙니다.
