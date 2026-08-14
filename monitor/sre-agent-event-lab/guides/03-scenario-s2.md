# 03. S2 — 응답 지연 장애

주문 API가 느려지게 만들고, p95 지연 경고를 받은 Agent가 오류 없는 장애를 설명하는지 봅니다. 500이 하나도 없기 때문에 S1보다 근거를 고르기 어렵습니다.

## 시작 조건

- [02-scenario-s1.md](02-scenario-s1.md)의 S1이 복구되고 캡처가 `conclusion`으로 끝났습니다.
- `evidence/state.json`에 `s1_recovered`와 `s1_captured`가 있습니다.
- 워크로드가 정상이고 S1 경고가 해제되어 있습니다.

## 실행 명령

```bash
cd monitor/sre-agent-event-lab
./scripts/lab.sh run s2
./scripts/lab.sh capture s2
```

## Azure에서 발생하는 변화

| 순서 | 변화 |
|---|---|
| 1 | Container App에 `ORDER_DELAY_MS=4000`이 설정되어 새 revision이 만들어집니다 |
| 2 | `/api/orders`에 요청 90건(동시 8)이 들어가고 모두 200이지만 4초 안팎이 걸립니다 |
| 3 | Application Insights workspace 테이블 `AppRequests`의 `DurationMs`가 올라갑니다 |
| 4 | 5분 창의 p95 지연이 2000ms를 넘으면 `alert-sre-lab-s2-latency`(Sev2)가 발생합니다 |
| 5 | 복구로 `ORDER_DELAY_MS=0` revision이 배포되고 경고가 자동 해제됩니다 |

## SRE Agent에서 확인할 항목

- 성공 응답만 있는 상황에서 지연을 근거로 삼는지, 오류 로그가 없다는 이유로 "이상 없음"이라고 답하지 않는지
- p95 값과 정상 구간의 차이를 수치로 제시하는지
- 원인을 최근 revision의 설정 변경으로 좁히는지, 일반적인 "리소스 부족"으로 뭉개지 않는지
- 완화책이 되돌리기 가능한 최소 변경인지

## 성공·부분 성공·실패 판정

| 기록된 상태 | 판정 |
|---|---|
| `conclusion` | 성공. 결론 내용의 깊이는 채점에서 다시 나뉩니다 |
| `conclusion-missing` | 실패. 조사는 시작했지만 결론이 없습니다 |
| `investigation-missing` | 실패. 스레드만 열리고 조사 단계가 없습니다 |
| `thread-not-created` | 실패. 경고가 Agent에 도달하지 못했습니다 |

지연 시나리오에서 흔한 부분 성공은 "느려졌다"까지만 말하고 어떤 변경 때문인지 짚지 못하는 결론입니다. 이 경우도 상태는 `conclusion`이므로, 직접 원인 항목의 점수로 구분합니다.

## 복구 확인

1. 활성 revision이 정상이고 `/api/orders`가 다시 빠르게 응답합니다.
2. `alert-sre-lab-s2-latency`가 `Resolved`입니다.

경고가 해제되지 않으면 부하가 남아 있는지, 새 revision으로 트래픽이 100% 넘어갔는지 확인합니다. 실패로 기록된 실행은 `./scripts/lab.sh run s2`를 다시 실행해 새 시도로 이어 갑니다.

되돌리기 자체가 실패하면 스크립트는 `CRITICAL:` 두 줄을 출력하고 0이 아닌 코드로 끝냅니다. 지연이 그대로 남아 있다는 뜻이므로, 다음 시나리오를 실행하기 전에 `ORDER_DELAY_MS=0`을 수동으로 되돌리고 새 revision이 정상인지 확인하세요.

## 다음 단계

권한 장애로 넘어갑니다: [04-scenario-s3.md](04-scenario-s3.md)
