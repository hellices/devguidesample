---
title: Azure Managed Redis OSS 정책의 Failover 후 재연결 실패 사례
description: 유지보수 이후 연결이 복구되지 않았던 사례의 축약 코드, 관측된 증상과 원인 추정을 구분해 기록합니다.
document_type: case
services:
- azure-managed-redis
technologies:
- nodejs
- redis
tags:
- diagnose
- operate
status: resolved
verification_status: verified
sources_checked_at: 2026-10-25
official_sources:
- title: Azure Managed Redis architecture
  url: https://learn.microsoft.com/azure/redis/architecture
- title: Failover and patching for Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/failover
- title: Connection resilience with Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/best-practices-connection
occurred_at: 2026-02-15
related_guides:
- ../clustering-policies/index.md
- ../clustering-policies/nodejs/index.md
- ../clustering-policies/java/index.md
- ../migration-from-azure-cache/index.md
redirect_from:
- cases/azure-managed-redis/cluster-failover-recovery/index.md
---

# Azure Managed Redis OSS 정책의 Failover 후 재연결 실패 사례

!!! tip "처음 연결하거나 정책을 선택하는 독자라면"
    [클러스터링 정책 이해와 선택](../clustering-policies/index.md)에서 시작합니다. 이 페이지는 일반 연결 가이드가 아니라 **특정 시점의 장애 기록**입니다. 현재 설정은 [Node.js 연결 가이드](../clustering-policies/nodejs/index.md)에서 관리합니다.

## 어떤 상황이었나 { #_1 }

원문에는 Azure Managed Redis를 OSS 정책으로 사용하던 애플리케이션이 **Planned Maintenance 이후 재연결하지 못했고, 애플리케이션 재기동 뒤 복구됐다**고 기록되어 있습니다.

발생일은 원문의 타임라인에 기록된 2026-02-15를 기준으로 합니다. 2026-10-24의 후속 분석은 이후에 추가된 조사이며, 그때 검토한 라이브러리 버전을 당시 실행 버전과 동일하다고 간주하지 않습니다.

| 구분 | 이 문서에서 알 수 있는 범위 |
|---|---|
| 사용 구성 | 원문은 OSS 정책으로 설명하며 Node.js의 `createCluster` 설정을 제시 |
| 관측 | 유지보수 중 기존 연결 실패, 재기동 뒤 다른 포트로 연결 |
| 자료의 한계 | 당시 전체 애플리케이션·원본 로그·정확한 실행 버전은 이 공개 문서에 포함되지 않음 |
| 해석 | 특정 노드 주소 재연결과 토폴로지 갱신의 관계를 조사한 사례. 모든 OSS 구성에 같은 장애가 발생한다는 증거는 아님 |

