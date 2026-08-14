# 04. S3 — Blob 권한 제거 장애

워크로드의 Blob 읽기 권한을 지우고, 애플리케이션 코드가 아니라 권한이 원인임을 Agent가 구분해 내는지 봅니다.

## 시작 조건

- [03-scenario-s2.md](03-scenario-s2.md)의 S2가 복구되고 캡처가 `conclusion`으로 끝났습니다.
- `evidence/state.json`에 `s2_recovered`와 `s2_captured`가 있습니다.
- 역할 할당을 만들고 지울 권한이 그대로 있습니다.

## 실행 명령

```bash
cd monitor/sre-agent-event-lab
./scripts/lab.sh run s3
./scripts/lab.sh capture s3
```

## Azure에서 발생하는 변화

| 순서 | 변화 |
|---|---|
| 1 | 워크로드 관리 ID의 `Storage Blob Data Reader` 할당이 Blob 컨테이너 범위에서 삭제됩니다 |
| 2 | `/api/documents`에 요청 60건(동시 4)이 들어가고 모두 HTTP 503을 받습니다 |
| 3 | Application Insights workspace 테이블 `AppDependencies`에 Storage 대상 `ResultCode == "403"`이 쌓입니다 |
| 4 | 5분 창의 403 의존성 실패가 5건을 넘으면 `alert-sre-lab-s3-storage-rbac`(Sev2)이 발생합니다 |
| 5 | 복구로 같은 이름·같은 범위의 역할 할당이 다시 만들어집니다 |

삭제와 복구는 출력에 기록된 Blob 컨테이너 범위의 단일 역할에만 적용됩니다. 구독이나 리소스 그룹 범위의 다른 할당은 건드리지 않습니다.

## SRE Agent에서 확인할 항목

- 앱이 돌려준 503과 실제 원인인 Storage 403을 구분하는지
- 호출한 관리 ID, 대상 범위, 필요한 데이터 평면 역할을 각각 지목하는지
- Activity Log의 역할 할당 삭제 기록을 근거로 인용하는지
- 복구책으로 구독 범위 권한이 아니라 원래 범위의 최소 역할을 제안하는지

마지막 항목은 운영 문서가 명시적으로 요구하는 내용이라, 실습에서 제품이 문서를 실제로 따르는지 가장 잘 드러나는 지점입니다.

## 성공·부분 성공·실패 판정

| 기록된 상태 | 판정 |
|---|---|
| `conclusion` | 성공. 권한 범위까지 짚었는지는 채점에서 확인합니다 |
| `conclusion-missing` | 실패. 결론에 도달하지 못했습니다 |
| `investigation-missing` | 실패. 조사 단계가 없습니다 |
| `thread-not-created` | 실패. 경고가 도달하지 않았습니다 |

권한 시나리오의 전형적인 부분 성공은 "Storage 접근 실패"까지만 말하고 어떤 역할이 어느 범위에서 사라졌는지 밝히지 못하는 결론입니다.

## 복구 확인

1. `Storage Blob Data Reader` 할당이 원래 Blob 컨테이너 범위에 다시 존재합니다.
2. `alert-sre-lab-s3-storage-rbac`가 `Resolved`입니다.

역할 전파에는 몇 분이 걸릴 수 있습니다. `/api/documents`가 200을 돌려주는지 직접 호출해 확인하고, 실패로 기록되었다면 `./scripts/lab.sh run s3`으로 새 시도를 시작합니다.

## 다음 단계

수집한 근거를 채점합니다: [05-results.md](05-results.md)