`createCluster` 사용만으로 리소스가 OSS 정책임을 확정할 수는 없습니다. 실제 환경을 진단할 때는 [리소스 정책 조회](../clustering-policies/index.md#set-and-check-policy)와 클라이언트 버전을 함께 확인합니다.

## 사례의 연결 설정 — 설명을 위한 축약 예시 { #_2 }

다음은 원문에 있던 연결 구성입니다. **실행 가능한 전체 코드나 현재 권장 예제가 아닙니다.** 원래 애플리케이션을 모르는 독자를 위해 생략된 입력을 아래에 설명합니다.

```javascript
redisClient = createCluster({
    rootNodes: [{ url: `rediss://${redisUrl.hostname}:${redisUrl.port}` }],
    defaults: {
        credentialsProvider: provider,
        socket: {
            tls: true,
            servername: redisUrl.hostname,
            connectTimeout: 1000,
            reconnectStrategy,
        },
    },
});
```

| 이름 | 이 코드에서의 역할 |
|---|---|
| `createCluster` | node-redis의 클러스터 클라이언트 생성 함수 |
| `redisUrl` | 외부에서 만든 연결 URL 객체. 캐시 호스트와 초기 연결 포트를 제공 |
| `provider` | 외부에서 만든 인증 공급자. 생성·갱신 구현은 생략되어 있음 |
| `reconnectStrategy` | 소켓 재연결 시도 방식을 정하는 외부 콜백. 구체적인 반환 조건은 생략되어 있음 |
| `redisClient` | 애플리케이션에서 공유하는 클라이언트 참조 |

**OSS에서 `createCluster`를 사용하는 것 자체는 잘못이 아닙니다.** 이 사례의 질문은 연결이 끊긴 뒤 클라이언트가 새 토폴로지를 발견했는지, 그리고 복구되지 않을 때 애플리케이션이 어떻게 대응했는지입니다.

`connectTimeout: 1000`은 현재 Microsoft Learn의 5초 권장값보다 짧습니다. 재연결 실패를 악화시킬 수 있는 설정이지만, 이 값 하나만으로 장기 장애의 원인을 확정하지 않습니다.

## 관측된 증상 { #_3 }

### 원문 타임라인 { #_4 }

| 시점 | 원문에 기록된 내용 |
|---|---|
| 2026-02-15 10:18:53 | Planned Maintenance 시작 |
| 유지보수 중 | 기존 `8503` 포트 연결이 끊기고 재연결 실패 |
| 애플리케이션 재기동 후 | `8500` 포트로 정상 연결 |

여기서 포트 번호는 당시 관측값이지 고정된 샤드 주소가 아닙니다. `8503`에서 `8500`으로 달라졌다는 사실만으로 VM의 정체나 클라이언트 내부 상태까지 확인되지는 않습니다.

### 관측을 설명하는 가설 { #root-cause }

[![재연결 실패의 설명 모델. 유지보수 전 클라이언트가 8503 포트의 샤드에 연결하다가 노드 교체 뒤 기존 주소로 재연결을 반복하고, 클라이언트를 새로 만들면 최신 토폴로지를 읽어 8500 포트로 연결하는 흐름이다. 내부 상태 전체를 당시 로그로 입증한 그림은 아니다.](images/failover-incident.svg)](images/failover-incident.svg)

Microsoft Learn의 [패치 과정](https://learn.microsoft.com/azure/redis/failover#how-does-patching-occur)은 새 VM 생성, 기존 노드 제거와 샤드 이동, 교체된 VM 삭제를 설명합니다. OSS에서는 클라이언트가 샤드에 직접 연결하므로 연결 대상이 달라질 수 있습니다.

이 제품 동작과 원문 관측을 연결한 가설은 다음과 같습니다.

1. 유지보수로 기존 연결이 끊어졌습니다.
2. 클라이언트가 알고 있던 주소로 재연결을 시도했지만 사용할 수 없었을 가능성이 있습니다.
3. 연결 자체가 실패하면 해당 연결에서 `MOVED` 응답을 받을 수 없습니다. 다른 경로의 토폴로지 갱신도 성공하지 못했다면 요청 실패가 계속될 수 있습니다.
4. 재기동으로 클라이언트를 다시 만들면서 최신 토폴로지를 발견했다는 설명은 관측과 부합합니다.

다만 원문만으로 네트워크·인증·재시도 중단 조건을 모두 배제하거나 slot 맵이 갱신되지 않았음을 단정할 수는 없습니다. 재발 조사에서는 유지보수 이벤트, 실행 버전, 재연결·토폴로지 갱신 로그와 접근 가능 주소를 함께 수집합니다.

## 복구 결과와 현재 가이드 { #_5 }

이 기록에서 관측된 복구는 **애플리케이션 재기동 후 연결 정상화**입니다. 정책 전환이나 라이브러리 업그레이드를 당시 적용해 재발 방지까지 검증했다고 기록된 것은 아닙니다.

### OSS를 유지할 때 확인할 설정 { #option-topology-refresh }

[Node.js의 재연결·토폴로지 갱신](../clustering-policies/nodejs/index.md#topology-refresh)에서 버전별 기능과 지속 실패 시 연결 재생성을 확인합니다. 현재 코드 예제도 그 문서에만 둡니다.

다른 정책을 검토한다면 [정책별 제약과 선택 기준](../clustering-policies/index.md#policy-comparison)을 비교합니다. Enterprise의 프록시는 클라이언트의 샤드 라우팅 부담을 줄이지만 모든 요청 실패를 없애는 해법은 아닙니다. Java를 사용하는 독자는 [Java 연결 가이드](../clustering-policies/java/index.md)를 참고합니다.

## 당시 동작을 살펴보는 샘플 { #_7 }

이 topic의 Node.js 샘플은 이전 연결 설정을 비교하기 위한 실험 자료입니다. 현재 권장 설정의 배포 템플릿이나 이 장애를 결정적으로 재현하는 자동 테스트가 아닙니다.

- [샘플 사용·검증·정리 방법](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-managed-redis/cluster-failover-recovery/samples/nodejs-cluster)
- [설명 모델의 편집 가능한 그림 원본](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-managed-redis/cluster-failover-recovery/samples/diagrams)
